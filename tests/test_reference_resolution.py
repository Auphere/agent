"""
Tests for ordinal reference resolution ("el segundo", "quinta opción", etc.).

These cases are critical to avoid re-searching and to fetch details for a previously
recommended place deterministically via `places_get_place_tool`.
"""

from src.agents.specialized.base_agent import _extract_reference_position, _resolve_place_id_from_previous_places


def test_extract_reference_position_spanish_ordinals():
    assert _extract_reference_position("Dame más info del segundo") == 2
    assert _extract_reference_position("Dame más info de la quinta opción que me diste") == 5


def test_extract_reference_position_english_ordinals():
    assert _extract_reference_position("Tell me more about the second one") == 2
    assert _extract_reference_position("More info about the fifth option") == 5


def test_resolve_place_id_prefers_most_recent_turn_and_position():
    previous_places = [
        {"_turn_number": 1, "_position_in_turn": 1, "place_id": "g-1a", "name": "A"},
        {"_turn_number": 1, "_position_in_turn": 2, "place_id": "g-1b", "name": "B"},
        {"_turn_number": 2, "_position_in_turn": 1, "place_id": "g-2a", "name": "C"},
        {"_turn_number": 2, "_position_in_turn": 2, "place_id": "g-2b", "name": "D"},
    ]

    assert _resolve_place_id_from_previous_places(previous_places, position=2) == "g-2b"


def test_resolve_place_id_fallbacks_to_order_when_position_missing():
    # Simulates cases where `_position_in_turn` was not injected but the list order
    # matches what the user saw in the UI for the most recent turn.
    previous_places = [
        {"_turn_number": 2, "place_id": "g-2a", "name": "C"},
        {"_turn_number": 2, "place_id": "g-2b", "name": "D"},
        {"_turn_number": 2, "place_id": "g-2c", "name": "E"},
        {"_turn_number": 2, "place_id": "g-2d", "name": "F"},
        {"_turn_number": 2, "place_id": "g-2e", "name": "G"},
    ]

    assert _resolve_place_id_from_previous_places(previous_places, position=5) == "g-2e"


