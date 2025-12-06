import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.classifiers.intent_classifier import IntentClassifier
from src.classifiers.models import IntentResult, IntentType
from src.config.settings import Settings
from src.validators.schemas import ValidatedContext, Location

@pytest.fixture
def mock_settings():
    return Settings(
        openai_api_key="sk-test",
        supported_languages="es,en",
        default_language="es",
    )

@pytest.fixture
def context():
    return ValidatedContext(
        user_id="test-user",
        session_id="test-session",
        language="es",
        location=Location(lat=40.4, lon=-3.7)
    )

@pytest.mark.asyncio
async def test_classify_returns_valid_result(mock_settings, context):
    # Mock the chain invoke
    mock_chain = AsyncMock()
    mock_chain.ainvoke.return_value = IntentResult(
        intention=IntentType.SEARCH,
        confidence=0.95,
        reasoning="User wants to find bars",
        complexity="low"
    )

    with patch("src.classifiers.intent_classifier.ChatOpenAI"), \
         patch("src.classifiers.intent_classifier.ChatPromptTemplate"):
        
        classifier = IntentClassifier(settings=mock_settings)
        classifier._chain = mock_chain  # Inject mock chain
        
        result = await classifier.classify("Buscar bares", context)
        
        assert result.intention == IntentType.SEARCH
        assert result.confidence == 0.95
        mock_chain.ainvoke.assert_called_once()

@pytest.mark.asyncio
async def test_classify_handles_errors_gracefully(mock_settings, context):
    mock_chain = AsyncMock()
    mock_chain.ainvoke.side_effect = Exception("API Error")

    with patch("src.classifiers.intent_classifier.ChatOpenAI"), \
         patch("src.classifiers.intent_classifier.ChatPromptTemplate"):
        
        classifier = IntentClassifier(settings=mock_settings)
        classifier._chain = mock_chain
        
        result = await classifier.classify("Error query", context)
        
        assert result.intention == IntentType.CHITCHAT  # Fallback
        assert result.confidence == 0.0

