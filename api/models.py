"""FastAPI request/response schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from src.validators.schemas import AgentQuery, ValidatedContext


class QueryRequest(AgentQuery):
    """Alias for readability inside the API layer."""


class PlaceResult(BaseModel):
    """
    Place result model for API responses.
    Flexible model that accepts any fields - backend will normalize.
    """
    class Config:
        extra = "allow"  # Allow extra fields for flexibility
    
    # Minimal required fields
    id: Optional[str] = None
    name: str = ""
    
    # Backend expects these but they're optional here
    address: Optional[str] = None
    rating: Optional[float] = Field(default=None, ge=0, le=5)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class QueryResponse(BaseModel):
    response_id: str = Field(default_factory=lambda: str(uuid4()))
    response_text: str
    intention: str
    confidence: float = Field(ge=0.0, le=1.0)
    model_used: str
    processing_time_ms: int
    language: str
    context: ValidatedContext
    places: List[Dict[str, Any]] = Field(default_factory=list)  # Accept dicts directly - already normalized
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    user_id: str
    session_id: Optional[str] = None
    messages: List[ChatMessage]
    mode: str = "chat"
    language: Optional[str] = None


class ChatResponse(BaseModel):
    response_id: str = Field(default_factory=lambda: str(uuid4()))
    messages: List[ChatMessage]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    database_status: str = "unknown"
    redis_status: str = "unknown"
    metrics: Optional[Dict[str, Any]] = None


# Chat models
class ChatResponse(BaseModel):
    """Chat response model."""
    id: str
    user_id: str
    session_id: str
    title: str
    mode: Optional[str] = None
    created_at: str
    updated_at: str


class ChatListResponse(BaseModel):
    """List of chats response."""
    chats: List[ChatResponse]
    total: int


class ChatCreateRequest(BaseModel):
    """Request to create a new chat."""
    user_id: str
    session_id: Optional[str] = None  # If not provided, will be generated
    title: Optional[str] = None  # If not provided, will be auto-generated
    mode: Optional[str] = None


class ChatUpdateRequest(BaseModel):
    """Request to update a chat."""
    title: Optional[str] = None
    mode: Optional[str] = None


class ChatHistoryMessage(BaseModel):
    """Single chat message for history retrieval."""
    role: str
    content: str
    places: Optional[list] = None
    plan: Optional[dict] = None


class ChatHistoryResponse(BaseModel):
    """Chat history response."""
    chat_id: str
    session_id: str
    messages: List[ChatHistoryMessage]


class ChatTitleGenerationRequest(BaseModel):
    """Request to generate a chat title."""
    user_query: str
    agent_response: Optional[str] = None
    language: str = "es"

