"""
Pydantic schemas - these define the shape of request/response JSON.
FastAPI uses them to validate incoming data and to generate the
interactive docs at /docs automatically.
"""
from datetime import datetime
from pydantic import BaseModel, Field,EmailStr

class SignupRequest(BaseModel):
    username : str = Field(..., min_length=10)
    email: EmailStr
    password: str = Field(..., min_length=8)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str    

class UserOut(BaseModel):
    id: int
    username: str
    email: EmailStr
    created_at: datetime

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
class ChatSessionCreate(BaseModel):
    title: str = Field(default="New chat", max_length=200)


class ChatSessionUpdate(BaseModel):
    title: str = Field(..., max_length=200)


class ChatSessionOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    created_at: datetime


class ChatSessionWithMessages(ChatSessionOut):
    messages: list[MessageOut] = []


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class SendMessageResponse(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut
