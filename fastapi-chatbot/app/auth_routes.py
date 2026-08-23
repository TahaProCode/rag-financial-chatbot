"""
Authentication routes: signup and login. Issues a JWT on success.
"""
from fastapi import APIRouter, HTTPException,Depends
from .dependencies import get_current_user
from . import auth_crud
from .auth import hash_password, verify_password, create_access_token
from .schemas import SignupRequest, LoginRequest, TokenResponse, UserOut,UserUpdateRequest

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