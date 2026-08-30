"""
FastAPI app.

Run with:   uvicorn app.main:app --reload --port 8000
Docs at:    http://localhost:8000/docs
UI at:      http://localhost:8000/
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore

from .graph import chat_graph_builder
from . import crud, schemas
from .database import DB_CONFIG, init_tables
from .rag_service import load_rag_service
from .ingest import run_ingestion
from .routers.auth_routes import router as auth_router
from .routers.admin_routes import router as admin_router
from .dependencies import get_current_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_tables()
    load_rag_service()
    run_ingestion()   # idempotent — skips automatically if data already exists

    db_uri = (
        f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
        f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}"
    )

    # 1. Thread Memory (Short Term)
    _checkpointer_cm = PostgresSaver.from_conn_string(db_uri)
    checkpointer = _checkpointer_cm.__enter__()
    checkpointer.setup()

    # 2. Permanent Memory Store (Long Term)
    _store_cm = PostgresStore.from_conn_string(db_uri)
    store = _store_cm.__enter__()
    store.setup()

    # 3. Compile graph with BOTH Checkpointer AND Store
    app.state.chat_graph = chat_graph_builder.compile(checkpointer=checkpointer, store=store)
    app.state.checkpointer_cm = _checkpointer_cm
    app.state.store_cm = _store_cm
    app.state.store = store
    print("Chat graph with Long-Term Memory Store loaded successfully.")
    yield

    app.state.checkpointer_cm.__exit__(None, None, None)
    app.state.store_cm.__exit__(None, None, None)


app = FastAPI(title="RAG Chatbot API", lifespan=lifespan)

# Routers Include
app.include_router(auth_router)
app.include_router(admin_router)

# 2. FIX: Admin router ko yahan include karein

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------
# Chat session CRUD
# ---------------------------------------------------------------------

@app.post("/api/chats", response_model=schemas.ChatSessionOut)
def create_chat(payload: schemas.ChatSessionCreate, current_user: dict = Depends(get_current_user)):
    """Create a new chat session bound to current user."""
    return crud.create_session(payload.title, user_id=current_user["id"])


@app.get("/api/chats", response_model=list[schemas.ChatSessionOut])
def list_chats(current_user: dict = Depends(get_current_user)):
    """List all chat sessions for the logged in user."""
    return crud.list_sessions(user_id=current_user["id"])


@app.get("/api/chats/{chat_id}", response_model=schemas.ChatSessionWithMessages)
def get_chat(chat_id: int, current_user: dict = Depends(get_current_user)):
    """Get one chat session plus its full message history."""
    session = crud.get_session(chat_id, user_id=current_user["id"])
    if not session:
        raise HTTPException(status_code=404, detail="Chat not found")
    session["messages"] = crud.list_messages(chat_id)
    return session


@app.put("/api/chats/{chat_id}", response_model=schemas.ChatSessionOut)
def rename_chat(chat_id: int, payload: schemas.ChatSessionUpdate, current_user: dict = Depends(get_current_user)):
    """Rename a chat's title."""
    updated = crud.update_session_title(chat_id, payload.title, user_id=current_user["id"])
    if not updated:
        raise HTTPException(status_code=404, detail="Chat not found")
    return updated


# ---------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------

@app.get("/api/chats/{chat_id}/messages", response_model=list[schemas.MessageOut])
def get_messages(chat_id: int, current_user: dict = Depends(get_current_user)):
    if not crud.get_session(chat_id, user_id=current_user["id"]):
        raise HTTPException(status_code=404, detail="Chat not found")
    return crud.list_messages(chat_id)


@app.post("/api/chats/{chat_id}/messages", response_model=schemas.SendMessageResponse)
def send_message(chat_id: int, payload: schemas.SendMessageRequest, current_user: dict = Depends(get_current_user)):
    chat_graph = getattr(app.state, "chat_graph", None)
    if chat_graph is None:
        raise HTTPException(status_code=503, detail="Graph is initializing, please try again.")

    session = crud.get_session(chat_id, user_id=current_user["id"])
    if not session:
        raise HTTPException(status_code=404, detail="Chat not found")

    user_message = crud.add_message(chat_id, "user", payload.content)

    if session["title"] == "New chat":
        auto_title = payload.content.strip()[:60]
        crud.update_session_title(chat_id, auto_title or "New chat", user_id=current_user["id"])

    config = {"configurable": {"thread_id": str(chat_id)}}
    result = chat_graph.invoke(
        {"messages": [HumanMessage(content=payload.content)], "top_k": payload.top_k},
        config=config,
    )
    answer = result["messages"][-1].content

    assistant_message = crud.add_message(chat_id, "assistant", answer)
    crud.touch_session(chat_id)

    return {"user_message": user_message, "assistant_message": assistant_message}


@app.delete("/api/chats/{chat_id}", status_code=204)
def delete_chat(chat_id: int, current_user: dict = Depends(get_current_user)):
    """Delete a chat session, its messages, and clear its memory."""
    deleted = crud.delete_session(chat_id, user_id=current_user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    chat_graph = getattr(app.state, "chat_graph", None)
    
    if chat_graph and getattr(chat_graph, "checkpointer", None):
        try:
            chat_graph.checkpointer.delete_thread(str(chat_id))
        except Exception as e:
            print(f"Checkpointer thread delete error: {e}")

    if chat_graph and getattr(chat_graph, "store", None):
        try:
            chat_graph.store.delete((f"user_profile_{chat_id}",), "profile_data")
            chat_graph.store.delete(("user_profile",), "profile_data")
        except Exception as e:
            print(f"Store memory delete error: {e}")


# ---------------------------------------------------------------------
# Frontend (basic ChatGPT-like UI)
# ---------------------------------------------------------------------

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def serve_ui():
    return FileResponse("static/index.html")