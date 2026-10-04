"""Reading and moving emails over IMAP (iCloud Mail by default)."""

import email
import imaplib
from datetime import datetime, timedelta
from email.message import Message

from . import config

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def imap_date(dt: datetime) -> str:
    """IMAP search dates must use English month names, e.g. 04-Oct-2026."""
    return f"{dt.day:02d}-{MONTHS[dt.month - 1]}-{dt.year}"


class Mailbox:
    def __init__(self, user: str, password: str,
                 server: str = config.IMAP_SERVER, port: int = config.IMAP_PORT):
        self.imap = imaplib.IMAP4_SSL(server, port)
        self.imap.login(user, password)
        # Read-only while reading, so nothing is marked as read.
        self.imap.select(config.MAILBOX, readonly=True)
        resp = self.imap.response("UIDVALIDITY")[1]
        self.uidvalidity = (resp[0] or b"").decode() if resp else ""

    def new_uids(self, last_uid: int, saved_uidvalidity: str) -> tuple[list[int], int]:
        """UIDs of emails newer than `last_uid` (or of the last N days on a first run).

        Returns (uids, effective_last_uid); the latter is reset to 0 when the
        mailbox's UIDVALIDITY changed and we fall back to a date search.
        """
        if last_uid and saved_uidvalidity == self.uidvalidity:
            _, data = self.imap.uid("search", None, f"UID {last_uid + 1}:*")
        else:
            last_uid = 0
            since = datetime.now() - timedelta(days=config.DAYS_BACK_FIRST_RUN)
            _, data = self.imap.uid("search", None, f'(SINCE "{imap_date(since)}")')
        raw = (data[0] or b"").split() if data else []
        return sorted(int(u) for u in raw if int(u) > last_uid), last_uid

    def fetch(self, uid: int) -> Message | None:
        _, fetched = self.imap.uid("fetch", str(uid), "(RFC822)")
        raw = next((p[1] for p in fetched if isinstance(p, tuple)), None)
        return email.message_from_bytes(raw) if raw else None

    def move(self, uids: list[int], folder: str | None) -> None:
        """Move emails out of the inbox into `folder` (created if missing)."""
        if not uids or not folder:
            return
        quoted = '"' + folder.replace('"', "") + '"'
        self.imap.create(quoted)          # fails harmlessly if it exists
        self.imap.select(config.MAILBOX)  # read-write, needed to move
        uid_set = ",".join(str(u) for u in uids)
        caps = set(self.imap.capabilities)
        if "MOVE" in caps:
            typ, data = self.imap.uid("MOVE", uid_set, quoted)
        elif "UIDPLUS" in caps:
            typ, data = self.imap.uid("COPY", uid_set, quoted)
            if typ == "OK":
                self.imap.uid("STORE", uid_set, "+FLAGS", r"(\Deleted)")
                typ, data = self.imap.uid("EXPUNGE", uid_set)
        else:
            typ, data = self.imap.uid("COPY", uid_set, quoted)
            print("Server can't move safely; emails were copied, not moved.")
        if typ == "OK":
            print(f"Moved {len(uids)} email(s) to {folder}.")
        else:
            print(f"Could not move emails to {folder}: {data}")

    def logout(self) -> None:
        try:
            self.imap.logout()
        except Exception:
            pass
