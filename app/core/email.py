import asyncio
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import Settings, settings


class EmailNotConfiguredError(RuntimeError):
    pass


class EmailSender:
    """Small SMTP transport used by verification and support workflows."""

    def __init__(self, config: Settings = settings):
        self.config = config

    async def send(
        self,
        *,
        to_address: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
        reply_to: str | None = None,
    ) -> None:
        if not self.config.EMAIL_ENABLED:
            raise EmailNotConfiguredError("Email delivery is disabled")

        message = EmailMessage()
        message["From"] = formataddr(
            (self.config.EMAIL_FROM_NAME, self.config.EMAIL_FROM_ADDRESS or "")
        )
        message["To"] = to_address
        message["Subject"] = subject
        if reply_to:
            message["Reply-To"] = reply_to
        message.set_content(text_body)
        if html_body:
            message.add_alternative(html_body, subtype="html")

        await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: EmailMessage) -> None:
        config = self.config
        smtp_class = smtplib.SMTP_SSL if config.SMTP_SECURITY == "ssl" else smtplib.SMTP
        with smtp_class(
            config.SMTP_HOST,
            config.SMTP_PORT,
            timeout=config.SMTP_TIMEOUT_SECONDS,
        ) as smtp:
            if config.SMTP_SECURITY == "starttls":
                smtp.starttls()
            smtp.login(config.SMTP_USERNAME or "", config.SMTP_PASSWORD or "")
            smtp.send_message(message)
