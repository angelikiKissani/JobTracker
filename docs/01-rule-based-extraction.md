# 01 — Building the Rule-Based Extraction Engine

## The problem

Job-search emails arrive from many sources directly from companies, and
through platforms such as Workable, Indeed and LinkedIn — each in its own format.
The original idea was for my job-application tracker in Google Sheets to be updated itself 
from these emails, instead of me entering every application and status change by hand.

## The approach

The idea was to build a rule-based engine that extracts the useful information
from each email: the company, the job title and the status of the application.
Before any rules can run, the email has to be properly decoded and cleaned,  
headers decoded, the plain-text or HTML version picked and HTML converted to
readable text.

Once an email is confirmed to be job-related and we have it's information extracted, the
pipeline finds the matching row in the Google Sheet and updates it or adds a new
row in case it's a new application.

The pipeline, which runs hourly on GitHub Actions:

1. **Read** new emails from iCloud Mail over IMAP, using the last processed UID so
   each email is handled exactly once.
2. **Clean** the text: decode headers and character sets, prefer plain text,
   strip HTML.
3. **Filter**: skip emails that contain none of the job-related keywords.
4. **Classify the status** with ordered keyword rules: Rejected, Offer, Interview,
   Recruiter Screen, Applied. The first match wins, so a rejection that mentions
   "your interview" is still a rejection.
5. **Extract the company and job title** from the sender's email domain, subject
   patterns such as "Python Developer - Satori Analytics", and phrases in the body
   such as "sent to Satori Analytics".
6. **Match** the email to an existing row by company, job title or a known
   contact, then update the status or add a new row.
7. **Save** all changes to the sheet in bulk, then move the email to an
   *Applications* folder.

## Challenges

**Unusual text encodings.** Some emails declared character sets Python didn't
recognise, which crashed the whole run. Decoding now falls back to UTF-8, and
broken characters are replaced instead of raising an error.

**Empty search results.** When there were no new emails, iCloud returned an empty
value instead of an empty list, so every scheduled run failed on quiet hours. The
search result is now handled safely in both forms.

**Several emails for one application.** Applying to a company through
Indeed produced three emails: from Indeed, from Workable and from the company.
Each named the company and role differently. Extracting the company from the body
and from "Title - Company" subjects lets all three resolve to the same row.

**Platforms mistaken for companies.** Early versions recorded "Indeed Apply" as
the employer. Platform domains and sender names are now kept in lists and never
treated as the company.

**Emails from people, not companies.** Recruiters and interviewers often write
from personal addresses. If the sender appears in the Contact or Interviewer
column, the email is matched to that row.

**Statuses moving backwards.** A late "application received" email could
overwrite an interview. Statuses now have a rank, and an email can only move an
application forward.

All of these cases are covered by automated tests that run on every commit.

## Limitations

The rules work well for the emails I have seen, but they have clear limits:

- **They are brittle.** New wording that isn't in the keyword lists is missed.
- **They need manual upkeep.** Every new platform, alias or phrasing means
  editing the configuration.
- **They struggle with context.** A job alert listing "positions" and a real
  application update can share the same words, and telling them apart would
  need more and more special cases.

These limits are the motivation for the next step: training a machine-learning
model on my own labelled emails and measuring whether it can beat these rules,
which now serve as the baseline.
