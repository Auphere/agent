import pytest
from uuid import uuid4

from src.config.settings import Settings
from src.validators.context_validator import ContextValidator
from src.validators.schemas import AgentQuery, ContextValidationError, Location, Preferences, QueryContext


def _build_settings() -> Settings:
    return Settings(
        _env_file=None,
        supported_languages="es,en",
        default_language="es",
        environment="test",
        frontend_url="http://localhost",
    )


@pytest.mark.asyncio
async def test_build_context_generates_session_when_missing():
    validator = ContextValidator(settings=_build_settings())
    request = AgentQuery(
        user_id=str(uuid4()),
        query="Buscar bares en Madrid",
    )

    context = await validator.build_context(request)

    assert context.session_id
    assert context.language == "es"


@pytest.mark.asyncio
async def test_validate_language_rejects_unsupported():
    validator = ContextValidator(settings=_build_settings())
    request = AgentQuery(
        user_id=str(uuid4()),
        session_id=str(uuid4()),
        query="Plan",
        language="de",
    )

    with pytest.raises(ContextValidationError):
        await validator.build_context(request)


@pytest.mark.asyncio
async def test_validate_location_out_of_range():
    validator = ContextValidator(settings=_build_settings())
    request = AgentQuery(
        user_id=str(uuid4()),
        session_id=str(uuid4()),
        query="Dónde comer",
        language="es",
        context=QueryContext(current_location=Location(lat=200, lon=10)),
    )

    with pytest.raises(ContextValidationError):
        await validator.build_context(request)


@pytest.mark.asyncio
async def test_preferences_pass_through():
    validator = ContextValidator(settings=_build_settings())
    request = AgentQuery(
        user_id=str(uuid4()),
        session_id=str(uuid4()),
        query="Plan familiar",
        language="es",
        context=QueryContext(
            current_location=Location(lat=40.4, lon=-3.7),
            preferences=Preferences(party_size=4, tags=["family"]),
        ),
    )

    validated = await validator.build_context(request)

    assert validated.preferences is not None
    assert validated.preferences.party_size == 4

