"""
Structured parameter extraction using LLM with Pydantic models.

This replaces regex-based extraction with reliable, scalable LLM-based extraction.

IMPROVEMENTS:
1. ✅ 100% LLM-based (no regex)
2. ✅ Detects implicit parameters ("para nosotros dos" → 2 people)
3. ✅ Multilingual support
4. ✅ Accumulates parameters across conversation turns
5. ✅ Type-safe with Pydantic
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger

logger = get_logger("structured_parameter_extractor")


class PlanParameters(BaseModel):
    """Structured plan parameters extracted from conversation."""
    
    num_people: Optional[int] = Field(
        None,
        description="Number of people. Extract from: '2 personas', 'nosotros dos', 'mi pareja y yo', 'para ambos', 'somos 4', '3 amigos', etc."
    )
    cities: Optional[List[str]] = Field(
        None,
        description="Cities mentioned. Extract city names."
    )
    primary_city: Optional[str] = Field(
        None,
        description=(
            "The main city the user wants the plan for in the CURRENT request. "
            "If multiple cities are mentioned across the conversation, pick the one that the user is asking to plan in now."
        ),
    )
    budget_per_person: Optional[float] = Field(
        None,
        description="Budget per person in euros. If 'presupuesto total' is mentioned, divide by num_people. Extract from: '50 euros', '50€', 'presupuesto de 50', '30 euros total' (divide by num_people)."
    )
    vibes: Optional[List[str]] = Field(
        None,
        description="Desired atmosphere/vibes. Options: romantic, energetic, chill, elegant, adventurous, cultural, festive, casual, fun, lively"
    )
    vibes_any: Optional[bool] = Field(
        None,
        description=(
            "True when the user explicitly states they have no preference about the vibe/atmosphere, "
            "e.g. 'cualquier ambiente está bien', 'me da igual el ambiente', 'lo que sea'."
        ),
    )
    date: Optional[str] = Field(
        None,
        description="Date in YYYY-MM-DD format if mentioned, or descriptive like 'este sábado', 'mañana'"
    )
    start_time: Optional[str] = Field(
        None,
        description="Start time in HH:MM format if mentioned, or descriptive like 'por la noche', 'mediodía'"
    )
    place_types: Optional[List[str]] = Field(
        None,
        description="Types of places desired: restaurants, bars, cafes, clubs, museums, parks, etc."
    )
    cuisine_preferences: Optional[List[str]] = Field(
        None,
        description="Cuisine preferences: mediterranean, italian, japanese, vegan, etc."
    )
    special_occasion: Optional[str] = Field(
        None,
        description="Special occasion: anniversary, birthday, first date, celebration, casual, etc."
    )


class StructuredParameterExtractor:
    """
    Extract plan parameters using structured LLM output.
    
    This is the SINGLE source of truth for parameter extraction,
    replacing PlanParameterMemory, PlanContextExtractor, and ParameterExtractor.
    """
    
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        
        # Use GPT-4o for reliable structured output
        self.llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0,
            api_key=self.settings.openai_api_key,
            timeout=(
                self.settings.llm_connection_timeout,
                self.settings.llm_read_timeout_standard,
            ),
            max_retries=self.settings.llm_max_retries,
        )
        
        # Create structured output extractor
        self.extractor = self.llm.with_structured_output(PlanParameters)
        
        logger.info("structured-parameter-extractor-initialized")
    
    async def extract_from_conversation(
        self,
        current_query: str,
        conversation_history: List[Dict[str, str]] | None = None,
    ) -> PlanParameters:
        """
        Extract ALL plan parameters from current query + conversation history.
        
        This accumulates parameters across turns automatically by looking
        at the entire conversation context.
        
        Args:
            current_query: Current user message
            conversation_history: Previous turns [{"user_query": "...", "agent_response": "..."}]
            
        Returns:
            PlanParameters object with all extracted fields
        """
        import time
        start_time = time.time()

        conversation_history = conversation_history or []

        # Build full conversation context
        messages_text = []
        for turn in conversation_history:
            messages_text.append(f"User: {turn.get('user_query', '')}")
            agent_response = turn.get('agent_response', '')
            if agent_response:
                messages_text.append(f"Assistant: {agent_response}")
        
        messages_text.append(f"User: {current_query}")
        
        conversation_text = "\n".join(messages_text)
        
        # Build extraction prompt
        prompt = f"""Extract ALL plan parameters from this conversation.

Look across ALL messages in the conversation, not just the last one.
If a parameter was mentioned in ANY previous message, include it.

Conversation:
{conversation_text}

Extract these parameters:

