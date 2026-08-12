import secrets

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from pydantic import BaseModel

from app.config import get_settings
from app.security.app_auth import create_session_token
from app.security.app_auth import request_has_valid_session
from app.security.app_auth import SESSION_COOKIE_NAME
from app.security.app_auth import verify_password


router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(payload: LoginRequest, response: Response):
    settings = get_settings()
    username_matches = secrets.compare_digest(
        payload.username.strip(),
        settings.app_username,
    )
    password_matches = verify_password(payload.password, settings.app_password_hash)
    if not username_matches or not password_matches:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_session_token(
        settings.app_username,
        settings.app_session_secret,
        settings.app_session_ttl_seconds,
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.app_session_ttl_seconds,
        httponly=True,
        secure=settings.environment == "production",
        samesite="none" if settings.environment == "production" else "lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": True, "username": settings.app_username}


@router.get("/session")
def session(request: Request):
    settings = get_settings()
    authenticated = request_has_valid_session(request, settings)
    return {
        "authenticated": authenticated,
        "username": (settings.app_username or "local") if authenticated else None,
    }


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=get_settings().environment == "production",
        samesite="none" if get_settings().environment == "production" else "lax",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": False}
