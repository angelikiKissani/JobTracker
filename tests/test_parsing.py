from jobtracker.parsing import email_text, flat_lines, get_body, norm
from tests.conftest import make_email


def test_prefers_plain_text_over_html():
    msg = make_email("Hi", "plain version", html="<p>html version</p>")
    assert get_body(msg).strip() == "plain version"


def test_html_only_email_is_converted_to_text():
    msg = make_email("Hi", "x")
    msg.set_content("<style>p{color:red}</style><p>Hello&nbsp;<b>there</b></p>",
                    subtype="html")
    text = " ".join(get_body(msg).split())
    assert text == "Hello there"
    assert "color" not in text


def test_unknown_charset_does_not_crash():
    msg = make_email("Hi", "hello")
    msg.replace_header("Content-Type", 'text/plain; charset="unknown-8bit"')
    assert get_body(msg).strip() == "hello"


def test_email_text_is_tidied_and_truncated():
    assert flat_lines("Hi   there\n\n\n  you ") == "Hi there\nyou"
    assert email_text("a" * 50, limit=10) == "a" * 10 + " …"


def test_norm_ignores_case_and_punctuation():
    assert norm("EveryPay (Skroutz)") == "everypayskroutz"
