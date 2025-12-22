"""
Plan-and-Execute Agent using LangGraph for advanced multi-step reasoning.

This agent implements a sophisticated Plan-and-Execute pattern where:
1. PLANNER: Creates a multi-step plan to accomplish the user's goal
2. EXECUTOR: Executes each step using appropriate tools
3. REPLANNER: Adapts the plan based on execution results
4. FINAL ANSWER: Synthesizes all information into a comprehensive response

Similar to how Perplexity, OpenAI, and Claude handle complex queries.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, TypedDict, Annotated, Sequence
from uuid import uuid4

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage, FunctionMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger
from src.agents.utils.place_extractor import extract_places_from_messages
from src.agents.utils.place_saver import save_places_to_db
from src.agents.utils.text_cleaner import clean_response_text


logger = get_logger("plan_and_execute_agent")


# State definition for the graph
class PlanExecuteState(TypedDict):
    """State for Plan-and-Execute agent."""
    
    # Input
    query: str
    language: str
    context: Dict[str, Any]
    
    # Planning
    plan: List[str]  # List of steps in the plan
    past_steps: Annotated[List[tuple], "operator.add"]  # (step, result) tuples
    current_step: Optional[str]
    
    # Execution
    messages: Annotated[Sequence[BaseMessage], "operator.add"]
    tool_results: List[Dict[str, Any]]
    
    # Output
    response_text: str
    places: List[Dict[str, Any]]
    plan_json: Optional[Dict[str, Any]]
    
    # Metadata
    agent_type: str
    model_used: str
    reasoning_steps: int


# Prompts
PLANNER_PROMPT = """You are an expert planning agent for finding and recommending places **and generating a structured itinerary JSON**.

⚠️ CRITICAL RULE: NEVER ASSUME OR INVENT INFORMATION NOT PROVIDED BY THE USER.

Your task is to create a detailed, step-by-step plan to accomplish the user's request.

Context:
{context}

User request: {query}

**STEP 0 - INFORMATION VALIDATION:**
Before creating any plan, verify you have:
1. **Location/City**: Is it explicitly mentioned? (e.g., "Madrid", "Barcelona", "en el centro de...")
2. **Intent**: Is it clear what the user wants to do?

If either is missing:
- **DO NOT CREATE A MULTI-STEP PLAN.**
- Return a plan with exactly ONE step: `STOP: Missing [information]`.
- Example: `{{"plan": ["STOP: Missing city"], "reasoning": "User didn't specify where they want to go."}}`

**STEP 1 - PLAN STRUCTURE (if info is complete):**
Create a plan with 3-5 specific steps.
Each step should specify which tool to use.

Available tools (preferred order):
1. geocode_city_tool: ALWAYS use first if a city is mentioned.
2. google_places_tool: Use for finding restaurants, bars, and activities.
3. rank_by_score_tool: Use to rank the findings.
4. generate_plan_json_tool: ALWAYS use as the last step to create the structured itinerary.

Return ONLY a JSON object:
{{
  "plan": [
    "Step 1: ...",
    "Step 2: ..."
  ],
  "reasoning": "Brief explanation of the plan strategy"
}}
"""

EXECUTOR_PROMPT = """You are an expert executor agent that carries out specific steps of a plan.

⚠️ CRITICAL RULE: Use ONLY information explicitly provided by the user. DO NOT assume, invent, or deduce information.

Current step to execute: {current_step}

Previous steps completed:
{past_steps}

Context:
{context}

Execute this step using the appropriate tools available to you.

Mandatory behaviors:
- If the step requires locations without coordinates, first call geocode_city_tool to obtain latitude/longitude.
- Prefer google_places_tool; use search_foursquare_places for richer metadata.
- Use rank_by_score_tool before finalizing selections.
- When ready to present an itinerary, CALL generate_plan_json_tool with required fields.

**CRITICAL - When calling generate_plan_json_tool:**
Use ONLY information explicitly provided by the user:
- date: Use "TBD" if user didn't specify (e.g., "este sábado", "el 25 de diciembre")
- start_time: Use "TBD" if not specified, or "19:00" only if user said "por la noche"/"evening"
- group_size: ONLY if explicitly stated or clearly inferable ("mi novia y yo" = 2, "nosotros dos" = 2)
- vibes: Use ONLY vibes/atmosphere mentioned by user (e.g., if user said "romántico", use ["romantic"])
- budget_per_person: Use None/null if not mentioned by user
- stops: Build from found places with conservative time estimates
- final_recommendations: Keep generic, don't invent user preferences

