import asyncio

from app.core.observability import ApplicationMetrics, ObservabilityMiddleware


def test_metrics_use_bounded_route_labels():
    registry = ApplicationMetrics()
    registry.observe_request("GET", "/orders/{order_id}", 200, 0.125)
    output = registry.render()
    assert 'route="/orders/{order_id}"' in output
    assert "rms_http_requests_total" in output
    assert "0.125000" in output


def test_observability_middleware_adds_request_id():
    messages = []

    async def endpoint(scope, receive, send):
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = ObservabilityMiddleware(endpoint)
    scope = {"type": "http", "method": "GET", "path": "/health", "headers": []}

    async def send(message):
        messages.append(message)

    asyncio.run(middleware(scope, lambda: None, send))
    headers = dict(messages[0]["headers"])
    assert len(headers[b"x-request-id"]) == 32
