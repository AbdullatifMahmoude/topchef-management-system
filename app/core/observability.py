import threading
import time
import uuid
from collections import defaultdict

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class ApplicationMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self._durations: dict[tuple[str, str], float] = defaultdict(float)

    def observe_request(self, method: str, route: str, status: int, seconds: float) -> None:
        key = (method, route, status)
        with self._lock:
            self._requests[key] += 1
            self._durations[(method, route)] += seconds

    def render(self) -> str:
        with self._lock:
            requests = dict(self._requests)
            durations = dict(self._durations)
        lines = [
            "# HELP rms_http_requests_total Total HTTP requests.",
            "# TYPE rms_http_requests_total counter",
        ]
        for (method, route, status), value in sorted(requests.items()):
            labels = f'method="{method}",route="{route}",status="{status}"'
            lines.append(f"rms_http_requests_total{{{labels}}} {value}")
        lines.extend([
            "# HELP rms_http_request_duration_seconds_sum Total request duration.",
            "# TYPE rms_http_request_duration_seconds_sum counter",
        ])
        for (method, route), value in sorted(durations.items()):
            labels = f'method="{method}",route="{route}"'
            lines.append(f"rms_http_request_duration_seconds_sum{{{labels}}} {value:.6f}")
        return "\n".join(lines) + "\n"


metrics = ApplicationMetrics()


class ObservabilityMiddleware:
    """Low-overhead request timing with bounded-cardinality route labels."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        request_id = dict(scope.get("headers", [])).get(b"x-request-id", b"").decode("ascii", "ignore")[:64]
        request_id = request_id or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        status_code = 500

        async def send_with_headers(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode("ascii")))
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            route = scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            metrics.observe_request(scope["method"], route_path, status_code, time.perf_counter() - started)
