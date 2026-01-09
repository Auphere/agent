"""
Plan-and-Execute Agent using LangGraph for advanced multi-step reasoning.

This agent implements a sophisticated Plan-and-Execute pattern where:
1. PLANNER: Creates a multi-step plan to accomplish the user's goal
2. EXECUTOR: Executes each step using appropriate tools
3. REPLANNER: Adapts the plan based on execution results (if needed)

The synthesis happens within the executor node when it completes the final step,
eliminating the need for a separate synthesizer node.
"""

from __future__ import annotations

import asyncio
import json
import operator
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Dict, List, Optional, TypedDict, Annotated, Sequence
from uuid import uuid4

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger
from src.agents.utils.place_saver import save_places_to_db
from src.agents.utils.text_cleaner import clean_response_text


# ============================================================================
# State definition for the graph with proper reducers
# ============================================================================

def add_messages(left: List[BaseMessage], right: List[BaseMessage]) -> List[BaseMessage]:
    """Custom reducer to add messages without duplicates."""
    return list(left) + list(right)


def add_steps(left: List[tuple], right: List[tuple]) -> List[tuple]:
    """Custom reducer to add past_steps."""
    return list(left) + list(right)


def merge_plan_params(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """
    Custom reducer to merge plan_params across turns.
    
    This ensures parameters accumulate across conversation turns:
    - Turn 1: {num_people: 4, budget: 7.5} 
    - Turn 2: {cities: ['Zaragoza']}
    - Result: {num_people: 4, budget: 7.5, cities: ['Zaragoza']}
    
    Rules:
    - New non-None values override old values
    - Lists are merged uniquely
    - Empty values are ignored
    """
    if not left:
        left = {}
    if not right:
        right = {}
    
    merged = dict(left)  # Start with previous params
    
    for key, value in right.items():
        # Only update if new value is meaningful
        if value is not None and value != [] and value != "":
            # For lists, merge uniquely
            if isinstance(value, list) and key in merged and isinstance(merged[key], list):
                merged[key] = list(set(merged[key] + value))
            else:
                # Override scalar values
                merged[key] = value
    
    return merged


class PlanExecuteState(TypedDict, total=False):
    """
    State for Plan-and-Execute agent following LangGraph best practices.
    
    Uses Annotated types with reducers for proper state accumulation:
    - messages: Accumulated via add_messages
    - past_steps: Accumulated via add_steps
    - plan_params: Accumulated via merge_plan_params (CRITICAL for multi-turn)
    - Other fields: Overwritten (last value wins)
    """
    # Input (immutable - set once at start)
    input: str
    language: str
    session_id: str  # Used as thread_id for checkpointing
    # Monotonic deadline used to avoid expensive last-mile synthesis near the Supervisor timeout
    deadline_ts: float
    
    # ✅ CRITICAL: Plan parameters with custom reducer for accumulation
    # This allows parameters to persist and accumulate across conversation turns
    plan_params: Annotated[Dict[str, Any], merge_plan_params]
    
    # Optional context for additional information
    context: Dict[str, Any]
    
    # Planning state (mutable)
    plan: List[str]
    past_steps: Annotated[List[tuple], add_steps]  # Proper reducer
    current_step: Optional[str]
    
    # Execution state (mutable) with proper reducer
    messages: Annotated[List[BaseMessage], add_messages]
    
    # Output (populated at end)
    response_text: str
    places: List[Dict[str, Any]]
    plan_json: Optional[Dict[str, Any]]
    
    # Metadata
    agent_type: str
    model_used: str
    reasoning_steps: int


# ============================================================================
# Prompts
# ============================================================================

PLANNER_PROMPT = """You are an expert planning agent for finding and recommending places.

Your task: Create a step-by-step plan to accomplish the user's request.

## ACCUMULATED PARAMETERS (from full conversation):

{plan_params}

## CURRENT CONTEXT:

{context}

## USER REQUEST:

{query}

## AVAILABLE TOOLS:

1. geocode_city_tool: Get coordinates for a city (use first if city mentioned)
2. places_search_tool: Search for restaurants, bars, activities (via auphere-places SoT)
3. rank_by_score_tool: Rank results by quality (deterministic)
4. places_clusters_tool: Cluster places into zones (PostGIS, deterministic)
5. calculate_route_tool: Estimate/optimize route order and travel time
6. generate_plan_json_tool: Create final structured itinerary (use last)

## OUTPUT FORMAT:

Return ONLY valid JSON:

{{
  "plan": [
    "Step 1: Use geocode_city_tool to get coordinates for [city]",
    "Step 2: Use places_search_tool to search for [type] in [city]",
    "Step 3: Use rank_by_score_tool to rank results for [criteria] and keep only top K",
    "Step 4: Use places_clusters_tool to cluster top candidates by zones (optional)",
    "Step 5: Use calculate_route_tool to optimize order and travel times (optional)",
    "Step 6: Use generate_plan_json_tool to create itinerary"
  ],
  "reasoning": "Brief explanation"
}}

## RULES:

- Create 3-5 specific, actionable steps
- Each step should mention which tool to use
- Always start with geocode_city_tool if a city is mentioned
- Always end with generate_plan_json_tool
- Be specific about what to search for
"""

EXECUTOR_PROMPT = """You are an expert executor agent that carries out specific steps of a plan.

Current step to execute: {step}

Previous steps completed:
{past_steps}

Context:
{context}

Execute this step using the appropriate tools available to you.
Be thorough and extract all relevant information.
Focus on quality over quantity.

CRITICAL TOOL USAGE RULES:

1. When calling `rank_by_score_tool`, you MUST pass:
   - `places`: the EXACT list returned by the previous `places_search_tool` call (do not invent)
   - `requirements`: a dict built from plan params (budget/vibe) and location if available:
     - budget: "low" | "medium" | "high" (or a numeric budget_per_person if you have it)
     - vibe: a short string like "cultural", "romantic", etc. (or omit if unknown)
     - location: {{ "lat": number, "lon": number }} when you have coordinates
   - Do not call `rank_by_score_tool` with partial args (it won't be able to rank).

2. When calling `generate_plan_json_tool`, you MUST:
   - Build the `stops` list from the places found in previous steps (REQUIRED, cannot be empty)
   - Each stop must include: stopNumber, localId, name, category, timing, location, details, selectionReasons, actions
   - Use the actual data from search results (coordinates, names, addresses)
   - If no places were found, DO NOT call this tool - instead report that no suitable places were found
"""

REPLANNER_PROMPT = """You are an expert replanner agent that adapts plans based on execution results.

Original plan:
{original_plan}

Steps completed so far:
{past_steps}

Current situation: {situation}

Analyze the execution results and decide:
1. Should we continue with the remaining steps?
2. Do we need to add new steps?
3. Do we have enough information to answer the user's query?

Response format (JSON):
{{
  "decision": "continue" or "replan" or "finish",
  "updated_plan": ["Step 1", "Step 2", ...],
  "reasoning": "Brief explanation"
}}
"""

SYNTHESIZER_PROMPT = """You are an expert synthesis agent that creates comprehensive final answers.

User query: {query}
Language: {language}

All executed steps and results:
{all_results}

Context:
{context}

**CRITICAL - HANDLING STOP CONDITIONS:**

If the executed steps contain "STOP:" or mention missing information:
- **ASK the user** for the specific missing information in a friendly way.
- Keep it brief and conversational.

**CRITICAL - RESPONSE FORMAT (When plan was created successfully):**

- **DO NOT list the places or stops in your text response.** The UI displays the plan card.
- Your response should ONLY contain:
  1. A brief, engaging intro (1-2 sentences).
  2. A section titled in the user's language:
     - If Language is Spanish (`es`): title it **"Qué esperar"**
     - Otherwise: title it **"What to Expect"**
     (2-3 sentences).
  3. A section titled in the user's language:
     - If Language is Spanish (`es`): title it **"Consejos"**
     - Otherwise: title it **"Pro Tips"**
     (2-3 bullet points).
- **DO NOT** repeat the itinerary, times, or addresses.
"""


# ============================================================================
# Main Agent Class
# ============================================================================

class PlanAndExecuteAgent:
    """
    Advanced Plan-and-Execute agent using LangGraph.
    
    Uses a multi-stage approach:
    1. Plans a strategy to accomplish the user's goal
    2. Executes each step using appropriate tools
    3. Synthesizes all information into a comprehensive response
    4. Can replan if needed based on intermediate results
    
    Timeout Configuration:
    - Planner: 60s (needs time to analyze and plan)
    - Executor: 90s (may call multiple tools)
    - Synthesizer: 60s (final response generation)
    
    Retry Configuration:
    - All LLMs: 3 retries with exponential backoff
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = get_logger("plan_and_execute_agent", settings=self.settings)

        # LLMs for different stages with improved timeout configuration
        # Planner: needs time for complex analysis
        self.planner_llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.3,
            api_key=self.settings.openai_api_key,
            timeout=(
                self.settings.llm_connection_timeout,
                self.settings.llm_read_timeout_standard  # 60s
            ),
            max_retries=self.settings.llm_max_retries,
        )

        # Executor: may need to process tool results
        self.executor_llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.5,
            api_key=self.settings.openai_api_key,
            timeout=(
                self.settings.llm_connection_timeout,
                self.settings.llm_read_timeout_complex  # 90s
            ),
            max_retries=self.settings.llm_max_retries,
        )

        # Synthesizer: final response generation
        self.synthesizer_llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.7,
            api_key=self.settings.openai_api_key,
            timeout=(
                self.settings.llm_connection_timeout,
                self.settings.llm_read_timeout_standard  # 60s
            ),
            max_retries=self.settings.llm_max_retries,
        )

        # Get tools
        from src.tools.tool_registry import get_plan_tools
        self.tools = get_plan_tools()

        # Add enrichment tools
        from src.tools.search.foursquare_v2 import (
            search_foursquare_places,
            get_foursquare_place_enrichment,
        )
        from src.tools.search.apify_enrichment import (
            scrape_instagram_place,
            scrape_tiktok_place,
            scrape_tripadvisor_reviews,
            get_social_media_summary,
        )

        self.enrichment_tools = [
            search_foursquare_places,
            get_foursquare_place_enrichment,
            scrape_instagram_place,
            scrape_tiktok_place,
            scrape_tripadvisor_reviews,
            get_social_media_summary,
        ]

        self.all_tools = self.tools + self.enrichment_tools
        
        # Lazy init for async components
        self.checkpoint_pool = None  # Dedicated connection pool for checkpointing
        self.checkpointer = None
        self.graph = None

        self.logger.info("plan-and-execute-agent-initialized")
    
    async def _ensure_graph_initialized(self):
        """
        Lazy initialize graph with async PostgreSQL checkpointer.
        
        Uses a dedicated connection pool with proper configuration:
        - autocommit=True: Required for setup() to commit table creation
        - row_factory=dict_row: Required for dictionary-style row access
        - Separate pool from SQLAlchemy to avoid connection conflicts
        """
        if self.graph is not None:
            return
        
        from psycopg_pool import AsyncConnectionPool
        from psycopg.rows import dict_row
        
        # Create dedicated connection pool for LangGraph checkpointing
        # This is separate from SQLAlchemy's pool to avoid conflicts
        self.checkpoint_pool = AsyncConnectionPool(
            conninfo=self.settings.database_url,
            min_size=2,  # Keep minimal for checkpoint operations
            max_size=5,  # Sufficient for concurrent checkpoint operations
            kwargs={
                "autocommit": True,  # Required: setup() needs to commit table creation
                "row_factory": dict_row,  # Required: checkpointer uses dict-style access
            },
            open=False,  # Defer opening until we're in async context
            timeout=30.0,
            max_idle=600.0,
            max_lifetime=3600.0,
        )
        
        # Open the pool (must be done in async context)
        await self.checkpoint_pool.open(wait=True, timeout=30.0)
        
        # Initialize checkpointer with the pool
        self.checkpointer = AsyncPostgresSaver(self.checkpoint_pool)
        
        # Setup database tables (idempotent operation)
        await self.checkpointer.setup()
        
        # Build the graph
        self.graph = self._build_graph()
        
        self.logger.info("langgraph-initialized-with-postgres-checkpointer")

    def _get_tool_by_name(self, name: str):
        """Return a tool instance by its registered name."""
        for tool in self.all_tools:
            if getattr(tool, "name", None) == name:
                return tool
        return None

    async def _ainvoke_tool(self, name: str, tool_args: Dict[str, Any]) -> Any:
        """Safely call a registered LangChain tool by name."""
        tool = self._get_tool_by_name(name)
        if tool is None:
            raise RuntimeError(f"Tool not found: {name}")
        return await tool.ainvoke(tool_args)

    @dataclass(frozen=True)
    class _PlacePick:
        """Internal normalized selection used to build stops deterministically."""
        id: str
        name: str
        category: str
        address: str
        lat: float
        lng: float
        rating: Optional[float]
        price_level: Optional[int]

    @staticmethod
    def _pick_category(place: Dict[str, Any]) -> str:
        """Best-effort mapping from place types to plan categories."""
        types = place.get("types") or []
        primary = (place.get("primary_type") or (types[0] if types else "") or "").lower()
        if "restaurant" in primary:
            return "restaurant"
        if "cafe" in primary or "coffee" in primary:
            return "cafe"
        if "bar" in primary or "pub" in primary:
            return "bar"
        if "park" in primary:
            return "activity"
        if "museum" in primary:
            return "activity"
        return "activity"

    def _to_place_pick(self, place: Dict[str, Any]) -> Optional["_PlacePick"]:
        """Convert a PlaceNormalized-like dict into a deterministic stop pick."""
        loc = place.get("location") or {}
        lat = loc.get("lat") or place.get("latitude")
        lng = loc.get("lng") or place.get("longitude") or loc.get("lon")
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except Exception:
            return None

        place_id = str(place.get("id") or place.get("place_id") or "")
        name = str(place.get("name") or "").strip()
        if not place_id or not name:
            return None

        address = str(place.get("address") or "").strip()
        category = self._pick_category(place)

        rating_val = place.get("rating")
        try:
            rating_f = float(rating_val) if rating_val is not None else None
        except Exception:
            rating_f = None

        price_val = place.get("price_level") or place.get("priceLevel")
        try:
            price_i = int(price_val) if price_val is not None else None
        except Exception:
            price_i = None

        return PlanAndExecuteAgent._PlacePick(
            id=place_id,
            name=name,
            category=category,
            address=address,
            lat=lat_f,
            lng=lng_f,
            rating=rating_f,
            price_level=price_i,
        )

    def _build_stops_from_picks(
        self,
        picks: List["_PlacePick"],
        vibes: List[str],
        start_time: str = "TBD",
    ) -> List[Dict[str, Any]]:
        """Build generate_plan_json_tool-compatible stops deterministically."""
        suggested_duration_by_category = {
            "restaurant": 90,
            "cafe": 60,
            "bar": 60,
            "activity": 90,
        }

        stops: List[Dict[str, Any]] = []
        for idx, pick in enumerate(picks, start=1):
            category = pick.category
            duration = suggested_duration_by_category.get(category, 75)
            recommended_start = start_time if idx == 1 else "TBD"

            stops.append(
                {
                    "stopNumber": idx,
                    "localId": pick.id,
                    "name": pick.name,
                    "category": category,
                    "typeLabel": None,
                    "timing": {
                        "recommendedStart": recommended_start,
                        "suggestedDurationMinutes": duration,
                        "estimatedEnd": "TBD",
                    },
                    "location": {
                        "address": pick.address,
                        "lat": pick.lat,
                        "lng": pick.lng,
                        "travelTimeFromPreviousMinutes": 0 if idx == 1 else None,
                    },
                    "details": {
                        "vibes": vibes,
                        "targetAudience": "couple" if "romantic" in [v.lower() for v in vibes] else "general",
                        "music": None,
                        "noiseLevel": None,
                        "averageSpendPerPerson": None,
                        "rating": pick.rating,
                        "priceLevel": pick.price_level,
                    },
                    "selectionReasons": [
                        "Buena opción según el vibe solicitado."
                    ],
                    "actions": {
                        "canReserve": None,
                        "reservationUrl": None,
                        "googleMapsUrl": None,
                        "phone": None,
                    },
                    "alternatives": None,
                    "personalTips": None,
                    "images": None,
                }
            )

        return stops

    async def _fallback_build_plan_json(self, state: "PlanExecuteState") -> tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Deterministic fallback for the final step: re-search, rank, build stops, call generate_plan_json_tool.
        Returns (plan_json, selected_places).
        """
        plan_params = state.get("plan_params", {}) or {}
        city = plan_params.get("primary_city") or (plan_params.get("cities") or [None])[0]
        city = str(city) if city else ""
        if not city:
            return None, []

        vibes = plan_params.get("vibes") or []
        if isinstance(vibes, str):
            vibes = [vibes]
        vibes = [str(v) for v in vibes if v]
        if not vibes:
            vibes = ["romantic"]

        budget = plan_params.get("budget_per_person")
        num_people = int(plan_params.get("num_people") or 2)

        # Re-geocode for location bias when possible
        origin = None
        try:
            geocode_raw = await self._ainvoke_tool("geocode_city_tool", {"city": city})
            if isinstance(geocode_raw, str):
                parsed = json.loads(geocode_raw)
                if isinstance(parsed, dict) and parsed.get("ok") is True:
                    origin = {"lat": float(parsed["latitude"]), "lon": float(parsed["longitude"])}
        except Exception:
            origin = None

        # Search candidates (keep it simple and deterministic)
        restaurant_query = "restaurantes románticos"
        park_query = "parques románticos"
        restaurants = await self._ainvoke_tool(
            "places_search_tool",
            {
                "query": restaurant_query,
                "city": city,
                "latitude": origin["lat"] if origin else None,
                "longitude": origin["lon"] if origin else None,
                "max_results": 10,
            },
        )
        parks = await self._ainvoke_tool(
            "places_search_tool",
            {
                "query": park_query,
                "city": city,
                "latitude": origin["lat"] if origin else None,
                "longitude": origin["lon"] if origin else None,
                "max_results": 10,
            },
        )

        def _extract_places(tool_result: Any) -> List[Dict[str, Any]]:
            if isinstance(tool_result, dict):
                return list(tool_result.get("places") or [])
            if isinstance(tool_result, list):
                return tool_result
            return []

        restaurant_places = _extract_places(restaurants)
        park_places = _extract_places(parks)
        candidates = restaurant_places + park_places

        if not candidates:
            return None, []

        # Rank deterministically via tool (now hardened)
        requirements: Dict[str, Any] = {"vibes": vibes, "budget": budget}
        if origin:
            requirements["location"] = origin
        ranked = await self._ainvoke_tool(
            "rank_by_score_tool",
            {
                "places": candidates,
                "requirements": requirements,
                "language": state.get("language", "es"),
                "user_query": state.get("input", ""),
                "requested_count": 5,
            },
        )

        ranked_places: List[Dict[str, Any]] = []
        if isinstance(ranked, dict) and not ranked.get("error"):
            for item in ranked.get("ranked_places") or []:
                if isinstance(item, dict) and isinstance(item.get("place"), dict):
                    ranked_places.append(item["place"])
        if not ranked_places:
            ranked_places = candidates[:5]

        # Pick stops: prefer 2 restaurants + 1 activity if possible.
        picks: List[PlanAndExecuteAgent._PlacePick] = []
        for p in ranked_places:
            pick = self._to_place_pick(p)
            if pick:
                picks.append(pick)
            if len(picks) >= 5:
                break

        if not picks:
            return None, []

        # Create a minimal but valid set of stops (3 stops for a "day" plan).
        restaurants_picks = [p for p in picks if p.category == "restaurant"]
        activity_picks = [p for p in picks if p.category == "activity"]
        final_picks: List[PlanAndExecuteAgent._PlacePick] = []
        if restaurants_picks:
            final_picks.append(restaurants_picks[0])
        if activity_picks:
            final_picks.append(activity_picks[0])
        if len(restaurants_picks) >= 2:
            final_picks.append(restaurants_picks[1])
        # Fill remaining if needed
        for p in picks:
            if len(final_picks) >= 3:
                break
            if p not in final_picks:
                final_picks.append(p)

        stops = self._build_stops_from_picks(final_picks, vibes=vibes, start_time="TBD")

        title = f"Día romántico en {city}"
        description = "Itinerario romántico con paradas seleccionadas por calidad y vibe."
        category = "romantic"

        plan_result = await self._ainvoke_tool(
            "generate_plan_json_tool",
            {
                "title": title,
                "description": description,
                "category": category,
                "vibes": vibes,
                "date": "TBD",
                "start_time": "TBD",
                "city": city,
                "group_size": num_people,
                "stops": stops,
                "total_duration_hours": 8.0,
                "budget_per_person": float(budget) if budget is not None else None,
                "user_max_budget_per_person": float(budget) if budget is not None else None,
                "final_recommendations": [
                    "Reserva con antelación si es fin de semana.",
                    "Lleva calzado cómodo para caminar entre paradas.",
                    "Si prefieres algo más tranquilo o más animado, puedo ajustar el plan.",
                ],
            },
        )

        if isinstance(plan_result, dict) and plan_result.get("success") is True and isinstance(plan_result.get("plan"), dict):
            return plan_result["plan"], [p for p in ranked_places[:5] if isinstance(p, dict)]

        return None, [p for p in ranked_places[:5] if isinstance(p, dict)]

    @staticmethod
    def _deep_find(obj: Any, key: str) -> Any:
        """Best-effort recursive extraction of a key from an arbitrary nested structure."""
        if isinstance(obj, dict):
            if key in obj:
                return obj.get(key)
            for v in obj.values():
                found = PlanAndExecuteAgent._deep_find(v, key)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for v in obj:
                found = PlanAndExecuteAgent._deep_find(v, key)
                if found is not None:
                    return found
        return None

    async def get_last_checkpoint(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch the latest LangGraph checkpoint for a given thread/session and extract partial outputs.

        Used to return a partial plan when the global Supervisor timeout triggers.
        """
        if not session_id:
            return None

        await self._ensure_graph_initialized()
        if self.checkpoint_pool is None:
            return None

        # LangGraph serializes checkpoints via msgpack into langgraph_checkpoints.checkpoint (BYTEA).
        try:
            import msgpack  # type: ignore
        except Exception:
            self.logger.warning("msgpack-not-available-cannot-decode-checkpoint")
            return None

        try:
            async with self.checkpoint_pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT checkpoint, metadata, checkpoint_id, created_at
                        FROM langgraph_checkpoints
                        WHERE thread_id = %s
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (str(session_id),),
                    )
                    row = await cur.fetchone()
        except Exception as exc:
            self.logger.warning("checkpoint-fetch-failed", session_id=session_id, error=str(exc))
            return None

        if not row:
            return None

        checkpoint_bytes = row[0]
        if isinstance(checkpoint_bytes, memoryview):
            checkpoint_bytes = checkpoint_bytes.tobytes()
        elif isinstance(checkpoint_bytes, bytearray):
            checkpoint_bytes = bytes(checkpoint_bytes)
        checkpoint_id = row[2] if len(row) > 2 else None
        if not checkpoint_bytes:
            return None

        try:
            decoded = msgpack.unpackb(checkpoint_bytes, raw=False)
        except Exception as exc:
            self.logger.warning("checkpoint-decode-failed", session_id=session_id, error=str(exc))
            return None

        plan_json = self._deep_find(decoded, "plan_json") or self._deep_find(decoded, "plan")
        places = self._deep_find(decoded, "places")
        plan_params = self._deep_find(decoded, "plan_params")
        past_steps = self._deep_find(decoded, "past_steps")
        response_text = self._deep_find(decoded, "response_text")

        has_plan = isinstance(plan_json, dict) and bool(plan_json)
        has_places = isinstance(places, list) and len(places) > 0
        has_text = isinstance(response_text, str) and bool(response_text.strip())
        if not (has_plan or has_places or has_text):
            return None

        return {
            "checkpoint_id": checkpoint_id,
            "plan": plan_json if isinstance(plan_json, dict) else None,
            "places": places if isinstance(places, list) else [],
            "plan_params": plan_params if isinstance(plan_params, dict) else {},
            "past_steps": past_steps if isinstance(past_steps, list) else [],
            "response_text": response_text if isinstance(response_text, str) else "",
        }

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph state machine."""
        workflow = StateGraph(PlanExecuteState)

        # Add nodes
        workflow.add_node("planner", self._plan_node)
        workflow.add_node("executor", self._execute_node)
        workflow.add_node("replanner", self._replan_node)

        # Set entry point
        workflow.set_entry_point("planner")

        # Add edges
        workflow.add_edge("planner", "executor")
        workflow.add_conditional_edges(
            "executor",
            self._should_continue_or_replan,
            {
                "continue": "executor",
                "replan": "replanner",
                "end": END,
            },
        )
        workflow.add_edge("replanner", "executor")

        return workflow.compile(checkpointer=self.checkpointer)

    async def _plan_node(self, state: PlanExecuteState) -> Dict[str, Any]:
        """Create initial plan with parameter validation."""
        self.logger.info("planning", query=state["input"])

        # ✅ Get plan_params from STATE (not context) - this is managed by LangGraph reducer
        plan_params = state.get("plan_params", {})
        
        self.logger.debug("plan-node-params", params=plan_params, has_params=bool(plan_params))
        
        # Check required fields (vibes is optional when user explicitly has no preference)
        required_fields = ["num_people", "cities", "budget_per_person"]
        missing: list[str] = []
        for field in required_fields:
            value = plan_params.get(field)
            if value is None or (isinstance(value, list) and len(value) == 0) or value == "":
                missing.append(field)

        # Vibes: required only if not explicitly "any"
        if plan_params.get("vibes_any") is not True:
            vibes_value = plan_params.get("vibes")
            if vibes_value is None or (isinstance(vibes_value, list) and len(vibes_value) == 0) or vibes_value == "":
                missing.append("vibes")
        
        if missing:
            self.logger.info("plan-stopped-missing-info", missing=missing)
            return {
                "plan": [f"STOP: Missing {', '.join(missing)}"],
                "current_step": f"STOP: Missing {', '.join(missing)}",
                "past_steps": [],
            }

        # Build prompt with plan_params
        context = state.get("context", {})
        prompt = PLANNER_PROMPT.format(
            query=state["input"],
            context=json.dumps(context, indent=2, default=str),
            plan_params=json.dumps(plan_params, indent=2),
        )

        try:
            response = await self.planner_llm.ainvoke([SystemMessage(content=prompt)])
            response_text = response.content

            # Parse JSON from response
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            try:
                plan_data = json.loads(response_text)
            except json.JSONDecodeError:
                plan_data = {"plan": [line.strip() for line in response_text.split("\n") if line.strip()]}

            plan = plan_data.get("plan", [])
            
            # Check for STOP in plan
            if plan and any(str(step).startswith("STOP:") for step in plan):
                return {
                    "plan": plan,
                    "current_step": plan[0],
                    "past_steps": [],
                }

            self.logger.info("plan-created", steps=len(plan))

        except Exception as e:
            self.logger.error("plan-parsing-error", error=str(e))
            plan = [
                "Step 1: Use places_search_tool to search for places.",
                "Step 2: Use generate_plan_json_tool to create itinerary.",
            ]

        return {
            "plan": plan,
            "current_step": plan[0] if plan else None,
            "past_steps": [],
            "agent_type": "plan_and_execute",
        }

    async def _execute_node(self, state: PlanExecuteState) -> Dict[str, Any]:
        """Execute current step using LLM with tools."""
        current_step = state.get("current_step")
        if not current_step:
            return {"current_step": None}

        self.logger.info("executing-step", step=current_step)
        
        # Handle STOP condition
        if current_step.startswith("STOP:"):
            # ✅ FIX: Get plan_params from state (not context) - it's a first-level field with reducer
            plan_params = state.get("plan_params", {})
            language = state.get("language", "es")
            
            self.logger.debug("execute-stop-condition", plan_params=plan_params)
            
            from src.agents.utils.structured_parameter_extractor import StructuredParameterExtractor
            extractor = StructuredParameterExtractor()
            missing = extractor.get_missing_required(plan_params)
            question = extractor.format_missing_fields_prompt(missing, language)
            
            self.logger.debug("execute-stop-missing", missing=missing, question_length=len(question))
            
            # Note: With reducers, we just return the NEW items - reducer handles accumulation
            return {
                "past_steps": [(current_step, {"response": question, "tool_calls": 0})],
                "current_step": None,
                "messages": [AIMessage(content=question)],
                "reasoning_steps": state.get("reasoning_steps", 0) + 1,
                "response_text": question,
            }

        # Execute step with AgentExecutor
        # ✅ Get plan_params from state (not context) - it's a first-level field with reducer
        plan_params = state.get("plan_params", {})
        context = state.get("context", {})

        # LangChain best practice: avoid injecting raw JSON-with-braces into a pre-formatted
        # prompt string via Python's `.format(...)`. Instead, pass it as a template variable.
        #
        # Also: limit what we pass to the executor to reduce token usage and avoid leaking PII.
        executor_context = {
            "validated_context": context.get("validated_context"),
            "location": context.get("location"),
            "preferences": context.get("preferences"),
            "plan_params": plan_params,
            "conversation_history_text": context.get("conversation_history_text"),
        }
        context_json = json.dumps(executor_context, indent=2, default=str)
        
        exec_prompt = f"""Execute this step of the plan:

**Step:** {current_step}

**Context:**
- Plan Parameters: {json.dumps(plan_params, indent=2)}
- User Query: {state['input']}
- Language: {state.get('language', 'es')}

Execute the step now using the appropriate tools."""

        from langchain.agents import AgentExecutor, create_openai_tools_agent
        
        prompt_template = (
            ChatPromptTemplate.from_messages(
                [
                    ("system", EXECUTOR_PROMPT),
                    ("human", "{input}"),
                    MessagesPlaceholder(variable_name="agent_scratchpad"),
                ]
            )
            .partial(
                step=current_step,
                past_steps=self._format_past_steps(state.get("past_steps", [])),
                context=context_json,
            )
        )
        
        agent = create_openai_tools_agent(
            llm=self.executor_llm,
            tools=self.all_tools,
            prompt=prompt_template,
        )
        
        agent_executor = AgentExecutor(
            agent=agent,
            tools=self.all_tools,
            verbose=False,
            max_iterations=3,
            handle_parsing_errors=True,
        )
        
        try:
            exec_result = await agent_executor.ainvoke({"input": exec_prompt})
            response_text = exec_result.get("output", "Step completed")

            # Guard rails: if any critical tool returned a structured error, stop early.
            for action, observation in exec_result.get("intermediate_steps", []) or []:
                tool_name = getattr(action, "tool", None) or str(action)
                if not isinstance(observation, dict):
                    continue
                if observation.get("error") is True:
                    # Deterministic error: do not continue with degraded state.
                    self.logger.warning("tool-error-detected", tool=tool_name, error=observation.get("message"))
                    language = state.get("language", "es")
                    msg = (
                        "Tuve un problema procesando los resultados para armar el plan. "
                        "¿Quieres que lo intente de nuevo enfocándonos solo en restaurantes, o prefieres un plan de 2 paradas (paseo + cena)?"
                        if str(language).startswith("es")
                        else "I hit an issue processing results to build the plan. Do you want me to retry focusing only on restaurants, or prefer a 2-stop plan (walk + dinner)?"
                    )
                    return {
                        "past_steps": [
                            (
                                current_step,
                                {"response": response_text, "tool_calls": len(exec_result.get("intermediate_steps", []))},
                            )
                        ],
                        "current_step": None,
                        "messages": [AIMessage(content=msg)],
                        "reasoning_steps": state.get("reasoning_steps", 0) + 1,
                        "response_text": msg,
                    }

                # If a tool returned {success: False, error: ...} treat it as a failure as well.
                if observation.get("success") is False and observation.get("error"):
                    self.logger.warning("tool-unsuccessful-detected", tool=tool_name, error=observation.get("error"))
                    language = state.get("language", "es")
                    msg = (
                        "Tuve un problema con una herramienta necesaria para armar el plan. "
                        "Puedo reintentar con una búsqueda más amplia o armar un plan más simple con menos paradas. "
                        "¿Qué prefieres?"
                        if str(language).startswith("es")
                        else "A required tool failed. I can retry with a broader search or generate a simpler plan with fewer stops. Which do you prefer?"
                    )
                    return {
                        "past_steps": [
                            (
                                current_step,
                                {"response": response_text, "tool_calls": len(exec_result.get("intermediate_steps", []))},
                            )
                        ],
                        "current_step": None,
                        "messages": [AIMessage(content=msg)],
                        "reasoning_steps": state.get("reasoning_steps", 0) + 1,
                        "response_text": msg,
                    }

            # Deterministic coverage gating: inspect tool observations (not LLM text)
            # If geocode_city_tool indicates outside coverage, stop and let LLM craft a friendly message.
            coverage_observation: dict | None = None
            for action, observation in exec_result.get("intermediate_steps", []) or []:
                tool_name = getattr(action, "tool", None) or str(action)
                if "geocode_city_tool" not in str(tool_name):
                    continue
                if not isinstance(observation, str):
                    continue
                try:
                    parsed = json.loads(observation)
                except Exception:
                    continue
                if isinstance(parsed, dict) and parsed.get("ok") is True and parsed.get("coverage_enabled") is True:
                    coverage_observation = parsed
                    break

            if coverage_observation and coverage_observation.get("is_within_coverage") is False:
                from src.config.settings import get_settings

                settings = get_settings()
                allowed = settings.coverage_countries_list
                language = state.get("language", "es")
                user_query = state.get("input", "")
                city_query = coverage_observation.get("query", "")
                country_name = coverage_observation.get("country_name", "")
                country_code = coverage_observation.get("country_code", "")

                policy_note = settings.coverage_policy_note
                policy_prompt = f"""You are Auphere, a helpful travel planning assistant.

The user asked for a plan in a location OUTSIDE our current MVP coverage.

Policy (non user-facing): {policy_note}
Allowed countries (ISO): {allowed}

Detected location:
- query: {city_query}
- country: {country_name} ({country_code})

User query: {user_query}
User language: {language}

Write a short, friendly response in the user's language.
Constraints:
- Do NOT mention internal markers, tools, or policies verbatim.
- Explain we currently have limited coverage during MVP.
- Ask the user to choose a city within the supported coverage to continue.
- Keep it concise (1-3 sentences)."""

                try:
                    msg = await self.synthesizer_llm.ainvoke([SystemMessage(content=policy_prompt)])
                    coverage_response = clean_response_text(msg.content)
                except Exception as exc:
                    self.logger.warning("coverage-response-generation-failed", error=str(exc))
                    coverage_response = (
                        "Ahora mismo tenemos cobertura limitada durante el MVP. "
                        "¿Quieres que armemos el plan en una ciudad dentro de nuestra cobertura para continuar?"
                        if str(language).startswith("es")
                        else "We currently have limited coverage during our MVP. Could you choose a city within our supported coverage to continue?"
                    )

                return {
                    "past_steps": [
                        (
                            current_step,
                            {
                                "response": response_text,
                                "tool_calls": len(exec_result.get("intermediate_steps", [])),
                            },
                        )
                    ],
                    "current_step": None,
                    "messages": [AIMessage(content=coverage_response)],
                    "reasoning_steps": state.get("reasoning_steps", 0) + 1,
                    "response_text": coverage_response,
                }
            
            # Check if final step
            if "generate_plan_json_tool" in current_step.lower():
                # Extract places and plan from intermediate steps
                places = []
                plan_json = None
                
                for step in exec_result.get("intermediate_steps", []):
                    action, observation = step
                    tool_name = action.tool if hasattr(action, 'tool') else str(action)
                    
                    if (
                        "places_search" in tool_name.lower()
                        or "places_get_place" in tool_name.lower()
                        or "google_places" in tool_name.lower()
                    ):
                        if isinstance(observation, list):
                            places.extend(observation)
                        elif isinstance(observation, dict) and "places" in observation:
                            places.extend(observation["places"])
                    
                    if "generate_plan_json" in tool_name.lower():
                        if isinstance(observation, dict):
                            plan_json = observation.get("plan")
                
                # Deduplicate
                seen_ids = set()
                unique_places = []
                for place in places:
                    place_id = place.get("place_id") or place.get("id") or place.get("name")
                    if place_id and place_id not in seen_ids:
                        seen_ids.add(place_id)
                        unique_places.append(place)
                
                # Synthesize final response (skip if close to deadline to avoid global timeout)
                deadline_ts = float(state.get("deadline_ts") or 0.0)
                should_skip_synthesis = deadline_ts > 0 and perf_counter() > (deadline_ts - 10.0)

                if should_skip_synthesis:
                    self.logger.warning(
                        "skipping-final-synthesis-near-deadline",
                        session_id=state.get("session_id"),
                    )
                    final_response = (
                        "Listo: ya armé el plan y lo dejé reflejado en la tarjeta del itinerario."
                        if str(state.get("language", "es")).startswith("es")
                        else "Done: I generated the plan and it’s available in the itinerary card."
                    )
                else:
                    synth_prompt = SYNTHESIZER_PROMPT.format(
                        query=state["input"],
                        language=state.get("language", "es"),
                        all_results=self._format_past_steps(state.get("past_steps", [])) + f"\n\nFinal: {response_text}",
                        context=json.dumps(context, indent=2, default=str),
                    )

                    synth_response = await self.synthesizer_llm.ainvoke([SystemMessage(content=synth_prompt)])
                    final_response = clean_response_text(synth_response.content)
                
                # Save places
                if unique_places:
                    try:
                        fallback_city = None
                        pp = state.get("plan_params") or {}
                        if isinstance(pp, dict):
                            fallback_city = pp.get("primary_city") or (pp.get("cities") or [None])[0]

                        unique_places = await save_places_to_db(
                            unique_places,
                            self.settings,
                            fallback_city=str(fallback_city) if fallback_city else None,
                        )
                        self.logger.info("places-saved", count=len(unique_places))
                    except Exception as exc:
                        self.logger.error("failed-to-save-places", error=str(exc))

                # With reducers, just return NEW items - reducer handles accumulation
                return {
                    "past_steps": [(current_step, {"response": response_text, "tool_calls": len(exec_result.get("intermediate_steps", []))})],
                    "current_step": None,
                    "plan_json": plan_json,
                    "places": unique_places[:5],
                    "messages": [AIMessage(content=final_response)],
                    "reasoning_steps": state.get("reasoning_steps", 0) + 1,
                    "response_text": final_response,
                }
            
            # Note: coverage gating handled above by inspecting tool observations.
            
            # Not final step - continue
            plan = state.get("plan", [])
            current_idx = next((i for i, step in enumerate(plan) if step == current_step), -1)
            next_step = plan[current_idx + 1] if current_idx >= 0 and current_idx + 1 < len(plan) else None
            
            # With reducers, just return NEW items
            return {
                "past_steps": [(current_step, {"response": response_text, "tool_calls": len(exec_result.get("intermediate_steps", []))})],
                "current_step": next_step,
                "messages": [AIMessage(content=response_text)],
                "reasoning_steps": state.get("reasoning_steps", 0) + 1,
            }
            
        except Exception as e:
            # If the final tool call failed (e.g., missing required args), fall back deterministically.
            if isinstance(current_step, str) and "generate_plan_json_tool" in current_step.lower():
                self.logger.error("execution-failed-final-step", error=str(e))
                plan_json, selected_places = await self._fallback_build_plan_json(state)
                if plan_json:
                    final_response = (
                        "Listo: generé el itinerario y lo dejé reflejado en la tarjeta del plan."
                        if str(state.get("language", "es")).startswith("es")
                        else "Done: I generated the itinerary and it’s available in the plan card."
                    )
                    return {
                        "past_steps": [(current_step, {"response": f"Fallback after error: {e}", "tool_calls": 0})],
                        "current_step": None,
                        "plan_json": plan_json,
                        "places": selected_places[:5],
                        "messages": [AIMessage(content=final_response)],
                        "reasoning_steps": state.get("reasoning_steps", 0) + 1,
                        "response_text": final_response,
                    }

                msg = (
                    "No pude generar el plan automáticamente porque los datos de los lugares estaban incompletos. "
                    "¿Quieres que lo armemos solo con restaurantes (más fácil) o que ampliemos la búsqueda a otra zona de Zaragoza?"
                    if str(state.get("language", "es")).startswith("es")
                    else "I couldn’t generate the plan automatically because the place data was incomplete. Do you want a restaurants-only plan (easier) or expand the search area?"
                )
                return {
                    "past_steps": [(current_step, {"response": f"Error: {e}", "tool_calls": 0})],
                    "current_step": None,
                    "messages": [AIMessage(content=msg)],
                    "reasoning_steps": state.get("reasoning_steps", 0) + 1,
                    "response_text": msg,
                }

            self.logger.error("execution-failed", error=str(e))
            # With reducers, just return NEW items
            return {
                "past_steps": [(current_step, {"response": f"Error: {e}", "tool_calls": 0})],
                "current_step": None,
                "messages": [AIMessage(content=f"Error: {e}")],
                "reasoning_steps": state.get("reasoning_steps", 0) + 1,
                "response_text": f"Lo siento, hubo un error: {e}",
            }

    async def _replan_node(self, state: PlanExecuteState) -> Dict[str, Any]:
        """Adapt plan based on execution results."""
        self.logger.info("replanning")

        prompt = REPLANNER_PROMPT.format(
            original_plan=json.dumps(state.get("plan", [])),
            past_steps=self._format_past_steps(state.get("past_steps", [])),
            situation="Execution in progress",
        )

        try:
            response = await self.planner_llm.ainvoke([SystemMessage(content=prompt)])
            replan_data = json.loads(response.content)
            decision = replan_data.get("decision", "continue")

            if decision == "continue":
                plan = state.get("plan", [])
                past_steps = state.get("past_steps", [])
                next_step = plan[len(past_steps)] if len(past_steps) < len(plan) else None
                return {"current_step": next_step}

            elif decision == "replan":
                new_plan = replan_data.get("updated_plan", [])
                return {"plan": new_plan, "current_step": new_plan[0] if new_plan else None}

            else:
                return {"current_step": None}

        except Exception as e:
            self.logger.error(f"Replan failed: {e}")
            return {"current_step": None}

    def _should_continue_or_replan(self, state: PlanExecuteState) -> str:
        """Decide whether to continue, replan, or finish."""
        current_step = state.get("current_step")

        if current_step is None:
            return "end"

        if isinstance(current_step, str) and current_step.startswith("STOP:"):
            return "end"

        return "continue"

    def _format_past_steps(self, past_steps: List[tuple]) -> str:
        """Format past steps for display in prompts."""
        if not past_steps:
            return "None yet."

        lines = []
        for idx, (step, result) in enumerate(past_steps, 1):
            lines.append(f"{idx}. {step}")
            if isinstance(result, dict):
                response = result.get("response", "")
                if response:
                    lines.append(f"   Result: {response[:200]}")
                tool_calls = result.get("tool_calls", 0)
                if tool_calls:
                    lines.append(f"   Tools used: {tool_calls}")

        return "\n".join(lines)

    async def run(
        self,
        query: str,
        language: str = "es",
        session_id: str | None = None,
        plan_params: Dict[str, Any] | None = None,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Execute the Plan-and-Execute agent with LangGraph state persistence.

        Args:
            query: User query
            language: Response language
            session_id: Session ID to use as thread_id for checkpointing (CRITICAL!)
            plan_params: Extracted plan parameters (managed by LangGraph reducer)
            context: Additional context (location, history, etc.)

        Returns:
            Dict with response_text, places, plan, and metadata
        """
        context = context or {}
        plan_params = plan_params or {}
        
        # ✅ CRITICAL: Use session_id as thread_id for persistent state across turns
        if not session_id:
            session_id = str(uuid4())
            self.logger.warning("no-session-id-provided-using-uuid", session_id=session_id)
        
        self.logger.info(
            "plan-and-execute-starting", 
            query=query, 
            language=language,
            session_id=session_id,
            plan_params=plan_params
        )
        
        # Ensure graph is initialized
        await self._ensure_graph_initialized()

        # Prepare serializable context for LangGraph checkpointing.
        #
        # IMPORTANT: LangGraph's Postgres checkpointer serializes state via msgpack.
        # SQLAlchemy models (e.g., ConversationTurn) are NOT msgpack-serializable.
        # We therefore exclude any rich objects and keep only JSON-serializable primitives.
        serializable_context = {
            k: v
            for k, v in context.items()
            if k
            not in [
                "history_messages",
                "plan_params",
                "recent_turns",  # contains SQLAlchemy ConversationTurn objects (non-serializable)
            ]
        }

        if "history_messages" in context and context["history_messages"]:
            history_summary = []
            for msg in context["history_messages"]:
                role = msg.__class__.__name__.replace("Message", "")
                content = msg.content if hasattr(msg, "content") else str(msg)
                history_summary.append(f"{role}: {content}")
            serializable_context["conversation_history_text"] = "\n".join(history_summary)

        deadline_ts = perf_counter() + max(5.0, float(self.settings.agent_max_execution_time) - 5.0)

        # ✅ Initial state with plan_params as first-level field
        initial_state = {
            "input": query,
            "language": language,
            "session_id": session_id,
            "deadline_ts": deadline_ts,
            "plan_params": plan_params,  # ✅ First-level field with reducer
            "context": serializable_context,
            "plan": [],
            "past_steps": [],
            "current_step": None,
            "messages": [],
            "response_text": "",
            "places": [],
            "plan_json": None,
            "agent_type": "plan_and_execute",
            "model_used": "",
            "reasoning_steps": 0,
        }

        # ✅ CRITICAL: Use session_id as thread_id for persistence
        config = {"configurable": {"thread_id": session_id}}

        try:
            final_state = await self.graph.ainvoke(initial_state, config)
            self.logger.info(
                "plan-and-execute-completed",
                reasoning_steps=final_state.get("reasoning_steps", 0),
                places_found=len(final_state.get("places", [])),
            )

            return {
                "response_text": final_state.get("response_text", ""),
                "places": final_state.get("places", []),
                "plan": final_state.get("plan_json"),
                "tool_calls": final_state.get("reasoning_steps", 0),
                "reasoning_steps": final_state.get("reasoning_steps", 0),
                "agent_type": "plan_and_execute",
                "model_used": "gpt-4o + gpt-4o-mini",
                "plan_params": final_state.get("plan_params", {}),  # ✅ From state, not context
            }

        except Exception as exc:
            self.logger.error("plan-and-execute-failed", error=str(exc), query=query)
            raise
    
    async def cleanup(self):
        """
        Cleanup resources, particularly the dedicated checkpoint connection pool.
        Should be called when shutting down the agent or application.
        """
        if self.checkpoint_pool is not None:
            try:
                await self.checkpoint_pool.close(timeout=5.0)
                self.logger.info("checkpoint-pool-closed")
            except Exception as e:
                self.logger.warning(f"Error closing checkpoint pool: {e}")
            finally:
                self.checkpoint_pool = None
                self.checkpointer = None
                self.graph = None
