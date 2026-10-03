#!/usr/bin/env python3
"""
job_tracker_cloud.py
Reads job-related emails from iCloud Mail (IMAP) and updates the
"Job Applications Tracker" Google Sheet. Built to run on GitHub Actions.

Required environment variables (set as GitHub repository secrets):
    ICLOUD_EMAIL                  your iCloud address
    ICLOUD_APP_PASSWORD           Apple app-specific password
    GOOGLE_SERVICE_ACCOUNT_JSON   full contents of the service-account key file
    SPREADSHEET_ID                the ID from your Google Sheet's URL

What it does:
  - New application -> fills the first blank row in "Tracker"
    (Company, Title, Status, Application Date).
  - Status change -> updates Status, logs it in "StatusHistory" and keeps
    "_StatusTracker" in sync, like the template does for manual edits.
  - Never touches Application Week, Notes, links or other columns.
Progress is stored in a hidden tab called "_tracker_state".
The mailbox is opened read-only, so emails are NOT marked as read.
"""

import email
import imaplib
import json
import os
import re
import sys
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape
from zoneinfo import ZoneInfo

import gspread

# ======================= SETTINGS =======================
SHEET_NAME = "Tracker"
HISTORY_TAB = "StatusHistory"
MIRROR_TAB = "_StatusTracker"
STATE_TAB = "_tracker_state"
TIMEZONE = ZoneInfo("Europe/Athens")
IMAP_SERVER = "imap.mail.me.com"
IMAP_PORT = 993
MAILBOX = "INBOX"
DAYS_BACK_FIRST_RUN = 30
MAX_PER_RUN = 300

COLUMNS = {
    "company": "Company",
    "role": "Title",
    "status": "Status",
    "date": "Application Date",
}

JOB_WORDS = ["application", "applying", "applied", "candidacy", "candidate",
             "interview", "position", "recruit", "hiring"]

# Checked top to bottom; first match wins.
# (status, phrases matched anywhere, phrases matched in the subject only)
STATUS_RULES = [
    ("Rejected", ["unfortunately", "not to move forward", "not moving forward",
                  "other candidates", "not been selected", "not selected",
                  "will not be proceeding", "decided to pursue",
                  "position has been filled", "regret to inform"], []),
    ("Offer", ["pleased to offer", "offer letter", "job offer",
               "extend an offer", "offer of employment"], []),
    ("Interview", ["invite you to an interview", "invite you to interview",
                   "schedule an interview", "technical interview",
                   "next round", "interview invitation"], ["interview"]),
    ("Recruiter Screen", ["phone screen", "schedule a call", "quick call",
                          "introductory call", "intro call", "recruiter call",
                          "like to speak with you", "schedule a time",
                          "move forward with your application"], []),
    ("Applied", ["application received", "thank you for applying",
                 "thanks for applying", "received your application",
                 "your application", "application for", "applied for",
                 "candidacy"], []),
]

# Higher rank wins; an email never moves a job "backwards".
STATUS_RANK = {"": 0, "Pending": 0, "Ghosted": 0, "Applied": 1,
               "Recruiter Screen": 2, "Interview": 3, "Offer": 4,
               "Rejected": 4, "Dropped": 5}

GENERIC_DOMAINS = [
    "greenhouse.io", "greenhouse-mail.io", "lever.co", "myworkday.com",
    "workday.com", "smartrecruiters.com", "icims.com", "ashbyhq.com",
    "workable.com", "workablemail.com", "teamtailor.com", "teamtailor-mail.com",
    "bamboohr.com", "jobvite.com", "recruitee.com", "personio.de",
    "personio.com", "successfactors.com", "taleo.net", "linkedin.com",
    "indeed.com", "indeedemail.com", "glassdoor.com", "kariera.gr",
    "karieragroup.com", "skywalker.gr", "jobfind.gr", "smartcv.co",
    "himalayas.app", "gmail.com", "outlook.com", "hotmail.com", "yahoo.com",
    "icloud.com", "me.com",
]
# ========================================================

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------- helpers --------------------------------
def decode(value):
    try:
        return str(make_header(decode_header(value or ""))).strip()
    except Exception:
        return (value or "").strip()


def norm(text):
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def same_company(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = sorted([a, b], key=len)
    return len(shorter) >= 3 and shorter in longer


def get_body(msg):
    plain, html = [], []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if "attachment" in str(part.get("Content-Disposition") or "").lower():
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8",
                              errors="replace")
        if part.get_content_type() == "text/plain":
            plain.append(text)
        elif part.get_content_type() == "text/html":
            html.append(text)
    if plain:
        return "\n".join(plain)
    text = "\n".join(html)
    text = re.sub(r"<(script|style).*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return unescape(text)


def classify(subject, body):
    subj, full = subject.lower(), (subject + " " + body).lower()
    for status, anywhere, subject_only in STATUS_RULES:
        if any(p in full for p in anywhere) or any(p in subj for p in subject_only):
            return status
    return None


def domain_company(addr):
    domain = addr.split("@")[-1].lower()
    if any(domain == g or domain.endswith("." + g) for g in GENERIC_DOMAINS):
        return None
    parts = domain.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "ac", "net"):
        root = parts[-3]
    elif len(parts) >= 2:
        root = parts[-2]
    else:
        return None
    return root.replace("-", " ").title()


