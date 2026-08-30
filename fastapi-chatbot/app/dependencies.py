"""
Reusable dependency for protecting routes — reads the JWT from an
httpOnly cookie (not the Authorization header) and resolves it to
the actual user before the route function runs.
"""
from fastapi import HTTPException, Request,Depends,status

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


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Dependency function: Pehle token verify karke user nikalega (via get_current_user),
    phir check karega ke role 'admin' hai ya nahi.
    """
    # Agar get_current_user dict return karta hai:
    user_role = current_user.get("role") if isinstance(current_user, dict) else getattr(current_user, "role", None)
    
    if user_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Admin privileges required."
        )
    return current_user