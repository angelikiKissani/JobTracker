"""Reading and moving emails from icloud email using IMAP"""

import email
import imaplib
from datetime import datetime, timedelta
from email.message import Message

from . import config

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# IMAP search dates must use English month names
def imap_date(dt: datetime) -> str:
    return f"{dt.day:02d}-{MONTHS[dt.month - 1]}-{dt.year}"


class Mailbox:
    # Connect to IMAP, Read-only emails-> not marked as read
    def __init__(self, user: str, password: str,
                 server: str = config.IMAP_SERVER, port: int = config.IMAP_PORT):
        self.imap = imaplib.IMAP4_SSL(server, port)
        self.imap.login(user, password)
       
        self.imap.select(config.MAILBOX, readonly=True)
        resp = self.imap.response("UIDVALIDITY")[1] #reading the server's reply
        self.uidvalidity = (resp[0] or b"").decode() if resp else ""  #turning it into usable text



          # Every email in a folder has a UID, a number that only goes up
          # The script saves the highest UID it has processed in the hidden _tracker_state tab
          # and next run it asks for "everything after that number."
          
    # Get the next uids, finds all the emails that are not read and downloads them       
    def new_uids(self, last_uid: int, saved_uidvalidity: str) -> tuple[list[int], int]:
        
        if last_uid and saved_uidvalidity == self.uidvalidity:
            _, data = self.imap.uid("search", None, f"UID {last_uid + 1}:*") 
                  #asks the server for every email from the next UID onwards
        else:
            #fisrt run
            last_uid = 0
            since = datetime.now() - timedelta(days=config.DAYS_BACK_FIRST_RUN)
            _, data = self.imap.uid("search", None, f'(SINCE "{imap_date(since)}")') 

              
        # read the result, the server replies with UIDs in one block of bytes, 
              # such as [b"101 102 105"]
        # This takes that block, splits it into [b"101", b"102", b"105"]
        raw = (data[0] or b"").split() if data else [] 
        return sorted(int(u) for u in raw if int(u) > last_uid), last_uid

    # download one email
    def fetch(self, uid: int) -> Message | None:
        _, fetched = self.imap.uid("fetch", str(uid), "(RFC822)")
              
        # The actual email is the second item of the tuple. 
# This line goes through the reply, finds the first tuple, takes its email bytes
        raw = next((p[1] for p in fetched if isinstance(p, tuple)), None)
        return email.message_from_bytes(raw) if raw else None

    def move(self, uids: list[int], folder: str | None) -> None:
        # Move emails out of the inbox into Applications Folder (created if missing).
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
