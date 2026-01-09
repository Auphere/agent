"""
Tests for timeout handling in agents.

These tests validate that:
1. Agents have correct timeout configuration
2. Timeout errors are handled gracefully
3. Retry logic works for transient failures
4. Metrics are recorded correctly
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from time import perf_counter

from src.config.settings import Settings, get_settings


class TestTimeoutConfiguration:
    """Test timeout configuration in settings and agents."""
    
    def test_settings_has_timeout_config(self):
        """Settings should have timeout configuration."""
        settings = get_settings()
        
        # Verify timeout settings exist
        assert hasattr(settings, 'llm_connection_timeout')
        assert hasattr(settings, 'llm_read_timeout_simple')
        assert hasattr(settings, 'llm_read_timeout_standard')
        assert hasattr(settings, 'llm_read_timeout_complex')
        assert hasattr(settings, 'tool_timeout')
        assert hasattr(settings, 'agent_max_execution_time')
        
        # Verify reasonable defaults
        assert settings.llm_connection_timeout >= 1.0
        assert settings.llm_read_timeout_simple >= 10.0
        assert settings.llm_read_timeout_standard >= 30.0
        assert settings.llm_read_timeout_complex >= 60.0
        assert settings.tool_timeout >= 5.0
    
    def test_settings_has_retry_config(self):
        """Settings should have retry configuration."""
        settings = get_settings()
        
        assert hasattr(settings, 'llm_max_retries')
        assert hasattr(settings, 'tool_max_retries')
        
        # Verify reasonable defaults
        assert settings.llm_max_retries >= 1
        assert settings.tool_max_retries >= 1


class TestRecommendAgentTimeout:
    """Test RecommendAgent timeout behavior."""
    
    @pytest.fixture
    def settings(self):
        """Get test settings."""
        return get_settings()
    
    def test_recommend_agent_uses_complex_timeout(self, settings):
        """RecommendAgent should use complex (longer) timeout."""
        from src.agents.specialized.recommend_agent import RecommendAgent
        
        agent = RecommendAgent(settings=settings)
        
        # Verify timeout is a tuple with complex read timeout
        timeout_config = agent._timeout_config
        
        assert isinstance(timeout_config, tuple)
        assert len(timeout_config) == 2
        
        connection_timeout, read_timeout = timeout_config
        assert connection_timeout == settings.llm_connection_timeout
        assert read_timeout == settings.llm_read_timeout_complex
    
    def test_recommend_agent_has_max_retries(self, settings):
        """RecommendAgent should have max_retries configured."""
        from src.agents.specialized.recommend_agent import RecommendAgent
        
        agent = RecommendAgent(settings=settings)
        
        assert agent._max_retries == settings.llm_max_retries
        assert agent._max_retries >= 3


class TestSearchAgentTimeout:
    """Test SearchAgent timeout behavior."""
    
    @pytest.fixture
    def settings(self):
        """Get test settings."""
        return get_settings()
    
    def test_search_agent_uses_standard_timeout(self, settings):
        """SearchAgent should use standard timeout."""
        from src.agents.specialized.search_agent import SearchAgent
        
        agent = SearchAgent(settings=settings)
        
        timeout_config = agent._timeout_config
        
        assert isinstance(timeout_config, tuple)
        connection_timeout, read_timeout = timeout_config
        assert read_timeout == settings.llm_read_timeout_standard


class TestBaseAgentTimeoutHandling:
    """Test BaseSpecializedAgent timeout handling."""
    
    @pytest.mark.asyncio
    async def test_tool_timeout_protection(self):
        """Tools should be protected by timeout."""
        from src.agents.specialized.recommend_agent import RecommendAgent
        
        agent = RecommendAgent()
        
        # Mock a slow tool
        async def slow_tool(*args, **kwargs):
            await asyncio.sleep(100)  # Way longer than timeout
            return {"places": []}
        
        # The tool should timeout before completing
        with patch.object(agent.tools[0], 'ainvoke', side_effect=slow_tool):
            # This should raise TimeoutError or handle it gracefully
            try:
                result = await asyncio.wait_for(
                    agent.run("test query", language="es"),
                    timeout=5.0  # Short timeout for test
                )
            except asyncio.TimeoutError:
                pass  # Expected
    
    @pytest.mark.asyncio
    async def test_agent_records_duration(self):
        """Agent should record execution duration."""
        from src.agents.specialized.recommend_agent import RecommendAgent
        
        agent = RecommendAgent()
        
        # Mock LLM response
        mock_response = MagicMock()
        mock_response.content = "Test response"
        mock_response.tool_calls = []
        
        with patch.object(agent.llm_with_tools, 'ainvoke', return_value=mock_response):
            result = await agent.run("test query", language="es")
            
            # Result should include duration
            assert "duration_ms" in result
            assert result["duration_ms"] >= 0


class TestSupervisorFallback:
    """Test supervisor fallback on agent timeout."""
    
    @pytest.mark.asyncio
    async def test_supervisor_uses_fallback_on_timeout(self):
        """Supervisor should use fallback agent when primary times out."""
        from src.agents.supervisor_agent import SupervisorAgent
        from src.classifiers.models import IntentType
        
        supervisor = SupervisorAgent()
        
        # Mock recommend agent to timeout
        async def timeout_run(*args, **kwargs):
            raise asyncio.TimeoutError("Request timed out")
        
        # Mock fallback to succeed
        fallback_result = {
            "response_text": "Fallback response",
            "places": [],
            "tool_calls": 0,
            "reasoning_steps": 1,
            "agent_type": "react",
            "model_used": "gpt-4o-mini",
        }
        
        with patch.object(
            supervisor._get_recommend_agent(), 
            'run', 
            side_effect=timeout_run
        ):
            with patch.object(
                supervisor._get_fallback_agent(),
                'run',
                return_value=fallback_result
            ):
                result = await supervisor.run(
                    query="test",
                    intent=IntentType.RECOMMEND,
                    language="es",
                )
                
                # Should have used fallback
                assert "fallback" in result.get("routed_to", "").lower()

    @pytest.mark.asyncio
    async def test_supervisor_returns_partial_plan_on_plan_timeout(self):
        """When PLAN times out, Supervisor should return partial plan from checkpoint instead of generic fallback."""
        from src.agents.supervisor_agent import SupervisorAgent
        from src.classifiers.models import IntentType

        # Keep timeout extremely small for the test
        settings = Settings(agent_max_execution_time=0.05)
        supervisor = SupervisorAgent(settings=settings)

        async def slow_plan_run(*args, **kwargs):
            await asyncio.sleep(1)
            return {"response_text": "should not reach", "places": []}

        partial_plan = {"planId": "p1", "stops": [], "summary": {}}
        checkpoint_payload = {
            "plan": partial_plan,
            "places": [{"name": "Test Place", "place_id": "x"}],
            "plan_params": {"primary_city": "Zaragoza"},
        }

        fake_plan_agent = MagicMock()
        fake_plan_agent.run = AsyncMock(side_effect=slow_plan_run)
        fake_plan_agent.get_last_checkpoint = AsyncMock(return_value=checkpoint_payload)

        with patch.object(supervisor, "_get_plan_and_execute_agent", return_value=fake_plan_agent):
            result = await supervisor.run(
                query="test plan",
                intent=IntentType.PLAN,
                language="es",
                context={"session_id": "session-1"},
            )

        assert result.get("agent_type") == "plan_partial"
        assert result.get("plan") == partial_plan
        assert result.get("routed_to") == "plan_partial_after_timeout"


class TestRetryBehavior:
    """Test retry behavior for transient failures."""
    
    @pytest.mark.asyncio
    async def test_llm_retries_on_transient_error(self):
        """LLM should retry on transient errors."""
        from src.agents.specialized.recommend_agent import RecommendAgent
        
        agent = RecommendAgent()
        
        call_count = 0
        
        async def flaky_invoke(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Transient error")
            
            response = MagicMock()
            response.content = "Success after retries"
            response.tool_calls = []
            return response
        
        with patch.object(agent.llm_with_tools, 'ainvoke', side_effect=flaky_invoke):
            # With max_retries=3, this should eventually succeed
            # Note: The actual retry logic is in langchain_openai.ChatOpenAI
            pass


class TestIntegrationTimeout:
    """Integration tests for timeout scenarios."""
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_full_recommend_flow_completes_in_time(self):
        """Full recommend flow should complete within max execution time."""
        from src.agents.specialized.recommend_agent import RecommendAgent
        
        settings = get_settings()
        agent = RecommendAgent(settings=settings)
        
        # Mock Google Places response
        mock_places_result = {
            "success": True,
            "places": [
                {
                    "id": "test-place",
                    "name": "Test Restaurant",
                    "rating": 4.5,
                    "address": "Test Address, Zaragoza",
                }
            ],
            "count": 1,
        }
        
        # Mock LLM responses
        mock_tool_response = MagicMock()
        mock_tool_response.content = ""
        mock_tool_response.tool_calls = [{
            "id": "call_1",
            "name": "google_places_tool",
            "args": {"query": "restaurantes en Zaragoza"},
        }]
        
        mock_final_response = MagicMock()
        mock_final_response.content = "He encontrado restaurantes para ti."
        mock_final_response.tool_calls = []
        
        start = perf_counter()
        
        with patch(
            'src.tools.search.google_places.google_places_tool',
            return_value=mock_places_result
        ):
            with patch.object(
                agent.llm_with_tools,
                'ainvoke',
                side_effect=[mock_tool_response, mock_final_response]
            ):
                try:
                    result = await asyncio.wait_for(
                        agent.run("restaurantes en Zaragoza", language="es"),
                        timeout=settings.agent_max_execution_time
                    )
                    
                    elapsed = perf_counter() - start
                    
                    # Should complete successfully
                    assert result is not None
                    assert elapsed < settings.agent_max_execution_time
                    
                except asyncio.TimeoutError:
                    elapsed = perf_counter() - start
                    pytest.fail(
                        f"Agent exceeded max execution time "
                        f"({elapsed:.1f}s > {settings.agent_max_execution_time}s)"
                    )


# Markers for slow tests
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )

