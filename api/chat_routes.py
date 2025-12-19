"""API routes for chat management (CRUD operations)."""

from typing import List
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_chat_repo, get_conversation_repo
from api.models import (
    ChatCreateRequest,
    ChatHistoryMessage,
    ChatHistoryResponse,
    ChatListResponse,
    ChatResponse,
    ChatUpdateRequest,
)
from src.database import ChatRepository, ConversationRepository
from src.utils.logger import get_logger
from src.utils.title_generator import generate_chat_title
from src.utils.normalizers import normalize_plan

router = APIRouter(prefix="/chats", tags=["chats"])
logger = get_logger("chat_routes")


@router.get("", response_model=ChatListResponse, status_code=status.HTTP_200_OK)
async def get_user_chats(
    user_id: str,
    limit: int = 50,
    offset: int = 0,
    chat_repo: ChatRepository = Depends(get_chat_repo),
) -> ChatListResponse:
    """
    Get all chats for a user.
    
    Args:
        user_id: User UUID
        limit: Maximum number of chats to return
        offset: Number of chats to skip
        
    Returns:
        List of chats ordered by most recently updated
    """
    try:
        chats = await chat_repo.get_user_chats(
            user_id=user_id,  # Now accepts string (Auth0 IDs)
            limit=limit,
            offset=offset,
        )
        
        chat_responses = [
            ChatResponse(
                id=str(chat.id),
                user_id=str(chat.user_id),
                session_id=str(chat.session_id),
                title=chat.title,
                mode=chat.mode,
                created_at=chat.created_at.isoformat(),
                updated_at=chat.updated_at.isoformat(),
            )
            for chat in chats
        ]
        
        logger.info(
            "user_chats_retrieved",
            user_id=user_id,
            count=len(chat_responses),
        )
        
        return ChatListResponse(chats=chat_responses, total=len(chat_responses))
        
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user_id format",
        )
    except Exception as exc:
        logger.error("failed_to_get_user_chats", user_id=user_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve chats: {str(exc)}",
        ) from exc


@router.get("/{id_or_session}", response_model=ChatResponse, status_code=status.HTTP_200_OK)
async def get_chat(
    id_or_session: str,
    chat_repo: ChatRepository = Depends(get_chat_repo),
) -> ChatResponse:
    """Get a specific chat by either Chat ID or Session ID."""
    try:
        try:
            uuid_val = UUID(id_or_session)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid ID format (must be a valid UUID)",
            )
        
        # Try Chat ID first
        chat = await chat_repo.get_chat_by_id(uuid_val)
        
        # If not found, try Session ID
        if not chat:
            chat = await chat_repo.get_chat_by_session_id(uuid_val)
        
        if not chat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found",
            )
        
        return ChatResponse(
            id=str(chat.id),
            user_id=str(chat.user_id),
            session_id=str(chat.session_id),
            title=chat.title,
            mode=chat.mode,
            created_at=chat.created_at.isoformat(),
            updated_at=chat.updated_at.isoformat(),
        )
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("failed_to_get_chat", chat_id=id_or_session, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve chat: {str(exc)}",
        ) from exc


