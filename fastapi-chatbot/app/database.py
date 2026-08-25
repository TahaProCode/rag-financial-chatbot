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
    """Create chat_sessions, chat_messages, and users tables if they don't exist yet."""
    create_user = """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL UNIQUE,
        hashed_password TEXT,
        google_id TEXT UNIQUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """

    alter_password_nullable = """
    ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL;
    """

    alter_add_google_id = """
    ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id TEXT UNIQUE;
    """
    create_sessions = """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL DEFAULT 'New chat',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """

    add_user_id_column = """
    ALTER TABLE chat_sessions
    ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
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
            cur.execute(create_user)   
            cur.execute(alter_add_google_id)        # 2. add google_id if missing
            cur.execute(alter_password_nullable)    # 1. users table pehle (chat_sessions isay reference karti hai)
            cur.execute(create_sessions)        # 2. chat_sessions table
            cur.execute(add_user_id_column)     # 3. ab user_id column add karo (users table exist karti hai ab)
            cur.execute(create_messages)        # 4. chat_messages
            cur.execute(create_index)           # 5. index
    print("users, chat_sessions, and chat_messages tables ready.")