def clean_display_name(name):
    for sep in (" from ", " at ", " via "):
        if sep in name.lower():
            idx = name.lower().index(sep)
            name = name[idx + len(sep):] if sep != " via " else name[:idx]
    name = re.sub(r"\b(careers?|jobs?|recruit(ing|ment|er)?|talent( acquisition)?|"
                  r"hiring( team)?|hr|people|team|no[- ]?reply|notifications?)\b",
                  " ", name, flags=re.I)
    name = re.sub(r"[|\-–:,@]+", " ", name)
    return " ".join(name.split())


def guess_company(subject, display_name, addr):
    company = domain_company(addr)
    if company:
        return company
    for word in ("at", "to", "with", "from"):
        m = re.search(rf"\b{word}\s+([A-Z][\w&.'’ ]{{1,40}}?)\s*(?:[!.,:|\-–]|$)",
                      subject)
        if m:
            return m.group(1).strip()
    return clean_display_name(display_name) or None


def guess_role(subject):
    patterns = [
        r"(?:for|as)\s+(?:the\s+|a\s+|an\s+)?(.+?)\s+(?:position|role|job|opening)\b",
        r"application(?:\s+\w+)?\s+for\s+(?:the\s+)?(.+?)(?:\s+(?:at|with)\s+|\s+[-–|]\s+|$)",
        r"(?:applying|applied)\s+(?:for|to)\s+(?:the\s+)?(.+?)\s+(?:at|with)\s+",
    ]
    for p in patterns:
        m = re.search(p, subject, flags=re.I)
        if m and 2 < len(m.group(1)) < 80:
            return m.group(1).strip(" -–|:")
    return None


def email_datetime(msg):
    try:
        return parsedate_to_datetime(msg["Date"]).astimezone(TIMEZONE)
    except Exception:
        return datetime.now(TIMEZONE)


