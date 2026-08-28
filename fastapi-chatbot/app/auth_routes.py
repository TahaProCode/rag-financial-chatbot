"""
Authentication routes: signup, login, Google OAuth, logout, refresh.
Sets JWTs (Access and Refresh) as httpOnly cookies — JavaScript cannot read them,
preventing XSS-based token theft, with IP binding and Refresh Token Rotation (RTR).
"""
import os
from fastapi import APIRouter, HTTPException, Depends, Response, Request, status
from jose import jwt, JWTError
from .dependencies import get_current_user
from . import auth_crud
from .auth import (
    hash_password, 
    verify_password, 
    create_access_token, 
    create_refresh_token, 
    get_client_ip, 
    SECRET_KEY, 
    ALGORITHM
)
from .schemas import (
    SignupRequest, LoginRequest, UserOut, UserUpdateRequest, GoogleAuthRequest
)
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

router = APIRouter(prefix="/api/auth", tags=["auth"])

ACCESS_TOKEN_MAX_AGE = 15 * 60       # 15 mins (Short-lived)
REFRESH_TOKEN_MAX_AGE = 7 * 24 * 60 * 60  # 7 days (Long-lived)


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    # Set Access Token Cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=False,  # Set True in production over HTTPS
        samesite="lax",
        max_age=ACCESS_TOKEN_MAX_AGE,
        path="/",
    )
    # Set Refresh Token Cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=False,  # Set True in production over HTTPS
        samesite="lax",
        max_age=REFRESH_TOKEN_MAX_AGE,
        path="/",
    )


@router.post("/signup", response_model=UserOut, status_code=201)
def signup(payload: SignupRequest, request: Request, response: Response):
    if auth_crud.get_user_by_email(payload.email):
        raise HTTPException(status_code=400, detail="Email already registered.")
    if auth_crud.get_user_by_username(payload.username):
        raise HTTPException(status_code=400, detail="Username already taken.")

    hashed = hash_password(payload.password)
    user = auth_crud.create_user(
        username=payload.username, email=payload.email, hashed_password=hashed
    )

    client_ip = get_client_ip(request)
    access_token = create_access_token({"sub": str(user["id"])})
    refresh_token = create_refresh_token(user_id=str(user["id"]), client_ip=client_ip)

    _set_auth_cookies(response, access_token, refresh_token)
    return UserOut(**user)


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, request: Request, response: Response):
    user = auth_crud.get_user_by_email(payload.email)
    if not user or not verify_password(payload.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    client_ip = get_client_ip(request)
    access_token = create_access_token({"sub": str(user["id"])})
    refresh_token = create_refresh_token(user_id=str(user["id"]), client_ip=client_ip)

    _set_auth_cookies(response, access_token, refresh_token)
    return UserOut(**user)


@router.post("/google", response_model=UserOut)
def google_login(payload: GoogleAuthRequest, request: Request, response: Response):
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

    client_ip = get_client_ip(request)
    access_token = create_access_token({"sub": str(user["id"])})
    refresh_token = create_refresh_token(user_id=str(user["id"]), client_ip=client_ip)

    _set_auth_cookies(response, access_token, refresh_token)
    return UserOut(**user)


@router.post("/refresh")
def refresh(request: Request, response: Response):
    # HttpOnly Cookie se refresh token read karna
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing."
        )

    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token."
        )

    if data.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type."
        )

    user_id = data.get("sub")
    token_ip = data.get("ip")
    current_ip = get_client_ip(request)

    # --- IP BINDING CHECK ---
    if token_ip != current_ip:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Security violation: IP address mismatch."
        )

    # --- REFRESH TOKEN ROTATION (RTR) ---
    new_access_token = create_access_token({"sub": str(user_id)})
    new_refresh_token = create_refresh_token(user_id=str(user_id), client_ip=current_ip)

    _set_auth_cookies(response, new_access_token, new_refresh_token)
    return {"detail": "Token refreshed successfully."}


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


@router.post("/logout")
def logout(response: Response):
    # Both cookies expire karwa rahe hain
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/")
    return {"detail": "Logged out."}