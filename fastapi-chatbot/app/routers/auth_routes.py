"""
Authentication routes: signup, login, Google OAuth, logout, refresh, user management.
Sets JWTs (Access and Refresh) as httpOnly cookies.
"""
from app.logging_config import logger
import os
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from jose import JWTError, jwt

from app import auth_crud
from app.auth import (
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
    create_refresh_token,
    get_client_ip,
    hash_password,
    verify_password,
)
from app.database import get_conn
from app.dependencies import get_current_user, require_admin
from app.schemas import (
    GoogleAuthRequest,
    LoginRequest,
    SignupRequest,
    UserOut,
    UserUpdateRequest,
)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

# Single Router instance
router = APIRouter(prefix="/api/auth", tags=["Auth"])

ACCESS_TOKEN_MAX_AGE = 15 * 60         # 15 mins
REFRESH_TOKEN_MAX_AGE = 7 * 24 * 60 * 60  # 7 days


# ---------------------------------------------------------------
# RATE LIMITING (login/signup brute-force se bachane ke liye)
# ---------------------------------------------------------------
# In-memory, IP-based. Single server/process ke liye theek hai.
# Multiple instances (load balancer ke peeche) ho toh Redis use karo.

def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=False,  # Set True in production
        samesite="lax",
        max_age=ACCESS_TOKEN_MAX_AGE,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=False,  # Set True in production
        samesite="lax",
        max_age=REFRESH_TOKEN_MAX_AGE,
        path="/",
    )


@router.post("/signup", response_model=UserOut, status_code=201)
def signup(payload: SignupRequest, request: Request, response: Response):
    logger.info(f"Signup attempt: email={payload.email}")  # email theek hai, password/hash NAHI
    if auth_crud.get_user_by_email(payload.email):
        logger.warning(f"Signup failed - email already registered: {payload.email}")
        raise HTTPException(status_code=400, detail="Email already registered.")
    if auth_crud.get_user_by_username(payload.username):
        logger.warning(f"Signup failed - username taken: {payload.username}")
        raise HTTPException(status_code=400, detail="Username already taken.")

    hashed = hash_password(payload.password)
    user = auth_crud.create_user(
        username=payload.username, email=payload.email, hashed_password=hashed
    )

    client_ip = get_client_ip(request)
    access_token = create_access_token({"sub": str(user["id"])})
    refresh_token = create_refresh_token(user_id=str(user["id"]), client_ip=client_ip)

    _set_auth_cookies(response, access_token, refresh_token)
    logger.info(f"Signup successful: user_id={user['id']}")
    return UserOut(**user)


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, request: Request, response: Response):
    logger.info(f"Login attempt: email={payload.email}")
    user = auth_crud.get_user_by_email(payload.email)
    if not user or not verify_password(payload.password, user["hashed_password"]):
        logger.warning(f"Login failed - invalid credentials: email={payload.email}")
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    client_ip = get_client_ip(request)
    access_token = create_access_token({"sub": str(user["id"])})
    refresh_token = create_refresh_token(user_id=str(user["id"]), client_ip=client_ip)

    _set_auth_cookies(response, access_token, refresh_token)
    logger.info(f"Login successful: user_id={user['id']}")
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
    token = request.cookies.get("refresh_token")
    if not token:
        logger.warning("Refresh attempt with no token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing."
        )

    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        logger.debug(f"Refresh token decode failed: {JWTError}", exc_info=True)   # detail sirf developer ke liye
        logger.warning("Refresh failed - invalid/expired token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token."
        )

    if data.get("type") != "refresh":
        logger.warning("Refresh failed - wrong token type used")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type."
        )

    user_id = data.get("sub")
    token_ip = data.get("ip")
    current_ip = get_client_ip(request)

    # IP Mismatch Check & Security Clean-up
    if token_ip != current_ip:
        logger.warning(f"Security alert - IP mismatch on refresh: user_id={user_id}")
        response.delete_cookie("access_token")
        response.delete_cookie("refresh_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Security violation: IP address mismatch."
        )

    # Naya Access Token aur Refresh Token (Token Rotation)
    new_access_token = create_access_token({"sub": str(user_id), "ip": current_ip})
    new_refresh_token = create_refresh_token(user_id=str(user_id), client_ip=current_ip)

    _set_auth_cookies(response, new_access_token, new_refresh_token)
    logger.info(f"Token refreshed successfully: user_id={user_id}")
    return {"detail": "Token refreshed successfully."}


@router.get("/admin/users", response_model=List[UserOut])
def get_all_users(admin_user: dict = Depends(require_admin)):
    """
    Sirf Admin role wala user access kar sakta hai.
    URL: /api/auth/admin/users
    """
    query = """
        SELECT id, username, email, role, created_at 
        FROM users 
        ORDER BY created_at DESC;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            logger.debug(f"Fetched {len(rows)} users from DB")
            return [
                {
                    "id": row[0],
                    "username": row[1],
                    "email": row[2],
                    "role": row[3],
                    "created_at": row[4]
                }
                for row in rows
            ]


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
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/")
    logger.info("User logged out")
    return {"detail": "Logged out."}