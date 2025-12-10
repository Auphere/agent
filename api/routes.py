"""API routes for the agent microservice with full persistence and monitoring."""

from __future__ import annotations

from time import perf_counter
from typing import Any, Dict
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import (
    get_chat_repo,
    get_context_validator,
    get_conversation_repo,
    get_intent_classifier,
    get_llm_router,
    get_memory_manager,
    get_metrics,
    get_metrics_repo,
    get_translator_instance,
)
from api.models import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
)
from src.agents.memory import MemoryManager
from src.agents.react_agent import ReactAgent
from src.classifiers.intent_classifier import IntentClassifier
from src.config import constants
from src.config.settings import Settings, get_settings
from src.database import ChatRepository, ConversationRepository, MetricsRepository
from src.i18n import Translator
from src.routers.llm_router import LLMRouter
from src.utils.logger import get_logger
from src.utils.metrics import MetricsCollector, QueryMetrics
from src.utils.title_generator import generate_chat_title
from src.utils.normalizers import normalize_plan
from src.validators.context_validator import ContextValidator
from src.validators.schemas import ContextValidationError

router = APIRouter(prefix="/agent", tags=["agent"])
logger = get_logger("routes")


@router.post("/query", response_model=QueryResponse, status_code=status.HTTP_200_OK)
async def query_agent(
    request: QueryRequest,
    validator: ContextValidator = Depends(get_context_validator),
    classifier: IntentClassifier = Depends(get_intent_classifier),
    llm_router: LLMRouter = Depends(get_llm_router),
    conversation_repo: ConversationRepository = Depends(get_conversation_repo),
    chat_repo: ChatRepository = Depends(get_chat_repo),
    metrics_repo: MetricsRepository = Depends(get_metrics_repo),
    memory_manager: MemoryManager = Depends(get_memory_manager),
    metrics_collector: MetricsCollector = Depends(get_metrics),
    translator: Translator = Depends(get_translator_instance),
) -> QueryResponse:
    """
    Process a user query through the complete agent pipeline:
    1. Context Validation
    2. Memory Loading (conversation history)
    3. Intent Classification
    4. LLM Routing
    5. Agent Execution (ReAct + Tools)
    6. Response Generation
    7. Persistence (save to database)
    8. Metrics Recording
    """

    # Initialize metrics
    query_id = str(uuid4())
    session_uuid = UUID(request.session_id) if request.session_id else uuid4()
    query_metrics = QueryMetrics(
        query_id=query_id,
        user_id=request.user_id,
        session_id=session_uuid,
    )
    
    # Get or create chat for this session
    user_uuid = UUID(request.user_id)
    chat = None
    is_new_chat = False

    try:
        start_time = perf_counter()
        
        # Get or create chat for this session
        chat = await chat_repo.get_chat_by_session_id(session_uuid)
        is_new_chat = chat is None

        # Step 1: Context Validation
        try:
            validated_context = await validator.build_context(request)
        except ContextValidationError as exc:
            query_metrics.success = False
            query_metrics.error = exc.message
            raise HTTPException(
                status_code=exc.status_code, detail=exc.message
            ) from exc

        # Step 2: Load Memory (conversation history + user patterns)
        memory_context = await memory_manager.build_agent_context(
            user_id=user_uuid,
            session_id=session_uuid,
            current_query=request.query,
            include_history=True,
            include_patterns=False,  # Can enable for more context
        )

        # Step 3: Intent Classification (with caching)
        # Check if chat_mode is "plan" OR if the existing chat is in plan mode
        chat_mode = validated_context.metadata.get("chat_mode", "explore")
        
        # If chat exists and is in plan mode, force PLAN intent for continuity
        if chat and chat.mode == "plan":
            chat_mode = "plan"
            logger.info(
                "forcing_plan_mode_from_existing_chat",
                chat_id=str(chat.id),
                session_id=str(session_uuid)
            )
        
        if chat_mode == "plan":
            # Force PLAN intent when user explicitly chooses plan mode
            from src.classifiers.models import IntentResult, IntentType
            intent_result = IntentResult(
                intention=IntentType.PLAN,
                confidence=1.0,
                complexity="high",
                reasoning="User selected Plan mode from UI or continuing plan conversation"
            )
        else:
            intent_result = await classifier.classify(request.query, validated_context)

        query_metrics.intention = intent_result.intention.value
        query_metrics.confidence = intent_result.confidence
        query_metrics.complexity = intent_result.complexity

        # Step 4: Model Routing
        selected_model = llm_router.route(intent_result)

        query_metrics.model_used = selected_model.name
        query_metrics.model_provider = selected_model.provider

        # Step 5: Execute Agent with Tools (NEW: Using Supervisor)
        from src.agents.supervisor_agent import SupervisorAgent
        
        supervisor = SupervisorAgent()

        # Prepare context for the agent
        agent_context = {
            "user_id": str(request.user_id),
            "session_id": str(session_uuid),
            "conversation_history": memory_context.get("conversation_history", ""),
            "history_messages": memory_context.get("history_messages", []),  # Include message history
            "previous_places": memory_context.get("previous_places", []),  # Include previous places for references
            "location": {
                "lat": validated_context.location.lat,
                "lon": validated_context.location.lon,
            }
            if validated_context.location
            else None,
            "preferences": validated_context.preferences.model_dump()
            if validated_context.preferences
            else None,
            "intention": intent_result.intention,  # Pass intent for context
        }

        # Supervisor routes to appropriate specialized agent
        agent_result = await supervisor.run(
            query=request.query,
            intent=intent_result.intention,
            language=validated_context.language,
            context=agent_context,
        )

        # Update metrics from agent execution
        query_metrics.tool_calls = agent_result.get("tool_calls", 0)
        query_metrics.reasoning_steps = agent_result.get("reasoning_steps", 0)
        query_metrics.places_found = len(agent_result.get("places", []))

        # Estimate tokens (rough approximation)
        query_metrics.input_tokens = len(request.query.split()) * 1.3
        query_metrics.output_tokens = (
            len(agent_result.get("response_text", "").split()) * 1.3
        )

        # Calculate cost
        query_metrics.estimate_cost()

        # Calculate elapsed time
        elapsed = int((perf_counter() - start_time) * 1000)
        query_metrics.processing_time_ms = elapsed
        query_metrics.mark_end()

        # Step 6: Save to Database (conversation turn)
        try:
            # Build extra_metadata with plan if generated
            extra_metadata = {
                "query_id": query_id,
                "reasoning": intent_result.reasoning,
                "cost_usd": query_metrics.estimated_cost_usd,
            }
            
            # Include plan in metadata if it was generated (normalize it first)
            raw_plan = agent_result.get("plan")
            normalized_plan = None
            if raw_plan:
                normalized_plan = normalize_plan(raw_plan)
                extra_metadata["plan"] = normalized_plan
            
            await conversation_repo.save_turn(
                user_id=user_uuid,
                session_id=session_uuid,
                user_query=request.query,
                query_language=validated_context.language,
                intention=intent_result.intention.value,
                confidence=intent_result.confidence,
                complexity=intent_result.complexity,
                model_used=selected_model.name,
                model_provider=selected_model.provider,
                agent_response=agent_result.get("response_text", ""),
                places_found=agent_result.get("places", []),
                processing_time_ms=elapsed,
                tool_calls=query_metrics.tool_calls,
                reasoning_steps=query_metrics.reasoning_steps,
                extra_metadata=extra_metadata,
            )
            logger.info("conversation_turn_saved", query_id=query_id)
            
            # Invalidate session context cache to force refresh on next query
            if memory_manager.conversation_memory.cache:
                cache_key = f"session_context:{session_uuid}"
                await memory_manager.conversation_memory.cache.delete(cache_key)
                logger.debug("session_cache_invalidated", session_id=str(session_uuid))
        except Exception as exc:
            logger.error("failed_to_save_turn", query_id=query_id, error=str(exc))

        # Step 6.5: Create or update chat
        try:
            chat_mode = validated_context.metadata.get("chat_mode", "explore")
            
            if is_new_chat:
                # Generate title from first query and response
                agent_response = agent_result.get("response_text", "")
                title = await generate_chat_title(
                    user_query=request.query,
                    agent_response=agent_response,
                    language=validated_context.language,
                )
                
                chat = await chat_repo.create_chat(
                    user_id=user_uuid,
                    session_id=session_uuid,
                    title=title,
                    mode=chat_mode,
                )
                logger.info(
                    "chat_created_from_query",
                    chat_id=str(chat.id),
                    session_id=str(session_uuid),
                    title=title,
                )
            else:
                # Update chat's updated_at timestamp
                await chat_repo.update_chat_updated_at(chat.id)
                
                # If this is the first turn and title is still default, update it
                # We already have history_messages from memory context, reuse it
                existing_turns = len(memory_context.get("history_messages", [])) // 2  # Divide by 2 (user + assistant messages)
                
                if existing_turns == 0 and chat.title in ["Nueva conversación", "New conversation"]:
                    # Regenerate title with actual context
                    agent_response = agent_result.get("response_text", "")
                    title = await generate_chat_title(
                        user_query=request.query,
                        agent_response=agent_response,
                        language=validated_context.language,
                    )
                    await chat_repo.update_chat_title(chat.id, title)
                    logger.info(
                        "chat_title_updated_from_first_turn",
                        chat_id=str(chat.id),
                        title=title,
                    )
        except Exception as exc:
            # Don't fail the request if chat creation/update fails
            logger.error("failed_to_manage_chat", session_id=str(session_uuid), error=str(exc))

        # Step 7: Record Metrics
        try:
            await metrics_repo.record_query(
                intention=intent_result.intention.value,
                model_used=selected_model.name,
                processing_time_ms=elapsed,
                confidence=intent_result.confidence,
                estimated_cost=query_metrics.estimated_cost_usd,
            )

            # Also record in-memory metrics
            metrics_collector.record_query(query_metrics)

            logger.info(
                "metrics_recorded",
                query_id=query_id,
                cost=query_metrics.estimated_cost_usd,
            )
        except Exception as exc:
            logger.error("failed_to_record_metrics", query_id=query_id, error=str(exc))

        # Construct metadata
        metadata = {
            "query_id": query_id,
            "stage": "agent_complete",
            "reasoning": intent_result.reasoning,
            "complexity": intent_result.complexity,
            "routing_cost_per_1k": selected_model.cost_per_1k,
            "estimated_cost_usd": query_metrics.estimated_cost_usd,
            "tool_calls": query_metrics.tool_calls,
            "reasoning_steps": query_metrics.reasoning_steps,
            "had_conversation_history": bool(
                memory_context.get("conversation_history")
            ),
        }

        # Normalize plan if present
        raw_plan_response = agent_result.get("plan")
        normalized_plan_response = normalize_plan(raw_plan_response) if raw_plan_response else None
        
        # Return final response with plan if generated
        return QueryResponse(
            response_text=agent_result.get("response_text", ""),
            intention=intent_result.intention.value,
            confidence=intent_result.confidence,
            model_used=selected_model.name,
            processing_time_ms=elapsed,
            language=validated_context.language,
            context=validated_context,
            metadata=metadata,
            places=agent_result.get("places", []),
            plan=normalized_plan_response,  # Include normalized plan if generated
        )

    except HTTPException:
        # Re-raise HTTP exceptions (from validation errors)
        raise

    except Exception as exc:
        # Log unexpected errors
        query_metrics.success = False
        query_metrics.error = str(exc)
        query_metrics.mark_end()
        metrics_collector.record_query(query_metrics)

        logger.error("query_failed", query_id=query_id, error=str(exc), exc_info=True)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator.get_error_message(
                "unknown_error", request.language or "es", error=str(exc)
            ),
        ) from exc


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    settings: Settings = Depends(get_settings),
) -> ChatResponse:
    """
    Legacy chat endpoint (for backward compatibility).
    Redirects to /query endpoint.
    """
    query_request = QueryRequest(
        user_id=uuid4(),  # Generate temporary user_id
        query=request.message,
        language=request.language or settings.default_language,
    )

    # Call query_agent internally
    # Note: This is a simplified version - in production, you'd forward all dependencies
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Use /agent/query endpoint instead",
    )


