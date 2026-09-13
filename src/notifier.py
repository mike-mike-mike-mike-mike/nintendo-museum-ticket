import os
import smtplib
from email.message import EmailMessage

from utils.logging_setter import setup_logger

logger = setup_logger("nintendo_notifier", "nintendo_notifier.log")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
BOOKING_URL = "https://museum-tickets.nintendo.com/en/calendar"


class EmailConfigError(Exception):
    """A required email environment variable is missing."""


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise EmailConfigError(f"environment variable {name} is not set")
    return value


def _build_message(new_dates: list[str], sender: str, recipient: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = f"Nintendo Museum: {len(new_dates)} new date(s) available"
    message["From"] = sender
    message["To"] = recipient
    lines = [
        "Newly available Nintendo Museum ticket dates:",
        "",
        *(f"  - {date}" for date in new_dates),
        "",
        f"Book here: {BOOKING_URL}",
    ]
    message.set_content("\n".join(lines))
    return message


def send_availability_email(new_dates: set[str], smtp_factory=None) -> None:
    """Send one email listing every newly available date. No dates, no email."""
    if not new_dates:
        return

    sender = _require("GMAIL_USER")
    password = _require("GMAIL_APP_PASSWORD")
    recipient = _require("NOTIFY_EMAIL_TO")

    message = _build_message(sorted(new_dates), sender, recipient)
    factory = smtp_factory or (lambda: smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30))

    with factory() as smtp:
        smtp.starttls()
        smtp.login(sender, password)
        smtp.send_message(message)

    logger.info("Sent availability email for %d date(s)", len(new_dates))
