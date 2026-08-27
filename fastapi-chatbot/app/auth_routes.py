"""
Authentication routes: signup, login, Google OAuth, logout.
Sets the JWT as an httpOnly cookie instead of returning it in the
response body — JavaScript can never read it, which prevents XSS
based token theft.
"""
import os
from fastapi import APIRouter, HTTPException, Depends, Response
from .dependencies import get_current_user
from . import auth_crud
from .auth import hash_password, verify_password, create_access_token
from .schemas import (
    SignupRequest, LoginRequest, UserOut, UserUpdateRequest, GoogleAuthRequest
)
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_MAX_AGE = 60 * 60 * 24  # 1 day — matches ACCESS_TOKEN_EXPIRE_MINUTES


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,        # JavaScript is CANNOT read this — XSS protection
        secure=False,         # set True once you're serving over HTTPS in production
        samesite="lax",       # blocks the cookie being sent on cross-site POSTs (CSRF mitigation)
        max_age=COOKIE_MAX_AGE,
        path="/",
    )


@router.post("/signup", response_model=UserOut, status_code=201)
def signup(payload: SignupRequest, response: Response):
    if auth_crud.get_user_by_email(payload.email):
        raise HTTPException(status_code=400, detail="Email already registered.")
    if auth_crud.get_user_by_username(payload.username):
        raise HTTPException(status_code=400, detail="Username already taken.")

    hashed = hash_password(payload.password)
    user = auth_crud.create_user(
        username=payload.username, email=payload.email, hashed_password=hashed
    )

    token = create_access_token({"sub": str(user["id"])})
    _set_auth_cookie(response, token)
    return UserOut(**user)


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, response: Response):
    user = auth_crud.get_user_by_email(payload.email)
    if not user or not verify_password(payload.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = create_access_token({"sub": str(user["id"])})
    _set_auth_cookie(response, token)
    return UserOut(**user)


@router.get("/me", response_model=UserOut)
def get_me(current_user: dict = Depends(get_current_user)):
    return UserOut(**current_user)


@router.put("/me", response_model=UserOut)
def update_me(payload: UserUpdateRequest, current_user: dict = Depends(get_current_user)):
    if auth_crud.get_user_by_username_excluding(payload.username, current_user["id"]):
        raise HTTPException(status_code=400, detail="Username already taken.")
    if auth_crud.get_user_by_email_excluding(payload.email, current_user["id"]):
        raise HTTPException(status_code=400, detail="Email already registered.")

    updated = auth_crud.update_user(current_user["id"], payload.username, payload.email)
    return UserOut(**updated)


@router.post("/google", response_model=UserOut)
def google_login(payload: GoogleAuthRequest, response: Response):
    try:
        idinfo = google_id_token.verify_oauth2_token(
            payload.id_token, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token.")

    email = idinfo["email"]
    google_id = idinfo["sub"]
    name = idinfo.get("name", "")

    user = auth_crud.get_or_create_google_user(email=email, google_id=google_id, name=name)

    token = create_access_token({"sub": str(user["id"])})
    _set_auth_cookie(response, token)
    return UserOut(**user)


@router.post("/logout")
def logout(response: Response):
    # httpOnly cookies can't be deleted by JavaScript — the server must
    # tell the browser to expire it via a Set-Cookie header.
    response.delete_cookie(key="access_token", path="/")
    return {"detail": "Logged out."}