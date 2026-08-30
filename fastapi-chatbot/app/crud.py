"""
CRUD (Create, Read, Update, Delete) functions for chat_sessions and
chat_messages. Kept separate from the FastAPI routes (main.py) so the
raw SQL is in one place and easy to test/reuse.
"""
from typing import Optional
from .database import get_conn


# -------- Chat Sessions ---------

def create_session(title: str = "New chat" , user_id : int = None) -> dict:
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO chat_sessions (title , user_id)
                   VALUES (%s,%s)
                   RETURNING id, title, created_at, updated_at;""",
                (title, user_id),
            )
            row = cur.fetchone()
    return _session_row_to_dict(row)


def list_sessions(user_id:int) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, title, created_at, updated_at
                   FROM chat_sessions
                   WHERE user_id = %s
                   ORDER BY updated_at DESC;""",
                   (user_id,),
            )
            rows = cur.fetchall()
    return [_session_row_to_dict(r) for r in rows]


def get_session(session_id: int , user_id:int) -> Optional[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, title, created_at, updated_at
                   FROM chat_sessions WHERE id = %s AND user_id = %s;""",
                (session_id,user_id)
            )
            row = cur.fetchone()
    return _session_row_to_dict(row) if row else None


def update_session_title(session_id: int, title: str , user_id:int) -> Optional[dict]:
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE chat_sessions
                   SET title = %s, updated_at = NOW()
                   WHERE id = %s AND user_id = %s
                   RETURNING id, title, created_at, updated_at;""",
                (title, session_id , user_id),
            )
            row = cur.fetchone()
    return _session_row_to_dict(row) if row else None


def touch_session(session_id: int) -> None:
    """Bump updated_at whenever a new message is added, so the sidebar
    can sort chats by most-recently-active."""
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE chat_sessions SET updated_at = NOW() WHERE id = %s;",
                (session_id,),
            )


def delete_session(session_id: int , user_id:int) -> bool:
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM chat_sessions WHERE id = %s AND user_id = %s RETURNING id;",
                (session_id,user_id),
            )
            row = cur.fetchone()
    return row is not None
# -------- Update user role  ---------

def update_user_role(user_id: int, new_role: str) -> Optional[dict]:
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE users
                   SET role = %s
                   WHERE id = %s
                   RETURNING id, username, email, role;""",
                (new_role, user_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            
            # Agar tuple return hota hai toh dict me convert karein
            if not isinstance(row, dict):
                return {
                    "id": row[0],
                    "username": row[1],
                    "email": row[2],
                    "role": row[3]
                }
            return row

# -------- Get all users  ---------
def list_all_users() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, email, role, created_at FROM users ORDER BY id DESC;")
            rows = cur.fetchall()
            
            # Agar tuple return ho raha hai toh usko dict mein map karein
            if rows and not isinstance(rows[0], dict):
                return [
                    {
                        "id": r[0],
                        "username": r[1],
                        "email": r[2],
                        "role": r[3],
                        "created_at": r[4],
                    }
                    for r in rows
                ]
            return rows
# ---------- Chat Messages ----------

def add_message(session_id: int, role: str, content: str) -> dict:
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO chat_messages (session_id, role, content)
                   VALUES (%s, %s, %s)
                   RETURNING id, session_id, role, content, created_at;""",
                (session_id, role, content),
            )
            row = cur.fetchone()
    return _message_row_to_dict(row)


def list_messages(session_id: int) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, session_id, role, content, created_at
                   FROM chat_messages
                   WHERE session_id = %s
                   ORDER BY created_at ASC;""",
                (session_id,),
            )
            rows = cur.fetchall()
    return [_message_row_to_dict(r) for r in rows]


def delete_message(message_id: int) -> bool:
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            # FIX: Table name chat_messages kar di hai aur parameter tuple fix kar diya hai
            cur.execute(
                "DELETE FROM chat_messages WHERE id = %s RETURNING id;",
                (message_id,),
            )
            row = cur.fetchone()
    return row is not None

# ---------- helpers ----------

def _session_row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "title": row[1],
        "created_at": row[2],
        "updated_at": row[3],
    }


def _message_row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "session_id": row[1],
        "role": row[2],
        "content": row[3],
        "created_at": row[4],
    }
