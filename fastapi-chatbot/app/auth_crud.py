"""
CRUD functions for the users table.
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
                   RETURNING id, username, email, role, created_at;""",
                (username, email, hashed_password),
            )
            row = cur.fetchone()
    return _user_row_to_dict(row)


def get_user_by_email(email: str) -> Optional[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, username, email, role, hashed_password, created_at
                   FROM users WHERE email = %s;""",
                (email,),
            )
            row = cur.fetchone()
    return _user_row_to_dict(row, include_password=True) if row else None


def get_user_by_username(username: str) -> Optional[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, username, email, role, created_at
                   FROM users WHERE username = %s;""",
                (username,),
            )
            row = cur.fetchone()
    return _user_row_to_dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[dict]:
    query = """
        SELECT id, username, email, role, created_at 
        FROM users 
        WHERE id = %s;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (user_id,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "username": row[1],
                "email": row[2],
                "role": row[3],
                "created_at": row[4]
            }


def get_or_create_google_user(email: str, google_id: str, name: str) -> dict:
    existing = get_user_by_email(email)
    if existing:
        return existing

    base_username = name.replace(" ", "_").lower() or email.split("@")[0]
    username = base_username

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO users (username, email, hashed_password, google_id)
                   VALUES (%s, %s, NULL, %s)
                   RETURNING id, username, email, role, created_at;""",
                (username, email, google_id),
            )
            row = cur.fetchone()
    return _user_row_to_dict(row)


def update_user(user_id: int, username: str, email: str) -> Optional[dict]:
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE users SET username = %s, email = %s
                   WHERE id = %s
                   RETURNING id, username, email, role, created_at;""",
                (username, email, user_id),
            )
            row = cur.fetchone()
    return _user_row_to_dict(row) if row else None


def get_user_by_username_excluding(username: str, exclude_user_id: int) -> Optional[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, username, email, role, created_at
                   FROM users WHERE username = %s AND id != %s;""",
                (username, exclude_user_id),
            )
            row = cur.fetchone()
    return _user_row_to_dict(row) if row else None


def get_user_by_email_excluding(email: str, exclude_user_id: int) -> Optional[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, username, email, role, created_at
                   FROM users WHERE email = %s AND id != %s;""",
                (email, exclude_user_id),
            )
            row = cur.fetchone()
    return _user_row_to_dict(row) if row else None


# ---------- Helpers ----------

def _user_row_to_dict(row, include_password: bool = False) -> dict:
    if include_password:
        return {
            "id": row[0],
            "username": row[1],
            "email": row[2],
            "role": row[3],
            "hashed_password": row[4],
            "created_at": row[5],
        }
    return {
        "id": row[0],
        "username": row[1],
        "email": row[2],
        "role": row[3],
        "created_at": row[4],
    }