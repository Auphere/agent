"""
Combined Intent Classifier + Parameter Extractor.

This reduces LLM calls from 2 to 1 by doing both:
1. Intent classification (SEARCH, RECOMMEND, PLAN, CHITCHAT)
2. Parameter extraction (num_people, cities, budget, vibes, etc.)

Benefits:
- 50% reduction in LLM calls for PLAN intent
- Lower latency
- Lower costs
- More context-aware extraction
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from src.classifiers.models import IntentType
from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger
from src.validators.schemas import ValidatedContext


class CombinedClassificationResult(BaseModel):
    """
    Combined result of intent classification + parameter extraction.
    
    This model extracts everything needed in a single LLM call.
    """
    
    # Intent classification
    intention: IntentType = Field(
        ..., 
        description="The classified intent: SEARCH, RECOMMEND, PLAN, or CHITCHAT"
    )
    confidence: float = Field(
        ..., 
        ge=0.0, 
        le=1.0, 
        description="Confidence score between 0.0 and 1.0"
    )
    reasoning: str = Field(
        ..., 
        description="Brief explanation of the classification"
    )
    complexity: Literal["low", "medium", "high"] = Field(
        "low", 
        description="Estimated complexity"
    )
    
    # Parameter extraction (for PLAN/RECOMMEND intents)
    num_people: Optional[int] = Field(
        None,
        description="Number of people. Extract from: '2 personas', 'nosotros dos', 'mi pareja', etc."
    )
    cities: Optional[List[str]] = Field(
        None,
        description="Cities mentioned in the query"
    )
    budget_per_person: Optional[float] = Field(
        None,
        description="Budget per person in euros"
    )
    vibes: Optional[List[str]] = Field(
        None,
        description="Atmosphere preferences: romantic, energetic, chill, elegant, cultural, festive"
    )
    date: Optional[str] = Field(
        None,
        description="Date if mentioned (YYYY-MM-DD or descriptive like 'este sábado')"
    )
    start_time: Optional[str] = Field(
        None,
        description="Start time if mentioned (HH:MM or descriptive like 'por la noche')"
    )
    place_types: Optional[List[str]] = Field(
        None,
        description="Types of places: restaurants, bars, cafes, clubs, museums"
    )
    cuisine_preferences: Optional[List[str]] = Field(
        None,
        description="Cuisine preferences: italian, japanese, mediterranean, vegan"
    )
    special_occasion: Optional[str] = Field(
        None,
        description="Special occasion: anniversary, birthday, first date"
    )


COMBINED_CLASSIFICATION_PROMPT = """You are an expert at understanding user requests for a place recommendation app.

Your task: Classify the intent AND extract relevant parameters in a single analysis.

## INPUT
Query: {query}
Language: {language}
Location: {location}
Chat Mode: {chat_mode}
Conversation History: {conversation_history}

## INTENT CLASSIFICATION RULES

1. **SEARCH**: User wants to find specific places
   - "Busca restaurantes chinos"
   - "Encuentra bares cerca de mí"
   - "Muéstrame cafeterías"

2. **RECOMMEND**: User wants suggestions or comparisons
   - "¿Cuál es el mejor restaurante?"
   - "Recomiéndame un bar"
   - "¿Qué lugar me sugieres?"

3. **PLAN**: User wants a multi-stop itinerary
   - "Plan para cenar y tomar copas"
   - "Itinerario para este sábado"
   - "Organiza una noche romántica"
   - NOTE: In "explore" mode, only classify as PLAN if user explicitly mentions plan/itinerary

4. **CHITCHAT**: Greeting, thanks, or off-topic
   - "Hola"
   - "Gracias"
   - "¿Cómo estás?"

## PARAMETER EXTRACTION RULES

For PLAN and RECOMMEND intents, extract:

1. **num_people**: Look for explicit or implicit numbers
   - "2 personas" → 2
   - "mi pareja y yo" → 2
   - "nosotros dos" → 2
   - "grupo de amigos" → infer 4-5 if no specific number

2. **cities**: Extract city names
   - "en Madrid" → ["Madrid"]
   - "Zaragoza" → ["Zaragoza"]

3. **budget_per_person**: Extract budget in euros
   - "50 euros por persona" → 50
   - "presupuesto de 100€" → 100
   - "100 euros en total para 2" → 50

4. **vibes**: Map to standard categories
   - "romántico" → ["romantic"]
   - "animado", "fiesta" → ["energetic", "festive"]
   - "tranquilo", "relajado" → ["chill"]
   - "elegante", "sofisticado" → ["elegant"]
   - "cultural" → ["cultural"]

5. **place_types**: What places they want
   - "cenar" → ["restaurants"]
   - "copas" → ["bars"]
   - "café" → ["cafes"]

6. **date/start_time**: When they want to go
   - "este sábado" → date
   - "por la noche" → start_time

## IMPORTANT

