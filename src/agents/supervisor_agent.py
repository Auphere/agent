"""SupervisorAgent - Routes queries to specialized agents."""

from __future__ import annotations

from typing import Any, Dict

from src.agents.react_agent import ReactAgent  # Fallback
from src.agents.specialized import RecommendAgent, SearchAgent
from src.agents.specialized.plan_and_execute_agent import PlanAndExecuteAgent
from src.classifiers.models import IntentType
from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger


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
        Route query to appropriate specialized agent.
        
        Args:
            query: User's query
            intent: Classified intent (from IntentClassifier)
            language: Response language
            context: Additional context
            
        Returns:
            Dict with response and metadata from specialized agent
        """
        context = context or {}
        
        self.logger.info(
            "supervisor-routing",
            query=query,
            intent=intent.value,
            language=language,
        )
        
        try:
            # Route to specialized agent based on intent (lazy initialization)
            if intent == IntentType.SEARCH:
                self.logger.info("routing-to-search-agent")
                result = await self._get_search_agent().run(query, language, context)
                
            elif intent == IntentType.PLAN:
                # Use new Plan-and-Execute agent for better quality
                self.logger.info("routing-to-plan-and-execute-agent")
                
                # ✅ Extract session_id and plan_params from context
                session_id = context.get("session_id")
                plan_params = context.get("plan_params", {})
                
                result = await self._get_plan_and_execute_agent().run(
                    query=query,
                    language=language,
                    session_id=session_id,  # ✅ CRITICAL for state persistence
                    plan_params=plan_params,  # ✅ Managed by LangGraph reducer
                    context=context
                )
                
            elif intent == IntentType.RECOMMEND:
                self.logger.info("routing-to-recommend-agent")
                result = await self._get_recommend_agent().run(query, language, context)
                
            elif intent == IntentType.CHITCHAT:
                # For chitchat, use a simple response (no need for specialized agent)
                self.logger.info("routing-to-fallback-agent-chitchat")
                result = await self._get_fallback_agent().run(query, language, context)
                
            else:
                # Unknown intent → fallback to general agent
                self.logger.warning(
                    "routing-to-fallback-agent-unknown",
                    intent=intent.value
                )
                result = await self._get_fallback_agent().run(query, language, context)
            
            # Add routing metadata
            result["routed_to"] = result.get("agent_type", "fallback")
            result["intent"] = intent.value
            
            self.logger.info(
                "supervisor-completed",
                routed_to=result["routed_to"],
                tool_calls=result.get("tool_calls", 0),
            )
            
            return result
            
        except Exception as exc:
            self.logger.error(
                "supervisor-failed",
                error=str(exc),
                intent=intent.value,
            )
            
            # Intelligent fallback based on original intent
            try:
                # If PlanAndExecuteAgent failed, try RecommendAgent (simpler)
                if intent == IntentType.PLAN:
                    self.logger.info("plan-and-execute-agent-failed-trying-recommend-agent")
                    result = await self._get_recommend_agent().run(query, language, context)
                    result["routed_to"] = "recommend_fallback_from_plan"
                    result["intent"] = intent.value
                    result["fallback_reason"] = "PlanAndExecuteAgent timeout/error"
                    return result
                
                # For other failures, use general fallback
                self.logger.info("attempting-fallback-agent-on-error")
                result = await self._get_fallback_agent().run(query, language, context)
                result["routed_to"] = "fallback_on_error"
                result["intent"] = intent.value
                return result
            except Exception as fallback_exc:
                self.logger.error(
                    "fallback-agent-also-failed",
                    error=str(fallback_exc)
                )
                raise

    async def cleanup(self) -> None:
        """Cleanup resources for any initialized specialized agents."""
        # PlanAndExecuteAgent maintains a dedicated psycopg async pool for checkpointing.
        if self._plan_and_execute_agent is not None:
            cleanup = getattr(self._plan_and_execute_agent, "cleanup", None)
            if callable(cleanup):
                await cleanup()

