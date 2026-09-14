import os
import re
import smtplib
from email.message import EmailMessage

from utils.logging_setter import setup_logger

logger = setup_logger("nintendo_notifier", "nintendo_notifier.log")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
BOOKING_URL = "https://museum-tickets.nintendo.com/en/calendar"
EMAIL_TO_SMS_GATEWAY_MATCHERS = ["vtext.com", "txt.att.net"]

_RECIPIENT_SEP_RE = re.compile(r"[,;\s]+")


class EmailConfigError(Exception):
    """A required email environment variable is missing."""


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise EmailConfigError(f"environment variable {name} is not set")
    return value


def _parse_recipients(value: str) -> list[str]:
    """Split on any run of commas, semicolons, or whitespace (including tabs)."""
    recipients = [part for part in _RECIPIENT_SEP_RE.split(value.strip()) if part]
    if not recipients:
        raise EmailConfigError("NOTIFY_EMAIL_TO contains no usable email addresses")
    return recipients

def _build_message(
    body: str, sender: str, recipients: list[str], subject: str | None = None
) -> EmailMessage:
    message = EmailMessage()
    if subject is not None:
        message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(body)
    return message


def _build_email_message(new_dates: list[str], sender: str, recipients: list[str]) -> EmailMessage:
    subject = f"Nintendo Museum: {len(new_dates)} new date(s) available"
    lines = [
        "Newly available Nintendo Museum ticket dates:",
        "",
        *(f"  - {date}" for date in new_dates),
        "",
        f"Book here: {BOOKING_URL}",
    ]
    return _build_message("\n".join(lines), sender, recipients, subject=subject)


def _build_sms_message(new_dates: list[str], sender: str, recipients: list[str]) -> EmailMessage:
    body = f"{len(new_dates)} new Nintendo Museum ticket date(s) available! Book: {BOOKING_URL}"
    return _build_message(body, sender, recipients)


def _partition_recipients(recipients: list[str]) -> tuple[list[str], list[str]]:
    """Split into (email_recipients, sms_gateway_recipients) by domain."""
    email_recipients = []
    sms_recipients = []
    for recipient in recipients:
        domain = recipient.rsplit("@", 1)[-1].lower()
        if domain in EMAIL_TO_SMS_GATEWAY_MATCHERS:
            sms_recipients.append(recipient)
        else:
            email_recipients.append(recipient)
    return email_recipients, sms_recipients


def send_availability_email(new_dates: set[str], smtp_factory=None) -> None:
    """Send one message listing every newly available date to each recipient,
    formatted for email or for an sms gateway address as appropriate. No
    dates, no message."""
    if not new_dates:
        return

    sender = _require("GMAIL_USER")
    password = _require("GMAIL_APP_PASSWORD")
    recipients = _parse_recipients(_require("NOTIFY_EMAIL_TO"))
    email_recipients, sms_recipients = _partition_recipients(recipients)

    sorted_dates = sorted(new_dates)
    messages = []
    if email_recipients:
        messages.append(_build_email_message(sorted_dates, sender, email_recipients))
    if sms_recipients:
        messages.append(_build_sms_message(sorted_dates, sender, sms_recipients))

    factory = smtp_factory or (lambda: smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30))

    with factory() as smtp:
        smtp.starttls()
        smtp.login(sender, password)
        for message in messages:
            smtp.send_message(message)

    logger.info(
        "Sent availability notification for %d date(s) to %d email and %d sms recipient(s)",
        len(new_dates), len(email_recipients), len(sms_recipients),
    )
