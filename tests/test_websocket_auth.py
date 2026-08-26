from app.core.enums import UserRole
from app.core.security import create_access_token
from app.modules.orders.router import authorize_websocket_token, websocket_protocol_token


def token_for(role: UserRole, user_id: int = 1) -> str:
    return create_access_token({"sub": "tester", "user_id": user_id, "role": role.value})


def test_websocket_rejects_missing_invalid_and_unknown_channel():
    assert authorize_websocket_token(None, "admin") is None
    assert authorize_websocket_token("invalid", "admin") is None
    assert authorize_websocket_token(token_for(UserRole.ADMIN), "private") is None


def test_admin_channel_only_accepts_admin():
    assert authorize_websocket_token(token_for(UserRole.ADMIN), "admin") is not None
    assert authorize_websocket_token(token_for(UserRole.CASHIER), "admin") is None
    assert authorize_websocket_token(token_for(UserRole.DELIVERY), "admin") is None


def test_cashier_channel_accepts_cashier_and_admin_only():
    assert authorize_websocket_token(token_for(UserRole.ADMIN), "cashier") is not None
    assert authorize_websocket_token(token_for(UserRole.CASHIER), "cashier") is not None
    assert authorize_websocket_token(token_for(UserRole.DELIVERY), "cashier") is None


def test_websocket_token_requires_user_id():
    token = create_access_token({"sub": "tester", "role": UserRole.ADMIN.value})
    assert authorize_websocket_token(token, "admin") is None


def test_websocket_token_is_read_from_protocol_header_not_url():
    token = token_for(UserRole.ADMIN)
    assert websocket_protocol_token(f"access_token, {token}") == token
    assert websocket_protocol_token(token) is None


def test_event_manager_does_not_accept_twice_after_authenticated_handshake():
    class FakeWebSocket:
        accepted = 0

        async def accept(self):
            self.accepted += 1

    async def scenario():
        manager = OrderEventsManager()
        websocket = FakeWebSocket()
        await manager.connect(websocket, "admin", already_accepted=True)
        assert websocket.accepted == 0
        await manager.disconnect(websocket, "admin")

    asyncio.run(scenario())
import asyncio
import json

from fastapi.testclient import TestClient

from app.core.events import OrderEventsManager
from app.main import app


def test_public_online_channel_connects_without_authentication():
    with TestClient(app).websocket_connect("/orders/ws/online") as websocket:
        websocket.send_json({"type": "HEARTBEAT"})
        assert websocket.receive_json() == {"type": "HEARTBEAT_ACK"}


def test_public_channel_only_receives_sanitized_commerce_events():
    class FakeWebSocket:
        def __init__(self):
            self.messages = []

        async def send_text(self, payload):
            self.messages.append(json.loads(payload))

    async def scenario():
        manager = OrderEventsManager()
        websocket = FakeWebSocket()
        manager.active_connections["online"] = [websocket]

        await manager.broadcast(
            {"type": "PRODUCT_UPDATED", "data": {"internal": "secret"}},
            "online",
        )
        await manager.broadcast(
            {"type": "NEW_ORDER", "data": {"customer_phone": "01000000000"}},
            "online",
        )

        assert websocket.messages == [{"type": "PRODUCT_UPDATED"}]

    asyncio.run(scenario())
