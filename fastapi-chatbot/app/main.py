"""
FastAPI app.

Run with:   uvicorn app.main:app --reload --port 8000
Docs at:    http://localhost:8000/docs
UI at:      http://localhost:8000/
"""
import os
import shutil
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage

from .logging_config import logger  
# FIXED IMPORTS: Async versions for async execution
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore

from .graph import chat_graph_builder
from . import crud, schemas
from .database import DB_CONFIG, init_tables
from .rag_service import load_rag_service
from .ingest import run_ingestion
from .routers.auth_routes import router as auth_router
from .routers.admin_routes import router as admin_router
from .dependencies import get_current_user

from dotenv import load_dotenv
load_dotenv()

# Upload Directory Path
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_tables()
    load_rag_service()
    run_ingestion()   # idempotent — skips automatically if data already exists

    db_uri = (
        f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
        f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}"
    )

    # ASYNC CHECKPOINTER & STORE LIFESPAN FIX
    async with AsyncPostgresSaver.from_conn_string(db_uri) as checkpointer, \
               AsyncPostgresStore.from_conn_string(db_uri) as store:
        
        await checkpointer.setup()
        logger.debug("Checkpointer (short-term memory) initialized in async mode")

        await store.setup()
        logger.debug("Store (long-term memory) initialized in async mode")

        # Compile graph with ASYNC Checkpointer AND Store
        app.state.chat_graph = chat_graph_builder.compile(checkpointer=checkpointer, store=store)
        app.state.checkpointer = checkpointer
        app.state.store = store

        yield

    logger.info("Application shutdown complete")


app = FastAPI(title="RAG Chatbot API", lifespan=lifespan)

# Routers Include
app.include_router(auth_router)
app.include_router(admin_router)

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
    logger.info(f"Chat session creation requested by user_id={current_user['id']}")
    session = crud.create_session(payload.title, user_id=current_user["id"])
    logger.info(f"Chat session created: chat_id={session['id']}")
    return session


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
# Messages & Upload File Integration
# ---------------------------------------------------------------------

@app.get("/api/chats/{chat_id}/messages", response_model=list[schemas.MessageOut])
def get_messages(chat_id: int, current_user: dict = Depends(get_current_user)):
    if not crud.get_session(chat_id, user_id=current_user["id"]):
        raise HTTPException(status_code=404, detail="Chat not found")
    return crud.list_messages(chat_id)


@app.post("/api/chats/{chat_id}/messages", response_model=schemas.SendMessageResponse)
async def send_message(
    chat_id: int,
    content: str = Form(...),
    top_k: int = Form(5),
    file: UploadFile = File(None),
    current_user: dict = Depends(get_current_user)
):
    logger.info(f"Message received: chat_id={chat_id}, user_id={current_user['id']}")
    logger.debug(f"Raw message content: {content}")
    
    chat_graph = getattr(app.state, "chat_graph", None)
    if chat_graph is None:
        logger.error(f"Chat graph not ready for chat_id={chat_id}")
        raise HTTPException(status_code=503, detail="Graph is initializing, please try again.")

    session = crud.get_session(chat_id, user_id=current_user["id"])
    if not session:
        logger.warning(f"Chat not found: chat_id={chat_id}, user_id={current_user['id']}")
        raise HTTPException(status_code=404, detail="Chat not found")

    saved_file_path = None
    if file:
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400, 
                detail=f"Unsupported file format '{file_ext}'. Allowed formats: {', '.join(ALLOWED_EXTENSIONS)}"
            )

        # Unique filename setup (e.g. 550e8400-e29b-41d4-a716-446655440000_report.xlsx)
        unique_filename = f"{uuid.uuid4()}_{file.filename}"
        saved_file_path = str(UPLOAD_DIR / unique_filename)

        try:
            with open(saved_file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            logger.info(f"File uploaded & saved to: {saved_file_path}")
        except Exception as e:
            logger.error(f"Failed to save file: {e}")
            raise HTTPException(status_code=500, detail="Could not save file on server.")
        finally:
            await file.close()

    # Database mein message add karna (file_path parameter optional/supported agar crud schema me update ho)
    user_message = crud.add_message(
        session_id=chat_id,
        role="user",
        content=content,
        file_path=saved_file_path
)

    if session["title"] == "New chat":
        auto_title = content.strip()[:60]
        crud.update_session_title(chat_id, auto_title or "New chat", user_id=current_user["id"])

    config = {"configurable": {"thread_id": str(chat_id)}}
    try:
        # LangChain Message construct (Prompt ke sath metadata ya file path pass ho sakta hai)
        graph_input_content = content
        result = await chat_graph.ainvoke(
       {
        "messages": [HumanMessage(content=graph_input_content)],
        "top_k": top_k,
        "file_path": saved_file_path
       },
       config=config,
)
    except Exception as e:
        logger.debug(f"Graph invocation failed for chat_id={chat_id}: {e}", exc_info=True)
        logger.error(f"Failed to generate response for chat_id={chat_id}")
        raise HTTPException(status_code=500, detail="Failed to generate response")
    
    answer = result["messages"][-1].content
    assistant_message = crud.add_message(chat_id, "assistant", answer)
    crud.touch_session(chat_id)

    logger.info(f"Message processed successfully: chat_id={chat_id}")
    return {"user_message": user_message, "assistant_message": assistant_message}


@app.delete("/api/chats/{chat_id}", status_code=204)
async def delete_chat(chat_id: int, current_user: dict = Depends(get_current_user)):
    """Delete a chat session, its messages, and clear its memory."""
    deleted = crud.delete_session(chat_id, user_id=current_user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    chat_graph = getattr(app.state, "chat_graph", None)
    
    if chat_graph and getattr(chat_graph, "checkpointer", None):
        try:
            await chat_graph.checkpointer.adelete_thread(str(chat_id))
        except Exception as e:
            logger.debug(f"Checkpointer thread delete error: {e}", exc_info=True)

    if chat_graph and getattr(chat_graph, "store", None):
        try:
            await chat_graph.store.adelete((f"user_profile_{chat_id}",), "profile_data")
            await chat_graph.store.adelete(("user_profile",), "profile_data")
        except Exception as e:
            logger.debug(f"Store memory delete error: {e}", exc_info=True)

    logger.info(f"Chat deleted successfully: chat_id={chat_id}")


# ---------------------------------------------------------------------
# Frontend & Static Files Setup
# ---------------------------------------------------------------------

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

@app.get("/")
def serve_ui():
    return FileResponse("static/index.html")