- Look across the ENTIRE conversation history, not just the current query
- Extract implicit information (e.g., "para ambos" implies 2 people)
- Return null for parameters not mentioned
- Be conservative - don't invent information not in the query
"""


class CombinedClassifier:
    """
    Combined classifier that does intent + parameter extraction in one LLM call.
    
    Reduces latency and costs by combining two operations.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = get_logger("combined-classifier", settings=self.settings)

        self.llm = ChatOpenAI(
            model="gpt-4o-mini",  # Fast and cheap
            temperature=0.0,  # Deterministic
            api_key=self.settings.openai_api_key,
            max_retries=2,
        )
        
        self._chain = self._build_chain()
        
        self.logger.info("combined-classifier-initialized")

    def _build_chain(self):
        """Build classification chain with structured output."""
        prompt = ChatPromptTemplate.from_messages([
            ("system", COMBINED_CLASSIFICATION_PROMPT),
            ("user", "{query}"),
        ])
        
        return prompt | self.llm.with_structured_output(CombinedClassificationResult)

    async def classify_and_extract(
        self,
        query: str,
        context: ValidatedContext,
        chat_mode: str = "explore",
        conversation_history: List[Dict[str, str]] | None = None,
    ) -> CombinedClassificationResult:
        """
        Classify intent AND extract parameters in a single LLM call.
        
        Args:
            query: User's input text
            context: Validated context
            chat_mode: Current chat mode ("explore" or "plan")
            conversation_history: Previous turns for context
            
        Returns:
            CombinedClassificationResult with intent + parameters
        """
        location_str = "Unknown"
        if context.location:
            location_str = f"{context.location.lat}, {context.location.lon}"

        # Build conversation history string
        history_str = "No previous conversation."
        if conversation_history:
            history_lines = []
            for turn in conversation_history:
                history_lines.append(f"User: {turn.get('user_query', '')}")
                response = turn.get('agent_response', '')
                if response:
                    history_lines.append(f"Assistant: {response[:200]}")  # Truncate
            history_str = "\n".join(history_lines[-10:])  # Last 10 lines

        self.logger.debug(
            "classifying-and-extracting",
            query=query,
            language=context.language,
            chat_mode=chat_mode,
        )

        try:
            result = await self._chain.ainvoke({
                "query": query,
                "language": context.language,
                "location": location_str,
                "chat_mode": chat_mode,
                "conversation_history": history_str,
            })
            
            # Override PLAN to RECOMMEND in explore mode if no explicit plan keyword
            if chat_mode == "explore" and result.intention == IntentType.PLAN:
                plan_keywords = ["plan", "planificar", "itinerario", "crear plan", "itinerary", "organiza"]
                has_plan_keyword = any(keyword in query.lower() for keyword in plan_keywords)
                
                if not has_plan_keyword:
                    self.logger.info(
                        "plan-intent-overridden-to-recommend",
                        reason="explore mode without explicit plan keyword"
                    )
                    result.intention = IntentType.RECOMMEND
                    result.reasoning = "Usuario en modo Explore, buscando recomendaciones"
            
            self.logger.info(
                "combined-classification-completed",
                intention=result.intention.value,
                confidence=result.confidence,
                has_params=bool(result.num_people or result.cities or result.budget_per_person),
            )
            
            return result

        except Exception as exc:
            self.logger.error("combined-classification-failed", error=str(exc))
            # Return safe fallback
            return CombinedClassificationResult(
                intention=IntentType.CHITCHAT,
                confidence=0.0,
                reasoning=f"Classification failed: {str(exc)}",
                complexity="low",
            )

    def to_intent_result(self, result: CombinedClassificationResult):
        """
        Convert to legacy IntentResult for backward compatibility.
        
        Args:
            result: CombinedClassificationResult
            
        Returns:
            IntentResult (legacy format)
        """
        from src.classifiers.models import IntentResult
        
        return IntentResult(
            intention=result.intention,
            confidence=result.confidence,
            reasoning=result.reasoning,
            complexity=result.complexity,
        )

    def to_plan_params(self, result: CombinedClassificationResult) -> Dict[str, Any]:
        """
        Extract plan parameters from result.
        
        Args:
            result: CombinedClassificationResult
            
        Returns:
            Dict of plan parameters (for agent context)
        """
        params = {}
        
        if result.num_people is not None:
            params["num_people"] = result.num_people
        if result.cities:
            params["cities"] = result.cities
        if result.budget_per_person is not None:
            params["budget_per_person"] = result.budget_per_person
        if result.vibes:
            params["vibes"] = result.vibes
        if result.date:
            params["date"] = result.date
        if result.start_time:
            params["start_time"] = result.start_time
        if result.place_types:
            params["place_types"] = result.place_types
        if result.cuisine_preferences:
            params["cuisine_preferences"] = result.cuisine_preferences
        if result.special_occasion:
            params["special_occasion"] = result.special_occasion
        
        return params

