from app.core.secrets import decrypt_secret, encrypt_secret


def test_secret_is_encrypted_at_rest_and_round_trips():
    plain = "EAAB-real-looking-access-token"
    encrypted = encrypt_secret(plain)
    assert encrypted.startswith("enc:v1:")
    assert plain not in encrypted
    assert decrypt_secret(encrypted) == plain


def test_legacy_plaintext_secret_remains_readable_for_migration():
    assert decrypt_secret("legacy-token") == "legacy-token"


def test_tampered_ciphertext_is_rejected():
    assert decrypt_secret("enc:v1:not-valid") == ""
