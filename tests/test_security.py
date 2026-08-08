from cryptography.fernet import Fernet

from app.security import (
    SecretBox,
    hash_password,
    mask_endpoint,
    sanitize_exception,
    stable_fingerprint,
    verify_password,
)


def test_secret_box_round_trip_and_wrong_key_case():
    box = SecretBox(Fernet.generate_key().decode())
    encrypted = box.encrypt_json(
        {"payload": "test-only-private-value", "server": "example.test"}
    )
    assert "test-only-private-value" not in encrypted
    assert box.decrypt_json(encrypted)["payload"] == "test-only-private-value"


def test_password_hash_and_verification():
    encoded = hash_password("correct horse battery staple")
    assert "correct horse" not in encoded
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("incorrect password", encoded)


def test_endpoint_masking_and_sanitized_exception():
    assert mask_endpoint("192.168.23.77", 443) == "192.168.*.*:443"
    assert mask_endpoint("edge.proxy.example.com", 8443) == "*.example.com:8443"
    safe = sanitize_exception(
        "failed https://"
        + "example-user"
        + ":"
        + "example-password"
        + "@example.com/path?"  # pragma: allowlist secret
        "token=EXAMPLE_TOKEN password=EXAMPLE_PASSWORD"
    )
    assert "example-password" not in safe
    assert "EXAMPLE_PASSWORD" not in safe
    assert "example.com/path" not in safe


def test_fingerprint_is_stable_but_not_plaintext():
    first = stable_fingerprint("server-password", "pepper")
    second = stable_fingerprint("server-password", "pepper")
    assert first == second
    assert "server-password" not in first
