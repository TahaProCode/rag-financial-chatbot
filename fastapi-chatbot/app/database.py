"""
Database layer: connects to the SAME Postgres db (rag_chatbot) you already
set up with pgvector, and adds two new tables for chat history:

- chat_sessions : one row per conversation (id, title, timestamps)
- chat_messages : one row per message (belongs to a session)

Uses psycopg2 directly (same style as your ingestion script), with a
simple connection pool so FastAPI can handle concurrent requests safely.
"""
import os
from contextlib import contextmanager
from psycopg2 import pool
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "rag-chatbot"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "taha123"),
}

# A small connection pool instead of one global connection -
# FastAPI can serve multiple requests at once, and each needs its own
# connection/cursor to avoid stepping on each other.
connection_pool = pool.SimpleConnectionPool(minconn=1, maxconn=10, **DB_CONFIG)


@contextmanager
def get_conn():
    """Borrow a connection from the pool, always return it when done."""
    conn = connection_pool.getconn()
    try:
        yield conn
    finally:
        connection_pool.putconn(conn)


def init_tables():
    """Create chat_sessions and chat_messages tables if they don't exist yet."""
    create_sessions = """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL DEFAULT 'New chat',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """
    create_messages = """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
        content TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """
    create_index = """
    CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
    ON chat_messages(session_id);
    """
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(create_sessions)
            cur.execute(create_messages)
            cur.execute(create_index)
    print("chat_sessions and chat_messages tables ready.")
