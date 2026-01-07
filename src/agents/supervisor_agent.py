"""SupervisorAgent - Routes queries to specialized agents."""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any, Dict

from src.agents.react_agent import ReactAgent  # Fallback
from src.agents.specialized import RecommendAgent, SearchAgent
from src.agents.specialized.plan_and_execute_agent import PlanAndExecuteAgent
from src.classifiers.models import IntentType
from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger
from src.utils.metrics import get_metrics_collector


class SupervisorAgent:
    """
    Supervisor agent that routes queries to specialized agents.
    
    Routing Logic:
    - SEARCH → SearchAgent (fast, focused)
    - PLAN → PlanAndExecuteAgent (advanced multi-step planning)
    - RECOMMEND → RecommendAgent (scoring-focused)
    - CHITCHAT → Simple response (no tools)
    - ERROR/UNKNOWN → ReactAgent (fallback)
    
    Benefits:
    - Each agent is optimized for its task
    - Better prompts (specialized)
    - Better model selection (right model for task)
    - Lower costs (right tool for job)
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = get_logger("supervisor-agent", settings=self.settings)
        
        # Lazy-initialized agents (only created when needed)
        self._search_agent = None
        self._plan_and_execute_agent = None
        self._recommend_agent = None
        self._fallback_agent = None
        
        self.logger.info("supervisor-agent-initialized")
    
    def _get_search_agent(self) -> SearchAgent:
        """Lazy initialization of SearchAgent."""
        if self._search_agent is None:
            self._search_agent = SearchAgent(settings=self.settings)
        return self._search_agent
    
    def _get_plan_and_execute_agent(self) -> PlanAndExecuteAgent:
        """Lazy initialization of Plan-and-Execute Agent (new, advanced)."""
        if self._plan_and_execute_agent is None:
            self._plan_and_execute_agent = PlanAndExecuteAgent(settings=self.settings)
        return self._plan_and_execute_agent
    
    def _get_recommend_agent(self) -> RecommendAgent:
        """Lazy initialization of RecommendAgent."""
        if self._recommend_agent is None:
            self._recommend_agent = RecommendAgent(settings=self.settings)
        return self._recommend_agent
    
    def _get_fallback_agent(self) -> ReactAgent:
        """Lazy initialization of fallback ReactAgent."""
        if self._fallback_agent is None:
            self._fallback_agent = ReactAgent(
                model_name="gpt-4o-mini",
                settings=self.settings
            )
        return self._fallback_agent

    async def run(
        self,
        query: str,
        intent: IntentType,
        language: str = "en",
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Route query to appropriate specialized agent with timeout protection.
        
        Args:
            query: User's query
            intent: Classified intent (from IntentClassifier)
            language: Response language
            context: Additional context
            
        Returns:
            Dict with response and metadata from specialized agent
        """
        context = context or {}
        start_time = perf_counter()
        metrics = get_metrics_collector()
        
        self.logger.info(
            "supervisor-routing",
            query=query,
            intent=intent.value,
            language=language,
            max_execution_time=self.settings.agent_max_execution_time,
        )
        
        try:
            # Wrap execution in global timeout
            result = await asyncio.wait_for(
                self._execute_agent(query, intent, language, context),
                timeout=self.settings.agent_max_execution_time
            )
            
            # Add routing metadata
            result["routed_to"] = result.get("agent_type", "fallback")
            result["intent"] = intent.value
            
            duration = perf_counter() - start_time
            metrics.record_timing(
                "supervisor.execution",
                duration * 1000,
                {"intent": intent.value, "success": "true"}
            )
            
            self.logger.info(
                "supervisor-completed",
                routed_to=result["routed_to"],
                tool_calls=result.get("tool_calls", 0),
                duration_ms=int(duration * 1000),
            )
            
            return result
            
        except asyncio.TimeoutError:
            duration = perf_counter() - start_time
            self.logger.error(
                "supervisor-timeout",
                intent=intent.value,
                timeout=self.settings.agent_max_execution_time,
                duration_ms=int(duration * 1000),
            )
            
            metrics.record_timing(
                "supervisor.execution",
                duration * 1000,
                {"intent": intent.value, "success": "false", "error": "timeout"}
            )
            
            # Try fallback with shorter timeout
            return await self._handle_timeout_fallback(query, intent, language, context)
            
        except Exception as exc:
            duration = perf_counter() - start_time
            self.logger.error(
                "supervisor-failed",
                error=str(exc),
                error_type=type(exc).__name__,
                intent=intent.value,
                duration_ms=int(duration * 1000),
            )
            
            metrics.record_timing(
                "supervisor.execution",
                duration * 1000,
                {"intent": intent.value, "success": "false", "error": type(exc).__name__}
            )
            
            return await self._handle_error_fallback(query, intent, language, context, exc)
    
    async def _execute_agent(
        self,
        query: str,
        intent: IntentType,
        language: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute the appropriate agent based on intent."""
        # Route to specialized agent based on intent (lazy initialization)
        if intent == IntentType.SEARCH:
            self.logger.info("routing-to-search-agent")
            return await self._get_search_agent().run(query, language, context)
            
        elif intent == IntentType.PLAN:
            # Use new Plan-and-Execute agent for better quality
            self.logger.info("routing-to-plan-and-execute-agent")
            
            # Extract session_id and plan_params from context
            session_id = context.get("session_id")
            plan_params = context.get("plan_params", {})
            
            return await self._get_plan_and_execute_agent().run(
                query=query,
                language=language,
                session_id=session_id,
                plan_params=plan_params,
                context=context
            )
            
        elif intent == IntentType.RECOMMEND:
            self.logger.info("routing-to-recommend-agent")
            return await self._get_recommend_agent().run(query, language, context)
            
        elif intent == IntentType.CHITCHAT:
            self.logger.info("routing-to-fallback-agent-chitchat")
            return await self._get_fallback_agent().run(query, language, context)
            
        else:
            self.logger.warning("routing-to-fallback-agent-unknown", intent=intent.value)
            return await self._get_fallback_agent().run(query, language, context)
    
    async def _handle_timeout_fallback(
        self,
        query: str,
        intent: IntentType,
        language: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Handle timeout by trying a simpler fallback agent."""
        self.logger.info("attempting-fallback-after-timeout", intent=intent.value)
        
        try:
            # Use shorter timeout for fallback (60s)
            fallback_timeout = min(60.0, self.settings.agent_max_execution_time / 2)
            
            result = await asyncio.wait_for(
                self._get_fallback_agent().run(query, language, context),
                timeout=fallback_timeout
            )
            
            result["routed_to"] = "fallback_after_timeout"
            result["intent"] = intent.value
            result["fallback_reason"] = "Primary agent timed out"
            
            return result
            
        except Exception as fallback_exc:
            self.logger.error(
                "fallback-also-failed-after-timeout",
                error=str(fallback_exc)
            )
            # Return error response instead of raising
            return {
                "response_text": "Lo siento, el servicio está experimentando retrasos. Por favor intenta de nuevo.",
                "places": [],
                "tool_calls": 0,
                "reasoning_steps": 0,
                "agent_type": "error",
                "model_used": "none",
                "routed_to": "error",
                "intent": intent.value,
                "error": "timeout_with_fallback_failure",
            }
    
    async def _handle_error_fallback(
        self,
        query: str,
        intent: IntentType,
        language: str,
        context: Dict[str, Any],
        original_error: Exception,
    ) -> Dict[str, Any]:
        """Handle errors with intelligent fallback based on intent."""
        try:
            # If PlanAndExecuteAgent failed, try RecommendAgent (simpler)
            if intent == IntentType.PLAN:
                self.logger.info("plan-agent-failed-trying-recommend-agent")
                result = await self._get_recommend_agent().run(query, language, context)
                result["routed_to"] = "recommend_fallback_from_plan"
                result["intent"] = intent.value
                result["fallback_reason"] = f"PlanAndExecuteAgent error: {type(original_error).__name__}"
                return result
            
            # For other failures, use general fallback
            self.logger.info("attempting-fallback-agent-on-error")
            result = await self._get_fallback_agent().run(query, language, context)
            result["routed_to"] = "fallback_on_error"
            result["intent"] = intent.value
            result["fallback_reason"] = f"Primary agent error: {type(original_error).__name__}"
            return result
            
        except Exception as fallback_exc:
            self.logger.error(
                "fallback-agent-also-failed",
                error=str(fallback_exc)
            )
            raise original_error  # Re-raise original to preserve stack trace

    async def cleanup(self) -> None:
        """Cleanup resources for any initialized specialized agents."""
        # PlanAndExecuteAgent maintains a dedicated psycopg async pool for checkpointing.
        if self._plan_and_execute_agent is not None:
            cleanup = getattr(self._plan_and_execute_agent, "cleanup", None)
            if callable(cleanup):
                await cleanup()

