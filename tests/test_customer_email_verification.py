import json

import pytest

from app.core.exceptions import AuthenticationError
from app.core.redis import InMemoryCache
from app.modules.customer import email_verification


@pytest.mark.asyncio
async def test_email_code_is_six_digits_verified_and_single_use(monkeypatch):
    cache = InMemoryCache()
    sent = {}
    monkeypatch.setattr(email_verification.settings, "EMAIL_ENABLED", True)

    async def send(_self, **message):
        sent.update(message)

    monkeypatch.setattr(email_verification.EmailSender, "send", send)
    challenge = await email_verification.create_email_challenge(
        cache,
        email="Customer@Example.com",
        phone="01000000001",
        actor_type="customer",
        actor_id=7,
        purpose="activate",
    )
    code = sent["text_body"].split("هو: ", 1)[1].splitlines()[0]

    assert len(code) == 6 and code.isdigit()
    assert await email_verification.verify_email_challenge(
        cache, challenge["challenge_id"], code
    ) is True
    record = await email_verification.consume_email_challenge(
        cache,
        challenge["challenge_id"],
        actor_type="customer",
        purpose="activate",
    )
    assert record["email"] == "customer@example.com"
    with pytest.raises(AuthenticationError):
        await email_verification.consume_email_challenge(
            cache,
            challenge["challenge_id"],
            actor_type="customer",
            purpose="activate",
        )


@pytest.mark.asyncio
async def test_wrong_email_code_is_limited(monkeypatch):
    cache = InMemoryCache()
    monkeypatch.setattr(email_verification.settings, "EMAIL_ENABLED", True)

    async def send(_self, **_message):
        return None

    monkeypatch.setattr(email_verification.EmailSender, "send", send)
    challenge = await email_verification.create_email_challenge(
        cache,
        email="customer@example.com",
        actor_type="customer",
        actor_id=7,
        purpose="reset_pin",
    )

    for _ in range(email_verification.MAX_VERIFY_ATTEMPTS):
        with pytest.raises(AuthenticationError, match="غير صحيح"):
            await email_verification.verify_email_challenge(
                cache, challenge["challenge_id"], "000000"
            )
    with pytest.raises(AuthenticationError, match="تجاوز"):
        await email_verification.verify_email_challenge(
            cache, challenge["challenge_id"], "000000"
        )


@pytest.mark.asyncio
async def test_unknown_reset_email_can_return_generic_challenge_without_sending(monkeypatch):
    cache = InMemoryCache()
    monkeypatch.setattr(email_verification.settings, "EMAIL_ENABLED", True)

    async def fail_if_sent(_self, **_message):
        raise AssertionError("No email should be sent for an unknown account")

    monkeypatch.setattr(email_verification.EmailSender, "send", fail_if_sent)
    result = await email_verification.create_email_challenge(
        cache,
        email="unknown@example.com",
        actor_type="customer",
        actor_id=None,
        purpose="reset_pin",
        send_email=False,
    )

    raw = await cache.get(email_verification._challenge_key(result["challenge_id"]))
    assert json.loads(raw)["actor_id"] is None
