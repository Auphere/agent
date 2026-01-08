"""API routes for the agent microservice with full persistence and monitoring."""

from __future__ import annotations

from time import perf_counter
from typing import Any, Dict, Optional
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
    PlanAiEditPayload,
    PlanAiEditResponse,
    # Qdrant (Phase: Vector DB)
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
from src.tools.place_tool import places_search_tool
from src.tools.generate_plan_json_tool import generate_plan_json_tool
from src.vector.qdrant_store import PlanVectorDoc, get_qdrant_store

router = APIRouter(prefix="/agent", tags=["agent"])
logger = get_logger("routes")


@router.post("/vectors/plans/upsert", status_code=status.HTTP_200_OK)
async def upsert_plan_vector(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upsert a plan into Qdrant for semantic retrieval.

    Expected payload:
    - plan_id, user_id, plan (PlanResponse-like dict)
    """
    settings = get_settings()
    store = get_qdrant_store(settings=settings)
    if not store.enabled:
        return {"success": True, "skipped": True, "reason": "qdrant_disabled"}

    plan = payload.get("plan") or {}
    plan_id = payload.get("plan_id") or plan.get("id")
    user_id = payload.get("user_id") or plan.get("user_id")
    if not plan_id or not user_id:
        return {"success": False, "error": "Missing plan_id/user_id"}

    execution = plan.get("execution") or {}
    city = execution.get("city") or plan.get("city")
    title = plan.get("name") or plan.get("title") or "Plan"
    tags = plan.get("tags") or []
    stops = plan.get("stops") or []
    stop_names = [
        s.get("name")
        for s in stops
        if isinstance(s, dict) and s.get("name")
    ]
    updated_at = plan.get("updated_at") or plan.get("updatedAt")

    doc = PlanVectorDoc(
        id=str(plan_id),
        user_id=str(user_id),
        title=str(title),
        city=str(city) if city else None,
        tags=[str(t) for t in tags] if isinstance(tags, list) else [],
        stop_names=[str(n) for n in stop_names],
        updated_at=str(updated_at) if updated_at else None,
    )

    store.upsert_plan(doc)
    return {"success": True}


@router.post("/vectors/plans/search", status_code=status.HTTP_200_OK)
async def search_plan_vectors(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Search a user's plans in Qdrant by semantic similarity.

    Expected payload:
    - user_id
    - query
    - limit (optional)
    """
    settings = get_settings()
    store = get_qdrant_store(settings=settings)
    if not store.enabled:
        return {"success": True, "results": [], "skipped": True, "reason": "qdrant_disabled"}

    user_id = payload.get("user_id")
    query = payload.get("query")
    limit = payload.get("limit", 10)
    if not user_id or not query:
        return {"success": False, "error": "Missing user_id/query"}

    results = store.search_plans(user_id=str(user_id), query=str(query), limit=int(limit))
    return {"success": True, "results": results}


def _get_stop_number(stop: Dict[str, Any]) -> Optional[int]:
    n = stop.get("stop_number") or stop.get("stopNumber")
    try:
        return int(n) if n is not None else None
    except Exception:
        return None


def _to_tool_stop(stop: Dict[str, Any]) -> Dict[str, Any]:
    """Convert backend stop (snake or camel) into generate_plan_json_tool stop schema (camel)."""
    timing = stop.get("timing") or {}
    location = stop.get("location") or {}
    details = stop.get("details") or {}
    actions = stop.get("actions") or {}

    def _get(obj: Dict[str, Any], snake: str, camel: str):
        return obj.get(snake) if snake in obj else obj.get(camel)

    return {
        "stopNumber": _get_stop_number(stop) or 1,
        "localId": stop.get("local_id") or stop.get("localId") or stop.get("local_id") or "",
        "name": stop.get("name") or "",
        "category": stop.get("category") or "",
        "typeLabel": stop.get("type_label") or stop.get("typeLabel"),
        "timing": {
            "recommendedStart": _get(timing, "recommended_start", "recommendedStart") or "TBD",
            "suggestedDurationMinutes": _get(timing, "suggested_duration_minutes", "suggestedDurationMinutes") or 60,
            "estimatedEnd": _get(timing, "estimated_end", "estimatedEnd") or "TBD",
        },
        "location": {
            "address": _get(location, "address", "address") or "",
            "zone": _get(location, "zone", "zone"),
            "lat": _get(location, "lat", "lat"),
            "lng": _get(location, "lng", "lng"),
            "travelTimeFromPreviousMinutes": _get(location, "travel_time_from_previous_minutes", "travelTimeFromPreviousMinutes"),
            "travelMode": _get(location, "travel_mode", "travelMode"),
        },
        "details": {
            "vibes": details.get("vibes") or [],
            "targetAudience": _get(details, "target_audience", "targetAudience"),
            "music": details.get("music"),
            "noiseLevel": _get(details, "noise_level", "noiseLevel"),
            "averageSpendPerPerson": _get(details, "average_spend_per_person", "averageSpendPerPerson"),
            # optional rating, used by plan tool for avg rating
            "rating": details.get("rating") or stop.get("rating"),
        },
        "selectionReasons": stop.get("selection_reasons") or stop.get("selectionReasons") or [],
        "actions": {
            "canReserve": _get(actions, "can_reserve", "canReserve") or False,
            "reservationUrl": _get(actions, "reservation_url", "reservationUrl"),
            "googleMapsUrl": _get(actions, "google_maps_url", "googleMapsUrl"),
            "phone": _get(actions, "phone", "phone"),
        },
        "alternatives": stop.get("alternatives"),
        "personalTips": stop.get("personal_tips") or stop.get("personalTips"),
        "images": stop.get("images"),
    }


def _camel_to_snake_stop(tool_stop: Dict[str, Any]) -> Dict[str, Any]:
    """Convert generate_plan_json_tool stop (camel) into backend stop schema (snake)."""
    timing = tool_stop.get("timing") or {}
    location = tool_stop.get("location") or {}
    details = tool_stop.get("details") or {}
    actions = tool_stop.get("actions") or {}

    return {
        "stop_number": tool_stop.get("stopNumber"),
        "local_id": tool_stop.get("localId"),
        "name": tool_stop.get("name"),
        "category": tool_stop.get("category"),
        "type_label": tool_stop.get("typeLabel"),
        "timing": {
            "recommended_start": timing.get("recommendedStart"),
            "suggested_duration_minutes": timing.get("suggestedDurationMinutes"),
            "estimated_end": timing.get("estimatedEnd"),
            "expected_occupancy": timing.get("expectedOccupancy") or timing.get("expected_occupancy"),
            "occupancy_recommendation": timing.get("occupancyRecommendation") or timing.get("occupancy_recommendation"),
        },
        "location": {
            "address": location.get("address"),
            "zone": location.get("zone"),
            "lat": location.get("lat"),
            "lng": location.get("lng"),
            "travel_time_from_previous_minutes": location.get("travelTimeFromPreviousMinutes"),
            "travel_mode": location.get("travelMode"),
        },
        "details": {
            "vibes": details.get("vibes") or [],
            "target_audience": details.get("targetAudience"),
            "music": details.get("music"),
            "noise_level": details.get("noiseLevel"),
            "average_spend_per_person": details.get("averageSpendPerPerson"),
            "rating": details.get("rating"),
        },
        "selection_reasons": tool_stop.get("selectionReasons") or [],
        "actions": {
            "can_reserve": actions.get("canReserve") or False,
            "reservation_url": actions.get("reservationUrl"),
            "google_maps_url": actions.get("googleMapsUrl"),
            "phone": actions.get("phone"),
        },
        "alternatives": tool_stop.get("alternatives"),
        "personal_tips": tool_stop.get("personalTips"),
    }


def _camel_to_snake_plan(plan_json: Dict[str, Any]) -> Dict[str, Any]:
    execution = plan_json.get("execution") or {}
    summary = plan_json.get("summary") or {}
    budget = (summary.get("budget") or {}) if isinstance(summary, dict) else {}
    metrics = (summary.get("metrics") or {}) if isinstance(summary, dict) else {}

    return {
        "name": plan_json.get("name") or plan_json.get("title"),
        "description": plan_json.get("description") or "",
        "category": plan_json.get("category"),
        "vibes": plan_json.get("vibes") or [],
        "tags": plan_json.get("tags") or [],
        "execution": {
            "date": execution.get("date"),
            "start_time": execution.get("startTime") or execution.get("start_time"),
            "duration_hours": execution.get("durationHours") or execution.get("duration_hours"),
            "city": execution.get("city"),
            "zones": execution.get("zones"),
            "group_size": execution.get("groupSize") or execution.get("group_size"),
            "group_composition": execution.get("groupComposition") or execution.get("group_composition"),
        },
        "stops": [_camel_to_snake_stop(s) for s in (plan_json.get("stops") or [])],
        "summary": {
            "total_duration": summary.get("totalDuration") or summary.get("total_duration"),
            "total_distance_km": summary.get("totalDistanceKm") or summary.get("total_distance_km"),
            "budget": {
                "total": budget.get("total"),
                "per_person": budget.get("perPerson") or budget.get("per_person"),
                "within_budget": budget.get("withinBudget") if "withinBudget" in budget else budget.get("within_budget"),
                "breakdown": budget.get("breakdown"),
            },
            "metrics": {
                "vibe_match_percent": metrics.get("vibeMatchPercent") or metrics.get("vibe_match_percent"),
                "average_venue_rating": metrics.get("averageVenueRating") or metrics.get("average_venue_rating"),
                "success_probability_label": metrics.get("successProbabilityLabel") or metrics.get("success_probability_label"),
            },
        },
        "final_recommendations": plan_json.get("finalRecommendations") or plan_json.get("final_recommendations") or [],
    }


def _renumber_stops_in_place(stops: list[dict]) -> None:
    for idx, s in enumerate(stops, 1):
        s["stop_number"] = idx


@router.post("/plan/edit", response_model=PlanAiEditResponse, status_code=status.HTTP_200_OK)
async def edit_plan(payload: PlanAiEditPayload) -> PlanAiEditResponse:
    """
    Phase 6: deterministic plan edits.

    The backend supplies the current plan as ground truth; this endpoint returns an updated plan payload
    suitable to persist via backend PATCH.
    """
    try:
        plan = payload.plan or {}
        edit = payload.edit

        stops = plan.get("stops") or []
        if not isinstance(stops, list) or len(stops) == 0:
            return PlanAiEditResponse(success=False, error="Plan has no stops")

        city = (
            (plan.get("execution") or {}).get("city")
            or edit.constraints.get("city")
            or plan.get("city")
        )
        if not city:
            return PlanAiEditResponse(success=False, error="Missing city in plan/execution")

        operation = (edit.operation or "").strip()
        if operation not in {"replace_stop", "remove_stop", "add_stop", "update_timing"}:
            return PlanAiEditResponse(success=False, error=f"Unsupported operation: {operation}")

        # -------------------------
        # remove_stop
        # -------------------------
        if operation == "remove_stop":
            if not edit.stop_number:
                return PlanAiEditResponse(success=False, error="stop_number is required for remove_stop")
            stops = [s for s in stops if _get_stop_number(s) != edit.stop_number]
            # re-number sequentially
            stops = [s for s in stops if isinstance(s, dict)]
            _renumber_stops_in_place(stops)
            updated = dict(plan)
            updated["stops"] = stops
            return PlanAiEditResponse(
                success=True,
                updated_plan=updated,
                summary=f"Stop #{edit.stop_number} eliminado.",
            )

        # -------------------------
        # update_timing (MVP)
        # -------------------------
        if operation == "update_timing":
            if not edit.stop_number:
                return PlanAiEditResponse(success=False, error="stop_number is required for update_timing")

            target = next((s for s in stops if _get_stop_number(s) == edit.stop_number), None)
            if not target or not isinstance(target, dict):
                return PlanAiEditResponse(success=False, error=f"Stop #{edit.stop_number} not found")

            constraints = edit.constraints or {}
            new_start = constraints.get("start_time") or constraints.get("recommended_start")
            new_duration = constraints.get("duration_minutes") or constraints.get("suggested_duration_minutes")

            timing = target.get("timing") or {}
            if not isinstance(timing, dict):
                timing = {}
            if isinstance(new_start, str) and new_start.strip():
                timing["recommended_start"] = new_start.strip()
            if new_duration is not None:
                try:
                    timing["suggested_duration_minutes"] = int(new_duration)
                except Exception:
                    pass
            target["timing"] = timing

            updated_stops = [s for s in stops if isinstance(s, dict)]
            _renumber_stops_in_place(updated_stops)

            # Rebuild plan via generate_plan_json_tool (keeps schema consistent)
            tool_stops = sorted([_to_tool_stop(s) for s in updated_stops], key=lambda s: s.get("stopNumber") or 0)
            execution = plan.get("execution") or {}
            date = execution.get("date") or "TBD"
            start_time = execution.get("start_time") or execution.get("startTime") or "TBD"
            group_size = execution.get("group_size") or execution.get("groupSize") or 2
            total_duration_hours = execution.get("duration_hours") or execution.get("durationHours") or 4

            plan_json = await generate_plan_json_tool(
                title=plan.get("name") or "Plan",
                description=plan.get("description") or "",
                category=plan.get("category") or "friends",
                vibes=plan.get("vibes") or [],
                date=date,
                start_time=start_time,
                city=city,
                group_size=int(group_size),
                stops=tool_stops,
                total_duration_hours=float(total_duration_hours),
                budget_per_person=constraints.get("budget_per_person"),
                user_max_budget_per_person=constraints.get("user_max_budget_per_person"),
                final_recommendations=plan.get("final_recommendations") or [],
            )

            if not isinstance(plan_json, dict) or plan_json.get("success") is False:
                updated = dict(plan)
                updated["stops"] = updated_stops
                return PlanAiEditResponse(
                    success=True,
                    updated_plan=updated,
                    summary=f"Horario actualizado en stop #{edit.stop_number}. (sin recálculo completo)",
                )

            updated_snake = _camel_to_snake_plan(plan_json)
            updated = dict(plan)
            updated.update(updated_snake)
            return PlanAiEditResponse(
                success=True,
                updated_plan=updated,
                summary=f"Horario actualizado en stop #{edit.stop_number}.",
            )

        # -------------------------
        # add_stop (MVP)
        # -------------------------
        if operation == "add_stop":
            constraints = edit.constraints or {}
            query = (constraints.get("query") or "").strip()
            if not query:
                query = (edit.instruction or "").strip()
            if not query:
                return PlanAiEditResponse(success=False, error="constraints.query or instruction is required for add_stop")

            insert_after = edit.stop_number  # optional: insert after stop_number

            search_result = await places_search_tool(query=query, city=city, max_results=10)
            if not search_result.get("success"):
                return PlanAiEditResponse(success=False, error=f"places_search_tool failed: {search_result.get('error')}")
            candidates = search_result.get("places", []) or []
            if not candidates:
                return PlanAiEditResponse(success=False, error="No candidates returned from places search")

            updated_stops = [s for s in stops if isinstance(s, dict)]
            existing_ids = set(
                (s.get("local_id") or s.get("localId") or "") for s in updated_stops if isinstance(s, dict)
            )
            chosen = next(
                (p for p in candidates if isinstance(p, dict) and (p.get("id") or p.get("place_id")) not in existing_ids),
                candidates[0],
            )
            chosen_id = chosen.get("place_id") or chosen.get("id")
            chosen_name = chosen.get("name")
            loc = chosen.get("location") or {}
            address = chosen.get("address") or chosen.get("formatted_address") or ""
            neighborhood = chosen.get("neighborhood")

            new_stop: Dict[str, Any] = {
                "stop_number": 0,
                "local_id": chosen_id,
                "name": chosen_name,
                "category": constraints.get("type") or "activity",
                "type_label": constraints.get("type_label"),
                "timing": {
                    "recommended_start": "TBD",
                    "suggested_duration_minutes": int(constraints.get("duration_minutes") or 60),
                    "estimated_end": "TBD",
                },
                "location": {
                    "address": address,
                    "zone": neighborhood,
                    "lat": loc.get("lat"),
                    "lng": loc.get("lng") or loc.get("lon"),
                },
                "details": {
                    "vibes": plan.get("vibes") or [],
                    "average_spend_per_person": constraints.get("average_spend_per_person"),
                },
                "selection_reasons": [f"Agregado por instrucción del usuario: {edit.instruction}"],
                "actions": {},
            }

            if insert_after and isinstance(insert_after, int):
                idx = max(0, min(len(updated_stops), insert_after))
                updated_stops.insert(idx, new_stop)  # after N => insert at index N
            else:
                updated_stops.append(new_stop)

            _renumber_stops_in_place(updated_stops)

            tool_stops = sorted([_to_tool_stop(s) for s in updated_stops], key=lambda s: s.get("stopNumber") or 0)
            execution = plan.get("execution") or {}
            date = execution.get("date") or "TBD"
            start_time = execution.get("start_time") or execution.get("startTime") or "TBD"
            group_size = execution.get("group_size") or execution.get("groupSize") or 2
            total_duration_hours = execution.get("duration_hours") or execution.get("durationHours") or 4

            plan_json = await generate_plan_json_tool(
                title=plan.get("name") or "Plan",
                description=plan.get("description") or "",
                category=plan.get("category") or "friends",
                vibes=plan.get("vibes") or [],
                date=date,
                start_time=start_time,
                city=city,
                group_size=int(group_size),
                stops=tool_stops,
                total_duration_hours=float(total_duration_hours),
                budget_per_person=constraints.get("budget_per_person"),
                user_max_budget_per_person=constraints.get("user_max_budget_per_person"),
                final_recommendations=plan.get("final_recommendations") or [],
            )

            if not isinstance(plan_json, dict) or plan_json.get("success") is False:
                updated = dict(plan)
                updated["stops"] = updated_stops
                return PlanAiEditResponse(
                    success=True,
                    updated_plan=updated,
                    summary=f"Parada agregada: {chosen_name}. (sin recálculo completo)",
                )

            updated_snake = _camel_to_snake_plan(plan_json)
            updated = dict(plan)
            updated.update(updated_snake)
            return PlanAiEditResponse(
                success=True,
                updated_plan=updated,
                summary=f"Parada agregada: {chosen_name}.",
            )

        # -------------------------
        # replace_stop (MVP)
        # -------------------------
        if operation == "replace_stop":
            if not edit.stop_number:
                return PlanAiEditResponse(success=False, error="stop_number is required for replace_stop")

            target = next((s for s in stops if _get_stop_number(s) == edit.stop_number), None)
            if not target or not isinstance(target, dict):
                return PlanAiEditResponse(success=False, error=f"Stop #{edit.stop_number} not found")

            # Determine place type from existing category if possible
            place_type = (target.get("category") or target.get("type_label") or "").lower()
            # constraints may override
            if isinstance(edit.constraints.get("type"), str) and edit.constraints["type"].strip():
                place_type = edit.constraints["type"].strip().lower()

            query = (edit.constraints.get("query") or "").strip()
            if not query:
                # fallback: use category + any user instruction keywords
                query = (target.get("category") or "lugar").strip()

            # call Places SoT
            search_result = await places_search_tool(query=query, city=city, max_results=10)
            if not search_result.get("success"):
                return PlanAiEditResponse(success=False, error=f"places_search_tool failed: {search_result.get('error')}")

            candidates = search_result.get("places", []) or []
            if not candidates:
                return PlanAiEditResponse(success=False, error="No candidates returned from places search")

            existing_ids = set()
            for s in stops:
                if not isinstance(s, dict):
                    continue
                existing_ids.add(s.get("local_id") or s.get("localId") or "")

            chosen = next(
                (p for p in candidates if isinstance(p, dict) and (p.get("id") or p.get("place_id")) not in existing_ids),
                candidates[0],
            )

            chosen_id = chosen.get("place_id") or chosen.get("id")
            chosen_name = chosen.get("name")
            loc = chosen.get("location") or {}
            address = chosen.get("address") or chosen.get("formatted_address") or ""
            neighborhood = chosen.get("neighborhood")

            # patch the stop, keep timing
            target["local_id"] = chosen_id
            target["name"] = chosen_name
            target["location"] = {
                **(target.get("location") or {}),
                "address": address,
                "zone": neighborhood,
                "lat": (loc.get("lat")),
                "lng": (loc.get("lng") or loc.get("lon")),
            }
            # record why we changed it
            reasons = target.get("selection_reasons") or []
            if not isinstance(reasons, list):
                reasons = []
            reasons = [f"Reemplazado por instrucción del usuario: {edit.instruction}"] + reasons[:2]
            target["selection_reasons"] = reasons

            # rebuild plan via generate_plan_json_tool (to recalc summary/consistency)
            tool_stops = [_to_tool_stop(s) for s in stops if isinstance(s, dict)]
            tool_stops = sorted(tool_stops, key=lambda s: s.get("stopNumber") or 0)

            execution = plan.get("execution") or {}
            date = execution.get("date") or "TBD"
            start_time = execution.get("start_time") or execution.get("startTime") or "TBD"
            group_size = execution.get("group_size") or execution.get("groupSize") or 2

            # duration fallback
            total_duration_hours = execution.get("duration_hours") or execution.get("durationHours") or 4

            plan_json = await generate_plan_json_tool(
                title=plan.get("name") or "Plan",
                description=plan.get("description") or "",
                category=plan.get("category") or "friends",
                vibes=plan.get("vibes") or [],
                date=date,
                start_time=start_time,
                city=city,
                group_size=int(group_size),
                stops=tool_stops,
                total_duration_hours=float(total_duration_hours),
                budget_per_person=edit.constraints.get("budget_per_person"),
                user_max_budget_per_person=edit.constraints.get("user_max_budget_per_person"),
                final_recommendations=plan.get("final_recommendations") or [],
            )

            if not isinstance(plan_json, dict) or plan_json.get("success") is False:
                # fallback: return minimally patched plan
                updated = dict(plan)
                updated["stops"] = stops
                return PlanAiEditResponse(
                    success=True,
                    updated_plan=updated,
                    summary=f"Stop #{edit.stop_number} reemplazado por {chosen_name}. (sin recálculo completo)",
                )

            updated_snake = _camel_to_snake_plan(plan_json)
            updated = dict(plan)
            updated.update(updated_snake)
            return PlanAiEditResponse(
                success=True,
                updated_plan=updated,
                summary=f"Stop #{edit.stop_number} reemplazado por {chosen_name}.",
            )

        return PlanAiEditResponse(success=False, error="Operation not implemented yet")
    except Exception as exc:
        logger.error("plan-edit-failed", error=str(exc))
        return PlanAiEditResponse(success=False, error=str(exc))


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
        # Use a process-wide singleton for robustness (avoids per-request LangGraph pool churn).
        from src.agents.supervisor_singleton import get_supervisor_agent
        
        supervisor = get_supervisor_agent()

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

    # Get metrics summary (do not let metrics failures break liveness/readiness)
    try:
        metrics_summary = metrics_collector.get_summary(last_n=100)
    except Exception as exc:
        logger.error("health_metrics_summary_failed", error=str(exc))
        metrics_summary = {"error": "metrics_summary_failed"}

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
