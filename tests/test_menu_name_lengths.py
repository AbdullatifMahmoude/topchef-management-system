import pytest
from pydantic import ValidationError

from app.modules.menu.schemas import CreateCategory, CreateProduct, CreateVariant


def test_menu_names_accept_up_to_two_hundred_fifty_five_characters():
    long_name = "س" * 255

    assert CreateCategory(cat_name=long_name).cat_name == long_name
    assert CreateVariant(name=long_name, price="10").name == long_name
    product = CreateProduct(
        cat_id=1,
        product_name=long_name,
        product_type="variant",
        description=None,
        is_available=True,
        variants=[{"name": long_name, "price": "10"}],
    )
    assert product.product_name == long_name


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (CreateCategory, {"cat_name": "س" * 256}),
        (CreateVariant, {"name": "س" * 256, "price": "10"}),
    ],
)
def test_menu_names_reject_more_than_two_hundred_fifty_five_characters(schema, payload):
    with pytest.raises(ValidationError):
        schema(**payload)
