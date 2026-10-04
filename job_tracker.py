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
  - Fills "Job Posting Link" (if empty) with the job link found in the email.
  - Copies every job email into an "Emails" tab, and puts a "View email"
    link in the Tracker's "Email" column (if you add a column with that name).
  - Never touches Application Week, Notes or other columns.
Progress is stored in a hidden tab called "_tracker_state".
Job emails are moved to the folder set in MOVE_TO_FOLDER (created if it
doesn't exist) after the sheet has been updated. Emails are NOT marked as read.
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
# Job emails are moved here after they're recorded. Set to None to keep
# them in the inbox.
MOVE_TO_FOLDER = "Applications"
DAYS_BACK_FIRST_RUN = 30
MAX_PER_RUN = 300

COLUMNS = {
    "company": "Company",
    "role": "Title",
    "status": "Status",
    "date": "Application Date",
}

# Filled only if these headers exist in the Tracker tab.
OPTIONAL_COLUMNS = {
    "link": "Job Posting Link",
    "email": "Email",
}

EMAILS_TAB = "Emails"
EMAIL_HEADERS = ["Date", "Company", "Title", "Detected Status", "From",
                 "Subject", "Email Text"]
EMAIL_TEXT_LIMIT = 3000   # characters of each email kept in the sheet

# Links in an email that point to a job posting on these sites.
JOB_LINK_HINTS = ["workable.com/j/", "apply.workable.com", "indeed.com/viewjob",
                  "indeed.com/rc/clk", "indeed.com/pagead", "linkedin.com/jobs/view",
                  "boards.greenhouse.io", "jobs.lever.co", "smartrecruiters.com/",
                  "teamtailor.com/jobs", "kariera.gr/jobs"]

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
    ("Applied", ["application received", "application submitted",
                 "submitted successfully", "submitting your application",
                 "thank you for applying",
                 "thanks for applying", "received your application",
                 "your application", "application for", "applied for",
                 "candidacy"], []),
]

# Higher rank wins; an email never moves a job "backwards".
STATUS_RANK = {"": 0, "Pending": 0, "Ghosted": 0, "Applied": 1,
               "Recruiter Screen": 2, "Interview": 3, "Offer": 4,
               "Rejected": 4, "Dropped": 5}

# Names that should count as the same company as a name in your sheet.
# Left side: what appears in emails (e.g. the email domain), right side:
# the name used in your sheet.
COMPANY_ALIASES = {
    "eurodyn": "European Dynamics",
}

# If an email comes from a person listed in one of these columns,
# it is matched to that row (e.g. your interviewer at a company).
PEOPLE_COLUMNS = ["Contact", "Interviewer"]

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
        try:
            text = payload.decode(part.get_content_charset() or "utf-8",
                                  errors="replace")
        except LookupError:  # unknown/unusual encoding name
            text = payload.decode("utf-8", errors="replace")
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


def get_html(msg):
    out = []
    for part in msg.walk():
        if part.get_content_type() != "text/html":
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        try:
            out.append(payload.decode(part.get_content_charset() or "utf-8",
                                      errors="replace"))
        except LookupError:
            out.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(out)


