"""Rule-based extraction: status, company, job title and posting link."""

import re
from email.message import Message
from html import unescape

from . import config
from .parsing import flat, get_html, norm

SKIP_SUBJECT_WORDS = ("thank", "application", "applying", "applied", "your",
                      "interview", "update", "invitation", "regarding", "re:")


def is_job_related(subject: str, body: str) -> bool:
    text = (subject + " " + body).lower()
    return any(word in text for word in config.JOB_WORDS)


def classify(subject: str, body: str) -> str | None:
    # find the status
    subj, full = subject.lower(), (subject + " " + body).lower()
    for status, anywhere, subject_only in config.STATUS_RULES:
        if any(p in full for p in anywhere) or any(p in subj for p in subject_only):
            return status
    return None


def same_company(a: str, b: str) -> bool:
    # Loose match, find company
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = sorted([a, b], key=len)
    return len(shorter) >= 3 and shorter in longer


def apply_alias(company: str | None) -> str | None:
  # find company alias
    if not company:
        return company
    for alias, real in config.COMPANY_ALIASES.items():
        if norm(alias) == norm(company):
            return real
    return company


def domain_company(addr: str) -> str | None:
    # find domain
    domain = addr.split("@")[-1].lower()
    if any(domain == g or domain.endswith("." + g) for g in config.GENERIC_DOMAINS):
        return None
    parts = domain.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "ac", "net"):
        root = parts[-3]
    elif len(parts) >= 2:
        root = parts[-2]
    else:
        return None
    return root.replace("-", " ").title()


def clean_display_name(name: str) -> str:
  # clean the name of the company
    for sep in (" from ", " at ", " via "):
        if sep in name.lower():
            idx = name.lower().index(sep)
            name = name[idx + len(sep):] if sep != " via " else name[:idx]
    name = re.sub(r"\b(careers?|jobs?|recruit(ing|ment|er)?|talent( acquisition)?|"
                  r"hiring( team)?|hr|people|team|no[- ]?reply|notifications?)\b",
                  " ", name, flags=re.I)
    name = re.sub(r"[|\-–:,@]+", " ", name)
    return " ".join(name.split())


def subject_dash_split(subject: str) -> tuple[str | None, str | None]:
    # regex find company and position Job Title - Company
    m = re.match(r"^\s*(.{3,80}?)\s+[-–|]\s+(.{2,60}?)\s*$", subject)
    if not m:
        return None, None
    left, right = m.group(1).strip(), m.group(2).strip()
    if any(w in left.lower() for w in SKIP_SUBJECT_WORDS):
        return None, None
    return left, right


def guess_company(subject: str, display_name: str, addr: str, body: str = "") -> str | None:
    return apply_alias(_guess_company(subject, display_name, addr, body))


def _guess_company(subject: str, display_name: str, addr: str, body: str) -> str | None:
    company = domain_company(addr)
    if company:
        return company
    for word in ("at", "to", "with", "from"):
        m = re.search(rf"\b{word}\s+([A-Z][\w&.'’ ]{{1,40}}?)\s*(?:[!.,:|\-–]|$)", subject)
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
    if name and name.lower() not in config.PLATFORM_NAMES:
        return name
    return None


def guess_role(subject: str, body: str = "") -> str | None:
    m = re.match(r"^\s*indeed application:\s*(.{3,80})$", subject, flags=re.I)
    if m:
        return m.group(1).strip()
    left, _ = subject_dash_split(subject)
    if left:
        return left
    subject_patterns = [
        r"(?:for|as)\s+(?:the\s+|a\s+|an\s+)?(.+?)\s+(?:position|role|job|opening)\b",
        r"application(?:\s+\w+)?\s+for\s+(?:the\s+)?(.+?)(?:\s+(?:at|with)\s+|\s+[-–|]\s+|$)",
        r"(?:applying|applied)\s+(?:for|to)\s+(?:the\s+)?(.+?)\s+(?:at|with)\s+",
        r"application\s+as\s+(?:an?\s+)?(.+?)(?:\s+(?:at|with)\s+|\s+[-–|]\s+|$)"
    ]
    for p in subject_patterns:
        m = re.search(p, subject, flags=re.I)
        if m and 2 < len(m.group(1)) < 80:
            return m.group(1).strip(" -–|:")
    text = flat(body)[:5000]
    body_patterns = [
        r"application (?:for|to) (?:the |our )?([A-Z][^.\n]{2,60}?) "
        r"(?:job|position|role|opening)\b",
        r"applying (?:for|to) (?:the |our )?([A-Z][^.\n]{2,60}?) "
        r"(?:job|position|role|opening)\b",
    ]
    for p in body_patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()
    return None


def find_posting_link(msg: Message, role: str | None) -> str | None:
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
        if any(h in low for h in config.JOB_LINK_HINTS) and \
                not any(x in low for x in ("unsubscribe", "privacy", "settings")):
            return href
    return None
