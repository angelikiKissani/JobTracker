import pytest

from jobtracker.extract import (
    classify,
    find_posting_link,
    guess_company,
    guess_role,
    is_job_related,
    same_company,
)
from tests.conftest import make_email


@pytest.mark.parametrize("subject, body, expected", [
    ("Thank you for applying to Kpler!", "We received your application.", "Applied"),
    ("Indeed Application: Python Developer",
     "Application submitted. The following items were sent to Satori Analytics.", "Applied"),
    ("Your application", "Unfortunately we will not be moving forward.", "Rejected"),
    ("Interview invitation - Data Engineer", "We'd like to meet you.", "Interview"),
    ("Your application", "Do you have time for a quick call this week?", "Recruiter Screen"),
    ("Great news", "We are pleased to offer you the position.", "Offer"),
    ("Weekly digest", "Top stories this week.", None),
])
def test_classify(subject, body, expected):
    assert classify(subject, body) == expected


def test_rejection_wins_even_if_interview_is_mentioned():
    body = "Thank you for interviewing with us. Unfortunately we chose other candidates."
    assert classify("Update on your application", body) == "Rejected"


def test_mentioning_a_future_interview_is_still_applied():
    body = "Thank you for applying. If selected for an interview, we will contact you."
    assert classify("Application received", body) == "Applied"


@pytest.mark.parametrize("subject, name, addr, body, expected", [
    ("Interview", "HR", "hr@eurodyn.com", "", "European Dynamics"),      # alias
    ("Thanks for applying to Satori Analytics", "Workable",
     "noreply@candidates.workablemail.com", "", "Satori Analytics"),     # subject
    ("Python Developer - Satori Analytics", "Satori Analytics",
     "noreply@candidates.workablemail.com", "", "Satori Analytics"),     # dash subject
    ("Indeed Application: Python Developer", "Indeed Apply", "apply@indeed.com",
     "The following items were sent to Satori Analytics. Good luck!",
     "Satori Analytics"),                                                # body
    ("Hello", "Indeed Apply", "apply@indeed.com", "", None),             # platform only
])
def test_guess_company(subject, name, addr, body, expected):
    assert guess_company(subject, name, addr, body) == expected


@pytest.mark.parametrize("subject, body, expected", [
    ("Indeed Application: Python Developer", "", "Python Developer"),
    ("Python Developer - Satori Analytics", "", "Python Developer"),
    ("Your application for the Backend Engineer position at Printec", "", "Backend Engineer"),
    ("Thanks for applying", "Your application for the Data Analyst job was received.",
     "Data Analyst"),
    ("Thanks for applying", "We received it.", None),
])
def test_guess_role(subject, body, expected):
    assert guess_role(subject, body) == expected


def test_same_company_is_loose_but_not_too_loose():
    assert same_company("Aegean", "Aegeanair")
    assert same_company("Satori", "Satori Analytics")
    assert not same_company("AB", "ABC Corp")
    assert not same_company("", "Orfium")


def test_is_job_related():
    assert is_job_related("Your application", "")
    assert not is_job_related("Dinner on Friday?", "See you at 8")


def test_posting_link_matches_the_job_title():
    html = ('<p>Your application for the <a href="https://apply.workable.com/satori/j/ABC/">'
            'Python Developer</a> job</p><a href="https://workable.com/privacy">privacy</a>')
    msg = make_email("Thanks", "text", html=html)
    assert find_posting_link(msg, "Python Developer") == "https://apply.workable.com/satori/j/ABC/"


def test_posting_link_ignores_unrelated_links():
    msg = make_email("Thanks", "text", html='<a href="https://example.com/unsubscribe">x</a>')
    assert find_posting_link(msg, "Python Developer") is None
