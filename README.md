# JobTracker

[![Tests](https://github.com/angelikiKissani/JobTracker/actions/workflows/tests.yml/badge.svg)](https://github.com/angelikiKissani/JobTracker/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)

An automated pipeline that reads job-application emails from my inbox, works out
what each one means, and keeps my job-search tracker in Google Sheets up to date —
no manual data entry.

Every hour, a GitHub Actions workflow checks for new emails, recognises
application confirmations, recruiter calls, interview invitations, rejections and
offers, and updates the matching row in the tracker. It runs entirely in the
cloud, for free.

> **Project status:** `v0.3.0` — rule-based baseline complete. Next phase:
> training a machine-learning classifier and measuring it against these rules.
> The [write-ups](#project-write-ups) document each step.

## Features

- **Automatic status tracking** — new applications are added; later emails move
  them through *Applied → Recruiter Screen → Interview → Offer / Rejected*.
  Statuses never move backwards (an old confirmation can't undo an interview).
- **Rule-based extraction** — keyword rules, sender-domain analysis and regex
  pattern matching on subjects and bodies work out the status, company and
  job title of each email.
- **Entity resolution** — emails from job platforms (Indeed, Workable,
  LinkedIn…), company domains, aliases (`eurodyn` → *European Dynamics*) and known
  interviewers are all matched to the same application, so three confirmation
  emails for one job produce one row.
- **Email archive** — each job email is copied into an *Emails* tab and linked
  from its tracker row; the job-posting link is extracted when present.
- **Inbox organisation** — processed job emails are moved to an *Applications*
  folder, only after they are safely recorded.
- **Incremental and idempotent** — tracks the last processed IMAP UID, so each
  email is handled exactly once, even across failures.

## Architecture

```mermaid
flowchart LR
    A[GitHub Actions<br/>hourly schedule] --> B[mailbox.py<br/>IMAP: fetch new emails]
    B --> C[parsing.py<br/>clean text and HTML]
    C --> F[extract.py<br/>rules and patterns]
    F --> G[pipeline.py<br/>match row, apply status rules]
    G --> H[sheets.py<br/>bulk-write Google Sheets]
    H --> I[mailbox.py<br/>move to Applications folder]
```

| Module | Responsibility |
|---|---|
| `config.py` | All settings: sheet layout, status rules, aliases, platform lists |
| `mailbox.py` | IMAP connection, incremental UID search, moving emails |
| `parsing.py` | Header decoding, plain-text / HTML extraction, encodings |
| `extract.py` | Rule-based status classification, company and title extraction |
| `sheets.py` | In-memory model of the sheet with batched writes |
| `pipeline.py` | Orchestration: one email in, one `Result` out |

### Project structure

```
JobTracker/
├── .github/workflows/
│   ├── job-tracker.yml   # hourly run: read emails, update the sheet
│   └── tests.yml         # lint and tests on every push
├── docs/                 # step-by-step project write-ups
├── src/jobtracker/       # the package (modules described above)
├── tests/                # unit and end-to-end pipeline tests
└── pyproject.toml        # dependencies and tool settings
```

The core logic (`process_message`) is pure: it takes an email and an in-memory
tracker and returns a result, which makes it fully testable without network access.

## Tech stack

Python 3.12 · IMAP · Google Sheets API (gspread) · GitHub Actions · pytest · ruff

## Setup

1. **Google Sheets** — create a service account in Google Cloud, enable the
   Sheets API, and share your sheet with the service account's email. The
   sheet needs a *Tracker* tab with the columns *Company*, *Title*, *Status* and
   *Application Date*; optional columns such as *Job Posting Link*, *Contact*,
   *Location* and *Email* are filled in when present.
2. **Mail** — create an app-specific password for your iCloud account.
3. **GitHub secrets** (*Settings → Secrets and variables → Actions*):

| Secret | Description |
|---|---|
| `ICLOUD_EMAIL` | Your iCloud Mail address |
| `ICLOUD_APP_PASSWORD` | App-specific password |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full contents of the service-account key file |
| `SPREADSHEET_ID` | The ID from the sheet's URL |

4. Run the **Job tracker** workflow from the *Actions* tab, or wait for the hourly run.

## Development

```bash
pip install -e ".[dev]"
pytest -v        # unit and pipeline tests
ruff check .     # linting
```

Every push runs the test suite and linter in CI.

## Privacy

Credentials live only in GitHub encrypted secrets, and personal data stays in a
private Google Sheet; nothing personal is stored in this repository. Emails are
read without being marked as read, and only emails that look job-related are
processed.

## Project write-ups

1. [Building the rule-based extraction engine](docs/01-rule-based-extraction.md)

## Roadmap

**Phase 1 — Rule-based baseline** ✅
- [x] Email reading, cleaning and rule-based extraction
- [x] Google Sheets sync, email archive and inbox organisation
- [x] Package structure, tests and CI

**Phase 2 — Machine learning**
- [ ] Build a labelled dataset from past and new emails
- [ ] Exploratory data analysis of the dataset
- [ ] Train a classifier (TF-IDF + logistic regression) and compare it with the rules
- [ ] Use the model in the pipeline, with confidence-based fallback to the rules
- [ ] Automatic weekly retraining with a metrics report

**Phase 3 — Analytics and demo**
- [ ] Analytics: application funnel, response rates by source, time-to-response
- [ ] Synthetic demo dataset so anyone can run the training and analysis
