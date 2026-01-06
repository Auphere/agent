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
    budget_per_person: Optional[float] = Field(
        None,
        description="Budget per person in euros. If 'presupuesto total' is mentioned, divide by num_people. Extract from: '50 euros', '50€', 'presupuesto de 50', '30 euros total' (divide by num_people)."
    )
    vibes: Optional[List[str]] = Field(
        None,
        description="Desired atmosphere/vibes. Options: romantic, energetic, chill, elegant, adventurous, cultural, festive, casual, fun, lively"
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

3. **budget_per_person**: Budget per person in euros
   - Look for: "50 euros", "50€", "presupuesto de 50", "50 por persona"
   - IMPORTANT: If "presupuesto total" or "en total" is mentioned, DIVIDE by num_people
   - Example: "presupuesto total de 30 euros" with 3 people → budget_per_person=10.0
   - Extract numeric value and calculate if needed

4. **vibes**: Atmosphere preferences (can be multiple)
   - Options: romantic, energetic, chill, elegant, adventurous, cultural, festive, casual, fun, lively
   - Look for: "romántico", "animado", "tranquilo", "elegante", "aventura", "cultural", "fiesta", "divertido" (→ fun/energetic), "conversar" (→ chill/casual)
   - Translate Spanish vibes to English options

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
        required_fields = ["num_people", "cities", "budget_per_person", "vibes"]
        
        missing = []
        for field in required_fields:
            value = params.get(field)
            # Check if value is None, empty list, or empty string
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

