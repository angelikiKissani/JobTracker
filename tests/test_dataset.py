from jobtracker import config
from jobtracker.dataset import build_row, email_id
from jobtracker.sheets import DatasetSheet
from tests.conftest import make_email


def test_application_email_gets_rule_label_and_prefilled_label():
    msg = make_email("Thanks for applying to Satori Analytics",
                     "Your application for the Python Developer job was submitted.")
    row = build_row(msg, "INBOX")
    assert len(row) == len(config.DATASET_HEADERS)
    assert row[2:5] == ["INBOX", "Careers <jobs@example.com>",
                        "Thanks for applying to Satori Analytics"]
    assert row[6] == row[7] == "Applied"   # Rule Label and Label
    assert row[8] is False                 # not reviewed yet


def test_job_alert_is_kept_as_not_an_update():
    msg = make_email("10 new Python positions for you", "Positions picked for you this week.")
    assert build_row(msg, "INBOX")[6] == config.NOT_UPDATE


def test_unrelated_email_is_not_in_the_dataset():
    assert build_row(make_email("Dinner on Friday?", "See you at 8!"), "INBOX") is None


def test_email_id_is_stable_and_unique():
    a = make_email("Subject A", "x")
    a["Message-ID"] = "<abc@mail.example.com>"
    b = make_email("Subject B", "x")
    b["Message-ID"] = "<xyz@mail.example.com>"
    assert email_id(a) == email_id(a)
    assert email_id(a) != email_id(b)
    assert len(email_id(a)) == 16


def test_dataset_skips_emails_it_already_has():
    msg = make_email("Your application", "Thank you for applying.")
    row = build_row(msg, "INBOX")
    dataset = DatasetSheet(existing_ids=["already-there"])
    assert dataset.add(row) is True
    assert dataset.add(row) is False       # same email again, e.g. after it was moved
    assert len(dataset.rows) == 1