"""
Reusable dependency for protecting routes — require a valid JWT and
resolve it to the actual user before the route function runs.
"""
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from . import auth_crud
from .auth import decode_access_token

# tokenUrl is just for the /docs page's "Authorize" button — it doesn't
# affect how we actually validate tokens (we do that ourselves below).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload.")

    user = auth_crud.get_user_by_id(int(user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists.")

    return user