from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.exceptions import ValidationError
from app.core.observability import ObservabilityMiddleware
from app.modules.infrastructure.middlewares.error_handler import (
    ErrorHandlerMiddleware,
    register_error_handlers,
)


class Payload(BaseModel):
    count: int


def build_client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(ObservabilityMiddleware)
    app.add_middleware(ErrorHandlerMiddleware)

    @app.get("/known")
    async def known():
        raise ValidationError("bad input")

    @app.get("/http")
    async def http():
        raise HTTPException(status_code=404, detail="missing")

    @app.post("/validated")
    async def validated(payload: Payload):
        return payload

    @app.get("/unknown")
    async def unknown():
        raise RuntimeError("database password must never be returned")

    return TestClient(app, raise_server_exceptions=False)


def test_known_and_http_errors_are_consistent():
    client = build_client()
    known = client.get("/known")
    missing = client.get("/http")
    assert known.json()["error_code"] == "VALIDATION_ERROR"
    assert missing.json()["error_code"] == "NOT_FOUND"
    assert known.json()["request_id"] == known.headers["x-request-id"]


def test_validation_error_is_structured_not_raw_fastapi_json():
    response = build_client().post("/validated", json={"count": "wrong"})
    payload = response.json()
    assert response.status_code == 422
    assert payload["error_code"] == "VALIDATION_ERROR"
    assert payload["detail"][0]["field"] == "count"


def test_unknown_error_does_not_leak_exception_text():
    response = build_client().get("/unknown")
    assert response.status_code == 500
    assert "password" not in response.text
    assert response.json()["error_code"] == "INTERNAL_ERROR"