For stop details:
- timing.recommendedStart: "TBD" if user didn't specify times
- timing.suggestedDurationMinutes: Conservative (60-90 min restaurant, 30-60 min bar/activity)
- details.averageSpendPerPerson: null if not mentioned
- selectionReasons: Based ONLY on place data and user's explicit request (don't invent preferences)

Be thorough and extract all relevant information.
Focus on quality over quantity.

Respond with the results of executing this step.
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
  "updated_plan": ["Step 1", "Step 2", ...],  # if replanning
  "reasoning": "Brief explanation"
}}
"""

SYNTHESIZER_PROMPT = """You are an expert synthesis agent that creates comprehensive final answers.

⚠️ CRITICAL RULE: Use ONLY information explicitly provided by the user and found by the tools. DO NOT assume, invent, or deduce user preferences.

User query: {query}
Language: {language}

All executed steps and results:
{all_results}

Context:
{context}

Create a comprehensive, well-structured response that:
1. Directly answers the user's query based ONLY on what they asked
2. Incorporates insights from all data sources (Foursquare, Instagram, TikTok, TripAdvisor)
3. Provides specific recommendations with reasoning based on actual place data
4. Mentions relevant details (ratings, reviews, tips, trending content)
5. Is written in a natural, conversational tone
6. Is in the requested language ({language})

**DO NOT invent or assume:**
- ❌ Specific dates or times if user didn't provide them
- ❌ Budget preferences if not mentioned
- ❌ Specific cuisine preferences beyond what user said
- ❌ Number of stops unless user specified
- ❌ Activity durations unless based on reasonable defaults

**ONLY mention:**
- ✅ Places found by the search tools
- ✅ Vibes/atmosphere explicitly requested by user
- ✅ Information from place data (ratings, reviews, etc.)
- ✅ Generic helpful tips (e.g., "reservar con anticipación")

