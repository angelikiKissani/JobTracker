"""Shared test helpers: build fake emails and a fake Tracker sheet."""

from email.message import EmailMessage

import pytest

from jobtracker.sheets import EmailLog, Tracker

HEADER = ["Company", "Title", "Status", "Job Posting Link", "Contact",
          "Application Date", "Location", "Interview Stage", "Interviewer",
          "Notes", "Application Week"]


def make_email(subject, body, sender="Careers <jobs@example.com>",
               html=None, date="Sun, 04 Oct 2026 12:58:00 +0300", charset="utf-8"):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["Date"] = date
    msg.set_content(body, charset=charset)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


@pytest.fixture
def tracker():
    rows = [
        HEADER,
        ["European Dynamics", "Python Developer", "Recruiter Screen", "", "",
         "2026-09-20 10:00:00", "Athens", "", "Lena Foliadi", "", "38"],
        ["Orfium", "Backend Software Engineer", "Rejected", "", "",
         "2026-09-10 09:00:00", "", "", "", "", "37"],
        ["", "", "Pending", "", "", "", "", "", "", "", ""],
        ["", "", "Pending", "", "", "", "", "", "", "", ""],
    ]
    return Tracker(rows)


@pytest.fixture
def log():
    return EmailLog()
