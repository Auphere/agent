import pytest
from src.routers.llm_router import LLMRouter
from src.classifiers.models import IntentResult, IntentType
from src.config.settings import Settings

@pytest.fixture
def router():
    settings = Settings(budget_mode=False)
    return LLMRouter(settings=settings)

def test_route_search_low_complexity(router):
    intent = IntentResult(
        intention=IntentType.SEARCH,
        confidence=0.9,
        reasoning="Simple search",
        complexity="low"
    )
    profile = router.route(intent)
    assert profile.name == "gpt-4o-mini"

def test_route_plan_high_complexity(router):
    intent = IntentResult(
        intention=IntentType.PLAN,
        confidence=0.9,
        reasoning="Complex itinerary",
        complexity="high"
    )
    profile = router.route(intent)
    assert profile.name == "gpt-4"

def test_route_budget_mode_override():
    settings = Settings(budget_mode=True)
    router = LLMRouter(settings=settings)
    
    intent = IntentResult(
        intention=IntentType.PLAN,
        confidence=0.9,
        reasoning="Complex itinerary",
        complexity="high"
    )
    profile = router.route(intent)
    assert profile.name == "gpt-4o-mini"

