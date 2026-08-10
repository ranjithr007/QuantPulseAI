import base64
import hashlib
import hmac
import json
import time


SESSION_COOKIE_NAME = "quantpulse_session"
PASSWORD_SCHEME = "pbkdf2_sha256"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        scheme, iterations_raw, salt, expected_digest = encoded_hash.split("$", 3)
        iterations = int(iterations_raw)
    except (AttributeError, TypeError, ValueError):
        return False

    if scheme != PASSWORD_SCHEME or iterations < 100_000 or not salt or not expected_digest:
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(actual_digest, expected_digest)


def create_session_token(username: str, secret: str, ttl_seconds: int) -> str:
    payload = {
        "sub": username,
        "exp": int(time.time()) + ttl_seconds,
        "v": 1,
    }
    encoded_payload = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        secret.encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded_payload}.{_base64url_encode(signature)}"


def validate_session_token(token: str, secret: str, expected_username: str) -> bool:
    try:
        encoded_payload, supplied_signature = token.split(".", 1)
        expected_signature = _base64url_encode(
            hmac.new(
                secret.encode("utf-8"),
                encoded_payload.encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return False
        payload = json.loads(_base64url_decode(encoded_payload))
        return (
            payload.get("v") == 1
            and payload.get("sub") == expected_username
            and int(payload.get("exp", 0)) > int(time.time())
        )
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return False


def request_has_valid_session(request, settings) -> bool:
    if not getattr(settings, "require_app_auth", False):
        return True
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    return validate_session_token(
        token,
        settings.app_session_secret,
        settings.app_username,
    )


def websocket_has_valid_session(websocket, settings) -> bool:
    if not getattr(settings, "require_app_auth", False):
        return True
    token = websocket.cookies.get(SESSION_COOKIE_NAME, "")
    return validate_session_token(
        token,
        settings.app_session_secret,
        settings.app_username,
    )


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")
