"""
CRUD functions for the users table. Kept separate from crud.py since
that file is chat-specific — this one is auth-specific.
"""
from typing import Optional
from .database import get_conn


def create_user(username: str, email: str, hashed_password: str) -> dict:
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO users (username, email, hashed_password)
                   VALUES (%s, %s, %s)
                   RETURNING id, username, email, created_at;""",
                (username, email, hashed_password),
            )
            row = cur.fetchone()
    return _user_row_to_dict(row)


def get_user_by_email(email: str) -> Optional[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id,username, email, hashed_password, created_at
                   FROM users WHERE email = %s;""",
                (email,),
            )
            row = cur.fetchone()
    return _user_row_to_dict(row, include_password=True) if row else None
def get_user_by_username(username: str) -> Optional[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, username, email, created_at
                   FROM users WHERE username = %s;""",
                (username,),
            )
            row = cur.fetchone()
    return _user_row_to_dict(row) if row else None

def get_user_by_id(user_id: int) -> Optional[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id,username, email, created_at
                   FROM users WHERE id = %s;""",
                (user_id,),
            )
            row = cur.fetchone()
    return _user_row_to_dict(row) if row else None

# ---------- OAuth2.0 google authentication check ----------
def get_or_create_google_user(email: str, google_id: str, name: str) -> dict:
    """
    Core linking logic:
    - Agar email already exists (chahe password se signup hua ho), usi account se login karo.
    - Agar exist nahi karta, naya account banao, password NULL rakhte hue.
    """
    existing = get_user_by_email(email)
    if existing:
        return existing  # SAME account se link ho gaya, jaisa humne decide kiya

    # Naya user — username Google ke naam se derive karte hain
    base_username = name.replace(" ", "_").lower() or email.split("@")[0]
    username = base_username

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO users (username, email, hashed_password, google_id)
                   VALUES (%s, %s, NULL, %s)
                   RETURNING id, username, email, created_at;""",
                (username, email, google_id),
            )
            row = cur.fetchone()
    return _user_row_to_dict(row)
# ---------- Update user details ----------
def update_user(user_id: int, username: str, email: str) -> Optional[dict]:
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE users SET username = %s, email = %s
                   WHERE id = %s
                   RETURNING id, username, email, created_at;""",
                (username, email, user_id),
            )
            row = cur.fetchone()
    return _user_row_to_dict(row) if row else None


def get_user_by_username_excluding(username: str, exclude_user_id: int) -> Optional[dict]:
    """Used during profile update — check if username is taken by SOMEONE ELSE."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, username, email, created_at
                   FROM users WHERE username = %s AND id != %s;""",
                (username, exclude_user_id),
            )
            row = cur.fetchone()
    return _user_row_to_dict(row) if row else None


def get_user_by_email_excluding(email: str, exclude_user_id: int) -> Optional[dict]:
    """Used during profile update — check if email is taken by SOMEONE ELSE."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, username, email, created_at
                   FROM users WHERE email = %s AND id != %s;""",
                (email, exclude_user_id),
            )
            row = cur.fetchone()
    return _user_row_to_dict(row) if row else None
# ---------- helpers ----------

def _user_row_to_dict(row, include_password: bool = False) -> dict:
    if include_password:
        return {
            "id": row[0],
            "username": row[1],
            "email": row[2],
            "hashed_password": row[3],
            "created_at": row[4],
        }
    return {
        "id": row[0],
        "username": row[1],
        "email": row[2],
        "created_at": row[3],
    }