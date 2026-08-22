"""
CRUD functions for the users table. Kept separate from crud.py since
that file is chat-specific — this one is auth-specific.
"""
from typing import Optional
from .database import get_conn


def create_user(username : str ,email: str, hashed_password: str) -> dict:
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO users (username ,email, hashed_password)
                   VALUES (%s ,%s, %s)
                   RETURNING id, email, created_at;""",
                (username , email, hashed_password),
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