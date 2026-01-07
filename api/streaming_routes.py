"""API routes for real-time streaming responses with agent reasoning."""

from __future__ import annotations

import asyncio
import json
from time import perf_counter
from typing import AsyncGenerator
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from api.dependencies import (
    get_chat_repo,
    get_context_validator,
    get_conversation_repo,
    get_intent_classifier,
    get_llm_router,
    get_memory_manager,
    get_translator_instance,
)
from api.models import QueryRequest
from src.agents.memory import MemoryManager
from src.classifiers.intent_classifier import IntentClassifier
from src.config import constants
from src.database import ChatRepository, ConversationRepository
from src.i18n import Translator
from src.routers.llm_router import LLMRouter
from src.utils.logger import get_logger
from src.utils.normalizers import normalize_plan
from src.utils.title_generator import generate_chat_title
from src.validators.context_validator import ContextValidator
from src.validators.schemas import ContextValidationError

router = APIRouter(prefix="/agent", tags=["agent-streaming"])
logger = get_logger("streaming_routes")


async def stream_agent_response(
    request: QueryRequest,
    validator: ContextValidator,
    classifier: IntentClassifier,
    llm_router: LLMRouter,
    conversation_repo: ConversationRepository,
    chat_repo: ChatRepository,
    memory_manager: MemoryManager,
    translator: Translator,
) -> AsyncGenerator[str, None]:
    """
    Stream agent response with real-time reasoning steps.
    
    Yields SSE events:
    - status: Processing updates ("thinking", "using_tools", etc.)
    - thought: Agent's reasoning (ReAct THINK step)
    - action: Tool being used (ReAct ACT step)
    - observation: Tool result (ReAct OBSERVE step)
    - token: Response text chunks
    - end: Final complete response
    - error: Error messages
    """
    
    query_id = str(uuid4())
    session_uuid = UUID(request.session_id) if request.session_id else uuid4()
    user_id = request.user_id  # Now accepts string (Auth0 IDs)
    
    try:
        start_time = perf_counter()
        
        # Step 1: Status update - Starting
        yield f"event: status\ndata: {json.dumps({'content': '🔍 Analizando tu consulta...'})}\n\n"
        await asyncio.sleep(0.1)
        
        # Get or create chat
        chat = await chat_repo.get_chat_by_session_id(session_uuid)
        is_new_chat = chat is None
        
        # Step 2: Validate context
        try:
            validated_context = await validator.build_context(request)
        except ContextValidationError as exc:
            error_data = {"content": f"Error de validación: {exc.message}"}
            yield f"event: error\ndata: {json.dumps(error_data)}\n\n"
            return
        
        # Step 3: Load memory (using NEW ConversationBuffer system)
        yield f"event: status\ndata: {json.dumps({'content': '🧠 Cargando contexto de conversación...'})}\n\n"
        await asyncio.sleep(0.1)
        
        memory_context = await memory_manager.build_agent_context(
            user_id=user_id,
            session_id=session_uuid,
            current_query=request.query,
            include_history=True,
            include_patterns=False,
            current_language=request.language or "es",
        )
        
        # Step 4: Intent classification
        yield f"event: status\ndata: {json.dumps({'content': '🎯 Clasificando intención...'})}\n\n"
        await asyncio.sleep(0.1)
        
        chat_mode = validated_context.metadata.get("chat_mode", "explore")
        
        # If user explicitly selected "plan" mode, force PLAN intent
        if chat_mode == "plan":
            from src.classifiers.models import IntentResult, IntentType
            intent_result = IntentResult(
                intention=IntentType.PLAN,
                confidence=1.0,
                complexity="high",
                reasoning="Usuario seleccionó modo Plan explícitamente"
            )
            
            thought_data = {"content": f"💭 **Pensamiento**: {intent_result.reasoning}"}
            yield f"event: thought\ndata: {json.dumps(thought_data)}\n\n"
        else:
            # In explore mode, pass chat_mode to classifier to prevent wrong PLAN classification
            intent_result = await classifier.classify(request.query, validated_context, chat_mode=chat_mode)
            
            thought_data = {
                "content": f"💭 **Detecté**: {intent_result.intention.value} (confianza: {intent_result.confidence:.0%})"
            }
            yield f"event: thought\ndata: {json.dumps(thought_data)}\n\n"
        
        await asyncio.sleep(0.1)
        
        # Step 5: Model routing
        selected_model = llm_router.route(intent_result)
        
        yield f"event: status\ndata: {json.dumps({'content': f'🤖 Usando modelo: {selected_model.name}'})}\n\n"
        await asyncio.sleep(0.1)
        
        # Step 5.5: Extract plan parameters if PLAN intent (BEFORE execution)
        plan_params = {}
        if intent_result.intention.value == "PLAN":
            yield f"event: status\ndata: {json.dumps({'content': '🧩 Extrayendo parámetros del plan...'})}\n\n"
            await asyncio.sleep(0.1)
            
            from src.agents.utils.structured_parameter_extractor import StructuredParameterExtractor
            
            try:
                extractor = StructuredParameterExtractor()
                
                # Load previous parameters from memory if available
                previous_params = {}
                conversation_history = []
                
                # ✅ FIX: Process recent_turns to extract plan_params from ALL turns
                recent_turns = memory_context.get("recent_turns", [])
                
                if recent_turns:
                    logger.debug(
                        "processing-recent-turns",
                        turn_count=len(recent_turns),
                        turn_type=type(recent_turns[0]).__name__ if recent_turns else None
                    )
                    
                    # Process turns to build conversation history AND find previous plan_params
                    # Turns are in reverse order (most recent first), so we iterate to find the most recent plan_params
                    for turn in recent_turns:
                        try:
                            # Extract user_query and agent_response
                            user_query = None
                            agent_response = None
                            extra_metadata = None
                            
                            # Try as object with attributes (ConversationTurn model)
                            if hasattr(turn, 'user_query'):
                                user_query = turn.user_query
                                agent_response = getattr(turn, 'agent_response', '')
                                extra_metadata = getattr(turn, 'extra_metadata', None)
                            # Try as dictionary
                            elif isinstance(turn, dict):
                                user_query = turn.get("user_query", "")
                                agent_response = turn.get("agent_response", "")
                                extra_metadata = turn.get("extra_metadata")
                            
                            if user_query:
                                conversation_history.append({
                                    "user_query": user_query,
                                    "agent_response": agent_response or "",
                                })
                            
                            # ✅ FIX: Extract plan_params from the MOST RECENT turn that has them
                            # This ensures we accumulate parameters across the conversation
                            if not previous_params and extra_metadata:
                                turn_plan_params = extra_metadata.get("plan_params")
                                if turn_plan_params and isinstance(turn_plan_params, dict) and len(turn_plan_params) > 0:
                                    previous_params = turn_plan_params.copy()
                                    logger.info(
                                        "loaded-previous-plan-params",
                                        params=previous_params,
                                        from_turn=user_query[:50] if user_query else "unknown"
                                    )
                                    
                        except Exception as e:
                            logger.warning("failed-to-process-turn", error=str(e))
                            continue
                
                logger.debug(
                    "extraction-context-built",
                    conversation_history_count=len(conversation_history),
                    previous_params_count=len(previous_params),
                    previous_params_keys=list(previous_params.keys()) if previous_params else []
                )
                
                # Extract parameters from conversation
                extracted_params = await extractor.extract_from_conversation(
                    current_query=request.query,
                    conversation_history=conversation_history,
                )
                
                logger.debug(
                    "extraction-results",
                    extracted=extracted_params.model_dump(exclude_none=True),
                    previous=previous_params
                )
                
                # Merge with previous parameters
                # IMPORTANT: Start with previous params to ensure we don't lose information
                plan_params = previous_params.copy() if previous_params else {}
                
                # Add/update with newly extracted params (only non-None values)
                new_dict = extracted_params.model_dump(exclude_none=True)
                for field, value in new_dict.items():
                    if value is not None and value != [] and value != "":
                        # For lists, merge uniquely
                        if isinstance(value, list) and field in plan_params and isinstance(plan_params[field], list):
                            plan_params[field] = list(set(plan_params[field] + value))
                        else:
                            # Add/override scalar values
                            plan_params[field] = value
                
                logger.debug("merged-params", result=plan_params)
                
                # Special handling: calculate budget_per_person from total budget if possible
                # This handles cases like:
                # - "presupuesto total de 100 euros"
                # - "100 euros en total"
                # - "tenemos un presupuesto de 100 euros"
                # - "100€ aproximadamente"
                query_lower = request.query.lower()
                
                # Check if budget_per_person is not already set and we have num_people
                if not plan_params.get("budget_per_person") and plan_params.get("num_people"):
                    import re
                    
                    # Multiple patterns to capture budget amounts
                    budget_patterns = [
                        r'presupuesto\s*(?:total\s*)?(?:de\s*)?(\d+)\s*€?(?:\s*euros?)?',
                        r'(\d+)\s*€?\s*(?:euros?)?\s*(?:en\s*)?total',
                        r'(\d+)\s*€?\s*(?:euros?)?\s*(?:aproximadamente|aprox)?',
                        r'tenemos\s*(?:un\s*)?(?:presupuesto\s*de\s*)?(\d+)\s*€?\s*(?:euros?)?',
                        r'(\d+)\s*€\s*(?:de\s*presupuesto)?',
                    ]
                    
                    for pattern in budget_patterns:
                        budget_match = re.search(pattern, query_lower)
                        if budget_match:
                            total_budget = float(budget_match.group(1))
                            plan_params["budget_per_person"] = round(total_budget / plan_params["num_people"], 2)
                            logger.info(
                                "budget-calculated-from-total",
                                total=total_budget,
                                num_people=plan_params["num_people"],
                                per_person=plan_params["budget_per_person"],
                                matched_pattern=pattern
                            )
                            break
                
                logger.info("plan-params-extracted-pre-execution", params=plan_params)
                
                # Show what we extracted
                extracted_count = len([v for v in plan_params.values() if v is not None and v != [] and v != ""])
                yield f"event: thought\ndata: {json.dumps({'content': f'💭 **Extracción**: Detecté {extracted_count} parámetros de tu consulta'})}\n\n"
                
            except Exception as e:
                logger.error("plan-params-extraction-failed-pre-execution", error=str(e))
                # Continue with empty params rather than failing
                plan_params = {}
        
        # Step 6: Execute agent
        from src.agents.supervisor_singleton import get_supervisor_agent
        
        supervisor = get_supervisor_agent()
        
        # Better status messages based on intent
        intent_name = intent_result.intention.value
        if intent_name == "PLAN":
            yield f"event: status\ndata: {json.dumps({'content': '📋 Creando plan detallado paso a paso...'})}\n\n"
            await asyncio.sleep(0.1)
            yield f"event: thought\ndata: {json.dumps({'content': '💭 **Planificador**: Analizando tu solicitud para crear el mejor itinerario'})}\n\n"
        elif intent_name == "SEARCH":
            yield f"event: status\ndata: {json.dumps({'content': '🔍 Buscando lugares perfectos para ti...'})}\n\n"
            await asyncio.sleep(0.1)
            yield f"event: thought\ndata: {json.dumps({'content': '💭 **Buscador**: Explorando bases de datos de millones de lugares'})}\n\n"
        elif intent_name == "RECOMMEND":
            yield f"event: status\ndata: {json.dumps({'content': '⭐ Generando recomendaciones personalizadas...'})}\n\n"
            await asyncio.sleep(0.1)
            yield f"event: thought\ndata: {json.dumps({'content': '💭 **Recomendador**: Analizando opciones y rankings'})}\n\n"
        else:
            yield f"event: status\ndata: {json.dumps({'content': '⚡ Ejecutando agente especializado...'})}\n\n"
            await asyncio.sleep(0.1)
        
        await asyncio.sleep(0.2)
        
        # Show what sources we'll use
        if intent_name == "PLAN":
            yield f"event: status\ndata: {json.dumps({'content': '🌐 Consultando: Foursquare (105M POIs), Instagram, TikTok, TripAdvisor...'})}\n\n"
            await asyncio.sleep(0.2)
            yield f"event: thought\ndata: {json.dumps({'content': '💭 **Paso 1**: Buscando lugares que coincidan con tus preferencias'})}\n\n"
        elif intent_name == "SEARCH":
            yield f"event: status\ndata: {json.dumps({'content': '🌐 Consultando: Google Places, Foursquare, base de datos local...'})}\n\n"
        
        # Execute agent (this is the actual work)
        # Periodic status updates during execution
        
        # Create a task for the agent execution
        async def execute_with_progress():
            # Status updater task
            async def show_progress():
                progress_messages = [
                    "🔍 Analizando millones de lugares...",
                    "📊 Evaluando ratings y reseñas...",
                    "📸 Consultando contenido en redes sociales...",
                    "⭐ Priorizando las mejores opciones...",
                    "🗺️ Calculando rutas óptimas...",
                    "✨ Finalizando recomendaciones...",
                ]
                
                for msg in progress_messages:
                    await asyncio.sleep(3)  # Update every 3 seconds
                    yield f"event: status\ndata: {json.dumps({'content': msg})}\n\n"
            
            # Run agent
            return await supervisor.run(
                query=request.query,
                intent=intent_result.intention,
                language=request.language or "es",
                context=agent_context,
            )
        
        # Build agent context with all necessary information
        # ✅ FIX: Merge memory_context directly into context (not nested)
        # ✅ FIX: Serialize datetime objects to strings
        # ✅ CRITICAL: plan_params and session_id at top level for LangGraph
        validated_context_dict = validated_context.dict()
        # Convert any datetime objects to ISO format strings
        for key, value in validated_context_dict.items():
            if hasattr(value, 'isoformat'):
                validated_context_dict[key] = value.isoformat()
        
        agent_context = {
            "user_id": str(user_id),
            "session_id": str(session_uuid),  # ✅ CRITICAL: Used as thread_id in LangGraph
            "plan_params": plan_params,  # ✅ CRITICAL: Passed to LangGraph state
            "validated_context": validated_context_dict,
            **memory_context,  # ← Unpack memory_context directly
        }
        
        # Execute agent with full context
        # session_id and plan_params will be extracted by specialized agents
        agent_result = await supervisor.run(
            query=request.query,
            intent=intent_result.intention,
            language=request.language or "es",
            context=agent_context,
        )
        
        # Show actions taken
        if agent_result.get("places"):
            action_data = {
                "content": f"🔧 **Acción**: Encontré {len(agent_result['places'])} lugares relevantes"
            }
            yield f"event: action\ndata: {json.dumps(action_data)}\n\n"
            await asyncio.sleep(0.2)
        
        # Stream response text word by word
        response_text = agent_result.get("response_text", "")
        
        if response_text:
            yield f"event: status\ndata: {json.dumps({'content': '✍️ Generando respuesta...'})}\n\n"
            await asyncio.sleep(0.1)
            
            words = response_text.split()
            chunk_size = 3  # words per chunk
            
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i:i+chunk_size])
                if i + chunk_size < len(words):
                    chunk += " "
                
                token_data = {"content": chunk}
                yield f"event: token\ndata: {json.dumps(token_data)}\n\n"
                
                await asyncio.sleep(0.05)
        
        # Step 7: Persistence
        yield f"event: status\ndata: {json.dumps({'content': '💾 Guardando conversación...'})}\n\n"
        await asyncio.sleep(0.1)
        
        # Create/update chat
        if is_new_chat:
            title = await generate_chat_title(request.query, agent_result.get("response_text", ""))
            chat = await chat_repo.create_chat(
                user_id=user_id,
                session_id=session_uuid,
                title=title,
                mode=chat_mode,
            )
            # Commit immediately so frontend can fetch the chat
            await chat_repo.session.commit()
        
        # Save conversation turn
        processing_time_partial = int((perf_counter() - start_time) * 1000)
        
        # ✅ Enhanced: Extract plan state for PLAN intention
        raw_plan_meta = agent_result.get("plan")
        extra_metadata = {"plan": normalize_plan(raw_plan_meta) if raw_plan_meta else None}
        
        # ✅ IMPROVED: Save plan_params (extracted pre-execution or returned by agent)
        if intent_result.intention.value == "PLAN":
            # Priority 1: Use plan_params from agent result (if agent updated them)
            if "plan_params" in agent_result and agent_result["plan_params"]:
                extra_metadata["plan_params"] = agent_result["plan_params"]
                logger.info("plan-params-from-agent-result", params=agent_result["plan_params"])
            # Priority 2: Use plan_params extracted pre-execution
            elif plan_params:
                extra_metadata["plan_params"] = plan_params
                logger.info("plan-params-from-pre-extraction", params=plan_params)
            else:
                extra_metadata["plan_params"] = None
                logger.warning("plan-params-not-available")
        
        await conversation_repo.save_turn(
            user_id=user_id,
            session_id=session_uuid,
            user_query=request.query,
            query_language=request.language or "es",
            intention=intent_result.intention.value,
            confidence=intent_result.confidence,
            complexity=intent_result.complexity,
            model_used=selected_model.name,
            model_provider=selected_model.provider,
            agent_response=response_text,
            places_found=agent_result.get("places"),
            processing_time_ms=processing_time_partial,
            tool_calls=agent_result.get("tool_calls", 0),
            reasoning_steps=agent_result.get("reasoning_steps", 0),
            extra_metadata=extra_metadata,
        )
        # Commit immediately so data is available for subsequent queries
        await conversation_repo.session.commit()
        
        # ✅ NEW: Invalidate cache after saving new turn
        await memory_manager.invalidate_session_cache(session_uuid)
        
        # Step 8: Send final response
        processing_time = int((perf_counter() - start_time) * 1000)
        
        raw_plan = agent_result.get("plan")
        normalized_plan = normalize_plan(raw_plan) if raw_plan else None

        end_data = {
            "content": response_text,
            "places": agent_result.get("places", []),
            "plan": normalized_plan,
            "metadata": {
                "intention": intent_result.intention.value,
                "confidence": intent_result.confidence,
                "model_used": selected_model.name,
                "processing_time_ms": processing_time,
                "session_id": str(session_uuid),
            }
        }
        yield f"event: end\ndata: {json.dumps(end_data)}\n\n"
        
    except Exception as exc:
        logger.error("streaming_error", query_id=query_id, error=str(exc), exc_info=True)
        error_data = {"content": f"Error: {str(exc)}"}
        yield f"event: error\ndata: {json.dumps(error_data)}\n\n"


@router.post("/query/stream")
async def query_agent_stream(
    request: QueryRequest,
    validator: ContextValidator = Depends(get_context_validator),
    classifier: IntentClassifier = Depends(get_intent_classifier),
    llm_router: LLMRouter = Depends(get_llm_router),
    conversation_repo: ConversationRepository = Depends(get_conversation_repo),
    chat_repo: ChatRepository = Depends(get_chat_repo),
    memory_manager: MemoryManager = Depends(get_memory_manager),
    translator: Translator = Depends(get_translator_instance),
):
    """
    Stream agent response with real-time reasoning steps.
    
    Returns Server-Sent Events (SSE) with:
    - status: Processing updates
    - thought: Agent reasoning
    - action: Tools being used
    - observation: Tool results
    - token: Response text
    - end: Final response
    """
    return StreamingResponse(
        stream_agent_response(
            request,
            validator,
            classifier,
            llm_router,
            conversation_repo,
            chat_repo,
            memory_manager,
            translator,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
