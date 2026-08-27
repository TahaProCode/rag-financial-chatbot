"""
Reusable dependency for protecting routes — reads the JWT from an
httpOnly cookie (not the Authorization header) and resolves it to
the actual user before the route function runs.
"""
from fastapi import HTTPException, Request

from . import auth_crud
from .auth import decode_access_token


def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")

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