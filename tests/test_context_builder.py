"""
Tests for new memory system (ConversationBuffer and ContextBuilder).
"""

import pytest
from datetime import datetime
from uuid import uuid4

from src.agents.conversation_buffer import ConversationContext, ConversationBuffer
from src.agents.context_builder import ContextBuilder, PlanContextExtractor
from src.database.models import ConversationTurn


class TestPlanContextExtractor:
    """Test plan parameter extraction from queries."""

    def test_extract_num_people(self):
        query = "Quiero un plan para 2 personas"
        extracted = PlanContextExtractor.extract_from_query(query, "es")
        assert extracted.get("num_people") == 2

    def test_extract_city(self):
        query = "Busco lugares en Zaragoza"
        extracted = PlanContextExtractor.extract_from_query(query, "es")
        assert extracted.get("cities") == ["Zaragoza"]

    def test_extract_duration(self):
        query = "Plan para la tarde"
        extracted = PlanContextExtractor.extract_from_query(query, "es")
        assert extracted.get("duration") == "afternoon"

    def test_extract_place_types(self):
        query = "Quiero visitar bares y restaurantes"
        extracted = PlanContextExtractor.extract_from_query(query, "es")
        place_types = extracted.get("place_types", [])
        assert "bars" in place_types
        assert "restaurants" in place_types

    def test_extract_vibe(self):
        query = "Busco algo romántico para una cita"
        extracted = PlanContextExtractor.extract_from_query(query, "es")
        assert extracted.get("vibe") == "romantic"

    def test_extract_multiple_fields(self):
        query = "Plan romántico para 2 personas en Zaragoza con bares"
        extracted = PlanContextExtractor.extract_from_query(query, "es")
        assert extracted.get("num_people") == 2
        assert extracted.get("cities") == ["Zaragoza"]
        assert "bars" in extracted.get("place_types", [])
        assert extracted.get("vibe") == "romantic"

    def test_merge_plan_state(self):
        existing = {"duration": "2 hours", "vibe": "romantic"}
        new = {"num_people": 2, "cities": ["Zaragoza"]}
        merged = PlanContextExtractor.merge_plan_state(existing, new)
        assert merged["duration"] == "2 hours"
        assert merged["vibe"] == "romantic"
        assert merged["num_people"] == 2
        assert merged["cities"] == ["Zaragoza"]

    def test_merge_list_fields(self):
        existing = {"place_types": ["bars"]}
        new = {"place_types": ["restaurants", "bars"]}
        merged = PlanContextExtractor.merge_plan_state(existing, new)
        place_types = merged["place_types"]
        assert "bars" in place_types
        assert "restaurants" in place_types
        # Should deduplicate
        assert place_types.count("bars") == 1

    def test_is_plan_ready_complete(self):
        plan_state = {
            "duration": "2 hours",
            "num_people": 2,
            "cities": ["Zaragoza"],
            "place_types": ["bars"],
            "vibe": "romantic",
        }
        is_ready, missing = PlanContextExtractor.is_plan_ready(plan_state)
        assert is_ready is True
        assert len(missing) == 0

    def test_is_plan_ready_incomplete(self):
        plan_state = {
            "duration": "2 hours",
            "num_people": 2,
            # Missing: cities, place_types, vibe
        }
        is_ready, missing = PlanContextExtractor.is_plan_ready(plan_state)
        assert is_ready is False
        assert "cities" in missing
        assert "place_types" in missing
        assert "vibe" in missing

    def test_format_missing_fields_prompt(self):
        missing = ["duration", "num_people"]
        prompt = PlanContextExtractor.format_missing_fields_prompt(missing, "es")
        assert "duración del plan" in prompt
        assert "número de personas" in prompt


class TestConversationContext:
    """Test ConversationContext dataclass."""

    def test_to_dict(self):
        context = ConversationContext(
            current_query="Test query",
            current_language="es",
            session_id=uuid4(),
            user_id=uuid4(),
        )
        data = context.to_dict()
        assert data["current_query"] == "Test query"
        assert data["current_language"] == "es"
        assert "session_id" in data
        assert "user_id" in data

    def test_default_values(self):
        context = ConversationContext(
            current_query="Test",
        )
        assert context.recent_turns == []
        assert context.recent_messages == []
        assert context.previous_places == []
        assert context.session_summary is None
        assert context.total_turns_in_session == 0


class TestContextBuilder:
    """Test ContextBuilder functionality."""

    def setup_method(self):
        self.builder = ContextBuilder()

    def test_build_messages_empty_context(self):
        context = ConversationContext(current_query="Hola")
        messages = self.builder.build_messages(
            context=context,
            system_prompt="Eres un asistente"
        )
        # Should have: SystemMessage + HumanMessage
        assert len(messages) >= 2
        assert messages[0].type == "system"
        assert messages[-1].type == "human"
        assert messages[-1].content == "Hola"

    def test_build_agent_context_dict(self):
        context = ConversationContext(
            current_query="Test query",
            current_language="es",
            session_id=uuid4(),
            user_id=uuid4(),
        )
        agent_context = self.builder.build_agent_context_dict(context)
        assert "user_id" in agent_context
        assert "session_id" in agent_context
        assert "current_query" in agent_context
        assert agent_context["current_query"] == "Test query"
        assert "history_messages" in agent_context
        assert "estimated_tokens" in agent_context

    def test_extract_plan_state_empty(self):
        context = ConversationContext(current_query="Test")
        plan_state = self.builder.extract_plan_state(context)
        assert plan_state["is_complete"] is False
        assert len(plan_state["missing_fields"]) == 5  # All required fields

    def test_format_place_references(self):
        places = [
            {"name": "Bar 1", "_turn_number": 1, "_position": 1, "rating": 4.5},
            {"name": "Bar 2", "_turn_number": 1, "_position": 2, "rating": 4.0},
        ]
        formatted = self.builder._format_place_references(places)
        assert "Bar 1" in formatted
        assert "Bar 2" in formatted
        assert "4.5" in formatted


class TestMemoryTokenManagement:
    """Test token estimation and management."""

    def test_estimate_tokens(self):
        builder = ContextBuilder()
        text = "Hello world! This is a test."
        tokens = builder._estimate_tokens(text)
        # Rough estimate: ~7 tokens (1 token ≈ 4 chars)
        assert tokens > 0
        assert tokens < len(text)  # Should be less than char count

    def test_context_within_budget(self):
        context = ConversationContext(
            current_query="Short query",
            estimated_tokens=500,
        )
        builder = ContextBuilder(max_context_tokens=4000)
        agent_context = builder.build_agent_context_dict(context)
        # Should be within budget
        assert agent_context["estimated_tokens"] == 500
        assert agent_context["tokens_remaining"] == 3500


# Note: Full integration tests with database would go in a separate test file
# that uses fixtures for DB setup
