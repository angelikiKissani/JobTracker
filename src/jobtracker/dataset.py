import hashlib
from email.Message import Message   
from email.Utils import parseaddr


from . import config 
from .extract import classify, is_job_related
from .parsing import decode, email_datetime, email_text, get_body, stamp


def email_id(msg: Message) -> str :
    # stable email ID to avoid duplicates
    key = (msg.get("Message-ID") or "").strip
    if not key:
        key = "|".join(str(msg.get(h, "")) for h in ("From", "Date", "Subject"))
    return hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:16]


def build_row(msg: Message, folder: str) -> list | None:
    # row for a new job appl or no row for unrelated email
    subject = decode(msg.get("Subject"))
    display_name, addr = parseaddr(decode(msg.get("From")))
    body = get_body(msg)
    if not is_job_related(subject, body):
        return None
    rule_label = classify(subject, body) or config.NOT_UPDATE
    return [email_id(msg), stamp(email_datetime(msg)), folder,
            f"{display_name} <{addr}>".strip(), subject, email_text(body),
            rule_label, rule_label, False]