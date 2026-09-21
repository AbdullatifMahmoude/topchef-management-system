import pytest

from app.core.exceptions import AuthenticationError
from app.core.redis import InMemoryCache
from app.modules.settings import whatsapp_verification as verification
from app.modules.settings.schemas import WhatsAppSettingsResponse


def ready_settings():
    return WhatsAppSettingsResponse(
        api_key_configured=True, phone_number_id="123",
        first_order_template_name="first",
        order_details_template_name="details", order_status_template_name="status",
        language_code="ar", graph_api_version="v23.0", enabled=True,
        bulk_template_name="bulk", password_reset_template_name="reset",
        reset_code_expiry_minutes=10, bulk_send_limit=500, bulk_message="",
        business_phone_number="201000000001", webhook_verify_token_configured=True,
        app_secret_configured=True,
    )


@pytest.mark.asyncio
async def test_inbound_challenge_requires_same_sender_and_is_single_use(monkeypatch):
    redis = InMemoryCache()
    monkeypatch.setattr(verification.settings, "WHATSAPP_VERIFICATION_ENABLED", True)

    async def fake_settings(_self):
        return ready_settings()

    monkeypatch.setattr(verification.SettingsService, "get_whatsapp_settings", fake_settings)
    challenge = await verification.create_inbound_challenge(
        object(), redis, phone="01000000001", actor_type="customer", actor_id=7, purpose="login"
    )
    assert challenge["expires_in"] == 60
    code = challenge["whatsapp_url"].split("TCV-")[1]
    assert not await verification.consume_incoming_message(redis, "201000000002", f"TCV-{code}")
    assert await verification.consume_incoming_message(redis, "201000000001", f"TCV-{code}")
    assert await verification.challenge_status(redis, challenge["challenge_id"])
    record = await verification.consume_verified_challenge(
        redis, challenge["challenge_id"], actor_type="customer", purpose="login"
    )
    assert record["actor_id"] == 7
    with pytest.raises(AuthenticationError):
        await verification.consume_verified_challenge(
            redis, challenge["challenge_id"], actor_type="customer", purpose="login"
        )
