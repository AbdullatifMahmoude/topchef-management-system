from datetime import UTC, datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.ai_menu import register_ai_menu, service
from app.modules.infrastructure.middlewares.auth import AuthMiddleware
from app.modules.meta_agent.schemas import MenuProduct, MenuVariant


def build_client(monkeypatch, catalog: dict) -> TestClient:
    async def fake_catalog(_db):
        return catalog

    monkeypatch.setattr(service, "get_public_catalog", fake_catalog)
    app = FastAPI()
    register_ai_menu(app)
    app.add_middleware(AuthMiddleware)
    return TestClient(app)


def test_ai_menu_is_public_current_and_excludes_delivery_fee(monkeypatch):
    catalog = {
        "generated_at": datetime(2026, 9, 21, 12, 30, tzinfo=UTC),
        "currency": "EGP",
        "products": [
            MenuProduct(
                id=1,
                name="وجبة توب شيف",
                description="وجبة متاحة",
                category="الوجبات",
                variants=[MenuVariant(id=2, name="عادي", price=Decimal("125.00"))],
            )
        ],
        "offers": [
            {
                "name": "خصم الغداء",
                "code": "LUNCH10",
                "type": "percentage",
                "value": Decimal("10.00"),
                "minimum": Decimal("100.00"),
                "maximum_discount": None,
                "valid_to": datetime(2026, 9, 30, 23, 59, tzinfo=UTC),
                "products": ["وجبة توب شيف"],
                "rules": {},
            }
        ],
    }

    response = build_client(monkeypatch, catalog).get("/ai-menu")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, max-age=0, must-revalidate"
    assert "وجبة توب شيف" in response.text
    assert "125.00 جنيه" in response.text
    assert "LUNCH10" in response.text
    assert "رسوم التوصيل غير مدرجة" in response.text
    assert "المطعم يحددها" in response.text
    assert "سعر التوصيل" not in response.text


def test_ai_menu_escapes_database_content(monkeypatch):
    catalog = {
        "generated_at": datetime(2026, 9, 21, 12, 30, tzinfo=UTC),
        "currency": "EGP",
        "products": [
            MenuProduct(
                id=1,
                name="<script>alert(1)</script>",
                category="الوجبات",
                variants=[MenuVariant(id=2, name="عادي", price=Decimal(10))],
            )
        ],
        "offers": [],
    }

    response = build_client(monkeypatch, catalog).get("/ai-menu")

    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
