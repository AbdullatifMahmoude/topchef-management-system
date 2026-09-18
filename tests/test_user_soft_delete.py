from app.modules.users.repository import deleted_phone, deleted_username


def test_deleted_phone_fits_database_column_and_is_unique():
    first = deleted_phone(4)
    second = deleted_phone(7)
    assert first == "D00000000000004"
    assert len(first) <= 15
    assert first != second
    assert len(deleted_phone(2_147_483_647)) == 15


def test_deleted_username_is_bounded_and_unique():
    first = deleted_username(4)
    second = deleted_username(7)
    assert len(first) <= 200
    assert first != second
