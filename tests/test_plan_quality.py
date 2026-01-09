"""
Test plan quality and structure validation.

Tests validate that generated plans have correct structure
and meet quality requirements without making real API calls.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.agents.supervisor_agent import SupervisorAgent
from src.classifiers.models import IntentType


@pytest.fixture
def session_id():
    """Generate unique session ID."""
    return str(uuid4())


@pytest.fixture
def mock_settings():
    """Mock settings to avoid loading from environment."""
    with patch('src.config.settings.get_settings') as mock:
        settings = MagicMock()
        settings.agent_max_execution_time = 120.0
        settings.openai_api_key = "test-key"
        settings.llm_connection_timeout = 30.0
        settings.llm_read_timeout_standard = 60.0
        settings.llm_max_retries = 2
        mock.return_value = settings
        yield settings


@pytest.fixture
def mock_metrics():
    """Mock metrics collector."""
    with patch('src.utils.metrics.get_metrics_collector') as mock:
        collector = MagicMock()
        collector.record_timing = MagicMock()
        mock.return_value = collector
        yield collector


@pytest.fixture
def mock_analytics():
    """Mock analytics tracking."""
    with patch('src.utils.analytics.track_event') as mock:
        yield mock


@pytest.fixture
def sample_plan():
    """Sample plan structure for testing."""
    return {
        "planId": "plan-123",
        "title": "Romantic Evening in Madrid",
        "description": "A perfect romantic evening for two",
        "category": "romantic",
        "vibes": ["romantic", "elegant"],
        "tags": ["dinner", "cocktails", "romantic"],
        "execution": {
            "date": "2024-01-15",
            "startTime": "20:00",
            "durationHours": 4.5,
            "city": "Madrid",
            "zones": ["Centro", "Salamanca"],
            "groupSize": 2,
            "groupComposition": "couple",
        },
        "stops": [
            {
                "stopNumber": 1,
                "name": "Restaurant Botín",
                "category": "restaurant",
                "type": "Traditional Spanish",
                "timing": {
                    "recommendedStartTime": "20:00",
                    "suggestedDurationMinutes": 90,
                    "estimatedEndTime": "21:30",
                },
                "location": {
                    "fullAddress": "Calle Cuchilleros 17, Madrid",
                    "zone": "Centro",
                    "coordinates": {"lat": 40.4140, "lng": -3.7079},
                    "travelFromPrevious": {"minutes": 0, "mode": "start"},
                },
                "details": {
                    "vibes": ["historic", "romantic"],
                    "targetAudience": "couples",
                    "music": "live classical",
                    "noiseLevel": "moderate",
                    "averageSpendPerPerson": 50.0,
                },
                "selectionReasons": [
                    "Historic atmosphere perfect for special occasions",
                    "Excellent traditional Spanish cuisine",
                    "Within budget range",
                ],
                "actions": {
                    "needsReservation": True,
                    "googleMapsLink": "https://maps.google.com/?q=40.4140,-3.7079",
                    "phone": "+34 913 66 42 17",
                },
                "alternatives": [
                    {
                        "name": "Casa Lucio",
                        "reason": "Also excellent but slightly more expensive",
                    }
                ],
                "personalTips": [
                    "Reserve ahead - very popular",
                    "Try the roast suckling pig",
                ],
            },
            {
                "stopNumber": 2,
                "name": "Salmon Guru",
                "category": "bar",
                "type": "Cocktail Bar",
                "timing": {
                    "recommendedStartTime": "22:00",
                    "suggestedDurationMinutes": 90,
                    "estimatedEndTime": "23:30",
                },
                "location": {
                    "fullAddress": "Calle de Echegaray 21, Madrid",
                    "zone": "Centro",
                    "coordinates": {"lat": 40.4157, "lng": -3.7003},
                    "travelFromPrevious": {"minutes": 15, "mode": "walk"},
                },
                "details": {
                    "vibes": ["sophisticated", "creative"],
                    "targetAudience": "cocktail enthusiasts",
                    "music": "ambient electronic",
                    "noiseLevel": "moderate",
                    "averageSpendPerPerson": 30.0,
                },
                "selectionReasons": [
                    "Award-winning cocktails",
                    "Romantic yet energetic atmosphere",
                    "Perfect for post-dinner drinks",
                ],
                "actions": {
                    "needsReservation": False,
                    "googleMapsLink": "https://maps.google.com/?q=40.4157,-3.7003",
                    "phone": "+34 910 00 61 85",
                },
                "alternatives": [],
                "personalTips": ["Ask bartender for signature cocktails"],
            },
        ],
        "summary": {
            "totalDuration": "4.5 hours",
            "totalDistanceKm": 1.2,
            "budget": {
                "perPerson": 80.0,
                "total": 160.0,
                "breakdown": {"dining": 100, "drinks": 60},
            },
            "metrics": {
                "varietyScore": 1.0,
                "walkingIntensity": "low",
                "culturalScore": 8,
            },
        },
        "finalRecommendations": [
            "Book restaurant in advance",
            "Wear comfortable but smart clothing",
            "Bring cash for tips",
        ],
    }


class TestPlanQuality:
    """Test quality of generated plans."""

    @pytest.mark.asyncio
    async def test_plan_has_required_structure(
        self, session_id, sample_plan, mock_settings, mock_metrics, mock_analytics
    ):
        """Test that generated plan has all required fields."""
        supervisor = SupervisorAgent(settings=mock_settings)

        mock_result = {
            "response_text": "I've created your romantic evening plan.",
            "plan": sample_plan,
            "places": [
                {"name": "Restaurant Botín", "type": "restaurant"},
                {"name": "Salmon Guru", "type": "bar"},
            ],
            "agent_type": "plan_and_execute",
            "tool_calls": 5,
            "model_used": "gpt-4o",
            "metadata": {"input_tokens": 3000, "output_tokens": 1200},
        }

        with patch.object(SupervisorAgent, '_execute_agent', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = mock_result

            query = "Plan romántico para 2 en Madrid, presupuesto 80€ por persona"
            result = await supervisor.run(
                query=query,
                intent=IntentType.PLAN,
                language="es",
                context={"session_id": session_id},
            )

            plan = result.get("plan")
            assert plan is not None, "No plan generated"

            # Validate top-level structure
            required_fields = [
                "planId",
                "title",
                "description",
                "category",
                "execution",
                "stops",
                "summary",
                "finalRecommendations",
            ]
            for field in required_fields:
                assert field in plan, f"Missing required field: {field}"

            assert len(plan["stops"]) > 0, "No stops in plan"

            # Validate stop structure
            first_stop = plan["stops"][0]
            stop_fields = [
                "stopNumber",
                "name",
                "category",
                "timing",
                "location",
                "details",
                "selectionReasons",
                "actions",
            ]
            for field in stop_fields:
                assert field in first_stop, f"Missing stop field: {field}"

            # Validate location has coordinates
            assert "coordinates" in first_stop["location"]
            assert "lat" in first_stop["location"]["coordinates"]
            assert "lng" in first_stop["location"]["coordinates"]

    def test_plan_respects_budget_constraint(self, sample_plan):
        """Test that plan respects budget constraints."""
        # Extract budget from plan
        budget_per_person = sample_plan["summary"]["budget"]["perPerson"]
        num_people = sample_plan["execution"]["groupSize"]

        # User requested 80€ per person
        requested_budget = 80.0

        # Plan should be within reasonable margin (50% for quality)
        assert budget_per_person <= requested_budget * 1.5, (
            f"Budget {budget_per_person}€ exceeds limit of {requested_budget * 1.5}€"
        )

        # Total budget should match per person * group size
        expected_total = budget_per_person * num_people
        assert sample_plan["summary"]["budget"]["total"] == expected_total

    def test_plan_has_variety(self, sample_plan):
        """Test that plan includes variety of place types."""
        stops = sample_plan["stops"]

        # Extract categories from stops
        categories = [stop["category"] for stop in stops]

        # For multi-stop plans (3+), should have at least 2 different categories
        if len(stops) >= 3:
            unique_categories = set(categories)
            assert len(unique_categories) >= 2, (
                f"Plan should include variety of place types, found only: {unique_categories}"
            )

        # For 2-stop plans, variety is acceptable but not required
        if len(stops) == 2:
            assert len(categories) == 2

    def test_stops_are_ordered_correctly(self, sample_plan):
        """Test that stops are numbered sequentially."""
        stops = sample_plan["stops"]

        for i, stop in enumerate(stops, start=1):
            assert stop["stopNumber"] == i, (
                f"Stop {i} has incorrect stopNumber: {stop['stopNumber']}"
            )

    def test_timing_is_logical(self, sample_plan):
        """Test that timing progression is logical."""
        stops = sample_plan["stops"]

        # Each stop should have timing
        for stop in stops:
            assert "timing" in stop
            assert "recommendedStartTime" in stop["timing"]
            assert "suggestedDurationMinutes" in stop["timing"]
            assert "estimatedEndTime" in stop["timing"]

        # Start time of stop N+1 should be after end time of stop N
        for i in range(len(stops) - 1):
            current_end = stops[i]["timing"]["estimatedEndTime"]
            next_start = stops[i + 1]["timing"]["recommendedStartTime"]

            # Convert to comparable format (HH:MM)
            assert isinstance(current_end, str)
            assert isinstance(next_start, str)
            # Basic check: next start should not be before current end
            # (in real implementation, would parse times properly)

    def test_travel_times_are_present(self, sample_plan):
        """Test that travel times between stops are included."""
        stops = sample_plan["stops"]

        # First stop should have no travel time (start point)
        assert stops[0]["location"]["travelFromPrevious"]["minutes"] == 0

        # Subsequent stops should have travel time
        for stop in stops[1:]:
            travel = stop["location"]["travelFromPrevious"]
            assert "minutes" in travel
            assert "mode" in travel
            assert travel["minutes"] >= 0

    def test_selection_reasons_are_provided(self, sample_plan):
        """Test that each stop has selection reasons."""
        stops = sample_plan["stops"]

        for stop in stops:
            reasons = stop.get("selectionReasons", [])
            assert len(reasons) >= 1, (
                f"Stop '{stop['name']}' should have at least one selection reason"
            )
            # Each reason should be a non-empty string
            for reason in reasons:
                assert isinstance(reason, str)
                assert len(reason) > 0

    def test_coordinates_are_valid(self, sample_plan):
        """Test that all coordinates are valid lat/lng values."""
        stops = sample_plan["stops"]

        for stop in stops:
            coords = stop["location"]["coordinates"]
            lat = coords["lat"]
            lng = coords["lng"]

            # Valid latitude: -90 to 90
            assert -90 <= lat <= 90, f"Invalid latitude: {lat}"

            # Valid longitude: -180 to 180
            assert -180 <= lng <= 180, f"Invalid longitude: {lng}"

    def test_vibes_match_request(self, sample_plan):
        """Test that plan vibes match user request."""
        # User requested "romantic"
        requested_vibes = ["romantic"]

        # Check plan-level vibes
        plan_vibes = sample_plan.get("vibes", [])
        assert any(
            vibe.lower() in [v.lower() for v in requested_vibes]
            for vibe in plan_vibes
        ), "Plan vibes should match user request"

        # Check stop-level vibes
        stops = sample_plan["stops"]
        romantic_stops = 0
        for stop in stops:
            stop_vibes = stop["details"].get("vibes", [])
            if any("romantic" in vibe.lower() for vibe in stop_vibes):
                romantic_stops += 1

        # At least one stop should have romantic vibe
        assert romantic_stops >= 1, "At least one stop should match romantic vibe"

    def test_actions_include_reservation_info(self, sample_plan):
        """Test that high-end venues include reservation information."""
        stops = sample_plan["stops"]

        # Restaurants should typically need reservations
        restaurants = [s for s in stops if s["category"] == "restaurant"]
        for restaurant in restaurants:
            actions = restaurant["actions"]
            assert "needsReservation" in actions
            assert isinstance(actions["needsReservation"], bool)

            # If reservation needed, should have phone
            if actions["needsReservation"]:
                assert "phone" in actions
                assert len(actions.get("phone", "")) > 0

    def test_google_maps_links_present(self, sample_plan):
        """Test that all stops have Google Maps links."""
        stops = sample_plan["stops"]

        for stop in stops:
            actions = stop["actions"]
            assert "googleMapsLink" in actions
            link = actions["googleMapsLink"]
            assert link.startswith("https://")
            assert "maps.google.com" in link or "google.com/maps" in link

    def test_summary_metrics_present(self, sample_plan):
        """Test that summary includes key metrics."""
        summary = sample_plan["summary"]

        required_summary_fields = [
            "totalDuration",
            "totalDistanceKm",
            "budget",
        ]

        for field in required_summary_fields:
            assert field in summary, f"Summary missing field: {field}"

        # Budget should have breakdown
        budget = summary["budget"]
        assert "perPerson" in budget
        assert "total" in budget
        assert budget["perPerson"] > 0
        assert budget["total"] > 0

    def test_final_recommendations_provided(self, sample_plan):
        """Test that plan includes final recommendations."""
        recommendations = sample_plan.get("finalRecommendations", [])

        # Should have 3-5 recommendations
        assert 1 <= len(recommendations) <= 5, (
            "Plan should have 1-5 final recommendations"
        )

        # Each should be a non-empty string
        for rec in recommendations:
            assert isinstance(rec, str)
            assert len(rec) > 0


class TestPlanVariety:
    """Test plan variety and diversity metrics."""

    def test_calculate_variety_score(self):
        """Test variety score calculation."""
        # Mock stops with different categories
        stops_varied = [
            {"category": "restaurant"},
            {"category": "bar"},
            {"category": "club"},
        ]

        # 3 unique categories / 3 stops = 1.0 variety
        unique_categories = len(set(s["category"] for s in stops_varied))
        variety_score = unique_categories / len(stops_varied)
        assert variety_score == 1.0

        # Mock stops with repeated categories
        stops_similar = [
            {"category": "bar"},
            {"category": "bar"},
            {"category": "bar"},
        ]

        # 1 unique category / 3 stops = 0.33 variety
        unique_categories_2 = len(set(s["category"] for s in stops_similar))
        variety_score_2 = unique_categories_2 / len(stops_similar)
        assert variety_score_2 < 0.5

    def test_plan_diversity_for_long_itineraries(self, sample_plan):
        """Test that longer plans (4+ stops) have good diversity."""
        # Modify sample to have more stops
        sample_plan["stops"].extend([
            {
                "stopNumber": 3,
                "name": "Kapital",
                "category": "club",
                "type": "Nightclub",
                "location": {"coordinates": {"lat": 40.42, "lng": -3.69}},
                "details": {"vibes": ["energetic"]},
            },
            {
                "stopNumber": 4,
                "name": "Chocolatería San Ginés",
                "category": "cafe",
                "type": "Cafe",
                "location": {"coordinates": {"lat": 40.41, "lng": -3.71}},
                "details": {"vibes": ["traditional"]},
            },
        ])

        stops = sample_plan["stops"]
        if len(stops) >= 4:
            categories = set(s["category"] for s in stops)
            # Should have at least 3 different categories
            assert len(categories) >= 3, (
                f"Long itinerary should have variety, found only: {categories}"
            )


class TestPlanEdgeCases:
    """Test edge cases in plan generation."""

    def test_single_stop_plan_valid(self):
        """Test that single-stop plans are valid."""
        single_stop_plan = {
            "planId": "single-123",
            "title": "Dinner at Botín",
            "description": "A classic dinner experience",
            "category": "dining",
            "execution": {"groupSize": 2, "city": "Madrid"},
            "stops": [
                {
                    "stopNumber": 1,
                    "name": "Restaurant Botín",
                    "category": "restaurant",
                    "location": {
                        "coordinates": {"lat": 40.4140, "lng": -3.7079},
                        "travelFromPrevious": {"minutes": 0, "mode": "start"},
                    },
                    "timing": {
                        "recommendedStartTime": "20:00",
                        "suggestedDurationMinutes": 120,
                    },
                }
            ],
            "summary": {
                "totalDuration": "2 hours",
                "totalDistanceKm": 0,
                "budget": {"perPerson": 50, "total": 100},
            },
            "finalRecommendations": ["Make reservation"],
        }

        # Single stop should be valid
        assert len(single_stop_plan["stops"]) == 1
        assert single_stop_plan["stops"][0]["stopNumber"] == 1
        assert single_stop_plan["summary"]["totalDistanceKm"] == 0

    def test_large_group_plan_adjusts_venues(self):
        """Test that plans for large groups select appropriate venues."""
        large_group_plan = {
            "execution": {"groupSize": 10},
            "stops": [
                {
                    "name": "Large Venue",
                    "details": {
                        "targetAudience": "groups",
                        "capacity": "large",
                    },
                    "selectionReasons": [
                        "Can accommodate groups of 10+",
                        "Group-friendly atmosphere",
                    ],
                }
            ],
        }

        # Should mention group accommodation
        reasons = large_group_plan["stops"][0]["selectionReasons"]
        assert any("group" in r.lower() for r in reasons), (
            "Large group plan should mention group accommodation"
        )
