"""SupervisorAgent - Routes queries to specialized agents."""

from __future__ import annotations

from typing import Any, Dict

from src.agents.react_agent import ReactAgent  # Fallback
from src.agents.specialized import PlanAgent, RecommendAgent, SearchAgent
from src.classifiers.models import IntentType
from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger


class SupervisorAgent:
    """
    Supervisor agent that routes queries to specialized agents.
    
    Routing Logic:
    - SEARCH → SearchAgent (fast, focused)
    - PLAN → PlanAgent (complex, multi-tool)
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
        self._plan_agent = None
        self._recommend_agent = None
        self._fallback_agent = None
        
        self.logger.info("supervisor-agent-initialized")
    
    def _get_search_agent(self) -> SearchAgent:
        """Lazy initialization of SearchAgent."""
        if self._search_agent is None:
            self._search_agent = SearchAgent(settings=self.settings)
        return self._search_agent
    
    def _get_plan_agent(self) -> PlanAgent:
        """Lazy initialization of PlanAgent."""
        if self._plan_agent is None:
            self._plan_agent = PlanAgent(settings=self.settings)
        return self._plan_agent
    
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
                self.logger.info("routing-to-plan-agent")
                result = await self._get_plan_agent().run(query, language, context)
                
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
                # If PlanAgent failed, try RecommendAgent (simpler, more likely to succeed)
                if intent == IntentType.PLAN:
                    self.logger.info("plan-agent-failed-trying-recommend-agent")
                    result = await self._get_recommend_agent().run(query, language, context)
                    result["routed_to"] = "recommend_fallback_from_plan"
                    result["intent"] = intent.value
                    result["fallback_reason"] = "PlanAgent timeout/error"
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