@router.get("/{id_or_session}/history", response_model=ChatHistoryResponse, status_code=status.HTTP_200_OK)
async def get_chat_history(
    id_or_session: str,
    chat_repo: ChatRepository = Depends(get_chat_repo),
    conversation_repo: ConversationRepository = Depends(get_conversation_repo),
    limit: int = 50,
) -> ChatHistoryResponse:
    """Get the full message history for a chat by either Chat ID or Session ID."""
    try:
        try:
            uuid_val = UUID(id_or_session)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid ID format (must be a valid UUID)",
            )
        
        # Try to find by Chat ID first
        chat = await chat_repo.get_chat_by_id(uuid_val)
        
        # If not found, try to find by Session ID
        if not chat:
            chat = await chat_repo.get_chat_by_session_id(uuid_val)

        if not chat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found",
            )

        turns = await conversation_repo.get_session_history(
            session_id=chat.session_id,
            limit=limit,
        )

        messages: List[ChatHistoryMessage] = []
        for turn in turns:
            messages.append(
                ChatHistoryMessage(
                    role="user",
                    content=turn.user_query,
                )
            )
            # Normalize plan if present
            raw_plan = turn.extra_metadata.get("plan") if turn.extra_metadata else None
            normalized_plan = normalize_plan(raw_plan) if raw_plan else None
            
            messages.append(
                ChatHistoryMessage(
                    role="assistant",
                    content=turn.agent_response,
                    places=turn.places_found or [],
                    plan=normalized_plan,
                )
            )

        logger.info(
            "chat_history_retrieved",
            chat_id=str(chat.id),
            session_id=str(chat.session_id),
            count=len(messages),
        )

        return ChatHistoryResponse(
            chat_id=str(chat.id),
            session_id=str(chat.session_id),
            messages=messages,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("failed_to_get_chat_history", chat_id=id_or_session, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve chat history: {str(exc)}",
        ) from exc


@router.post("", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
async def create_chat(
    request: ChatCreateRequest,
    chat_repo: ChatRepository = Depends(get_chat_repo),
) -> ChatResponse:
    """
    Create a new chat.
    
    If title is not provided, it will be auto-generated from the first message.
    If session_id is not provided, a new UUID will be generated.
    """
    try:
        user_id = request.user_id  # Now accepts string (Auth0 IDs)
        session_uuid = UUID(request.session_id) if request.session_id else uuid4()
        
        # Check if chat with this session_id already exists
        existing_chat = await chat_repo.get_chat_by_session_id(session_uuid)
        if existing_chat:
            # Return existing chat instead of creating duplicate
            return ChatResponse(
                id=str(existing_chat.id),
                user_id=existing_chat.user_id,
                session_id=str(existing_chat.session_id),
                title=existing_chat.title,
                mode=existing_chat.mode,
                created_at=existing_chat.created_at.isoformat(),
                updated_at=existing_chat.updated_at.isoformat(),
            )
        
        # Generate title if not provided
        title = request.title
        if not title:
            # Try to get first message from conversation history to generate title
            # For now, use a default title - title generation will happen in the query endpoint
            title = "Nueva conversación"
        
        chat = await chat_repo.create_chat(
            user_id=user_id,
            session_id=session_uuid,
            title=title,
            mode=request.mode,
        )
        
        logger.info(
            "chat_created",
            chat_id=str(chat.id),
            user_id=request.user_id,
            session_id=str(session_uuid),
        )
        
        return ChatResponse(
            id=str(chat.id),
            user_id=str(chat.user_id),
            session_id=str(chat.session_id),
            title=chat.title,
            mode=chat.mode,
            created_at=chat.created_at.isoformat(),
            updated_at=chat.updated_at.isoformat(),
        )
        
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user_id or session_id format",
        )
    except Exception as exc:
        logger.error("failed_to_create_chat", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create chat: {str(exc)}",
        ) from exc


@router.patch("/{id_or_session}", response_model=ChatResponse, status_code=status.HTTP_200_OK)
async def update_chat(
    id_or_session: str,
    request: ChatUpdateRequest,
    chat_repo: ChatRepository = Depends(get_chat_repo),
) -> ChatResponse:
    """Update a chat (currently only title and mode) by either Chat ID or Session ID."""
    try:
        uuid_val = UUID(id_or_session)
        
        # Find the chat first to get the real ID
        chat = await chat_repo.get_chat_by_id(uuid_val)
        if not chat:
            chat = await chat_repo.get_chat_by_session_id(uuid_val)
            
        if not chat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found",
            )
            
        chat_uuid = chat.id
        
        if request.title:
            chat = await chat_repo.update_chat_title(chat_uuid, request.title)
        
        logger.info("chat_updated", chat_id=str(chat_uuid))
        
        return ChatResponse(
            id=str(chat.id),
            user_id=str(chat.user_id),
            session_id=str(chat.session_id),
            title=chat.title,
            mode=chat.mode,
            created_at=chat.created_at.isoformat(),
            updated_at=chat.updated_at.isoformat(),
        )
        
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid chat_id format",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("failed_to_update_chat", chat_id=chat_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update chat: {str(exc)}",
        ) from exc


@router.delete("/{id_or_session}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    id_or_session: str,
    user_id: str,
    chat_repo: ChatRepository = Depends(get_chat_repo),
) -> None:
    """
    Delete a chat by either Chat ID or Session ID.
    
    Args:
        id_or_session: Chat UUID or Session UUID to delete
        user_id: User UUID (for security - only owner can delete)
    """
    try:
        uuid_val = UUID(id_or_session)
        
        # Find the chat first to get the real ID and owner
        chat = await chat_repo.get_chat_by_id(uuid_val)
        if not chat:
            chat = await chat_repo.get_chat_by_session_id(uuid_val)
            
        if not chat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found",
            )
            
        if chat.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to delete this chat",
            )
            
        deleted = await chat_repo.delete_chat(chat.id, user_id)
        
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found",
            )
        
        logger.info("chat_deleted", chat_id=str(chat.id), user_id=user_id)
        
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid chat_id or user_id format",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("failed_to_delete_chat", chat_id=chat_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete chat: {str(exc)}",
        ) from exc