def stamp(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ------------------------- google sheet --------------------------------
def google_client():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        sys.exit("Missing GOOGLE_SERVICE_ACCOUNT_JSON secret.")
    return gspread.service_account_from_dict(json.loads(raw))


def optional_tab(sh, name):
    try:
        return sh.worksheet(name)
    except gspread.WorksheetNotFound:
        return None


def load_state(sh):
    ws = optional_tab(sh, STATE_TAB)
    if ws is None:
        ws = sh.add_worksheet(title=STATE_TAB, rows=5, cols=2)
        try:
            ws.hide()
        except Exception:
            pass
    values = {r[0]: r[1] for r in ws.get_all_values() if len(r) >= 2}
    return ws, values


def save_state(ws, last_uid, uidvalidity):
    ws.update(range_name="A1",
              values=[["last_uid", str(last_uid)], ["uidvalidity", uidvalidity]])


class Tracker:
    """Loads the Tracker tab once, edits it in memory, writes changes in bulk."""

    def __init__(self, sh):
        self.ws = sh.worksheet(SHEET_NAME)
        self.history_ws = optional_tab(sh, HISTORY_TAB)
        self.mirror_ws = optional_tab(sh, MIRROR_TAB)

        self.rows = self.ws.get_all_values()
        header = [h.strip() for h in self.rows[0]]
        self.col = {}
        for key, name in COLUMNS.items():
            if name not in header:
                sys.exit(f'Column "{name}" not found in the {SHEET_NAME} tab.')
            self.col[key] = header.index(name)

        self.width = max(len(r) for r in self.rows)
        for row in self.rows:
            row.extend([""] * (self.width - len(row)))

        self.changes = {}       # (row, col) 1-based -> value, Tracker tab
        self.mirror = {}        # (row, col) 1-based -> value, _StatusTracker
        self.history = []       # rows for StatusHistory

    def get(self, r, key):
        return self.rows[r][self.col[key]].strip()

    def set(self, r, key, value):
        value = "" if value is None else value
        self.rows[r][self.col[key]] = value
        self.changes[(r + 1, self.col[key] + 1)] = value

    def is_blank(self, r):
        return not self.get(r, "company") and not self.get(r, "role")

    def find_row(self, company, role):
        if not norm(company):
            return None
        for r in range(len(self.rows) - 1, 0, -1):
            if same_company(self.get(r, "company"), company):
                existing_role = self.get(r, "role")
                if role and existing_role and norm(role) != norm(existing_role):
                    continue
                return r
        return None

    def new_row(self):
        for r in range(1, len(self.rows)):
            if self.is_blank(r):
                return r
        self.rows.append([""] * self.width)
        return len(self.rows) - 1

    def change_status(self, r, new_status, old_status):
        self.set(r, "status", new_status)
        company, role = self.get(r, "company"), self.get(r, "role")
        self.history.append([stamp(datetime.now(TIMEZONE)), company, role,
                             old_status, new_status])
        for c, v in enumerate([company, role, new_status], start=1):
            self.mirror[(r + 1, c)] = v

    def save(self):
        if self.changes:
            needed = max(r for r, _ in self.changes)
            if needed > self.ws.row_count:
                self.ws.add_rows(needed - self.ws.row_count)
            cells = [gspread.Cell(r, c, v) for (r, c), v in self.changes.items()]
            self.ws.update_cells(cells, value_input_option="USER_ENTERED")
        if self.mirror and self.mirror_ws:
            needed = max(r for r, _ in self.mirror)
            if needed > self.mirror_ws.row_count:
                self.mirror_ws.add_rows(needed - self.mirror_ws.row_count)
            cells = [gspread.Cell(r, c, v) for (r, c), v in self.mirror.items()]
            self.mirror_ws.update_cells(cells, value_input_option="USER_ENTERED")
        if self.history and self.history_ws:
            self.history_ws.append_rows(self.history,
                                        value_input_option="USER_ENTERED",
                                        table_range="A1")


# ------------------------------ main ----------------------------------
def main():

    user = (os.environ.get("ICLOUD_EMAIL") or "").strip()
    password = (os.environ.get("ICLOUD_APP_PASSWORD") or "").strip().replace(" ", "")
    print(f"Username domain: {user.split('@')[-1] if '@' in user else '(no @ - short name)'}")
    print(f"Password length: {len(password)}")
    
    
    spreadsheet_id = os.environ.get("SPREADSHEET_ID")
    if not user or not password or not spreadsheet_id:
        sys.exit("Missing ICLOUD_EMAIL, ICLOUD_APP_PASSWORD or SPREADSHEET_ID secret.")

    sh = google_client().open_by_key(spreadsheet_id)
    tracker = Tracker(sh)
    state_ws, state = load_state(sh)

    imap = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    imap.login(user, password)
    imap.select(MAILBOX, readonly=True)
    resp = imap.response("UIDVALIDITY")[1]
    uidvalidity = (resp[0] or b"").decode() if resp else ""

    last_uid = int(state.get("last_uid") or 0)
    if last_uid and state.get("uidvalidity", "") == uidvalidity:
        _, data = imap.uid("search", None, f"UID {last_uid + 1}:*")
    else:
        last_uid = 0
        since = datetime.now() - timedelta(days=DAYS_BACK_FIRST_RUN)
        since_str = f"{since.day:02d}-{MONTHS[since.month - 1]}-{since.year}"
        _, data = imap.uid("search", None, f'(SINCE "{since_str}")')

    uids = sorted(int(u) for u in data[0].split() if int(u) > last_uid)
    batch = uids[:MAX_PER_RUN]
    print(f"{len(uids)} new emails, checking {len(batch)} this run.")

    added = updated = 0
    for uid in batch:
        last_uid = uid
        _, fetched = imap.uid("fetch", str(uid), "(RFC822)")
        raw = next((p[1] for p in fetched if isinstance(p, tuple)), None)
        if not raw:
            continue
        msg = email.message_from_bytes(raw)

        subject = decode(msg.get("Subject"))
        display_name, addr = parseaddr(decode(msg.get("From")))
        body = get_body(msg)
        text = (subject + " " + body).lower()

        if not any(w in text for w in JOB_WORDS):
            continue
        status = classify(subject, body)
        if not status:
            continue

        company = guess_company(subject, display_name, addr) or "(unknown)"
        role = guess_role(subject)
        row = tracker.find_row(company, role)

        if row:
            current = tracker.get(row, "status")
            if role and not tracker.get(row, "role"):
                tracker.set(row, "role", role)
            if status != current and \
                    STATUS_RANK.get(status, 0) >= STATUS_RANK.get(current, 0):
                tracker.change_status(row, status, current)
                updated += 1
                print(f"Updated: {tracker.get(row, 'company')} "
                      f"({tracker.get(row, 'role')}): {current} -> {status}")
        else:
            row = tracker.new_row()
            tracker.set(row, "company", company)
            tracker.set(row, "role", role or "(check email)")
            tracker.set(row, "date", stamp(email_datetime(msg)))
            tracker.change_status(row, status, "")
            added += 1
            print(f"Added:   {company} ({role or 'role unknown'}) -> {status}")

    imap.logout()

    if tracker.changes:
        tracker.save()
    save_state(state_ws, last_uid, uidvalidity)
    print(f"Done. {added} added, {updated} updated.")


if __name__ == "__main__":
    main()
