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
    """Fetch all registered users for admin dashboard."""
    # Security Check: Direct regular users ko block karo
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # DB se users list fetch karein
    users = crud.list_all_users() # Ensure crud me list_all_users() function majood ho
    return users

@router.put("/users/{user_id}/role")
def change_user_role(
    user_id: int, 
    payload: RoleUpdatePayload, 
    current_user: dict = Depends(get_current_user)
):
    # Security check: Sirf Admin role change kar sakta hai
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    # Prevent self-demotion (Optionally Admin apna role accidently badal kar user na kar le)
    if current_user.get("id") == user_id and payload.role != "admin":
        raise HTTPException(status_code=400, detail="You cannot revoke your own admin rights.")

    updated_user = crud.update_user_role(user_id, payload.role)
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")

    return updated_user