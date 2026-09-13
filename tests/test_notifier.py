from email.utils import getaddresses

import pytest

from src.notifier import EmailConfigError, send_availability_email


class FakeSMTP:
    def __init__(self):
        self.started_tls = False
        self.login_args = None
        self.messages = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, message):
        self.messages.append(message)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("GMAIL_USER", "sender@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-password")
    monkeypatch.setenv("NOTIFY_EMAIL_TO", "me@example.com")


def test_sends_one_message_listing_every_date(env):
    fake = FakeSMTP()
    send_availability_email({"2026-12-16", "2026-12-15"}, smtp_factory=lambda: fake)

    assert len(fake.messages) == 1
    message = fake.messages[0]
    body = message.get_content()
    assert "2026-12-15" in body and "2026-12-16" in body
    assert body.index("2026-12-15") < body.index("2026-12-16")
    assert message["To"] == "me@example.com"
    assert message["From"] == "sender@gmail.com"
    assert "2" in message["Subject"]


def test_starts_tls_and_logs_in(env):
    fake = FakeSMTP()
    send_availability_email({"2026-12-15"}, smtp_factory=lambda: fake)
    assert fake.started_tls is True
    assert fake.login_args == ("sender@gmail.com", "app-password")


def test_no_dates_sends_nothing(env):
    fake = FakeSMTP()
    send_availability_email(set(), smtp_factory=lambda: fake)
    assert fake.messages == []


@pytest.mark.parametrize("missing", ["GMAIL_USER", "GMAIL_APP_PASSWORD", "NOTIFY_EMAIL_TO"])
def test_missing_secret_raises(env, monkeypatch, missing):
    monkeypatch.delenv(missing)
    with pytest.raises(EmailConfigError):
        send_availability_email({"2026-12-15"}, smtp_factory=lambda: FakeSMTP())


def test_secret_value_never_appears_in_error(env, monkeypatch):
    monkeypatch.delenv("NOTIFY_EMAIL_TO")
    with pytest.raises(EmailConfigError) as caught:
        send_availability_email({"2026-12-15"}, smtp_factory=lambda: FakeSMTP())
    assert "app-password" not in str(caught.value)


def _delivered_recipients(message):
    """Reproduce what smtplib.send_message actually delivers to, not just the header text."""
    return [addr for _name, addr in getaddresses(message.get_all("to"))]


@pytest.mark.parametrize("separator", [" ", ",", ";", "\t"])
def test_multiple_recipients_all_receive_the_message(env, monkeypatch, separator):
    monkeypatch.setenv("NOTIFY_EMAIL_TO", f"one@example.com{separator}two@example.com")
    fake = FakeSMTP()
    send_availability_email({"2026-12-15"}, smtp_factory=lambda: fake)

    message = fake.messages[0]
    assert _delivered_recipients(message) == ["one@example.com", "two@example.com"]


def test_ragged_recipients_produce_exactly_two_with_no_empty_entry(env, monkeypatch):
    monkeypatch.setenv("NOTIFY_EMAIL_TO", "  one@example.com   two@example.com  ")
    fake = FakeSMTP()
    send_availability_email({"2026-12-15"}, smtp_factory=lambda: fake)

    message = fake.messages[0]
    assert _delivered_recipients(message) == ["one@example.com", "two@example.com"]


def test_single_recipient_still_delivers_to_exactly_one(env):
    fake = FakeSMTP()
    send_availability_email({"2026-12-15"}, smtp_factory=lambda: fake)

    message = fake.messages[0]
    assert _delivered_recipients(message) == ["me@example.com"]


def test_separators_only_value_raises_email_config_error(env, monkeypatch):
    monkeypatch.setenv("NOTIFY_EMAIL_TO", " , ; ")
    with pytest.raises(EmailConfigError):
        send_availability_email({"2026-12-15"}, smtp_factory=lambda: FakeSMTP())
