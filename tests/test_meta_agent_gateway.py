import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.redis import InMemoryCache, get_redis
from app.modules.infrastructure.middlewares.auth import AuthMiddleware
from app.modules.infrastructure.middlewares.error_handler import register_error_handlers
from app.modules.meta_agent import register_meta_agent, service
from app.modules.meta_agent.auth import META_AGENT_HEADER
from app.modules.settings import whatsapp_verification


def build_client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    register_meta_agent(app)
    app.add_middleware(AuthMiddleware)
    return TestClient(app, raise_server_exceptions=False)


def test_gateway_fails_closed_when_key_is_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "META_AGENT_API_KEY", None)

    response = build_client().get("/integrations/meta-agent/v1/health")

    assert response.status_code == 503
    assert response.json()["error_code"] == "META_AGENT_NOT_CONFIGURED"


def test_gateway_rejects_missing_key(monkeypatch):
    monkeypatch.setattr(settings, "META_AGENT_API_KEY", "configured-secret")

    response = build_client().get("/integrations/meta-agent/v1/health")

    assert response.status_code == 401
    assert response.json()["error_code"] == "META_AGENT_AUTH_ERROR"


def test_gateway_rejects_incorrect_key(monkeypatch):
    monkeypatch.setattr(settings, "META_AGENT_API_KEY", "configured-secret")

    response = build_client().get(
        "/integrations/meta-agent/v1/health",
        headers={META_AGENT_HEADER: "wrong-secret"},
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "META_AGENT_AUTH_ERROR"


def test_gateway_accepts_configured_key(monkeypatch):
    monkeypatch.setattr(settings, "META_AGENT_API_KEY", "configured-secret")

    response = build_client().get(
        "/integrations/meta-agent/v1/health",
        headers={META_AGENT_HEADER: "configured-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "integration": "meta-business-agent",
        "version": "v1",
    }


def test_gateway_base_url_is_an_authenticated_readiness_probe(monkeypatch):
    monkeypatch.setattr(settings, "META_AGENT_API_KEY", "configured-secret")

    unauthenticated = build_client().get("/integrations/meta-agent/v1")
    authenticated = build_client().get(
        "/integrations/meta-agent/v1",
        headers={META_AGENT_HEADER: "configured-secret"},
    )

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 200
    assert authenticated.json()["status"] == "ready"


def test_gateway_declares_read_only_capabilities(monkeypatch):
    monkeypatch.setattr(settings, "META_AGENT_API_KEY", "configured-secret")

    response = build_client().get(
        "/integrations/meta-agent/v1/capabilities",
        headers={META_AGENT_HEADER: "configured-secret"},
    )

    assert response.status_code == 200
    assert response.json()["allowed"] == [
        "menu_and_pricing",
        "order_status",
        "order_status_history",
        "customer_verification",
    ]
    assert response.json()["handoff_required"] == [
        "create_order",
        "update_order",
        "cancel_order",
    ]


def test_gateway_exposes_no_order_mutation_routes(monkeypatch):
    monkeypatch.setattr(settings, "META_AGENT_API_KEY", "configured-secret")
    client = build_client()
    headers = {META_AGENT_HEADER: "configured-secret"}

    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)(
            "/integrations/meta-agent/v1/orders/123/status",
            headers=headers,
        )
        assert response.status_code == 405


def test_customer_verification_tool_is_authenticated_and_phone_bound(monkeypatch):
    monkeypatch.setattr(settings, "META_AGENT_API_KEY", "configured-secret")
    cache = InMemoryCache()
    client = build_client()
    client.app.dependency_overrides[get_redis] = lambda: cache
    headers = {META_AGENT_HEADER: "configured-secret"}

    unauthenticated = client.post(
        "/integrations/meta-agent/v1/customer-verification",
        json={"customer_phone": "01000000000", "message": "TCV-12345678"},
    )
    invalid = client.post(
        "/integrations/meta-agent/v1/customer-verification",
        headers=headers,
        json={"customer_phone": "01000000000", "message": "TCV-12345678"},
    )

    assert unauthenticated.status_code == 401
    assert invalid.status_code == 200
    assert invalid.json() == {"verified": False}


def test_customer_verification_tool_consumes_live_sender_bound_code(monkeypatch):
    monkeypatch.setattr(settings, "META_AGENT_API_KEY", "configured-secret")
    cache = InMemoryCache()
    challenge_id = "challenge-id"
    code = "A1B2C3D4"
    record = {
        "phone": "01000000000",
        "actor_type": "customer",
        "actor_id": 7,
        "purpose": "reset_pin",
        "verified": False,
    }

    async def seed_cache():
        await cache.setex(
            whatsapp_verification._id_key(challenge_id),
            60,
            json.dumps(record),
        )
        await cache.setex(
            whatsapp_verification._code_key(code),
            60,
            challenge_id,
        )

    asyncio.run(seed_cache())
    client = build_client()
    client.app.dependency_overrides[get_redis] = lambda: cache
    wrong_sender = client.post(
        "/integrations/meta-agent/v1/customer-verification",
        headers={META_AGENT_HEADER: "configured-secret"},
        json={
            "customer_phone": "+201111111111",
            "message": f"TCV-{code}",
        },
    )
    response = client.post(
        "/integrations/meta-agent/v1/customer-verification",
        headers={META_AGENT_HEADER: "configured-secret"},
        json={
            "customer_phone": "+201000000000",
            "message": f"تأكيد حساب توب شيف TCV-{code}",
        },
    )

    assert wrong_sender.status_code == 200
    assert wrong_sender.json() == {"verified": False}
    assert response.status_code == 200
    assert response.json() == {"verified": True}
    assert asyncio.run(whatsapp_verification.challenge_status(cache, challenge_id)) is True


def test_menu_returns_only_service_payload(monkeypatch):
    monkeypatch.setattr(settings, "META_AGENT_API_KEY", "configured-secret")

    async def fake_menu(_db):
        return {
            "currency": "EGP",
            "products": [{
                "id": 1,
                "name": "وجبة توب شيف",
                "description": None,
                "category": "الوجبات",
                "variants": [{"id": 2, "name": "عادي", "price": Decimal("125.00")}],
            }],
        }

    monkeypatch.setattr(service, "get_available_menu", fake_menu)
    response = build_client().get(
        "/integrations/meta-agent/v1/menu",
        headers={META_AGENT_HEADER: "configured-secret"},
    )

    assert response.status_code == 200
    assert response.json()["products"][0]["variants"][0]["price"] == "125.00"


def test_order_status_requires_phone_ownership(monkeypatch):
    monkeypatch.setattr(settings, "META_AGENT_API_KEY", "configured-secret")

    async def fake_status(_db, *, order_number, customer_phone):
        if order_number != "123" or customer_phone != "01000000000":
            return None
        return {
            "order_number": "123",
            "status": "confirmed",
            "status_label": "تم التأكيد",
            "updated_at": datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC),
            "history": [],
        }

    monkeypatch.setattr(service, "get_owned_order_status", fake_status)
    client = build_client()
    headers = {META_AGENT_HEADER: "configured-secret"}

    owned = client.get(
        "/integrations/meta-agent/v1/orders/123/status?customer_phone=01000000000",
        headers=headers,
    )
    wrong_phone = client.get(
        "/integrations/meta-agent/v1/orders/123/status?customer_phone=01111111111",
        headers=headers,
    )

    assert owned.status_code == 200
    assert owned.json()["status"] == "confirmed"
    assert wrong_phone.status_code == 404
    assert wrong_phone.json()["error_code"] == "ORDER_NOT_FOUND"