Be detailed but concise. Highlight the most important and recent information.
Stick to facts from the data and the user's explicit request.
"""


class PlanAndExecuteAgent:
    """
    Advanced Plan-and-Execute agent using LangGraph.
    
    This agent uses a multi-stage approach:
    1. Plans a strategy to accomplish the user's goal
    2. Executes each step using appropriate tools
    3. Synthesizes all information into a comprehensive response
    4. Can replan if needed based on intermediate results
    """
    
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = get_logger("plan_and_execute_agent", settings=self.settings)
        
        # Use GPT-4o for complex planning and reasoning
        self.planner_llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.3,  # Lower for consistent planning
            api_key=self.settings.openai_api_key,
        )
        
        # Use GPT-4o-mini for execution (faster, cheaper)
        self.executor_llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.5,
            api_key=self.settings.openai_api_key,
        )
        
        # Use GPT-4o for final synthesis (better quality)
        self.synthesizer_llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.7,  # Higher for more natural language
            api_key=self.settings.openai_api_key,
        )
        
        # Get tools
        from src.tools.tool_registry import get_plan_tools
        self.tools = get_plan_tools()
        
        # Add new enrichment tools
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
        
        # All tools for executor
        self.all_tools = self.tools + self.enrichment_tools
        
        # Build the graph
        self.graph = self._build_graph()
        
        self.logger.info("plan-and-execute-agent-initialized")
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph state machine."""
        
        # Create state graph
        workflow = StateGraph(PlanExecuteState)
        
        # Add nodes
        workflow.add_node("planner", self._plan_node)
        workflow.add_node("executor", self._execute_node)
        workflow.add_node("replanner", self._replan_node)
        workflow.add_node("synthesizer", self._synthesize_node)
        
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
                "finish": "synthesizer",
            }
        )
        workflow.add_edge("replanner", "executor")
        workflow.add_edge("synthesizer", END)
        
        # Compile with checkpointing for resumability
        memory = MemorySaver()
        return workflow.compile(checkpointer=memory)
    
    async def _plan_node(self, state: PlanExecuteState) -> Dict[str, Any]:
        """Create initial plan."""
        self.logger.info("planning", query=state["query"])
        
        prompt = PLANNER_PROMPT.format(
            query=state["query"],
            context=json.dumps(state.get("context", {}), indent=2),
        )
        
        messages = [SystemMessage(content=prompt)]
        response = await self.planner_llm.ainvoke(messages)
        
        # Parse plan from response
        try:
            # Try to parse as JSON
            response_text = response.content
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            try:
                plan_data = json.loads(response_text)
            except json.JSONDecodeError:
                # If it's not JSON, maybe it's just text
                plan_data = {"plan": [line.strip() for line in response_text.split("\n") if line.strip()]}

            if not isinstance(plan_data, dict):
                plan_data = {"plan": [str(plan_data)]}

            plan = plan_data.get("plan", [])
            reasoning = plan_data.get("reasoning", "Plan strategy created.")
            
            # Check for STOP condition
            if plan and any(isinstance(step, str) and step.startswith("STOP:") for step in plan):
                self.logger.info("plan-stopped-missing-info", reasoning=reasoning)
                return {
                    "plan": plan,
                    "current_step": plan[0],
                    "past_steps": [],
                }
            
            self.logger.info("plan-created", steps=len(plan), reasoning=reasoning)
            
        except Exception as e:
            self.logger.error("plan-parsing-error", error=str(e))
            # Fallback
            plan = [
                "Step 1: Use google_places_tool to search for restaurants in the requested area.",
                "Step 2: Use generate_plan_json_tool to create a structured itinerary.",
            ]
            reasoning = "Fallback plan due to parsing error."
        
        return {
            "plan": plan,
            "current_step": plan[0] if plan else None,
            "past_steps": [],
            "agent_type": "plan_and_execute",
        }

    async def _execute_node(self, state: PlanExecuteState) -> Dict[str, Any]:
        """Execute current step."""
        current_step = state.get("current_step")
        if not current_step:
            return {"current_step": None}
        
        # Helpers
        def _tool_name_from_call(call: Any) -> str:
            if isinstance(call, dict):
                return call.get("name") or call.get("tool") or call.get("function", {}).get("name") or ""
            return getattr(call, "name", "") or ""

        def _get_tool(tool_name: str):
            for t in self.all_tools:
                if getattr(t, "name", None) == tool_name:
                    return t
            return None

        def _extract_city_from_query(q: str) -> Optional[str]:
            ql = (q or "").strip()
            if not ql:
                return None
            # Common Spanish patterns: "en la ciudad de X", "en X"
            m = re.search(r"\ben\s+la\s+ciudad\s+de\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+)", ql, re.IGNORECASE)
            if m:
                return m.group(1).strip().strip(".,")
            m = re.search(r"\ben\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)", ql, re.IGNORECASE)
            if m:
                return m.group(1).strip().strip(".,")
            return None

        def _extract_lat_lon_from_text(text: str) -> Optional[Dict[str, float]]:
            if not text:
                return None
            m = re.search(r"lat\s*=\s*([\-0-9\.]+)\s*,\s*lon\s*=\s*([\-0-9\.]+)", text)
            if not m:
                return None
            try:
                return {"latitude": float(m.group(1)), "longitude": float(m.group(2))}
            except Exception:
                return None

        def _ensure_location_in_context(ctx: Dict[str, Any], lat: float, lon: float, city: Optional[str] = None) -> Dict[str, Any]:
            updated = dict(ctx or {})
            loc = dict(updated.get("location") or {})
            loc["latitude"] = lat
            loc["longitude"] = lon
            if city and not loc.get("city"):
                loc["city"] = city
            updated["location"] = loc
            return updated

        def _build_google_places_query(step: str, user_query: str) -> str:
            # Minimal deterministic query building to avoid hallucination.
            sl = step.lower()
            if "restaurant" in sl or "restauran" in sl:
                return f"restaurantes románticos {user_query}"
            if "bar" in sl:
                return f"bares divertidos y románticos {user_query}"
            if "activity" in sl or "actividad" in sl:
                return f"actividades divertidas y románticas {user_query}"
            return user_query

        def _pick_top_places(places: List[Dict[str, Any]], n: int = 3) -> List[Dict[str, Any]]:
            def key(p: Dict[str, Any]):
                rating = p.get("rating") or 0
                reviews = p.get("user_ratings_total") or 0
                return (rating, reviews)
            return sorted(places or [], key=key, reverse=True)[:n]

        def _place_to_stop(place: Dict[str, Any], stop_number: int, category: str, vibes: List[str]) -> Dict[str, Any]:
            lat = place.get("latitude")
            lon = place.get("longitude")
            duration = 90 if category == "restaurant" else 60
            return {
                "stopNumber": stop_number,
                "localId": str(place.get("id") or place.get("name") or f"stop-{stop_number}"),
                "name": place.get("name") or "Unknown",
                "category": category,
                "typeLabel": place.get("primary_type") or (place.get("types") or [None])[0],
                "timing": {
                    "recommendedStart": "TBD",
                    "suggestedDurationMinutes": duration,
                    "estimatedEnd": "TBD",
                },
                "location": {
                    "address": place.get("address"),
                    "lat": lat,
                    "lng": lon,
                    "zone": place.get("neighborhood"),
                    "travelTimeFromPreviousMinutes": None,
                },
                "details": {
                    "vibes": vibes,
                    "targetAudience": ["couple"],
                    "music": None,
                    "noiseLevel": None,
                    "averageSpendPerPerson": None,
                },
                "selectionReasons": [
                    f"Rating: {place.get('rating')} ({place.get('user_ratings_total', 0)} reseñas)",
                    "Criterio: coincide con lo solicitado por el usuario",
                ],
                "actions": {
                    "canReserve": False,
                    "reservationUrl": place.get("website"),
                    "googleMapsUrl": place.get("google_maps_uri"),
                    "phone": place.get("phone"),
                },
                "alternatives": None,
                "personalTips": None,
            }

        # Check for STOP condition in execution
        if current_step.startswith("STOP:"):
            self.logger.info("execution-stopped", reason=current_step)
            # Remove STOP: prefix for the response
            clean_response = current_step.replace("STOP:", "").strip()
            
            result = {
                "step": current_step,
                "response": clean_response,
                "tool_calls": 0,
                "is_stop": True
            }
            
            return {
                "past_steps": state.get("past_steps", []) + [(current_step, result)],
                "current_step": None, # Force finish
                "messages": state.get("messages", []) + [AIMessage(content=clean_response)],
                "reasoning_steps": state.get("reasoning_steps", 0) + 1,
            }

        # Deterministic tool execution for critical steps (stability)
        ctx = dict(state.get("context") or {})
        city_guess = (ctx.get("location") or {}).get("city") or _extract_city_from_query(state.get("query", "")) or _extract_city_from_query(state.get("context", {}).get("current_query", "") if isinstance(state.get("context"), dict) else "")

        # If step requires google_places_tool, ensure we actually call it and store results
        if "google_places_tool" in current_step:
            # Ensure we have coordinates once
            loc = ctx.get("location") or {}
            lat = loc.get("latitude")
            lon = loc.get("longitude")
            if lat is None or lon is None:
                geocode_tool = _get_tool("geocode_city_tool")
                if geocode_tool and city_guess:
                    geo_text = await geocode_tool.ainvoke({"city": city_guess})
                    coords = _extract_lat_lon_from_text(geo_text if isinstance(geo_text, str) else str(geo_text))
                    if coords:
                        lat = coords["latitude"]
                        lon = coords["longitude"]
                        ctx = _ensure_location_in_context(ctx, lat, lon, city_guess)

            # Now call google places deterministically
            gp_tool = _get_tool("google_places_tool")
            if gp_tool:
                gp_query = _build_google_places_query(current_step, state["query"])
                gp_result = await gp_tool.ainvoke(
                    {
                        "query": gp_query,
                        "latitude": lat,
                        "longitude": lon,
                        "radius_meters": 3000,
                        "max_results": 10,
                        "language": state.get("language", "es"),
                    }
                )
                # Store tool result in messages for downstream extractors
                tool_msg = FunctionMessage(name="google_places_tool", content=json.dumps(gp_result))
                prior_messages = list(state.get("messages", []))
                aggregated_messages = prior_messages + [tool_msg]

                past_steps = state.get("past_steps", [])
                past_steps.append(
                    (
                        current_step,
                        {
                            "step": current_step,
                            "response": "google_places_tool executed",
                            "tool_calls": 1,
                            "tool_results": [tool_msg],
                        },
                    )
                )

                # Advance
                plan = state.get("plan", [])
                completed_count = len(past_steps)
                next_step = plan[completed_count] if completed_count < len(plan) else None
                self.logger.info("step-executed", completed=completed_count, total=len(plan))
                return {
                    "context": ctx,
                    "past_steps": past_steps,
                    "current_step": next_step,
                    "messages": aggregated_messages,
                    "reasoning_steps": state.get("reasoning_steps", 0) + 1,
                }

        # If step requires generate_plan_json_tool, build plan deterministically from prior google places results
        if "generate_plan_json_tool" in current_step:
            # Collect places from previous tool messages
            all_msgs = list(state.get("messages", []))
            restaurants: List[Dict[str, Any]] = []
            activities: List[Dict[str, Any]] = []
            for msg in all_msgs:
                if isinstance(msg, FunctionMessage) and getattr(msg, "name", "") == "google_places_tool":
                    try:
                        payload = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                        places = payload.get("places", []) if isinstance(payload, dict) else []
                        # Heuristic: classify based on last step text
                        # If last step contains "restaurant" -> restaurant bucket else activity bucket.
                        # (This keeps us data-driven and avoids hallucination.)
                        # We'll just append and later pick top.
                        if places:
                            # decide bucket based on whether any place looks like restaurant
                            # otherwise treat as activities
                            if any("restaurant" in (p.get("primary_type") or "").lower() for p in places):
                                restaurants.extend(places)
                            else:
                                activities.extend(places)
                    except Exception:
                        continue

            # Fallback: if we couldn't bucket, just split by order
            combined = restaurants + activities
            top = _pick_top_places(combined, n=3)
            if not top:
                # No tool data; cannot create a real plan JSON
                clean_response = "No tengo suficientes datos (lugares) para construir un plan. ¿Puedes confirmar la zona exacta y si prefieres restaurante + bar o restaurante + actividad?"
                past_steps = state.get("past_steps", [])
                past_steps.append((current_step, {"step": current_step, "response": clean_response, "tool_calls": 0}))
                return {
                    "past_steps": past_steps,
                    "current_step": None,
                    "messages": state.get("messages", []) + [AIMessage(content=clean_response)],
                    "reasoning_steps": state.get("reasoning_steps", 0) + 1,
                }

            vibes = ["romantic", "fun"]
            city_final = (ctx.get("location") or {}).get("city") or city_guess or "TBD"
            stops = []
            for idx, place in enumerate(top, 1):
                cat = "restaurant" if idx == 1 else "bar"
                stops.append(_place_to_stop(place, idx, cat, vibes))
            total_minutes = sum(s["timing"]["suggestedDurationMinutes"] for s in stops)
            gpjt = _get_tool("generate_plan_json_tool")
            if gpjt:
                plan_result = await gpjt.ainvoke(
                    {
                        "title": f"Noche romántica y divertida en {city_final}",
                        "description": "Plan sugerido basado en lugares encontrados.",
                        "category": "romantic",
                        "vibes": vibes,
                        "date": "TBD",
                        "start_time": "TBD",
                        "city": city_final,
                        "group_size": 2,
                        "stops": stops,
                        "total_duration_hours": round(total_minutes / 60.0, 2),
                        "total_distance_km": None,
                        "budget_per_person": None,
                        "final_recommendations": ["Reserva con anticipación si es posible.", "Confirma horarios antes de ir."],
                    }
                )
                tool_msg = FunctionMessage(name="generate_plan_json_tool", content=json.dumps(plan_result))
                plan_json = None
                try:
                    plan_json = plan_result.get("plan") if isinstance(plan_result, dict) else None
                except Exception:
                    plan_json = None

                past_steps = state.get("past_steps", [])
                past_steps.append((current_step, {"step": current_step, "response": "generate_plan_json_tool executed", "tool_calls": 1, "tool_results": [tool_msg]}))
                self.logger.info("step-executed", completed=len(past_steps), total=len(state.get("plan", [])))
                return {
                    "context": ctx,
                    "past_steps": past_steps,
                    "current_step": None,
                    "messages": state.get("messages", []) + [tool_msg],
                    "plan_json": plan_json,
                    "reasoning_steps": state.get("reasoning_steps", 0) + 1,
                }

        self.logger.info("executing-step", step=current_step)
        
        prompt = EXECUTOR_PROMPT.format(
            current_step=current_step,
            past_steps=self._format_past_steps(state.get("past_steps", [])),
            context=json.dumps(state.get("context", {}), indent=2),
        )
        
        messages = [SystemMessage(content=prompt), HumanMessage(content=state["query"])]
        
        # Use executor with tools
        executor_with_tools = self.executor_llm.bind_tools(self.all_tools)
        response = await executor_with_tools.ainvoke(messages)
        
        prior_messages = list(state.get("messages", []))
        plan_json = state.get("plan_json")
        
        # Execute any tool calls
        if hasattr(response, "tool_calls") and response.tool_calls:
            # Create tool node and execute
            tool_node = ToolNode(self.all_tools)
            tool_results = await tool_node.ainvoke({"messages": [response]})
            tool_messages = tool_results.get("messages", [])
            
            # Try to extract plan JSON from tool outputs
            plan_json = plan_json or self._extract_plan_json_from_messages(tool_messages)
            
            # Store results
            result = {
                "step": current_step,
                "response": response.content if hasattr(response, "content") else str(response),
                "tool_calls": len(response.tool_calls),
                "tool_results": tool_messages,
            }
            aggregated_messages = prior_messages + [response] + tool_messages
        else:
            # If the step mentioned a tool but it wasn't called, that's a problem
            # but for now we just record it
            result = {
                "step": current_step,
                "response": response.content if hasattr(response, "content") else str(response),
                "tool_calls": 0,
            }
            aggregated_messages = prior_messages + [response]
        
        # Add to past steps
        past_steps = state.get("past_steps", [])
        past_steps.append((current_step, result))
        
        # Get next step
        plan = state.get("plan", [])
        completed_count = len(past_steps)
        next_step = plan[completed_count] if completed_count < len(plan) else None
        
        self.logger.info("step-executed", completed=completed_count, total=len(plan))
        
        return {
            "past_steps": past_steps,
            "current_step": next_step,
            "messages": aggregated_messages,
            "plan_json": plan_json,
            "reasoning_steps": state.get("reasoning_steps", 0) + 1,
        }

    def _should_continue_or_replan(self, state: PlanExecuteState) -> str:
        """Decide whether to continue, replan, or finish."""
        plan = state.get("plan", [])
        past_steps = state.get("past_steps", [])
        current_step = state.get("current_step")
        
        # If no more steps, finish
        if not current_step or len(past_steps) >= len(plan):
            return "finish"
        
        # If last step was a STOP, finish
        if past_steps:
            last_result = past_steps[-1][1]
            if last_result.get("is_stop"):
                return "finish"
            
            # If last step made no tool calls, try replanning
            # BUT only if it wasn't a STOP step
            if last_result.get("tool_calls", 0) == 0:
                # If we have no more steps anyway, just finish
                if len(past_steps) >= len(plan):
                    return "finish"
                return "replan"
        
        # If we have done less than half the plan, continue
        if len(past_steps) < len(plan) // 2:
            return "continue"
        
        # Otherwise, check if we should replan
        return "continue"
    
    async def _replan_node(self, state: PlanExecuteState) -> Dict[str, Any]:
        """Replan based on execution results."""
        self.logger.info("replanning")
        
        prompt = REPLANNER_PROMPT.format(
            original_plan="\n".join(f"{i+1}. {step}" for i, step in enumerate(state.get("plan", []))),
            past_steps=self._format_past_steps(state.get("past_steps", [])),
            situation="Evaluating if we need to adjust the plan based on results so far",
        )
        
        messages = [SystemMessage(content=prompt)]
        response = await self.planner_llm.ainvoke(messages)
        
        # Parse replanning decision
        try:
            response_text = response.content
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            
            replan_data = json.loads(response_text)
            decision = replan_data.get("decision", "continue")
            updated_plan = replan_data.get("updated_plan", state.get("plan", []))
            
            if decision == "finish":
                return {"current_step": None}
            
            # Update plan if replanned
            if decision == "replan":
                remaining_idx = len(state.get("past_steps", []))
                next_step = updated_plan[remaining_idx] if remaining_idx < len(updated_plan) else None
                
                self.logger.info("plan-updated", new_steps=len(updated_plan))
                
                return {
                    "plan": updated_plan,
                    "current_step": next_step,
                }
        
        except json.JSONDecodeError:
            self.logger.warning("replan-parsing-failed")
        
        # Default: continue with current plan
        return {}
    
    async def _synthesize_node(self, state: PlanExecuteState) -> Dict[str, Any]:
        """Synthesize final answer from all results."""
        self.logger.info("synthesizing-final-answer")
        
        all_results = self._format_past_steps(state.get("past_steps", []))
        
        prompt = SYNTHESIZER_PROMPT.format(
            query=state["query"],
            language=state["language"],
            all_results=all_results,
            context=json.dumps(state.get("context", {}), indent=2),
        )
        
        messages = [SystemMessage(content=prompt)]
        response = await self.synthesizer_llm.ainvoke(messages)
        
        response_text = clean_response_text(response.content if hasattr(response, "content") else str(response))
        
        # Extract places from all messages
        all_messages = state.get("messages", [])
        places = extract_places_from_messages(all_messages)
        
        # Save places to DB
        if places:
            try:
                places = await save_places_to_db(places, self.settings)
                self.logger.info("places-saved", count=len(places))
            except Exception as exc:
                self.logger.error("failed-to-save-places", error=str(exc))
        
        self.logger.info("synthesis-complete", places_count=len(places))
        
        return {
            "response_text": response_text,
            "places": places,
            "plan_json": state.get("plan_json"),
            "model_used": "gpt-4o (plan+synth), gpt-4o-mini (exec)",
        }
    
    def _format_past_steps(self, past_steps: List[tuple]) -> str:
        """Format past steps for display in prompts."""
        if not past_steps:
            return "None yet."
        
        lines = []
        for idx, (step, result) in enumerate(past_steps, 1):
            lines.append(f"{idx}. {step}")
            
            response = result.get("response", "")
            if response:
                lines.append(f"   Result: {response[:200]}...")  # First 200 chars
            
            tool_calls = result.get("tool_calls", 0)
            if tool_calls:
                lines.append(f"   Tools used: {tool_calls}")
        
        return "\n".join(lines)
    
    def _extract_plan_json_from_messages(self, messages: Sequence[BaseMessage]) -> Optional[Dict[str, Any]]:
        """Extract plan JSON from tool messages if generate_plan_json_tool was called."""
        for msg in messages:
            if isinstance(msg, FunctionMessage) or getattr(msg, "type", "") == "tool":
                content = getattr(msg, "content", None)
                if not content:
                    continue
                try:
                    parsed = content if isinstance(content, dict) else json.loads(content)
                    if isinstance(parsed, dict) and parsed.get("success") and parsed.get("plan"):
                        return parsed.get("plan")
                except Exception:
                    continue
        return None
    
    async def run(
        self,
        query: str,
        language: str = "es",
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Execute the Plan-and-Execute agent.
        
        Args:
            query: User query
            language: Response language
            context: Additional context
            
        Returns:
            Dict with response_text, places, and metadata
        """
        context = context or {}
        
        self.logger.info(
            "plan-and-execute-starting",
            query=query,
            language=language,
        )
        
        # Prepare serializable context
        # Remove non-serializable LangChain message objects
        serializable_context = {k: v for k, v in context.items() if k != "history_messages"}
        
        # Convert history messages to serializable format if needed by prompts
        if "history_messages" in context and context["history_messages"]:
            # Convert to simple string summary for context
            history_summary = []
            for msg in context["history_messages"]:
                role = msg.__class__.__name__.replace("Message", "")
                content = msg.content if hasattr(msg, "content") else str(msg)
                history_summary.append(f"{role}: {content}")
            serializable_context["conversation_history_text"] = "\n".join(history_summary)
        
        # Initial state
        initial_state = {
            "query": query,
            "language": language,
            "context": serializable_context,
            "plan": [],
            "past_steps": [],
            "current_step": None,
            "messages": [],
            "tool_results": [],
            "response_text": "",
            "places": [],
            "plan_json": None,
            "agent_type": "plan_and_execute",
            "model_used": "",
            "reasoning_steps": 0,
        }
        
        # Run the graph
        config = {"configurable": {"thread_id": str(uuid4())}}
        
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
                "model_used": final_state.get("model_used", "gpt-4o + gpt-4o-mini"),
            }
            
        except Exception as exc:
            self.logger.error(
                "plan-and-execute-failed",
                error=str(exc),
                query=query,
            )
            raise

