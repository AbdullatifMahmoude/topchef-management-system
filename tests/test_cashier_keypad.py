from pathlib import Path


CASHIER_JS = (
    Path(__file__).parents[1] / "app" / "frontend" / "cashier" / "js" / "cashier.js"
)
CASHIER_HTML = CASHIER_JS.parents[1] / "cashier.html"


def test_keypad_preserves_an_explicit_leading_zero():
    source = CASHIER_JS.read_text(encoding="utf-8")

    assert 'value = value === "0" ? key : value + key' not in source
    assert "value += key;" in source


def test_keypad_starts_with_one_on_the_top_row():
    source = CASHIER_HTML.read_text(encoding="utf-8")

    one = source.index('data-key="1"')
    four = source.index('data-key="4"')
    seven = source.index('data-key="7"')
    assert one < four < seven
