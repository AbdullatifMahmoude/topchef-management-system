from pathlib import Path


def test_cashier_socket_is_lazy_to_avoid_temporal_dead_zone():
    source = Path("app/frontend/cashier/js/cashier.js").read_text(encoding="utf-8")
    assert "let cashierLiveSocket = null;" in source
    assert "function getCashierLiveSocket()" in source
    assert "const cashierLiveSocket" not in source
    assert "getCashierLiveSocket().connect();" in source
