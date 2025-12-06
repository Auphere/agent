"""Routing logic to select the optimal LLM for the task."""

from __future__ import annotations

from src.classifiers.models import IntentResult, IntentType
from src.config.models_config import MODEL_PROFILES, ModelProfile
from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger


class LLMRouter:
    """Decides which LLM to use based on intent, complexity, and budget."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = get_logger("llm-router", settings=self.settings)

    def route(self, classification: IntentResult) -> ModelProfile:
        """
        Select the best model profile for the given classification.
        
        Enhanced Strategy for Multi-Tool Agent:
        - Budget Mode ON: Always use cheapest model (gpt-4o-mini)
        - PLAN + High Complexity: gpt-4 (complex routing, scoring, itinerary)
        - PLAN + Medium Complexity: gpt-4-turbo
        - RECOMMEND + Medium/High: gpt-4-turbo (needs good reasoning for scoring)
        - SEARCH (any complexity): gpt-4o-mini (tool-driven, less reasoning)
        - CHITCHAT: gpt-3.5-turbo (simple responses)
        
        Tool Usage Considerations:
        - google_places_tool: Works well with any model (data-driven)
        - rank_by_score_tool: Benefits from better reasoning (prefer gpt-4-turbo+)
        - calculate_route_tool: Works well with any model (API-driven)
        - generate_itinerary_tool: Benefits from better reasoning (prefer gpt-4-turbo+)
        """
        
        # 1. Budget Override
        if self.settings.budget_mode:
            self.logger.info("router-budget-mode-active", selection="gpt-4o-mini")
            return MODEL_PROFILES["gpt-4o-mini"]

        intention = classification.intention
        complexity = classification.complexity

        # 2. Enhanced Routing Logic
        selected_model_key = "gpt-4o-mini"  # Default

        if intention == IntentType.PLAN:
            # Plans benefit from better reasoning (routing, scoring, itinerary)
            if complexity == "high":
                selected_model_key = "gpt-4"  # Best reasoning for complex plans
            elif complexity == "medium":
                selected_model_key = "gpt-4-turbo"  # Good balance
            else:
                selected_model_key = "gpt-4o-mini"  # Simple plans
        
        elif intention == IntentType.RECOMMEND:
            # Recommendations benefit from scoring tool + good reasoning
            if complexity == "high":
                selected_model_key = "gpt-4-turbo"  # Complex scoring/ranking
            elif complexity == "medium":
                selected_model_key = "gpt-4-turbo"  # Benefit from better reasoning
            else:
                selected_model_key = "gpt-4o-mini"  # Simple recommendations

        elif intention == IntentType.SEARCH:
            # Search is mostly tool-driven (google_places_tool, web_search_tool)
            # Less reasoning needed, prefer faster/cheaper model
            selected_model_key = "gpt-4o-mini"
            
        elif intention == IntentType.CHITCHAT:
            # Simple conversation, use cheapest model
            selected_model_key = "gpt-3.5-turbo"

        # 3. Fallback validation
        if selected_model_key not in MODEL_PROFILES:
            self.logger.warning("router-model-not-found", model=selected_model_key)
            selected_model_key = "gpt-4o-mini"

        profile = MODEL_PROFILES[selected_model_key]
        
        self.logger.info(
            "model-routed",
            intention=intention.value,
            complexity=complexity,
            selected=profile.name,
            cost_per_1k=profile.cost_per_1k,
            reasoning=classification.reasoning
        )
        
        return profile

