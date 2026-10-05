"""End-to-end tests of email -> sheet updates, without any network access."""

from jobtracker.pipeline import process_message
from tests.conftest import make_email

WORKABLE = "Workable <noreply@candidates.workablemail.com>"


def test_new_application_fills_first_blank_row(tracker, log):
    msg = make_email("Thanks for applying to Satori Analytics",
                     "Your application for the Python Developer job was submitted "
                     "successfully.", sender=WORKABLE)
    result = process_message(msg, tracker, log)

    assert result.action == "added"
    assert tracker.rows[3][:3] == ["Satori Analytics", "Python Developer", "Applied"]
    assert tracker.rows[3][5] == "2026-10-04 12:58:00"
    assert tracker.history[-1][1:] == ["Satori Analytics", "Python Developer", "", "Applied"]
    assert len(log.rows) == 1


def test_three_emails_for_one_application_make_one_row(tracker, log):
    emails = [
        make_email("Indeed Application: Python Developer",
                   "Application submitted. The following items were sent to "
                   "Satori Analytics. Good luck!", sender="Indeed Apply <apply@indeed.com>"),
        make_email("Thanks for applying to Satori Analytics",
                   "Your application for the Python Developer job was submitted.",
                   sender=WORKABLE),
        make_email("Python Developer - Satori Analytics",
                   "Thank you for submitting your application to our Python Developer "
                   "position.", sender=f"Satori Analytics <{WORKABLE.split('<')[1]}"),
    ]
    actions = [process_message(m, tracker, log).action for m in emails]

    assert actions == ["added", "unchanged", "unchanged"]
    satori = [r for r in tracker.rows if r[0] == "Satori Analytics"]
    assert len(satori) == 1


def test_rejection_updates_existing_row(tracker, log):
    msg = make_email("Your application", "Unfortunately we will not be moving forward.",
                     sender="HR <hr@eurodyn.com>")
    result = process_message(msg, tracker, log)

    assert result.action == "updated"
    assert (result.old_status, result.status) == ("Recruiter Screen", "Rejected")
    assert tracker.rows[1][2] == "Rejected"
    assert tracker.mirror[(2, 3)] == "Rejected"


def test_status_never_moves_backwards(tracker, log):
    msg = make_email("Application received", "Thank you for applying.",
                     sender="HR <hr@eurodyn.com>")
    assert process_message(msg, tracker, log).action == "unchanged"
    assert tracker.rows[1][2] == "Recruiter Screen"


def test_email_from_known_interviewer_matches_their_row(tracker, log):
    msg = make_email("Next steps", "We'd like to schedule an interview with the team.",
                     sender="Lena Foliadi <lena@gmail.com>")
    result = process_message(msg, tracker, log)
    assert result.company == "European Dynamics"
    assert result.status == "Interview"


def test_non_job_email_is_skipped(tracker, log):
    msg = make_email("Dinner on Friday?", "See you at 8!")
    assert process_message(msg, tracker, log).action == "skipped"
    assert not tracker.changes and not log.rows

