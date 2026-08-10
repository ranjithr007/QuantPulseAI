import hashlib
from types import SimpleNamespace

from app.security.app_auth import create_session_token
from app.security.app_auth import validate_session_token
from app.security.app_auth import verify_password


def _password_hash(password="correct horse battery staple"):
    iterations = 100_000
    salt = "quantpulse-test-salt"
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        iterations,
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def test_password_verification_accepts_only_matching_password():
    encoded = _password_hash()
    assert verify_password("correct horse battery staple", encoded) is True
    assert verify_password("wrong password", encoded) is False


def test_signed_session_rejects_tampering_and_wrong_user():
    token = create_session_token("ranjithr007", "s" * 32, 3600)
    assert validate_session_token(token, "s" * 32, "ranjithr007") is True
    assert validate_session_token(f"{token}x", "s" * 32, "ranjithr007") is False
    assert validate_session_token(token, "s" * 32, "another-user") is False
