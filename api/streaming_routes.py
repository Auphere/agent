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
        
        # Step 6: Execute agent
        from src.agents.supervisor_agent import SupervisorAgent
        
        supervisor = SupervisorAgent()
        
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
        
        # Execute agent
        # ✅ FIX: Merge memory_context directly into context (not nested)
        # ✅ FIX: Serialize datetime objects to strings
        validated_context_dict = validated_context.dict()
        # Convert any datetime objects to ISO format strings
        for key, value in validated_context_dict.items():
            if hasattr(value, 'isoformat'):
                validated_context_dict[key] = value.isoformat()
        
        agent_context = {
            "user_id": str(user_id),
            "session_id": str(session_uuid),
            "validated_context": validated_context_dict,
            **memory_context,  # ← Unpack memory_context directly
        }
        
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
        
        if intent_result.intention.value == "PLAN":
            from src.agents.context_builder import PlanContextExtractor
            # Extract plan parameters from query for future reference
            extracted_params = PlanContextExtractor.extract_from_query(
                request.query,
                request.language or "es"
            )
            if extracted_params:
                extra_metadata["plan_params"] = extracted_params
        
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
