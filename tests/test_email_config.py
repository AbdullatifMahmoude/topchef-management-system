from unittest.mock import MagicMock, call, patch

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.email import EmailNotConfiguredError, EmailSender


def _settings(**overrides) -> Settings:
    values = {
        "DATABASE_URL": "sqlite+aiosqlite:///test.db",
        "SECRET_KEY": "test-secret",
        "REDIS_URL": "redis://localhost:6379/0",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_email_can_remain_disabled_without_credentials():
    config = _settings()
    assert config.EMAIL_ENABLED is False
    assert config.SMTP_HOST == "smtp.hostinger.com"


def test_enabled_email_requires_all_credentials():
    with pytest.raises(ValidationError, match="SMTP_PASSWORD"):
        _settings(EMAIL_ENABLED=True)


@pytest.mark.asyncio
async def test_sender_rejects_delivery_while_disabled():
    with pytest.raises(EmailNotConfiguredError):
        await EmailSender(_settings()).send(
            to_address="customer@example.com",
            subject="Verify",
            text_body="Code: 123456",
        )


def test_ssl_sender_authenticates_and_sends_message():
    config = _settings(
        EMAIL_ENABLED=True,
        SMTP_USERNAME="no-reply@topchefeg.com",
        SMTP_PASSWORD="mailbox-password",
        EMAIL_FROM_ADDRESS="no-reply@topchefeg.com",
        SUPPORT_EMAIL="support@topchefeg.com",
    )
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp
    message = MagicMock()

    with patch("app.core.email.smtplib.SMTP_SSL", return_value=smtp) as smtp_class:
        EmailSender(config)._send_sync(message)

    smtp_class.assert_called_once_with("smtp.hostinger.com", 465, timeout=15)
    smtp.login.assert_called_once_with("no-reply@topchefeg.com", "mailbox-password")
    smtp.send_message.assert_called_once_with(message)


def test_starttls_sender_upgrades_connection_before_login():
    config = _settings(
        EMAIL_ENABLED=True,
        SMTP_PORT=587,
        SMTP_SECURITY="STARTTLS",
        SMTP_USERNAME="no-reply@topchefeg.com",
        SMTP_PASSWORD="mailbox-password",
        EMAIL_FROM_ADDRESS="no-reply@topchefeg.com",
        SUPPORT_EMAIL="support@topchefeg.com",
    )
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp

    with patch("app.core.email.smtplib.SMTP", return_value=smtp):
        EmailSender(config)._send_sync(MagicMock())

    assert smtp.method_calls[:2] == [
        call.starttls(),
        call.login("no-reply@topchefeg.com", "mailbox-password"),
    ]
