"""SQLAlchemy models for agent persistence."""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import JSON, BigInteger, Float, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class ConversationTurn(Base):
    """
    Stores individual turns in agent conversations.
    Each turn represents a user query + agent response.
    """

    __tablename__ = "conversation_turns"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    # User & session identification
    user_id: Mapped[str] = mapped_column(String(255), index=True)  # Changed to String to support Auth0 IDs
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), index=True)

    # Query details
    user_query: Mapped[str] = mapped_column(Text, nullable=False)
    query_language: Mapped[str] = mapped_column(String(5), nullable=False)

    # Classification results
    intention: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    complexity: Mapped[str] = mapped_column(String(10), nullable=False)

    # Model selection
    model_used: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model_provider: Mapped[str] = mapped_column(String(20), nullable=False)

    # Response
    agent_response: Mapped[str] = mapped_column(Text, nullable=False)
    places_found: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Performance metrics
    processing_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tool_calls: Mapped[int] = mapped_column(BigInteger, default=0)
    reasoning_steps: Mapped[int] = mapped_column(BigInteger, default=0)

    # Additional metadata (renamed from 'metadata' to avoid SQLAlchemy conflict)
    extra_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<ConversationTurn {self.id} user={self.user_id} intent={self.intention}>"


class UserPreference(Base):
    """
    Stores user preferences for personalization.
    """

    __tablename__ = "user_preferences"

    # Primary key
    user_id: Mapped[str] = mapped_column(
        String(255),  # Changed to String to support Auth0 IDs
        primary_key=True,
    )

    # Preferences
    preferred_language: Mapped[str] = mapped_column(String(5), nullable=False)
    preferred_model: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    budget_mode: Mapped[bool] = mapped_column(default=False)

    # Personalization data
    favorite_categories: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    location_history: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    interaction_count: Mapped[int] = mapped_column(BigInteger, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<UserPreference user={self.user_id} lang={self.preferred_language}>"


class Chat(Base):
    """
    Stores chat/conversation sessions with users.
    Each chat has a title and is associated with a user and session_id.
    """

    __tablename__ = "chats"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    # User & session identification
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)  # Changed to String to support Auth0 IDs
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), unique=True, index=True, nullable=False)

    # Chat metadata
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Optional: store mode (explore/plan) for context
    mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<Chat {self.id} user={self.user_id} title='{self.title}'>"


class AgentMetrics(Base):
    """
    Aggregated metrics for monitoring and optimization.
    """

    __tablename__ = "agent_metrics"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    # Time window
    date: Mapped[datetime] = mapped_column(nullable=False, index=True)
    hour: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Aggregations
    total_queries: Mapped[int] = mapped_column(BigInteger, default=0)
    avg_processing_time_ms: Mapped[float] = mapped_column(Float, default=0.0)
    avg_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    # By intention
    search_count: Mapped[int] = mapped_column(BigInteger, default=0)
    recommend_count: Mapped[int] = mapped_column(BigInteger, default=0)
    plan_count: Mapped[int] = mapped_column(BigInteger, default=0)
    chitchat_count: Mapped[int] = mapped_column(BigInteger, default=0)

    # By model
    model_usage: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Estimated costs
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)

    def __repr__(self) -> str:
        """String representation."""
        return f"<AgentMetrics {self.date} queries={self.total_queries}>"

