from pathlib import Path


def test_cashier_order_tabs_request_the_selected_server_page():
    source = Path("app/frontend/cashier/js/cashier.js").read_text(encoding="utf-8")

    assert "`/orders/?page=${page}&page_size=${ordersPageSize}&source=online`" in source
    assert "`/orders/?page=${page}&page_size=${ordersPageSize}&source=cashier`" in source
    assert "/orders/?page=1&page_size=500&source=online" not in source
    assert "/orders/?page=1&page_size=500&source=cashier" not in source