1. **num_people**: Number of people going
   - Look for: "2 personas", "para 3", "somos 4", "nosotros dos", "mi pareja y yo", "para ambos", "grupo de 5"
   - Extract the number even if expressed as words: "dos" → 2, "tres" → 3
   - Implicit: "mi novia y yo" → 2, "con amigos" → infer from context

2. **cities**: Which cities are mentioned
   - Extract city names: "Madrid", "Barcelona", "Zaragoza", etc.
   - IMPORTANT: Also set **primary_city** to the main city for the CURRENT request
     (e.g., 'crear un plan en Zaragoza' → primary_city='Zaragoza'), even if other cities appear in history.

3. **budget_per_person**: Budget per person in euros
   - Look for: "50 euros", "50€", "presupuesto de 50", "50 por persona"
   - IMPORTANT: If "presupuesto total" or "en total" is mentioned, DIVIDE by num_people
   - Example: "presupuesto total de 30 euros" with 3 people → budget_per_person=10.0
   - Extract numeric value and calculate if needed

4. **vibes**: Atmosphere preferences (can be multiple)
   - Options: romantic, energetic, chill, elegant, adventurous, cultural, festive, casual, fun, lively
   - Look for: "romántico", "animado", "tranquilo", "elegante", "aventura", "cultural", "fiesta", "divertido" (→ fun/energetic), "conversar" (→ chill/casual)
   - Translate Spanish vibes to English options
   - IMPORTANT: If the user explicitly says they have NO preference (e.g., "cualquier ambiente está bien", "me da igual", "lo que sea"), set:
     - vibes_any=true
     - vibes=null (or an empty list)

5. **date**: Date if mentioned
   - Extract: "2024-12-25", "este sábado", "mañana", "el viernes"

6. **start_time**: Start time if mentioned
   - Extract: "20:00", "por la noche", "mediodía", "tarde"

7. **place_types**: Types of places desired
   - Extract: restaurants, bars, cafes, clubs, museums, parks

8. **cuisine_preferences**: Cuisine preferences
   - Extract: mediterranean, italian, japanese, mexican, vegan, seafood

9. **special_occasion**: Special occasion if mentioned
   - Extract: anniversary, birthday, first date, celebration, casual hangout

