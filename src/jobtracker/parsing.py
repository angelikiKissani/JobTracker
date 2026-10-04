"""Turning raw email messages into clean text."""

import re
from datetime import datetime
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from html import unescape

from . import config


def decode(value: str | None) -> str:
    """Decode an encoded email header (e.g. '=?utf-8?...') into plain text."""
    try:
        return str(make_header(decode_header(value or ""))).strip()
    except Exception:
        return (value or "").strip()


def norm(text) -> str:
    """Lowercase and keep only letters/digits, for loose comparisons."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def flat(text: str | None) -> str:
    """Collapse all whitespace (including newlines) into single spaces."""
    return " ".join((text or "").split())


def flat_lines(text: str | None) -> str:
    """Collapse whitespace within lines and drop empty lines."""
    lines = [" ".join(line.split()) for line in (text or "").splitlines()]
    return "\n".join(line for line in lines if line)


def _decode_part(part: Message) -> str | None:
    payload = part.get_payload(decode=True)
    if payload is None:
        return None
    try:
        return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    except LookupError:  # unknown or unusual encoding name
        return payload.decode("utf-8", errors="replace")


def html_to_text(html: str) -> str:
    text = re.sub(r"<(script|style).*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return unescape(text)


def get_body(msg: Message) -> str:
    """Return the email's text, preferring the plain-text version."""
    plain, html = [], []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if "attachment" in str(part.get("Content-Disposition") or "").lower():
            continue
        text = _decode_part(part)
        if text is None:
            continue
        if part.get_content_type() == "text/plain":
            plain.append(text)
        elif part.get_content_type() == "text/html":
            html.append(text)
    if plain:
        return "\n".join(plain)
    return html_to_text("\n".join(html))


def get_html(msg: Message) -> str:
    """Return the email's raw HTML (empty if it has none)."""
    out = []
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            text = _decode_part(part)
            if text:
                out.append(text)
    return "\n".join(out)


def email_text(body: str, limit: int = config.EMAIL_TEXT_LIMIT) -> str:
    """Tidy email text for storing in the sheet, truncated to `limit` characters."""
    text = flat_lines(body)
    if len(text) > limit:
        text = text[:limit] + " …"
    return text


def email_datetime(msg: Message) -> datetime:
    try:
        return parsedate_to_datetime(msg["Date"]).astimezone(config.TIMEZONE)
    except Exception:
        return datetime.now(config.TIMEZONE)


def stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")
