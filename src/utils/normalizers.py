"""
Data normalizers to ensure consistent data structure across the application.
"""

from typing import Any, Dict, Optional
import re


def snake_to_camel(snake_str: str) -> str:
    """Convert snake_case to camelCase."""
    components = snake_str.split('_')
    return components[0] + ''.join(x.title() for x in components[1:])


def convert_keys_to_camel(data: Any) -> Any:
    """Recursively convert dictionary keys from snake_case to camelCase."""
    if isinstance(data, dict):
        return {snake_to_camel(k): convert_keys_to_camel(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [convert_keys_to_camel(item) for item in data]
    else:
        return data


def _parse_duration_string(duration_str: str) -> int:
    """Convert duration strings like '6h 00m' to minutes."""
    try:
        duration_str = duration_str.lower()
        hours = 0
        minutes = 0
        if "h" in duration_str:
            parts = duration_str.split("h")
            hours = int(parts[0].strip())
            rest = parts[1]
            if "m" in rest:
                rest = rest.replace("m", "").strip()
                if rest:
                    minutes = int(rest)
        elif "m" in duration_str:
            minutes = int(duration_str.replace("m", "").strip())
        return hours * 60 + minutes
    except Exception:
        return 0


def _normalize_new_plan_format(raw_plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize the structured plan produced by generate_plan_json_tool.
    This keeps rich fields (stopsDetailed, summary, execution, vibes, tags).
    """
    plan_id = raw_plan.get("planId") or raw_plan.get("id") or raw_plan.get("_id")

    # Map top-level fields
    name = raw_plan.get("title") or raw_plan.get("name") or "Untitled Plan"
    description = raw_plan.get("description", "")
    category = raw_plan.get("category")
    vibes = raw_plan.get("vibes", [])
    tags = raw_plan.get("tags", [])
    execution = raw_plan.get("execution")
    summary = raw_plan.get("summary")
    final_recommendations = raw_plan.get("finalRecommendations", [])

    # Stops detailed - normalize each stop's structure
    raw_stops = raw_plan.get("stops", [])
    stops_detailed = []
    for stop in raw_stops:
        # Normalize vibes within stop details
        if stop.get("details") and stop["details"].get("vibes"):
            vibes_field = stop["details"]["vibes"]
            if not isinstance(vibes_field, list):
                stop["details"]["vibes"] = [vibes_field] if vibes_field else []
        
        # Normalize target_audience to array
        if stop.get("details") and stop["details"].get("target_audience"):
            target_audience = stop["details"]["target_audience"]
            if not isinstance(target_audience, list):
                stop["details"]["target_audience"] = [target_audience] if target_audience else []
        
        # Convert snake_case keys to camelCase for frontend
        stop_camel = convert_keys_to_camel(stop)
        stops_detailed.append(stop_camel)

    # Derive lightweight stops array for backward compatibility
    stops_simple = []
    for stop in stops_detailed:
        timing = stop.get("timing", {})
        stops_simple.append(
            {
                "place": {  # minimal placeholder; UI mainly uses stopsDetailed
                    "id": stop.get("local_id") or stop.get("name"),
                    "name": stop.get("name"),
                    "address": stop.get("location", {}).get("address"),
                },
                "duration": int(timing.get("suggested_duration_minutes", 60)),
                "startTime": timing.get("recommended_start") or "19:00",
                "activity": stop.get("type_label") or stop.get("category") or "Visit",
            }
        )

    # Compute numeric totals if available
    total_duration_minutes = 0
    if summary and summary.get("total_duration"):
        total_duration_minutes = _parse_duration_string(summary["total_duration"])
    total_distance_km = None
    if summary and summary.get("total_distance_km") is not None:
        total_distance_km = float(summary["total_distance_km"])

    normalized = {
        "id": str(plan_id) if plan_id else None,
        "name": name,
        "description": description,
        "category": category,
        "vibes": vibes if isinstance(vibes, list) else [vibes] if vibes else [],
        "tags": tags,
        "execution": execution,
        "stops": stops_simple,
        "stopsDetailed": stops_detailed,
        "summary": summary,
        "finalRecommendations": final_recommendations,
        # Legacy numeric fields for components that still rely on them
        "totalDuration": total_duration_minutes,
        "totalDistance": total_distance_km,
    }

    return {k: v for k, v in normalized.items() if v is not None}


def _normalize_legacy_plan_format(raw_plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize the legacy plan format (name/description/vibe + stops with place).
    """
    plan_id = raw_plan.get("id") or raw_plan.get("_id")
    stops = raw_plan.get("stops", [])

    normalized_stops = []
    for stop in stops:
        if not stop:
            continue

        place_data = stop.get("place", {})
        if not place_data:
            continue

        normalized_stop = {
            "place": place_data,
            "duration": int(stop.get("duration", 60)),
            "startTime": stop.get("startTime") or stop.get("start_time") or "19:00",
            "activity": stop.get("activity", "Visit"),
        }
        normalized_stops.append(normalized_stop)

    vibe = raw_plan.get("vibe", "casual")
    if isinstance(vibe, list):
        vibe = vibe[0] if vibe else "casual"

    normalized = {
        "id": str(plan_id) if plan_id else None,
        "name": raw_plan.get("name", "Unnamed Plan"),
        "description": raw_plan.get("description", ""),
        "vibe": vibe,
        "totalDuration": int(raw_plan.get("totalDuration") or raw_plan.get("total_duration", 0)),
        "totalDistance": float(raw_plan.get("totalDistance") or raw_plan.get("total_distance", 0)),
        "stops": normalized_stops,
    }

    return {k: v for k, v in normalized.items() if v is not None}


def normalize_plan(raw_plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Normalize plan data to a consistent frontend-friendly format.

    Supports both the new structured plan JSON (generate_plan_json_tool) and the
    legacy simple plan format.
    """
    if not raw_plan:
        return None

    # New format detection: presence of planId and rich stop fields
    if raw_plan.get("planId") or (raw_plan.get("stops") and raw_plan.get("summary")):
        try:
            return _normalize_new_plan_format(raw_plan)
        except Exception:
            # Fallback to legacy if anything goes wrong
            return _normalize_legacy_plan_format(raw_plan)

    # Legacy format fallback
    return _normalize_legacy_plan_format(raw_plan)
