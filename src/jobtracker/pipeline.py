"""MAIN FLOW: read new emails, understand them, update the sheet."""

import os
from collections import Counter
from dataclasses import dataclass
from email.message import Message
from email.utils import parseaddr

from . import ai as ai_module
from . import config
from .extract import (
    apply_alias,
    classify,
    find_posting_link,
    guess_company,
    guess_role,
    is_job_related,
)
from .parsing import decode, email_datetime, email_text, get_body, stamp
from .sheets import EmailLog, Tracker


@dataclass
class Result:
    # RESULT OF EACH EMAIL
    action: str            # "added", "updated", "unchanged" or "skipped"
    subject: str = ""
    company: str = ""
    role: str = ""
    status: str = ""
    old_status: str = ""
    read_by: str = ""      # "AI" or "Rules"
    reason: str = ""       # why it was skipped

    @property
    def is_job_email(self) -> bool:
        # IF its a job email do not skip
        return self.action != "skipped"

    def describe(self) -> str:
        # describe action of the email
        if self.action == "added":
            return f"Added:   {self.company} ({self.role or 'role unknown'}) -> {self.status}"
        if self.action == "updated":
            return (f"Updated: {self.company} ({self.role}): "
                    f"{self.old_status} -> {self.status}")
        if self.action == "unchanged":
            return f"Seen:    {self.company} ({self.role}) stays {self.old_status}"
        return f"Skipped: {self.subject} ({self.reason})"


def understand(msg: Message, subject: str, display_name: str, addr: str, body: str,
               tracker: Tracker, ai_client=None) -> tuple[dict | None, str]:
    """Extract details with rules.
    Returns (details, read_by). 
    details is None when the email isn't an application update.
    """
    #classify -> 
    #guess_company ->                 
    #guess_role
                   
    status = classify(subject, body)
    if not status:
        return None, "Rules"
    return {"status": status,
            "company": guess_company(subject, display_name, addr, body),
            "job_title": guess_role(subject, body)}, "Rules"


def process_message(msg: Message, tracker: Tracker, log: EmailLog,
                    ai_client=None) -> Result:
    # Handle one email
    # update the Tracker and copy it to the Emails tab 

    #STEPS:
    #decode   -> 
    #parseaddr (email.utils) + decode->                         
    #get_body  -> 
    #understand  (classify, guess_company, guess_role)-> 
    #RETURN INFO AND GET STATUS, COMPANY, ROLE, ROW  -> 
                        
    subject = decode(msg.get("Subject"))
    display_name, addr = parseaddr(decode(msg.get("From")))
    body = get_body(msg)
    
    # action skipped if its not job related 
    if not is_job_related(subject, body):
        return Result("skipped", subject, reason="not job-related")
    info, read_by = understand(msg, subject, display_name, addr, body, tracker, ai_client)
    if info is None:
        return Result("skipped", subject, read_by=read_by,
                      reason=f"{read_by}: not an application update")

    status = info["status"]
    company = info.get("company") or "(unknown)"
    role = info.get("job_title")
    row = tracker.find_by_person(display_name, addr) or tracker.find_row(company, role)

    #UPDATE  action = "updated" or unchanged OR ADD NEW JOB APPLICATION
    if row:
        old = tracker.get(row, "status")
        if role and tracker.get(row, "role") in ("", config.PLACEHOLDER_ROLE):
            tracker.set(row, "role", role)
        if status != old and config.STATUS_RANK.get(status, 0) >= config.STATUS_RANK.get(old, 0):
            tracker.change_status(row, status, old)
            action = "updated"
        else:
            action = "unchanged"
    else:
        old = ""
        row = tracker.new_row()
        tracker.set(row, "company", company)
        tracker.set(row, "role", role or config.PLACEHOLDER_ROLE)
        tracker.set(row, "date", stamp(email_datetime(msg)))
        tracker.change_status(row, status, "")
        action = "added"

    _record_email(msg, tracker, log, row, status, info, read_by,
                  f"{display_name} <{addr}>".strip(), subject, body)
    return Result(action, subject, tracker.get(row, "company"), tracker.get(row, "role"),
                  status, old, read_by)


def _record_email(msg, tracker, log, row, status, info, read_by, sender, subject, body):
    """Copy the email to the Emails tab and fill optional Tracker columns."""
    email_row = log.add([stamp(email_datetime(msg)), tracker.get(row, "company"),
                         tracker.get(row, "role"), status, sender, subject,
                         email_text(body), info.get("summary", ""),
                         info.get("next_step", ""), info.get("interview_time", ""),
                         read_by])
    if tracker.has("email"):
        tracker.set(row, "email", log.link(email_row))
    if tracker.has("link") and not tracker.get(row, "link"):
        link = find_posting_link(msg, tracker.get(row, "role"))
        if link:
            tracker.set(row, "link", link)
    if tracker.has("contact") and not tracker.get(row, "contact") and info.get("contact_name"):
        contact = info["contact_name"]
        if info.get("contact_email"):
            contact += f" ({info['contact_email']})"
        tracker.set(row, "contact", contact)
    if tracker.has("location") and not tracker.get(row, "location") and info.get("location"):
        tracker.set(row, "location", info["location"])


def run() -> None:
    from . import sheets
    from .mailbox import Mailbox

    user = (os.environ.get("ICLOUD_EMAIL") or "").strip()
    password = (os.environ.get("ICLOUD_APP_PASSWORD") or "").strip().replace(" ", "")
    spreadsheet_id = (os.environ.get("SPREADSHEET_ID") or "").strip()
    if not user or not password or not spreadsheet_id:
        raise SystemExit("Missing ICLOUD_EMAIL, ICLOUD_APP_PASSWORD or SPREADSHEET_ID secret.")

    sh = sheets.open_spreadsheet(spreadsheet_id)
    tracker = Tracker.load(sh)
    log = EmailLog.load(sh)
    state_ws, state = sheets.load_state(sh)
    ai_client = ai_module.make_client()
    print("AI email understanding: " + ("on" if ai_client else "off (keyword rules)"))

    box = Mailbox(user, password)
    uids, last_uid = box.new_uids(int(state.get("last_uid") or 0),
                                  state.get("uidvalidity", ""))
    batch = uids[:config.MAX_PER_RUN]
    print(f"{len(uids)} new emails, checking {len(batch)} this run.")

    counts: Counter = Counter()
    to_move: list[int] = []
    for uid in batch:
        last_uid = uid
        msg = box.fetch(uid)
        if msg is None:
            continue
        result = process_message(msg, tracker, log, ai_client)
        counts[result.action] += 1
        if result.is_job_email:
            to_move.append(uid)
        if result.action != "skipped" or result.read_by == "AI":
            print(result.describe())

    # Save to the sheet first, so an email is only moved once it's recorded.
    log.save()
    tracker.save()
    sheets.save_state(state_ws, last_uid, box.uidvalidity)
    print(f"Done. {counts['added']} added, {counts['updated']} updated, "
          f"{counts['unchanged']} unchanged, {counts['skipped']} skipped.")

    try:
        box.move(to_move, config.MOVE_TO_FOLDER)
    except Exception as exc:  # never fail the run just because of moving
        print(f"Could not move emails: {exc}")
    box.logout()
