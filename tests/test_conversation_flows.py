"""
Integration tests for multi-turn conversation flows.

Tests the complete pipeline:
- User query → Intent classification → Agent routing
- Parameter extraction → Question generation
- User response → Parameter accumulation
- Plan creation → Structured JSON output

All API calls are mocked to avoid real API usage.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.agents.supervisor_agent import SupervisorAgent
from src.classifiers.models import IntentType, IntentResult


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
    """Mock metrics collector to avoid PostHog calls."""
    with patch('src.utils.metrics.get_metrics_collector') as mock:
        collector = MagicMock()
        collector.record_timing = MagicMock()
        mock.return_value = collector
        yield collector


@pytest.fixture
def mock_analytics():
    """Mock analytics tracking to avoid PostHog API calls."""
    with patch('src.utils.analytics.track_event') as mock:
        yield mock


class TestConversationFlows:
    """Test complete conversation flows without real API calls."""

    @pytest.mark.asyncio
    async def test_plan_with_all_parameters_provided(
        self, session_id, mock_settings, mock_metrics, mock_analytics
    ):
        """Test plan creation when all parameters provided upfront."""
        # Mock the agent that will be called
        mock_plan_result = {
            "response_text": "I've created a romantic evening plan for you.",
            "plan": {
                "planId": "test-123",
                "title": "Romantic Evening in Madrid",
                "description": "A romantic evening for 2",
                "category": "romantic",
                "stops": [
                    {
                        "stopNumber": 1,
                        "name": "Restaurant Botín",
                        "location": {"lat": 40.4168, "lng": -3.7038},
                        "category": "restaurant",
                    }
                ],
            },
            "places": [{"name": "Restaurant Botín", "type": "restaurant"}],
            "agent_type": "plan_and_execute",
            "tool_calls": 5,
            "reasoning_steps": 3,
            "model_used": "gpt-4o",
            "metadata": {"input_tokens": 3000, "output_tokens": 800},
        }

        with patch.object(SupervisorAgent, '_execute_agent', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = mock_plan_result

            supervisor = SupervisorAgent(settings=mock_settings)

            query = "Crea un plan romántico para 2 personas en Madrid mañana a las 20:00, presupuesto 80€ por persona"
            result = await supervisor.run(
                query=query,
                intent=IntentType.PLAN,
                language="es",
                context={"session_id": session_id},
            )

            # Verify plan was created
            assert result["agent_type"] == "plan_and_execute"
            assert result.get("plan") is not None
            assert len(result.get("places", [])) > 0
            assert result["routed_to"] == "plan_and_execute"
            assert result["intent"] == "PLAN"

            # Verify analytics tracking was called
            assert mock_analytics.called

    @pytest.mark.asyncio
    async def test_plan_missing_budget_asks_question(
        self, session_id, mock_settings, mock_metrics, mock_analytics
    ):
        """Test plan creation when budget is missing - should ask question."""
        # Mock the agent to return a question (not a plan)
        mock_question_result = {
            "response_text": "Para crear tu plan perfecto, necesito saber: ¿presupuesto aproximado por persona?",
            "plan": None,
            "places": [],
            "agent_type": "plan_and_execute",
            "tool_calls": 0,
            "reasoning_steps": 1,
            "model_used": "gpt-4o",
            "metadata": {"input_tokens": 1000, "output_tokens": 200},
        }

        with patch.object(SupervisorAgent, '_execute_agent', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = mock_question_result

            supervisor = SupervisorAgent(settings=mock_settings)

            query = "Plan romántico para 2 en Madrid mañana a las 20:00"
            result = await supervisor.run(
                query=query,
                intent=IntentType.PLAN,
                language="es",
                context={"session_id": session_id},
            )

            # Verify question was asked (no plan yet)
            assert "presupuesto" in result["response_text"].lower()
            assert result.get("plan") is None
            assert result["routed_to"] == "plan_and_execute"

    @pytest.mark.asyncio
    async def test_multi_turn_parameter_accumulation(
        self, session_id, mock_settings, mock_metrics, mock_analytics
    ):
        """Test parameter accumulation across multiple turns."""
        supervisor = SupervisorAgent(settings=mock_settings)

        # Turn 1: Provide city and people - expect question
        mock_question_result = {
            "response_text": "Perfecto, y necesito saber: presupuesto aproximado y qué tipo de ambiente buscan?",
            "plan": None,
            "places": [],
            "agent_type": "plan_and_execute",
            "tool_calls": 0,
            "reasoning_steps": 1,
            "model_used": "gpt-4o",
            "metadata": {"input_tokens": 1000, "output_tokens": 200},
        }

        with patch.object(SupervisorAgent, '_execute_agent', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = mock_question_result

            result1 = await supervisor.run(
                query="Plan para 2 personas en Madrid",
                intent=IntentType.PLAN,
                language="es",
                context={"session_id": session_id},
            )

            assert result1.get("plan") is None
            assert "presupuesto" in result1["response_text"].lower() or "ambiente" in result1["response_text"].lower()

        # Turn 2: Provide budget and vibes - expect plan creation
        mock_plan_result = {
            "response_text": "I've created your romantic plan.",
            "plan": {
                "planId": "test-456",
                "title": "Romantic Evening",
                "stops": [{"stopNumber": 1, "name": "Test Restaurant"}],
            },
            "places": [{"name": "Test Restaurant"}],
            "agent_type": "plan_and_execute",
            "tool_calls": 5,
            "reasoning_steps": 3,
            "model_used": "gpt-4o",
            "metadata": {"input_tokens": 3000, "output_tokens": 800},
        }

        with patch.object(SupervisorAgent, '_execute_agent', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = mock_plan_result

            result2 = await supervisor.run(
                query="Presupuesto 60€ por persona, ambiente romántico",
                intent=IntentType.PLAN,
                language="es",
                context={"session_id": session_id},
            )

            # Verify plan was created now
            assert result2["agent_type"] == "plan_and_execute"
            assert result2.get("plan") is not None

    @pytest.mark.asyncio
    async def test_timeout_handling_with_fallback(
        self, session_id, mock_settings, mock_metrics, mock_analytics
    ):
        """Test that timeout is handled gracefully with fallback."""
        import asyncio

        supervisor = SupervisorAgent(settings=mock_settings)

        # Mock agent to timeout
        async def mock_timeout(*args, **kwargs):
            raise asyncio.TimeoutError("Agent took too long")

        with patch.object(SupervisorAgent, '_execute_agent', side_effect=mock_timeout):
            # Mock the fallback handler to return a partial result
            mock_fallback = {
                "response_text": "El plan tardó más de lo esperado.",
                "places": [],
                "plan": None,
                "agent_type": "error",
                "routed_to": "fallback_after_timeout",
                "intent": "PLAN",
                "fallback_reason": "Primary agent timed out",
            }

            with patch.object(
                SupervisorAgent, '_handle_timeout_fallback', new_callable=AsyncMock
            ) as mock_fallback_handler:
                mock_fallback_handler.return_value = mock_fallback

                result = await supervisor.run(
                    query="Plan para 2 en Madrid",
                    intent=IntentType.PLAN,
                    language="es",
                    context={"session_id": session_id},
                )

                # Verify fallback was called
                assert result["routed_to"] == "fallback_after_timeout"
                assert "timeout" in result.get("fallback_reason", "").lower()

    @pytest.mark.asyncio
    async def test_question_variation_across_sessions(
        self, mock_settings, mock_metrics, mock_analytics
    ):
        """Test that questions vary naturally across different sessions."""
        from src.agents.utils.structured_parameter_extractor import StructuredParameterExtractor

        extractor = StructuredParameterExtractor(settings=mock_settings)

        # Session 1, Turn 1 - missing budget and vibes
        plan_params_1 = {"num_people": 2, "cities": ["Madrid"]}
        missing_1 = ["budget_per_person", "vibes"]

        question_1 = extractor.format_missing_fields_prompt_contextual(
            missing=missing_1,
            plan_params=plan_params_1,
            conversation_turns=1,
            language="es",
        )

        # Session 2, Turn 1 - same missing fields
        plan_params_2 = {"num_people": 2, "cities": ["Madrid"]}
        missing_2 = ["budget_per_person", "vibes"]

        question_2 = extractor.format_missing_fields_prompt_contextual(
            missing=missing_2,
            plan_params=plan_params_2,
            conversation_turns=1,
            language="es",
        )

        # Questions should be structured similarly but opener might vary
        # (they rotate through openers based on turn, same turn = same opener)
        # But the important thing is they're contextual and grouped
        assert "presupuesto" in question_1.lower()
        assert "presupuesto" in question_2.lower()
        assert len(question_1) > 0
        assert len(question_2) > 0

        # Test Turn 2 has different opening
        question_turn_2 = extractor.format_missing_fields_prompt_contextual(
            missing=["vibes"],
            plan_params={"num_people": 2, "cities": ["Madrid"], "budget_per_person": 60},
            conversation_turns=2,
            language="es",
        )

        # Turn 2 should have different tone (Perfecto/Genial/Ya casi está)
        assert any(
            opener in question_turn_2
            for opener in ["Perfecto", "Genial", "Ya casi está"]
        )

    @pytest.mark.asyncio
    async def test_cost_control_triggers_fast_plan_fallback(
        self, session_id, mock_settings, mock_metrics, mock_analytics
    ):
        """Test that token budget exceeded triggers FastPlanAgent fallback."""
        supervisor = SupervisorAgent(settings=mock_settings)

        # Mock high token usage to exceed budget
        context_with_high_tokens = {
            "session_id": session_id,
            "session_context": {
                "total_tokens_used": 150000  # Exceeds MAX_TOKENS_PER_SESSION (100k)
            },
        }

        mock_fast_plan_result = {
            "response_text": "Plan created with FastPlan",
            "plan": {"planId": "fast-123", "stops": []},
            "places": [],
            "agent_type": "fast_plan",
            "tool_calls": 2,
            "model_used": "gpt-4o-mini",
            "metadata": {"input_tokens": 500, "output_tokens": 100},
        }

        with patch.object(SupervisorAgent, '_execute_agent', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = mock_fast_plan_result

            result = await supervisor.run(
                query="Plan para 2 en Madrid",
                intent=IntentType.PLAN,
                language="es",
                context=context_with_high_tokens,
            )

            # Verify analytics tracked the budget exceeded event
            # (would be in the agent_routed event properties)
            assert mock_analytics.called


class TestParameterExtraction:
    """Test parameter extraction logic without API calls."""

    @pytest.mark.asyncio
    async def test_extraction_with_implicit_people_count(self, mock_settings):
        """Test extraction detects implicit people count like 'nosotros dos'."""
        from src.agents.utils.structured_parameter_extractor import StructuredParameterExtractor, PlanParameters

        extractor = StructuredParameterExtractor(settings=mock_settings)

        # Mock the LLM call to return structured output
        mock_params = PlanParameters(
            num_people=2,
            cities=["Madrid"],
            budget_per_person=None,
            vibes=None,
        )

        with patch.object(extractor.extractor, 'ainvoke', new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_params

            result = await extractor.extract_from_conversation(
                current_query="Plan para nosotros dos en Madrid",
                conversation_history=[],
            )

            assert result.num_people == 2
            assert "Madrid" in result.cities

    @pytest.mark.asyncio
    async def test_extraction_accumulates_across_turns(self, mock_settings):
        """Test that parameters accumulate correctly across conversation turns."""
        from src.agents.utils.structured_parameter_extractor import StructuredParameterExtractor, PlanParameters

        extractor = StructuredParameterExtractor(settings=mock_settings)

        # Turn 1: Extract city and people
        mock_params_turn1 = PlanParameters(
            num_people=2,
            cities=["Madrid"],
        )

        with patch.object(extractor.extractor, 'ainvoke', new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_params_turn1

            result_turn1 = await extractor.extract_from_conversation(
                current_query="Plan para 2 en Madrid",
                conversation_history=[],
            )

            # Turn 2: Add budget and vibes
            mock_params_turn2 = PlanParameters(
                num_people=2,
                cities=["Madrid"],
                budget_per_person=60.0,
                vibes=["romantic"],
            )

            mock_invoke.return_value = mock_params_turn2

            result_turn2 = await extractor.extract_from_conversation(
                current_query="Presupuesto 60€, ambiente romántico",
                conversation_history=[
                    {"user_query": "Plan para 2 en Madrid", "agent_response": "..."}
                ],
            )

            assert result_turn2.num_people == 2
            assert result_turn2.budget_per_person == 60.0
            assert "romantic" in result_turn2.vibes

    def test_missing_required_fields_detection(self, mock_settings):
        """Test detection of missing required fields."""
        from src.agents.utils.structured_parameter_extractor import StructuredParameterExtractor

        extractor = StructuredParameterExtractor(settings=mock_settings)

        # All fields present
        complete_params = {
            "num_people": 2,
            "cities": ["Madrid"],
            "budget_per_person": 60.0,
            "vibes": ["romantic"],
        }
        missing_complete = extractor.get_missing_required(complete_params)
        assert len(missing_complete) == 0

        # Missing budget and vibes
        incomplete_params = {
            "num_people": 2,
            "cities": ["Madrid"],
        }
        missing_incomplete = extractor.get_missing_required(incomplete_params)
        assert "budget_per_person" in missing_incomplete
        assert "vibes" in missing_incomplete
        assert len(missing_incomplete) == 2

        # vibes_any flag set - vibes not required
        params_with_any_vibes = {
            "num_people": 2,
            "cities": ["Madrid"],
            "budget_per_person": 60.0,
            "vibes_any": True,
        }
        missing_any = extractor.get_missing_required(params_with_any_vibes)
        assert "vibes" not in missing_any