@router.get("/health", response_model=HealthResponse)
async def health_check(
    settings: Settings = Depends(get_settings),
    metrics_collector: MetricsCollector = Depends(get_metrics),
    conversation_repo: ConversationRepository = Depends(get_conversation_repo),
) -> HealthResponse:
    """
    Health check endpoint with service metrics and DB status.
    """
    # Check Database Connection
    db_status = "unknown"
    try:
        if settings.database_url:
            is_connected = await conversation_repo.check_connection()
            db_status = "online" if is_connected else "offline"
        else:
            db_status = "disabled"
    except Exception:
        db_status = "error"

    # Get metrics summary
    metrics_summary = metrics_collector.get_summary(last_n=100)

    return HealthResponse(
        status="healthy",
        service=settings.service_name,
        version=settings.version,
        environment=settings.environment,
        database_status=db_status,
        redis_status="disabled", # TODO: Implement Redis check if needed
        metrics=metrics_summary,
    )


@router.get("/metrics/summary")
async def get_metrics_summary(
    metrics_repo: MetricsRepository = Depends(get_metrics_repo),
    days_back: int = 7,
) -> Dict[str, Any]:
    """
    Get aggregated metrics summary from database.

    Args:
        days_back: Number of days to analyze (default: 7)

    Returns:
        Aggregated metrics including query counts, costs, and performance stats
    """
    try:
        summary = await metrics_repo.get_metrics_summary(days_back=days_back)
        return summary
    except Exception as exc:
        logger.error("failed_to_get_metrics_summary", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve metrics: {str(exc)}",
        ) from exc


@router.get("/metrics/performance")
async def get_performance_stats(
    metrics_collector: MetricsCollector = Depends(get_metrics),
) -> Dict[str, Any]:
    """
    Get real-time performance statistics.

    Returns:
        Performance stats including P50, P95, P99 latencies
    """
    return metrics_collector.get_performance_stats()
