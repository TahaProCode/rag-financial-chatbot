from app.logging_config import logger
from fastapi import HTTPException,Depends ,APIRouter,Request
from app import crud
from app.dependencies import get_current_user
from app.schemas import RoleUpdatePayload


router = APIRouter(prefix="/api/admin", tags=["admin"])

# ---------------------------------------------------------------------
# Admin Routes
# ---------------------------------------------------------------------
@router.get("/users")
def get_all_users(current_user: dict = Depends(get_current_user)):
    logger.info(f"Admin dashboard - user list requested by user_id={current_user.get('id')}")
    """Fetch all registered users for admin dashboard."""
    # Security Check: Direct regular users ko block karo
    if current_user.get("role") != "admin":
        logger.warning(f"Unauthorized admin access attempt by user_id={current_user.get('id')}")
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # DB se users list fetch karein
    users = crud.list_all_users() # Ensure crud me list_all_users() function majood ho
    logger.debug(f"Returned {len(users)} users to admin_id={current_user.get('id')}")
    return users

@router.put("/users/{user_id}/role")
def change_user_role(
    user_id: int, 
    payload: RoleUpdatePayload, 
    current_user: dict = Depends(get_current_user)
):
    logger.info(f"Role change requested: target_user_id={user_id}, new_role={payload.role}, by admin_id={current_user.get('id')}")
    # Security check: Sirf Admin role change kar sakta hai
    if current_user.get("role") != "admin":
        logger.warning(f"Unauthorized role-change attempt by user_id={current_user.get('id')}")
        raise HTTPException(status_code=403, detail="Admin access required")

    # Prevent self-demotion (Optionally Admin apna role accidently badal kar user na kar le)
    if current_user.get("id") == user_id and payload.role != "admin":
        logger.warning(f"Admin attempted self-demotion: admin_id={current_user.get('id')}")
        raise HTTPException(status_code=400, detail="You cannot revoke your own admin rights.")

    updated_user = crud.update_user_role(user_id, payload.role)
    if not updated_user:
        logger.warning(f"Role change failed - user not found: target_user_id={user_id}")
        raise HTTPException(status_code=404, detail="User not found")
    
    logger.info(f"Role changed successfully: user_id={user_id}, new_role={payload.role}")
    return updated_user