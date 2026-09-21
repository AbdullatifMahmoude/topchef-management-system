import pytest

from app.core.config import settings
from app.core.exceptions import AuthenticationServiceUnavailable
from app.modules.settings import whatsapp_verification


@pytest.mark.asyncio
async def test_whatsapp_account_verification_is_disabled_by_default():
    assert settings.WHATSAPP_VERIFICATION_ENABLED is False
    with pytest.raises(AuthenticationServiceUnavailable):
        await whatsapp_verification.create_inbound_challenge(
            object(),
            object(),
            phone="01000000001",
            actor_type="customer",
            actor_id=7,
            purpose="activate",
        )


def test_meta_agent_is_disabled_by_default():
    assert settings.META_AGENT_ENABLED is False
