"""Intent classification logic using mini-LLMs."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from src.classifiers.models import IntentResult, IntentType
from src.classifiers.prompts import SYSTEM_CLASSIFICATION_PROMPT
from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger
from src.validators.schemas import ValidatedContext


class IntentClassifier:
    """Classifies user queries into predefined intents using a lightweight LLM."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = get_logger("intent-classifier", settings=self.settings)

        # Initialize LLM (using gpt-4o-mini for speed/cost as per architecture)
        # Fallback to settings.openai_api_key if needed, though langchain picks it up from env
        self.llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.0,
            api_key=self.settings.openai_api_key,
            max_retries=2,
        )
        
        self._chain = self._build_chain()

    def _build_chain(self):
        """Construct the classification chain with structured output."""
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_CLASSIFICATION_PROMPT),
                ("user", "{query}"),
            ]
        )
        
        # Using Pydantic output parser via with_structured_output
        return prompt | self.llm.with_structured_output(IntentResult)

    async def classify(self, query: str, context: ValidatedContext) -> IntentResult:
        """
        Classify the user query based on text and context.
        
        Args:
            query: The user's input text.
            context: Validated context from Step 1.
            
        Returns:
            IntentResult object with classification details.
        """
        location_str = "Unknown"
        if context.location:
            location_str = f"{context.location.lat}, {context.location.lon}"

        self.logger.debug("classifying-intent", query=query, language=context.language)

        try:
            result: IntentResult = await self._chain.ainvoke(
                {
                    "query": query,
                    "language": context.language,
                    "location": location_str,
                }
            )
            
            self.logger.info(
                "intent-classified",
                intention=result.intention.value,
                confidence=result.confidence,
                complexity=result.complexity
            )
            return result

        except Exception as exc:
            self.logger.error("intent-classification-failed", error=str(exc))
            # Fallback safely to CHITCHAT or SEARCH if classification fails? 
            # For now, we assume it shouldn't fail often, or we propagate.
            # Let's return a safe fallback to keep the service alive.
            return IntentResult(
                intention=IntentType.CHITCHAT,
                confidence=0.0,
                reasoning=f"Classification failed: {str(exc)}",
                complexity="low"
            )

