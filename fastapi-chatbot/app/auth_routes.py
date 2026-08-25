"""
Authentication routes: signup and login. Issues a JWT on success.
"""
import os
from fastapi import APIRouter, HTTPException,Depends
from .dependencies import get_current_user
from . import auth_crud
from .auth import hash_password, verify_password, create_access_token
from .schemas import SignupRequest, LoginRequest, TokenResponse, UserOut,UserUpdateRequest,GoogleAuthRequest
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
# Prefix updated to /api/auth to match JS request URL
router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.post("/signup", response_model=TokenResponse, status_code=201)
def signup(payload: SignupRequest):
    if auth_crud.get_user_by_email(payload.email):
        raise HTTPException(status_code=400, detail="Email already registered.")
    if auth_crud.get_user_by_username(payload.username):
        raise HTTPException(status_code=400, detail="Username already taken.")

    hashed = hash_password(payload.password)
    user = auth_crud.create_user(
        username=payload.username, email=payload.email, hashed_password=hashed
    )

    token = create_access_token({"sub": str(user["id"])})
    return TokenResponse(access_token=token, user=UserOut(**user))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest):
    user = auth_crud.get_user_by_email(payload.email)
    if not user or not verify_password(payload.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = create_access_token({"sub": str(user["id"])})
    return TokenResponse(access_token=token, user=UserOut(**user))


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


@router.post("/google", response_model=TokenResponse)
def google_login(payload: GoogleAuthRequest):
    try:
        # Ye line Google ki public key se signature verify karti hai
        idinfo = google_id_token.verify_oauth2_token(
            payload.id_token, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token.")

    email = idinfo["email"]
    google_id = idinfo["sub"]  # Google ka unique user identifier
    name = idinfo.get("name", "")

    user = auth_crud.get_or_create_google_user(email=email, google_id=google_id, name=name)

    # Yahan se aage BILKUL WAISA HI hai jaisa normal login mein hota hai
    token = create_access_token({"sub": str(user["id"])})
    return TokenResponse(access_token=token, user=UserOut(**user))