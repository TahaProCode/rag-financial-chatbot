"""
FastAPI app.

Run with:  uvicorn app.main:app --reload --port 8000
Docs at:   http://localhost:8000/docs
UI at:     http://localhost:8000/
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore #imp
from .graph import chat_graph_builder
from .import crud, schemas
from .database import DB_CONFIG, init_tables
from .rag_service import load_rag_service



# async def lifespan(app: FastAPI):
#     # Runs once when the server starts
#     init_tables()
#     load_rag_service()  # loads the embedding model - can take a few seconds
#     yield
#     # (nothing needed on shutdown)
# async def lifespan(app: FastAPI):
#     global chat_graph, _checkpointer_cm

#     init_tables()
#     load_rag_service()

#     _checkpointer_cm = PostgresSaver.from_conn_string(
#     f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
#     f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}"
# )
#     checkpointer = _checkpointer_cm.__enter__()
#     checkpointer.setup()
    
#     chat_graph = chat_graph_builder.compile(checkpointer=checkpointer)
#     print("Chat graph loaded")
#     yield

#     _checkpointer_cm.__exit__(None, None, None)


# Baqi saare imports same rahenge, bas PostgresStore import karein:
  # <-- Import Long term store


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_tables()
    load_rag_service()

    db_uri = (
        f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
        f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}"
    )

    # 1. Thread Memory (Short Term)
    _checkpointer_cm = PostgresSaver.from_conn_string(db_uri)
    checkpointer = _checkpointer_cm.__enter__()
    checkpointer.setup()

    # 2. Permanent Memory Store (Long Term like Video)
    _store_cm = PostgresStore.from_conn_string(db_uri)
    store = _store_cm.__enter__()
    store.setup() # Yeh database mein automatic `langgraph_store` tables bana dega
    
    # 3. Compile graph with BOTH Checkpointer AND Store and save to app.state
    app.state.chat_graph = chat_graph_builder.compile(checkpointer=checkpointer, store=store)
    app.state.checkpointer_cm = _checkpointer_cm
    app.state.store_cm = _store_cm
    
    print("Chat graph with Long-Term Memory Store loaded successfully.")
    yield

    app.state.checkpointer_cm.__exit__(None, None, None)
    app.state.store_cm.__exit__(None, None, None)

app = FastAPI(title="RAG Chatbot API", lifespan=lifespan)
# Allow the frontend (served from the same app, but also handy if you ever
# split it out to its own dev server on a different port) to call the API.
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
def create_chat(payload: schemas.ChatSessionCreate):
    """Create a new chat session (like clicking 'New chat')."""
    return crud.create_session(payload.title)


@app.get("/api/chats", response_model=list[schemas.ChatSessionOut])
def list_chats():
    """List all chat sessions, most recently active first (sidebar list)."""
    return crud.list_sessions()


@app.get("/api/chats/{chat_id}", response_model=schemas.ChatSessionWithMessages)
def get_chat(chat_id: int):
    """Get one chat session plus its full message history."""
    session = crud.get_session(chat_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat not found")
    session["messages"] = crud.list_messages(chat_id)
    return session


@app.put("/api/chats/{chat_id}", response_model=schemas.ChatSessionOut)
def rename_chat(chat_id: int, payload: schemas.ChatSessionUpdate):
    """Rename a chat's title."""
    updated = crud.update_session_title(chat_id, payload.title)
    if not updated:
        raise HTTPException(status_code=404, detail="Chat not found")
    return updated


# ---------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------

@app.get("/api/chats/{chat_id}/messages", response_model=list[schemas.MessageOut])
def get_messages(chat_id: int):
    if not crud.get_session(chat_id):
        raise HTTPException(status_code=404, detail="Chat not found")
    return crud.list_messages(chat_id)


@app.post("/api/chats/{chat_id}/messages", response_model=schemas.SendMessageResponse)
def send_message(chat_id: int, payload: schemas.SendMessageRequest):
    # Retrieve chat_graph directly from app state context
    chat_graph = getattr(app.state, "chat_graph", None)
    if chat_graph is None:
        raise HTTPException(status_code=503, detail="Graph is initializing, please try again.")

    session = crud.get_session(chat_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat not found")

    user_message = crud.add_message(chat_id, "user", payload.content)

    if session["title"] == "New chat":
        auto_title = payload.content.strip()[:60]
        crud.update_session_title(chat_id, auto_title or "New chat")

    config = {"configurable": {"thread_id": str(chat_id)}}
    result = chat_graph.invoke(
        {"messages": [HumanMessage(content=payload.content)], "top_k": payload.top_k},
        config=config,
    )
    answer = result["messages"][-1].content

    assistant_message = crud.add_message(chat_id, "assistant", answer)
    crud.touch_session(chat_id)

    return {"user_message": user_message, "assistant_message": assistant_message}

# def send_message(chat_id: int, payload: schemas.SendMessageRequest):
#     """
#     The core chat action: store the user's message, run it through the
#     RAG pipeline (retrieve + Ollama), store the assistant's reply, and
#     return both. Also auto-titles a fresh chat from the first message.
#     """
#     from .rag_service import rag_service  # imported here so lifespan has already loaded it

#     session = crud.get_session(chat_id)
#     if not session:
#         raise HTTPException(status_code=404, detail="Chat not found")

#     user_message = crud.add_message(chat_id, "user", payload.content)

#     # Auto-title new chats from their first message, like ChatGPT does
#     if session["title"] == "New chat":
#         auto_title = payload.content.strip()[:60]
#         crud.update_session_title(chat_id, auto_title or "New chat")

#     answer = rag_service.answer(payload.content, top_k=payload.top_k)
#     assistant_message = crud.add_message(chat_id, "assistant", answer)

#     crud.touch_session(chat_id)

#     return {"user_message": user_message, "assistant_message": assistant_message}


@app.delete("/api/chats/{chat_id}", status_code=204)
def delete_chat(chat_id: int):
    """Delete a chat session and all its messages (ON DELETE CASCADE)."""
    deleted = crud.delete_session(chat_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    chat_graph = getattr(app.state, "chat_graph", None)
    # Checkpointer thread state logic safe execution
    if chat_graph and getattr(chat_graph, "checkpointer", None):
        try:
            chat_graph.checkpointer.delete_thread(str(chat_id))
        except AttributeError:
            # Fallback if specific driver structure varies
            pass

# def delete_message(message_id: int):
#     deleted = crud.delete_message(message_id)
#     if not deleted:
#         raise HTTPException(status_code=404, detail="Message not found")


# ---------------------------------------------------------------------
# Frontend (basic ChatGPT-like UI)
# ---------------------------------------------------------------------

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def serve_ui():
    return FileResponse("static/index.html")