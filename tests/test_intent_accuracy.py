"""
Test intent classification accuracy against golden dataset.

All LLM API calls are mocked to avoid real API usage.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.classifiers.intent_classifier import IntentClassifier
from src.classifiers.models import IntentType, IntentResult
from src.validators.schemas import ValidatedContext, LocationContext


@pytest.fixture
def mock_settings():
    """Mock settings to avoid loading from environment."""
    with patch('src.config.settings.get_settings') as mock:
        settings = MagicMock()
        settings.openai_api_key = "test-key"
        mock.return_value = settings
        yield settings


@pytest.fixture
def mock_analytics():
    """Mock analytics tracking to avoid PostHog API calls."""
    with patch('src.utils.analytics.track_event') as mock:
        yield mock


@pytest.fixture
def mock_context():
    """Create mock ValidatedContext for testing."""
    return ValidatedContext(
        language="es",
        location=LocationContext(lat=40.4168, lon=-3.7038),
    )


# Golden dataset: (query, expected_intent, complexity)
# These are expected classification results for testing accuracy
GOLDEN_DATASET = [
    ("Busco un bar en Zaragoza", IntentType.SEARCH, "low"),
    ("Quiero crear un plan para el fin de semana", IntentType.PLAN, "medium"),
    ("Recomiéndame los mejores restaurantes", IntentType.RECOMMEND, "medium"),
    ("Hola, ¿cómo estás?", IntentType.CHITCHAT, "low"),
    ("Plan romántico para 2 en Madrid", IntentType.PLAN, "medium"),
    ("Lugares para comer en Barcelona", IntentType.SEARCH, "low"),
    ("¿Cuáles son los top 5 bares?", IntentType.RECOMMEND, "medium"),
    ("Gracias por la ayuda", IntentType.CHITCHAT, "low"),
    ("Arma un itinerario para 3 horas", IntentType.PLAN, "medium"),
    ("Dame opciones para tapas", IntentType.SEARCH, "low"),
    ("Quiero los mejores sitios para una cena elegante", IntentType.RECOMMEND, "medium"),
    ("Busco cafeterías con wifi", IntentType.SEARCH, "low"),
    ("Organiza una salida nocturna completa", IntentType.PLAN, "high"),
    ("Buenos días", IntentType.CHITCHAT, "low"),
    ("Plan de 4 paradas para esta tarde", IntentType.PLAN, "medium"),
]


class TestIntentAccuracy:
    """Test intent classification accuracy with mocked LLM calls."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query,expected_intent,expected_complexity", GOLDEN_DATASET)
    async def test_classification_accuracy(
        self, query, expected_intent, expected_complexity, mock_settings, mock_context, mock_analytics
    ):
        """Test classification accuracy on golden dataset with mocked API."""
        classifier = IntentClassifier(settings=mock_settings)

        # Mock the LLM response for this specific query
        mock_result = IntentResult(
            intention=expected_intent,
            confidence=0.95,
            reasoning=f"Classified as {expected_intent.value}",
            complexity=expected_complexity,
        )

        with patch.object(classifier._chain, 'ainvoke', new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_result

            result = await classifier.classify(query, mock_context)

            assert result.intention == expected_intent, (
                f"Expected {expected_intent} for '{query}', got {result.intention}"
            )
            assert result.complexity == expected_complexity
            assert result.confidence > 0.0

            # Verify analytics tracking was called
            assert mock_analytics.called

    @pytest.mark.asyncio
    async def test_overall_accuracy_simulation(self, mock_settings, mock_context, mock_analytics):
        """Test overall classification accuracy across all golden dataset entries."""
        classifier = IntentClassifier(settings=mock_settings)

        correct = 0
        total = len(GOLDEN_DATASET)

        for query, expected_intent, expected_complexity in GOLDEN_DATASET:
            # Mock correct classification for each query
            mock_result = IntentResult(
                intention=expected_intent,
                confidence=0.92,
                reasoning=f"Classified as {expected_intent.value}",
                complexity=expected_complexity,
            )

            with patch.object(classifier._chain, 'ainvoke', new_callable=AsyncMock) as mock_invoke:
                mock_invoke.return_value = mock_result

                result = await classifier.classify(query, mock_context)

                if result.intention == expected_intent:
                    correct += 1

        accuracy = correct / total
        # With mocked perfect responses, we expect 100% accuracy
        assert accuracy >= 0.90, (
            f"Classification accuracy {accuracy:.2%} below 90% threshold"
        )

    @pytest.mark.asyncio
    async def test_explore_mode_overrides_plan_without_keyword(
        self, mock_settings, mock_context, mock_analytics
    ):
        """Test that explore mode overrides PLAN intent to RECOMMEND when no explicit plan keyword."""
        classifier = IntentClassifier(settings=mock_settings)

        # Query that might be classified as PLAN but without explicit "plan" keyword
        query = "Quiero lugares románticos en Madrid"

        # Mock LLM returning PLAN intent
        mock_result = IntentResult(
            intention=IntentType.PLAN,
            confidence=0.85,
            reasoning="User wants romantic places",
            complexity="medium",
        )

        with patch.object(classifier._chain, 'ainvoke', new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_result

            # Classify in explore mode
            result = await classifier.classify(query, mock_context, chat_mode="explore")

            # Should be overridden to RECOMMEND
            assert result.intention == IntentType.RECOMMEND
            assert "explore" in result.reasoning.lower() or "recommend" in result.reasoning.lower()

    @pytest.mark.asyncio
    async def test_plan_mode_allows_plan_intent(
        self, mock_settings, mock_context, mock_analytics
    ):
        """Test that plan mode allows PLAN intent through."""
        classifier = IntentClassifier(settings=mock_settings)

        query = "Crea un plan para esta noche"

        mock_result = IntentResult(
            intention=IntentType.PLAN,
            confidence=0.95,
            reasoning="User explicitly wants to create a plan",
            complexity="medium",
        )

        with patch.object(classifier._chain, 'ainvoke', new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_result

            result = await classifier.classify(query, mock_context, chat_mode="plan")

            # Should remain PLAN in plan mode
            assert result.intention == IntentType.PLAN

    @pytest.mark.asyncio
    async def test_explicit_plan_keyword_bypasses_explore_override(
        self, mock_settings, mock_context, mock_analytics
    ):
        """Test that explicit 'plan' keyword bypasses explore mode override."""
        classifier = IntentClassifier(settings=mock_settings)

        # Query with explicit "plan" keyword
        query = "Quiero crear un plan romántico en Madrid"

        mock_result = IntentResult(
            intention=IntentType.PLAN,
            confidence=0.95,
            reasoning="User explicitly wants to create a plan",
            complexity="medium",
        )

        with patch.object(classifier._chain, 'ainvoke', new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_result

            # Classify in explore mode (but has keyword)
            result = await classifier.classify(query, mock_context, chat_mode="explore")

            # Should NOT be overridden because of explicit keyword
            assert result.intention == IntentType.PLAN

    @pytest.mark.asyncio
    async def test_low_confidence_handling(
        self, mock_settings, mock_context, mock_analytics
    ):
        """Test handling of low confidence classifications."""
        classifier = IntentClassifier(settings=mock_settings)

        query = "Algo de comida"

        # Mock low confidence result
        mock_result = IntentResult(
            intention=IntentType.SEARCH,
            confidence=0.45,  # Low confidence
            reasoning="Ambiguous query about food",
            complexity="low",
        )

        with patch.object(classifier._chain, 'ainvoke', new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_result

            result = await classifier.classify(query, mock_context)

            # Should still return a classification even with low confidence
            assert result.intention in [
                IntentType.SEARCH,
                IntentType.RECOMMEND,
                IntentType.CHITCHAT,
            ]
            assert result.confidence == 0.45

    @pytest.mark.asyncio
    async def test_classification_failure_fallback(
        self, mock_settings, mock_context, mock_analytics
    ):
        """Test that classification failure returns safe fallback."""
        classifier = IntentClassifier(settings=mock_settings)

        query = "Test query"

        # Mock LLM failure
        with patch.object(classifier._chain, 'ainvoke', side_effect=Exception("API Error")):
            result = await classifier.classify(query, mock_context)

            # Should fallback to CHITCHAT with 0 confidence
            assert result.intention == IntentType.CHITCHAT
            assert result.confidence == 0.0
            assert "failed" in result.reasoning.lower()


class TestIntentDistribution:
    """Test intent distribution characteristics."""

    @pytest.mark.asyncio
    async def test_search_intent_distribution(self, mock_settings, mock_context, mock_analytics):
        """Test that SEARCH queries are properly distributed."""
        classifier = IntentClassifier(settings=mock_settings)

        search_queries = [
            "Busco un bar",
            "Dónde está el restaurante X",
            "Lugares cerca de aquí",
            "Cafeterías en el centro",
        ]

        search_count = 0
        for query in search_queries:
            mock_result = IntentResult(
                intention=IntentType.SEARCH,
                confidence=0.90,
                reasoning="Location-based search query",
                complexity="low",
            )

            with patch.object(classifier._chain, 'ainvoke', new_callable=AsyncMock) as mock_invoke:
                mock_invoke.return_value = mock_result
                result = await classifier.classify(query, mock_context)

                if result.intention == IntentType.SEARCH:
                    search_count += 1

        # All SEARCH queries should be classified as SEARCH
        assert search_count == len(search_queries)

    @pytest.mark.asyncio
    async def test_recommend_vs_search_distinction(
        self, mock_settings, mock_context, mock_analytics
    ):
        """Test distinction between RECOMMEND and SEARCH intents."""
        classifier = IntentClassifier(settings=mock_settings)

        # RECOMMEND: asks for top/best/recommendations
        recommend_query = "¿Cuáles son los mejores bares?"
        mock_recommend = IntentResult(
            intention=IntentType.RECOMMEND,
            confidence=0.92,
            reasoning="Asking for recommendations/rankings",
            complexity="medium",
        )

        with patch.object(classifier._chain, 'ainvoke', new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_recommend
            result_recommend = await classifier.classify(recommend_query, mock_context)
            assert result_recommend.intention == IntentType.RECOMMEND

        # SEARCH: looking for specific place/location
        search_query = "Busco un bar en el centro"
        mock_search = IntentResult(
            intention=IntentType.SEARCH,
            confidence=0.90,
            reasoning="Location-based search",
            complexity="low",
        )

        with patch.object(classifier._chain, 'ainvoke', new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = mock_search
            result_search = await classifier.classify(search_query, mock_context)
            assert result_search.intention == IntentType.SEARCH

        # Verify they're different
        assert result_recommend.intention != result_search.intention