IMPORTANT:
- Return NULL for fields not mentioned in ANY message
- Look across the ENTIRE conversation, not just the last message
- Extract implicit information (e.g., "mi novia y yo" → num_people=2)
- If user says "para nosotros dos", extract num_people=2
- If user says "en total", interpret budget as total, divide by num_people if known
"""
        
        logger.debug("extracting-parameters", query_length=len(current_query), history_turns=len(conversation_history))
        
        try:
            # Call LLM with structured output
            params = await self.extractor.ainvoke(prompt)
            
            logger.info(
                "parameters-extracted",
                num_people=params.num_people,
                cities=params.cities,
                budget=params.budget_per_person,
                vibes=params.vibes,
            )

            # PHASE 2.3: Track parameter extraction in PostHog
            try:
                from src.utils.analytics import track_event

                extracted_fields = [k for k, v in params.model_dump(exclude_none=True).items() if v]
                extraction_latency_ms = int((time.time() - start_time) * 1000)

                track_event(
                    'parameters_extracted',
                    properties={
                        'fields_extracted': extracted_fields,
                        'num_fields': len(extracted_fields),
                        'has_required_fields': all([
                            params.num_people is not None,
                            params.cities is not None and len(params.cities) > 0,
                            params.budget_per_person is not None,
                        ]),
                        'has_num_people': params.num_people is not None,
                        'has_cities': params.cities is not None and len(params.cities) > 0,
                        'has_budget': params.budget_per_person is not None,
                        'has_vibes': params.vibes is not None and len(params.vibes) > 0,
                        'extraction_latency_ms': extraction_latency_ms,
                        'conversation_turn': len(conversation_history) + 1,
                    }
                )
            except Exception as track_error:
                # Fail-safe: Don't break extraction if tracking fails
                logger.warning("extraction-tracking-failed", error=str(track_error))

            return params
            
        except Exception as e:
            logger.error("extraction-failed", error=str(e))
            # Return empty parameters on error
            return PlanParameters()
    
    def merge_with_previous(
        self,
        new_params: PlanParameters,
        previous_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Merge new parameters with previous, new values take precedence.
        
        Args:
            new_params: Newly extracted parameters
            previous_params: Previously stored parameters from DB
            
        Returns:
            Merged dictionary with accumulated parameters
        """
        merged = previous_params.copy()
        
        # Convert new params to dict
        new_dict = new_params.model_dump(exclude_none=True)
        
        # Merge: new values override old values
        for field, value in new_dict.items():
            if value is not None:
                # For lists, merge uniquely
                if isinstance(value, list) and field in merged and isinstance(merged[field], list):
                    # Merge lists and remove duplicates
                    merged[field] = list(set(merged[field] + value))
                else:
                    # Override scalar values
                    merged[field] = value
        
        logger.debug("parameters-merged", merged_count=len(merged), new_count=len(new_dict))
        
        return merged
    
    def get_missing_required(self, params: Dict[str, Any]) -> List[str]:
        """
        Get list of required parameters that are still missing.
        
        Args:
            params: Current parameter dictionary
            
        Returns:
            List of missing required field names
        """
        # "vibes" is required ONLY if the user did not explicitly say they have no preference.
        required_fields = ["num_people", "cities", "budget_per_person", "vibes"]
        
        missing = []
        for field in required_fields:
            value = params.get(field)
            # Check if value is None, empty list, or empty string
            if field == "vibes":
                if params.get("vibes_any") is True:
                    continue
                if value is None or (isinstance(value, list) and len(value) == 0) or value == "":
                    missing.append(field)
            else:
                if value is None or (isinstance(value, list) and len(value) == 0) or value == "":
                    missing.append(field)
        
        return missing
    
    def format_missing_fields_prompt(self, missing: List[str], language: str = "es") -> str:
        """
        Generate a friendly, conversational prompt asking for missing fields.

        Args:
            missing: List of missing field names
            language: Response language (es or en)

        Returns:
            Natural language question
        """
        if not missing:
            return ""

        if language.startswith("es"):
            field_prompts = {
                "num_people": "¿Cuántas personas van?",
                "cities": "¿En qué ciudad?",
                "budget_per_person": "¿Qué presupuesto aproximado por persona?",
                "vibes": "¿Qué tipo de ambiente buscan? (romántico, animado, tranquilo, elegante, etc.)",
            }

            questions = [field_prompts.get(field, field) for field in missing]

            if len(questions) == 1:
                return f"Para crear tu plan perfecto, necesito saber: {questions[0]}"
            elif len(questions) == 2:
                return f"Para crear tu plan perfecto, necesito saber:\n• {questions[0]}\n• {questions[1]}"
            else:
                bullets = "\n".join([f"• {q}" for q in questions])
                return f"Para crear tu plan perfecto, necesito saber:\n{bullets}"
        else:
            # English
            field_prompts = {
                "num_people": "How many people?",
                "cities": "Which city?",
                "budget_per_person": "Approximate budget per person?",
                "vibes": "What kind of atmosphere? (romantic, energetic, chill, elegant, etc.)",
            }

            questions = [field_prompts.get(field, field) for field in missing]

            if len(questions) == 1:
                return f"To create your perfect plan, I need to know: {questions[0]}"
            elif len(questions) == 2:
                return f"To create your perfect plan, I need to know:\n• {questions[0]}\n• {questions[1]}"
            else:
                bullets = "\n".join([f"• {q}" for q in questions])
                return f"To create your perfect plan, I need to know:\n{bullets}"

    def format_missing_fields_prompt_contextual(
        self,
        missing: List[str],
        plan_params: Dict[str, Any],
        conversation_turns: int = 1,
        language: str = "es",
    ) -> str:
        """
        Generate context-aware, varied prompts based on conversation state.

        This method creates natural questions that:
        - Reference what we already know
        - Vary opening based on turn count
        - Group related questions together
        - Feel conversational, not robotic

        Args:
            missing: List of missing field names
            plan_params: Current parameters (to reference in questions)
            conversation_turns: Number of turns so far (for variation)
            language: Response language (es or en)

        Returns:
            Natural, varied question with conversational connectors
        """
        if not missing:
            return ""

        # Extract what we already know for context
        has_city = bool(plan_params.get('cities') or plan_params.get('primary_city'))
        has_people = plan_params.get('num_people') is not None
        has_budget = plan_params.get('budget_per_person') is not None
        has_vibes = bool(plan_params.get('vibes'))

        city_name = plan_params.get('primary_city') or (plan_params.get('cities', [None])[0] if plan_params.get('cities') else None)
        num_people = plan_params.get('num_people')
        budget = plan_params.get('budget_per_person')

        if language.startswith("es"):
            # Vary opening based on turn count
            if conversation_turns == 1:
                openers = [
                    "Para crear tu plan perfecto",
                    "Para armar el plan ideal",
                    "Antes de empezar",
                ]
            elif conversation_turns == 2:
                openers = [
                    "Perfecto, y",
                    "Genial, ahora",
                    "Ya casi está, solo",
                ]
            else:
                openers = [
                    "Último detalle",
                    "Para afinarlo",
                    "Solo me falta",
                ]

            # Select opener based on turn (rotate through options)
            opener_index = min(conversation_turns - 1, len(openers) - 1)
            opener = openers[opener_index]

            # Build context-aware questions
            questions = []

            # Handle cities and num_people together if both missing
            if "cities" in missing and "num_people" in missing:
                questions.append("¿cuántas personas van y en qué ciudad?")
                missing = [m for m in missing if m not in ["cities", "num_people"]]
            elif "cities" in missing:
                if has_people:
                    questions.append(f"¿en qué ciudad quieren el plan?")
                else:
                    questions.append("¿en qué ciudad?")
                missing = [m for m in missing if m != "cities"]
            elif "num_people" in missing:
                if has_city:
                    questions.append(f"¿cuántas personas van?")
                else:
                    questions.append("¿cuántas personas?")
                missing = [m for m in missing if m != "num_people"]

            # Handle budget and vibes together if both missing
            if "budget_per_person" in missing and "vibes" in missing:
                if conversation_turns == 1:
                    questions.append("¿presupuesto aproximado por persona y qué tipo de ambiente buscan? (romántico, animado, tranquilo...)")
                else:
                    questions.append("¿presupuesto y qué vibe prefieren?")
                missing = [m for m in missing if m not in ["budget_per_person", "vibes"]]
            elif "budget_per_person" in missing:
                if has_people:
                    questions.append(f"¿presupuesto aproximado por persona?")
                else:
                    questions.append("¿presupuesto total?")
                missing = [m for m in missing if m != "budget_per_person"]
            elif "vibes" in missing:
                if conversation_turns == 1:
                    questions.append("¿qué tipo de ambiente buscan? (romántico, animado, tranquilo, elegante...)")
                else:
                    # Shorter, more direct on later turns
                    questions.append("¿prefieren algo romántico, animado, o tranquilo?")
                missing = [m for m in missing if m != "vibes"]

            # Handle any remaining fields
            for field in missing:
                if field == "date":
                    questions.append("¿qué día?")
                elif field == "start_time":
                    questions.append("¿a qué hora?")

            # Build final response with context
            if len(questions) == 0:
                return ""
            elif len(questions) == 1:
                # Add context if we know something
                if has_city and city_name:
                    return f"{opener}, necesito saber {questions[0]}"
                elif has_people:
                    return f"{opener}, necesito saber {questions[0]}"
                else:
                    return f"{opener}, necesito saber {questions[0]}"
            elif len(questions) == 2:
                return f"{opener}, necesito saber:\n• {questions[0]}\n• {questions[1]}"
            else:
                bullets = "\n".join([f"• {q}" for q in questions[:3]])  # Max 3
                return f"{opener}, necesito:\n{bullets}"

        else:
            # English version
            if conversation_turns == 1:
                opener = "To create your perfect plan"
            elif conversation_turns == 2:
                opener = "Great, now"
            else:
                opener = "Last thing"

            questions = []

            # Handle cities and num_people together
            if "cities" in missing and "num_people" in missing:
                questions.append("how many people and which city?")
                missing = [m for m in missing if m not in ["cities", "num_people"]]
            elif "cities" in missing:
                if has_people:
                    questions.append("which city?")
                else:
                    questions.append("which city?")
                missing = [m for m in missing if m != "cities"]
            elif "num_people" in missing:
                if has_city:
                    questions.append("how many people?")
                else:
                    questions.append("how many people?")
                missing = [m for m in missing if m != "num_people"]

            # Handle budget and vibes together
            if "budget_per_person" in missing and "vibes" in missing:
                if conversation_turns == 1:
                    questions.append("approximate budget per person and what kind of atmosphere? (romantic, lively, chill...)")
                else:
                    questions.append("budget and what vibe?")
                missing = [m for m in missing if m not in ["budget_per_person", "vibes"]]
            elif "budget_per_person" in missing:
                questions.append("approximate budget per person?")
                missing = [m for m in missing if m != "budget_per_person"]
            elif "vibes" in missing:
                if conversation_turns == 1:
                    questions.append("what kind of atmosphere? (romantic, lively, chill, elegant...)")
                else:
                    questions.append("romantic, lively, or chill vibe?")
                missing = [m for m in missing if m != "vibes"]

            # Handle remaining fields
            for field in missing:
                if field == "date":
                    questions.append("what day?")
                elif field == "start_time":
                    questions.append("what time?")

            # Build final response
            if len(questions) == 0:
                return ""
            elif len(questions) == 1:
                return f"{opener}, I need to know {questions[0]}"
            elif len(questions) == 2:
                return f"{opener}, I need to know:\n• {questions[0]}\n• {questions[1]}"
            else:
                bullets = "\n".join([f"• {q}" for q in questions[:3]])
                return f"{opener}, I need:\n{bullets}"

