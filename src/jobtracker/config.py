"""All tunable settings in one place."""

from zoneinfo import ZoneInfo

# --------------------------------------------------------------------------
# Google Sheet layout
# --------------------------------------------------------------------------
SHEET_NAME = "Tracker"
HISTORY_TAB = "StatusHistory"
MIRROR_TAB = "_StatusTracker"
STATE_TAB = "_tracker_state"
EMAILS_TAB = "Emails"

# Required columns in the Tracker tab (key -> header text).
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
    "contact": "Contact",
    "location": "Location",
}

# If an email comes from a person listed in one of these columns,
# it is matched to that row (interviewer at a company).
PEOPLE_COLUMNS = ["Contact", "Interviewer"]

EMAIL_HEADERS = [
    "Date", "Company", "Title", "Detected Status", "From", "Subject",
    "Email Text", "AI Summary", "Next Step", "Interview Time", "Read By",
]
EMAIL_TEXT_LIMIT = 3000  # characters of each email kept in the sheet

TIMEZONE = ZoneInfo("Europe/Athens")

# --------------------------------------------------------------------------
# Mailbox
# --------------------------------------------------------------------------
# The Application updates will be moved to folder Applications
IMAP_SERVER = "imap.mail.me.com"
IMAP_PORT = 993
MAILBOX = "INBOX"
MOVE_TO_FOLDER = "Applications" 
DAYS_BACK_FIRST_RUN = 30
MAX_PER_RUN = 300

# --------------------------------------------------------------------------
# Rule-based extraction
# --------------------------------------------------------------------------
# An email must contain at least one of these to be considered at all.
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
                 "thank you for applying", "thanks for applying",
                 "received your application", "your application",
                 "application for", "applied for", "candidacy"], []),
]
STATUSES = ["Applied", "Recruiter Screen", "Interview", "Offer", "Rejected"]

# Higher rank wins, an email never moves a job "backwards"
STATUS_RANK = {"": 0, "Pending": 0, "Ghosted": 0, "Applied": 1,
               "Recruiter Screen": 2, "Interview": 3, "Offer": 4,
               "Rejected": 4, "Dropped": 5}

# Names in emails (e.g. an email domain) -> the name used in your sheet.
COMPANY_ALIASES = {
    "eurodyn": "European Dynamics",
}

# Job platforms or personal mail providers
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

# Sender names of job platforms; NEVER treated as the company.
PLATFORM_NAMES = ["indeed", "indeed apply", "workable", "linkedin",
                  "linkedin jobs", "greenhouse", "lever", "smartrecruiters",
                  "teamtailor", "glassdoor", "kariera", "skywalker", "jobfind"]

# Links in an email that POINTS TO A JOB POSTING -> GET JOB LINK
JOB_LINK_HINTS = ["workable.com/j/", "apply.workable.com", "indeed.com/viewjob",
                  "indeed.com/rc/clk", "indeed.com/pagead", "linkedin.com/jobs/view",
                  "boards.greenhouse.io", "jobs.lever.co", "smartrecruiters.com/",
                  "teamtailor.com/jobs", "kariera.gr/jobs"]

PLACEHOLDER_ROLE = "(check email)"