def find_posting_link(msg, role):
    """Return the job-posting link in the email, if there is one."""
    html = get_html(msg)
    if not html:
        return None
    anchors = re.findall(r'<a\b[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                         html, flags=re.S | re.I)
    links = []
    for href, label in anchors:
        href = unescape(href).strip()
        if not href.lower().startswith("http"):
            continue
        label = " ".join(unescape(re.sub(r"<[^>]+>", " ", label)).split())
        links.append((href, label))
    if role:
        for href, label in links:
            if norm(label) and norm(label) == norm(role):
                return href
    for href, _ in links:
        low = href.lower()
        if any(h in low for h in JOB_LINK_HINTS) and \
                not any(x in low for x in ("unsubscribe", "privacy", "settings")):
            return href
    return None


def email_text(body):
    lines = [" ".join(line.split()) for line in body.splitlines()]
    text = "\n".join(line for line in lines if line)
    if len(text) > EMAIL_TEXT_LIMIT:
        text = text[:EMAIL_TEXT_LIMIT] + " …"
    return text


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


def apply_alias(company):
    if not company:
        return company
    for alias, real in COMPANY_ALIASES.items():
        if norm(alias) == norm(company):
            return real
    return company


# Sender names of job platforms; never treated as the company.
PLATFORM_NAMES = ["indeed", "indeed apply", "workable", "linkedin",
                  "linkedin jobs", "greenhouse", "lever", "smartrecruiters",
                  "teamtailor", "glassdoor", "kariera", "skywalker", "jobfind"]

SKIP_SUBJECT_WORDS = ("thank", "application", "applying", "applied", "your",
                      "interview", "update", "invitation", "regarding", "re:")


def flat(text):
    return " ".join((text or "").split())


def subject_dash_split(subject):
    """'Python Developer - Satori Analytics' -> ('Python Developer', 'Satori Analytics')"""
    m = re.match(r"^\s*(.{3,80}?)\s+[-–|]\s+(.{2,60}?)\s*$", subject)
    if not m:
        return None, None
    left, right = m.group(1).strip(), m.group(2).strip()
    if any(w in left.lower() for w in SKIP_SUBJECT_WORDS):
        return None, None
    return left, right


def guess_company(subject, display_name, addr, body=""):
    return apply_alias(_guess_company(subject, display_name, addr, body))


def _guess_company(subject, display_name, addr, body=""):
    company = domain_company(addr)
    if company:
        return company
    for word in ("at", "to", "with", "from"):
        m = re.search(rf"\b{word}\s+([A-Z][\w&.'’ ]{{1,40}}?)\s*(?:[!.,:|\-–]|$)",
                      subject)
        if m:
            return m.group(1).strip()
    _, right = subject_dash_split(subject)
    if right:
        return right
    m = re.search(r"\b(?:were sent to|was sent to|submitted to|sent to)\s+"
                  r"([A-Z][\w&.'’ ]{1,40}?)\s*[.!,]", flat(body)[:5000])
    if m:
        return m.group(1).strip()
    name = clean_display_name(display_name)
    if name and name.lower() not in PLATFORM_NAMES:
        return name
    return None


def guess_role(subject, body=""):
    m = re.match(r"^\s*indeed application:\s*(.{3,80})$", subject, flags=re.I)
    if m:
        return m.group(1).strip()
    left, _ = subject_dash_split(subject)
    if left:
        return left
    patterns = [
        r"(?:for|as)\s+(?:the\s+|a\s+|an\s+)?(.+?)\s+(?:position|role|job|opening)\b",
        r"application(?:\s+\w+)?\s+for\s+(?:the\s+)?(.+?)(?:\s+(?:at|with)\s+|\s+[-–|]\s+|$)",
        r"(?:applying|applied)\s+(?:for|to)\s+(?:the\s+)?(.+?)\s+(?:at|with)\s+",
    ]
    for p in patterns:
        m = re.search(p, subject, flags=re.I)
        if m and 2 < len(m.group(1)) < 80:
            return m.group(1).strip(" -–|:")
    text = flat(body)[:5000]
    for p in [r"application (?:for|to) (?:the |our )?([A-Z][^.\n]{2,60}?) "
              r"(?:job|position|role|opening)\b",
              r"applying (?:for|to) (?:the |our )?([A-Z][^.\n]{2,60}?) "
              r"(?:job|position|role|opening)\b"]:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()
    return None


def email_datetime(msg):
    try:
        return parsedate_to_datetime(msg["Date"]).astimezone(TIMEZONE)
    except Exception:
        return datetime.now(TIMEZONE)


def stamp(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ------------------------- google sheet --------------------------------
def move_emails(imap, uids, folder):
    """Move the given emails out of the inbox into `folder`."""
    if not uids or not folder:
        return
    quoted = '"' + folder.replace('"', "") + '"'
    imap.create(quoted)                   # fails harmlessly if it exists
    imap.select(MAILBOX)                  # read-write, needed to move
    uid_set = ",".join(str(u) for u in uids)
    caps = set(imap.capabilities)
    if "MOVE" in caps:
        typ, data = imap.uid("MOVE", uid_set, quoted)
    elif "UIDPLUS" in caps:
        typ, data = imap.uid("COPY", uid_set, quoted)
        if typ == "OK":
            imap.uid("STORE", uid_set, "+FLAGS", r"(\Deleted)")
            typ, data = imap.uid("EXPUNGE", uid_set)
    else:
        typ, data = imap.uid("COPY", uid_set, quoted)
        print("Server can't move safely; emails were copied, not moved.")
    if typ == "OK":
        print(f"Moved {len(uids)} email(s) to {folder}.")
    else:
        print(f"Could not move emails to {folder}: {data}")


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


class EmailLog:
    """Copies job emails into the Emails tab."""

    def __init__(self, sh):
        ws = optional_tab(sh, EMAILS_TAB)
        if ws is None:
            ws = sh.add_worksheet(title=EMAILS_TAB, rows=200,
                                  cols=len(EMAIL_HEADERS))
            ws.update(range_name="A1", values=[EMAIL_HEADERS])
            try:
                ws.freeze(rows=1)
            except Exception:
                pass
        self.ws = ws
        self.next_row = len(ws.col_values(1)) + 1
        self.rows = []

    def add(self, values):
        self.rows.append(values)
        return self.next_row + len(self.rows) - 1

    def link(self, r):
        return f'=HYPERLINK("#gid={self.ws.id}&range=A{r}", "View email")'

    def save(self):
        if not self.rows:
            return
        last = self.next_row + len(self.rows) - 1
        if last > self.ws.row_count:
            self.ws.add_rows(last - self.ws.row_count + 100)
        self.ws.update(range_name=f"A{self.next_row}", values=self.rows,
                       value_input_option="RAW")


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

        for key, name in OPTIONAL_COLUMNS.items():
            if name in header:
                self.col[key] = header.index(name)
        self.people_cols = [header.index(c) for c in PEOPLE_COLUMNS if c in header]
        self.width = max(len(r) for r in self.rows)
        for row in self.rows:
            row.extend([""] * (self.width - len(row)))

        self.changes = {}       # (row, col) 1-based -> value, Tracker tab
        self.mirror = {}        # (row, col) 1-based -> value, _StatusTracker
        self.history = []       # rows for StatusHistory

    def has(self, key):
        return key in self.col

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
                if existing_role == "(check email)":
                    existing_role = ""
                if role and existing_role and norm(role) != norm(existing_role):
                    continue
                return r
        return None

    def find_by_person(self, display_name, addr):
        name, addr = norm(display_name), (addr or "").lower()
        for r in range(len(self.rows) - 1, 0, -1):
            for c in self.people_cols:
                cell = self.rows[r][c]
                if not cell.strip():
                    continue
                if (len(name) >= 5 and norm(cell) == name) or \
                        (addr and addr in cell.lower()):
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
    spreadsheet_id = os.environ.get("SPREADSHEET_ID")
    if not user or not password or not spreadsheet_id:
        sys.exit("Missing ICLOUD_EMAIL, ICLOUD_APP_PASSWORD or SPREADSHEET_ID secret.")

    sh = google_client().open_by_key(spreadsheet_id)
    tracker = Tracker(sh)
    log = EmailLog(sh)
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

    uids = sorted(int(u) for u in ((data[0] or b"").split() if data else [])
                  if int(u) > last_uid)
    batch = uids[:MAX_PER_RUN]
    print(f"{len(uids)} new emails, checking {len(batch)} this run.")

    added = updated = 0
    to_move = []
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
        to_move.append(uid)

        company = guess_company(subject, display_name, addr, body) or "(unknown)"
        role = guess_role(subject, body)
        row = tracker.find_by_person(display_name, addr) or \
            tracker.find_row(company, role)

        if row:
            current = tracker.get(row, "status")
            if role and tracker.get(row, "role") in ("", "(check email)"):
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

        # Keep a copy of the email and link it from the Tracker row.
        email_row = log.add([stamp(email_datetime(msg)), tracker.get(row, "company"),
                             tracker.get(row, "role"), status,
                             f"{display_name} <{addr}>".strip(), subject,
                             email_text(body)])
        if tracker.has("email"):
            tracker.set(row, "email", log.link(email_row))
        if tracker.has("link") and not tracker.get(row, "link"):
            link = find_posting_link(msg, role or tracker.get(row, "role"))
            if link:
                tracker.set(row, "link", link)

    # Save to the sheet first, so an email is only moved once it's recorded.
    log.save()
    if tracker.changes:
        tracker.save()
    save_state(state_ws, last_uid, uidvalidity)
    print(f"Done. {added} added, {updated} updated.")

    try:
        move_emails(imap, to_move, MOVE_TO_FOLDER)
    except Exception as exc:  # never fail the run just because of moving
        print(f"Could not move emails: {exc}")
    imap.logout()


if __name__ == "__main__":
    main()
