"""
FastPlanAgent - deterministic, low-latency plan generator.

Design goals:
- World-class latency: avoid multi-round LLM tool loops.
- Robustness: always return a valid plan JSON when city is known and places exist.
- Scalability: parallelize independent tool calls; keep responses small.
- UX: if some parameters are missing, use sensible defaults and ask a brief follow-up.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple

from src.config.settings import Settings, get_settings
from src.tools.place_tool import places_search_tool
from src.tools.generate_plan_json_tool import generate_plan_json_tool
from src.tools.processing.scoring import rank_by_score_tool
from src.tools.search.geocoding import geocode_city_tool
from src.utils.logger import get_logger
from src.agents.utils.place_saver import save_places_to_db


@dataclass(frozen=True)
class _Pick:
    id: str
    name: str
    category: str
    address: str
    lat: float
    lng: float
    rating: Optional[float]
    price_level: Optional[int]
    primary_type: Optional[str]


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _get_primary_type(place: Dict[str, Any]) -> Optional[str]:
    pt = place.get("primary_type")
    if isinstance(pt, str) and pt:
        return pt.lower()
    types = place.get("types") or []
    if isinstance(types, list) and types:
        t0 = types[0]
        if isinstance(t0, str) and t0:
            return t0.lower()
    return None


def _pick_category(place: Dict[str, Any]) -> str:
    primary = (_get_primary_type(place) or "").lower()
    if "restaurant" in primary:
        return "restaurant"
    if "cafe" in primary or "coffee" in primary:
        return "cafe"
    if "bar" in primary or "pub" in primary or "nightclub" in primary:
        return "bar"
    # everything else becomes activity; frontend can label it
    return "activity"


def _to_pick(place: Dict[str, Any]) -> Optional[_Pick]:
    loc = place.get("location") or {}
    lat = loc.get("lat") or place.get("latitude")
    lng = loc.get("lng") or place.get("longitude") or loc.get("lon")

    lat_f = _safe_float(lat)
    lng_f = _safe_float(lng)
    if lat_f is None or lng_f is None:
        return None

    place_id = str(place.get("id") or place.get("place_id") or "").strip()
    name = str(place.get("name") or "").strip()
    if not place_id or not name:
        return None

    address = str(place.get("address") or place.get("formatted_address") or "").strip()
    category = _pick_category(place)
    rating = _safe_float(place.get("rating"))
    price_level = _safe_int(place.get("price_level") or place.get("priceLevel"))
    primary_type = _get_primary_type(place)

    return _Pick(
        id=place_id,
        name=name,
        category=category,
        address=address,
        lat=lat_f,
        lng=lng_f,
        rating=rating,
        price_level=price_level,
        primary_type=primary_type,
    )


def _dedupe_places(places: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    unique: List[Dict[str, Any]] = []
    for p in places:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or p.get("place_id") or "")
        if not pid:
            continue
        if pid in seen:
            continue
        seen.add(pid)
        unique.append(p)
    return unique


def _default_vibes(query: str) -> List[str]:
    q = (query or "").lower()
    if any(k in q for k in ["románt", "romant", "cita", "pareja"]):
        return ["romantic"]
    if any(k in q for k in ["animad", "fiesta", "bar", "salir", "noche"]):
        return ["energetic"]
    if any(k in q for k in ["cultura", "turíst", "turist", "muse", "histori", "conocer"]):
        return ["cultural"]
    return ["cultural"]


def _queries_for_vibes(vibes: List[str]) -> List[str]:
    vset = {str(v).lower() for v in (vibes or [])}
    # Keep queries short and API-friendly.
    queries: List[str] = []
    if "cultural" in vset:
        queries.extend(["atracciones turísticas", "museos", "sitios culturales"])
    if "energetic" in vset:
        queries.extend(["bares animados", "tapas", "cocktails"])
    if "romantic" in vset:
        queries.extend(["restaurantes románticos", "parques bonitos", "miradores"])
    if not queries:
        queries = ["atracciones turísticas", "restaurantes", "bares"]
    # Dedupe while keeping order
    out: List[str] = []
    seen: set[str] = set()
    for q in queries:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out[:3]


def _build_stops(picks: List[_Pick], vibes: List[str]) -> List[Dict[str, Any]]:
    durations = {"restaurant": 90, "bar": 60, "cafe": 50, "activity": 90}
    vibes_norm = [str(v) for v in vibes if v]
    if not vibes_norm:
        vibes_norm = ["cultural"]

    stops: List[Dict[str, Any]] = []
    for idx, pick in enumerate(picks, start=1):
        stops.append(
            {
                "stopNumber": idx,
                "localId": pick.id,
                "name": pick.name,
                "category": pick.category,
                "typeLabel": pick.primary_type,
                "timing": {
                    "recommendedStart": "TBD",
                    "suggestedDurationMinutes": durations.get(pick.category, 75),
                    "estimatedEnd": "TBD",
                },
                "location": {
                    "address": pick.address,
                    "lat": pick.lat,
                    "lng": pick.lng,
                    "travelTimeFromPreviousMinutes": 0 if idx == 1 else None,
                },
                "details": {
                    "vibes": vibes_norm,
                    "targetAudience": "friends",
                    "music": None,
                    "noiseLevel": None,
                    "averageSpendPerPerson": None,
                    "rating": pick.rating,
                    "priceLevel": pick.price_level,
                },
                "selectionReasons": [
                    "Seleccionado por encaje con el vibe y buena valoración.",
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


def _compose_response_es(vibes: List[str], used_defaults: List[str]) -> str:
    vset = {v.lower() for v in vibes}
    if "romantic" in vset:
        expect = "Un recorrido con ritmo tranquilo, con un par de paradas bonitas para pasear y terminar con un buen sitio para comer o tomar algo."
        tips = [
            "Reserva con antelación si vas en fin de semana.",
            "Lleva calzado cómodo: lo ideal es moverse caminando por zonas céntricas.",
            "Si prefieres algo más íntimo o más animado, dime y ajusto las paradas.",
        ]
    elif "energetic" in vset:
        expect = "Un plan con puntos turísticos clave y un cierre más animado (tapas/bares) para sentir el ambiente de la ciudad."
        tips = [
            "Empieza temprano para evitar colas en los sitios más populares.",
            "Deja el tramo de bares para el final (mejor ambiente).",
            "Si no quieren caminar mucho, dime y lo adapto por zonas.",
        ]
    else:
        expect = "Un plan equilibrado con lo más emblemático + paradas culturales y un cierre cómodo para comer o tomar algo."
        tips = [
            "Si hay mucho sol o frío, alterna interiores (museos) y exteriores (plazas/parques).",
            "Comprueba horarios si vas en lunes o festivo.",
            "Si quieres más historia o más comida local, lo ajusto.",
        ]

    defaults_note = ""
    if used_defaults:
        defaults_note = (
            "\n\nHe usado valores por defecto para: "
            + ", ".join(used_defaults)
            + ". Si me confirmas esos datos, lo afino."
        )

    tips_md = "\n".join([f"- {t}" for t in tips[:3]])
    return (
        "Listo: ya dejé el plan listo en la tarjeta del itinerario.\n\n"
        "**Qué esperar:**\n"
        f"{expect}\n\n"
        "**Consejos:**\n"
        f"{tips_md}"
        f"{defaults_note}"
    )


class FastPlanAgent:
    """
    Deterministic planning agent intended to replace slow multi-round plan-and-execute for most cases.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = get_logger("fast_plan_agent", settings=self.settings)
        # LangChain tools are BaseTool objects; call them via .ainvoke({...}) for correctness.
        self._geocode_tool = geocode_city_tool
        self._places_search_tool = places_search_tool
        self._rank_tool = rank_by_score_tool
        self._plan_tool = generate_plan_json_tool

    async def _tool_ainvoke(self, tool: Any, args: Dict[str, Any]) -> Any:
        """
        Invoke a LangChain tool in a standards-compliant way.
        Tools in this codebase are `langchain_core.tools.BaseTool` instances.
        """
        return await tool.ainvoke(args)

    @staticmethod
    def _extract_places(tool_result: Any) -> List[Dict[str, Any]]:
        if isinstance(tool_result, dict):
            return list(tool_result.get("places") or [])
        if isinstance(tool_result, list):
            return [p for p in tool_result if isinstance(p, dict)]
        return []

    async def run(
        self,
        query: str,
        language: str = "es",
        session_id: str | None = None,
        plan_params: Dict[str, Any] | None = None,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        context = context or {}
        plan_params = plan_params or {}
        t0 = perf_counter()

        city = plan_params.get("primary_city") or (plan_params.get("cities") or [None])[0]
        city = str(city).strip() if city else ""
        if not city:
            msg = (
                "¿En qué ciudad quieres el plan (y para cuántas personas)?"
                if str(language).startswith("es")
                else "Which city do you want the plan for (and for how many people)?"
            )
            return {
                "response_text": msg,
                "places": [],
                "plan": None,
                "tool_calls": 0,
                "reasoning_steps": 0,
                "agent_type": "fast_plan",
                "model_used": "deterministic",
                "plan_params": plan_params,
            }

        used_defaults: List[str] = []
        group_size = plan_params.get("num_people")
        if group_size is None:
            group_size = 2
            used_defaults.append("número de personas=2")
        try:
            group_size_int = int(group_size)
        except Exception:
            group_size_int = 2
            used_defaults.append("número de personas=2")

        budget = plan_params.get("budget_per_person")
        budget_f: Optional[float]
        if budget is None:
            budget_f = 40.0
            used_defaults.append("presupuesto=40€/persona")
        else:
            budget_f = _safe_float(budget) or 40.0

        vibes = plan_params.get("vibes")
        if not vibes:
            vibes_list = _default_vibes(query)
            used_defaults.append(f"vibe={vibes_list[0]}")
        elif isinstance(vibes, list):
            vibes_list = [str(v) for v in vibes if v]
        else:
            vibes_list = [str(vibes)]

        # Geocode for bias (cached)
        origin: Optional[Dict[str, float]] = None
        try:
            geo_raw = await self._tool_ainvoke(self._geocode_tool, {"city": city})
            parsed = json.loads(geo_raw) if isinstance(geo_raw, str) else {}
            if isinstance(parsed, dict) and parsed.get("ok") is True:
                origin = {"lat": float(parsed["latitude"]), "lon": float(parsed["longitude"])}
        except Exception:
            origin = None

        queries = _queries_for_vibes(vibes_list)

        async def _search(q: str) -> Dict[str, Any]:
            args: Dict[str, Any] = {"query": q, "city": city, "max_results": 10}
            if origin:
                args["latitude"] = origin["lat"]
                args["longitude"] = origin["lon"]
            result = await self._tool_ainvoke(self._places_search_tool, args)
            return result if isinstance(result, dict) else {"success": True, "places": self._extract_places(result)}

        # Parallelize searches with a tight budget (world-class latency target).
        try:
            search_timeout = 12.0
            results = await asyncio.wait_for(
                asyncio.gather(*[_search(q) for q in queries], return_exceptions=True),
                timeout=search_timeout,
            )
        except Exception as exc:
            self.logger.warning("fast-plan-search-timeout", error=str(exc), city=city)
            results = []

        candidates: List[Dict[str, Any]] = []
        for r in results:
            if isinstance(r, Exception):
                continue
            candidates.extend(self._extract_places(r))

        candidates = _dedupe_places(candidates)
        if not candidates:
            # Broader fallback query (single call)
            broad = await _search("lugares emblemáticos")
            candidates = _dedupe_places(self._extract_places(broad))

        if not candidates:
            msg = (
                f"No encontré suficientes lugares para armar un plan en {city}. ¿Quieres que amplíe la búsqueda (zona/radio) o que lo haga por categorías (comida, cultura, bares)?"
                if str(language).startswith("es")
                else f"I couldn't find enough places to build a plan in {city}. Want me to broaden the search or split by categories?"
            )
            return {
                "response_text": msg,
                "places": [],
                "plan": None,
                "tool_calls": 1,
                "reasoning_steps": 1,
                "agent_type": "fast_plan",
                "model_used": "deterministic",
                "plan_params": {**plan_params, "num_people": group_size_int, "budget_per_person": budget_f, "vibes": vibes_list},
            }

        # Deterministic ranking (fast, local)
        requirements: Dict[str, Any] = {"vibes": vibes_list, "budget": budget_f}
        if origin:
            requirements["location"] = origin

        ranked = await self._tool_ainvoke(
            self._rank_tool,
            {
                "places": candidates,
                "requirements": requirements,
                "language": language,
                "user_query": query,
                "requested_count": 6,
            },
        )

        ranked_places: List[Dict[str, Any]] = []
        if isinstance(ranked, dict) and not ranked.get("error"):
            for item in ranked.get("ranked_places") or []:
                if isinstance(item, dict) and isinstance(item.get("place"), dict):
                    ranked_places.append(item["place"])
        if not ranked_places:
            ranked_places = candidates[:6]

        # Picks with diversity: activity + restaurant/bar (+ extra)
        picks: List[_Pick] = []
        for p in ranked_places:
            pick = _to_pick(p)
            if pick:
                picks.append(pick)
            if len(picks) >= 8:
                break

        if not picks:
            msg = (
                "Encontré resultados, pero sin coordenadas suficientes para armar el itinerario. ¿Quieres que lo haga con menos paradas o que amplíe la búsqueda?"
                if str(language).startswith("es")
                else "I found results but not enough coordinates to build the itinerary. Want fewer stops or a broader search?"
            )
            return {
                "response_text": msg,
                "places": [],
                "plan": None,
                "tool_calls": 2,
                "reasoning_steps": 2,
                "agent_type": "fast_plan",
                "model_used": "deterministic",
                "plan_params": {**plan_params, "num_people": group_size_int, "budget_per_person": budget_f, "vibes": vibes_list},
            }

        # Choose up to 4 stops.
        activities = [p for p in picks if p.category == "activity"]
        food = [p for p in picks if p.category in {"restaurant", "bar", "cafe"}]

        selected: List[_Pick] = []
        if activities:
            selected.append(activities[0])
        if food:
            selected.append(food[0])
        if len(activities) >= 2:
            selected.append(activities[1])
        if len(food) >= 2:
            selected.append(food[1])

        # Fill if still short
        for p in picks:
            if len(selected) >= 4:
                break
            if p not in selected:
                selected.append(p)

        selected = selected[:4]
        stops = _build_stops(selected, vibes=vibes_list)

        title = f"Plan para conocer {city}"
        category = "friends" if group_size_int > 2 else ("romantic" if "romantic" in {v.lower() for v in vibes_list} else "casual")
        description = "Itinerario optimizado con paradas recomendadas por calidad y encaje con tus preferencias."

        tool_result = await self._tool_ainvoke(
            self._plan_tool,
            {
                "title": title,
                "description": description,
                "category": category,
                "vibes": vibes_list,
                "date": "TBD",
                "start_time": "TBD",
                "city": city,
                "group_size": group_size_int,
                "stops": stops,
                "total_duration_hours": 6.0,
                "total_distance_km": None,
                "budget_per_person": budget_f,
                "user_max_budget_per_person": budget_f,
                "final_recommendations": [
                    "Si prefieres más cultura o más comida local, lo ajusto.",
                    "Si quieres minimizar caminatas, dime y lo reordeno por zonas.",
                    "Revisa horarios si vas en festivo.",
                ],
            },
        )

        plan_json = tool_result.get("plan") if isinstance(tool_result, dict) and tool_result.get("success") else None
        if not isinstance(plan_json, dict):
            msg = (
                "Encontré lugares, pero no pude construir el plan estructurado. ¿Quieres un plan más simple (2 paradas) o que reintente con otra búsqueda?"
                if str(language).startswith("es")
                else "I found places but couldn't build the structured plan. Want a simpler 2-stop plan or a broader retry?"
            )
            return {
                "response_text": msg,
                "places": candidates[:6],
                "plan": None,
                "tool_calls": 3,
                "reasoning_steps": 3,
                "agent_type": "fast_plan",
                "model_used": "deterministic",
                "plan_params": {**plan_params, "num_people": group_size_int, "budget_per_person": budget_f, "vibes": vibes_list},
            }

        # Save places (best-effort)
        selected_places = [p for p in ranked_places[:6] if isinstance(p, dict)]
        try:
            saved = await save_places_to_db(selected_places, self.settings, fallback_city=city)
            selected_places = saved or selected_places
        except Exception as exc:
            self.logger.warning("fast-plan-save-places-failed", error=str(exc))

        # Response text (deterministic, localized)
        response_text = (
            _compose_response_es(vibes_list, used_defaults)
            if str(language).startswith("es")
            else "Done: I generated the itinerary and it’s available in the plan card."
        )

        elapsed_ms = int((perf_counter() - t0) * 1000)
        self.logger.info("fast-plan-completed", city=city, elapsed_ms=elapsed_ms, stops=len(stops))

        updated_params = {**plan_params, "num_people": group_size_int, "budget_per_person": budget_f, "vibes": vibes_list}

        return {
            "response_text": response_text,
            "places": selected_places[:6],
            "plan": plan_json,
            "tool_calls": 4,
            "reasoning_steps": 4,
            "agent_type": "fast_plan",
            "model_used": "deterministic",
            "plan_params": updated_params,
        }


