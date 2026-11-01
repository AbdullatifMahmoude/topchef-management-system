from app.core.config import settings
from app.modules.settings.whatsapp_webhook import inbound_routing_policy


def test_meta_agent_configuration_makes_cloud_webhook_passive(monkeypatch):
    monkeypatch.setattr(settings, "META_AGENT_API_KEY", "configured-secret")
    monkeypatch.setattr(settings, "META_AGENT_ENABLED", True)

    assert inbound_routing_policy(False) == (True, "meta_agent_managed")


def test_disabled_meta_agent_does_not_take_over_webhook(monkeypatch):
    monkeypatch.setattr(settings, "META_AGENT_API_KEY", "configured-secret")
    monkeypatch.setattr(settings, "META_AGENT_ENABLED", False)

    assert inbound_routing_policy(False) == (False, "routing_suppressed")


def test_verification_message_remains_consumed(monkeypatch):
    monkeypatch.setattr(settings, "META_AGENT_API_KEY", "configured-secret")

    assert inbound_routing_policy(True) == (True, "verification_consumed")


def test_legacy_router_remains_active_without_meta_agent(monkeypatch):
    monkeypatch.setattr(settings, "META_AGENT_API_KEY", None)

    assert inbound_routing_policy(False) == (False, "routing_suppressed")
