"""Application settings and configuration helpers."""

from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized runtime configuration loaded from environment variables."""

    # Service metadata
    service_name: str = "auphere-agent"
    version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"

    # Networking
    agent_host: str = "0.0.0.0"
    agent_port: int = 8001
    frontend_url: str = "http://localhost:3000"

    # LLM API Keys
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    
    # External API Keys (BETA VERSION - for real-time data)
    google_places_api_key: Optional[str] = None  # PRIMARY search tool
    google_maps_api_key: Optional[str] = None     # For routing/maps
    openweather_api_key: Optional[str] = None     # Weather context
    serpapi_key: Optional[str] = None             # Web search (optional, can use DuckDuckGo free)
    yelp_fusion_api_key: Optional[str] = None     # Alternative reviews
    foursquare_api_key: Optional[str] = None      # Popularity data
    trustpilot_api_key: Optional[str] = None      # Reviews/sentiment
    instagram_api_key: Optional[str] = None       # Visual vibes
    spotify_api_key: Optional[str] = None         # Music matching
    apify_api_key: Optional[str] = None           # Web scraping
    
    # Internal Services
    database_url: Optional[str] = "postgresql://localhost:5432/auphere-agent"
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = True
    redis_key_prefix: str = "auphere:agent"
    places_api_url: str = "http://localhost:8002"
    places_api_timeout: int = 10
    backend_url: str = "http://localhost:8000"

    # Vector DB (Qdrant) - optional
    # Local: http://localhost:6333 | Production: Qdrant Cloud URL
    qdrant_enabled: bool = False
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: Optional[str] = None  # Required for Qdrant Cloud
    qdrant_collection_plans: str = "plans"
    qdrant_collection_user_profiles: str = "user_profiles"
    qdrant_collection_places: str = "places"

    # Embeddings config (MVP)
    embeddings_model: str = "text-embedding-3-small"
    embeddings_dimensions: int = 1536
    qdrant_distance: str = "cosine"  # cosine | dot | euclid
    
    # Analytics (PostHog) - optional
    # Local: console logging | Production: PostHog Cloud
    posthog_enabled: bool = False
    posthog_api_key: Optional[str] = None  # Required for production
    posthog_host: str = "https://eu.i.posthog.com"  # PostHog Cloud EU
    
    # Cache TTLs (in seconds)
    cache_ttl_intent: int = 3600  # 1 hour
    cache_ttl_places: int = 1800  # 30 minutes
    cache_ttl_translation: int = 86400  # 24 hours
    cache_ttl_user_context: int = 3600  # 1 hour

    # Localization
    supported_languages: str = "es,en"  # Raw CSV string from env
    default_language: str = "es"

    # Routing preferences
    budget_mode: bool = False
    preferred_model: str = "gpt-4o-mini"

    # Observability
    enable_tracing: bool = True
    trace_level: str = "debug"
    
    # LangSmith Tracing (optional but recommended for production)
    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "auphere-agent"
    langsmith_tracing_enabled: bool = True  # ✅ Enabled - requires LANGSMITH_API_KEY
    
    # Timeout Configuration (in seconds)
    # Connection timeout: time to establish connection
    # Read timeout: time to wait for response
    llm_connection_timeout: float = 5.0
    llm_read_timeout_simple: float = 30.0      # For classification, chitchat
    llm_read_timeout_standard: float = 60.0    # For search, simple recommendations
    llm_read_timeout_complex: float = 90.0     # For complex recommendations, plans
    tool_timeout: float = 15.0                 # For external API calls
    agent_max_execution_time: float = 180.0    # Max total agent execution time
    
    # Retry Configuration
    llm_max_retries: int = 3                   # Max retries for LLM calls
    tool_max_retries: int = 2                  # Max retries for tool calls

    # Geographic Coverage (MVP)
    # Comma-separated list of country codes (ISO 3166-1 alpha-2) allowed during MVP
    # Set to empty string to disable coverage restriction
    coverage_enabled: bool = True
    coverage_countries: str = "ES"  # Spain only for MVP. Add "PT,FR,IT" to expand
    # Non user-facing guidance for the agent when a query is outside coverage.
    # The agent (LLM) should generate the final friendly user response in the user's language.
    coverage_policy_note: str = (
        "During MVP, if the user requests a plan outside the configured coverage countries, "
        "politely explain the limitation and ask them to choose a city within coverage."
    )

    # API configuration
    allowed_origins: str = ""  # Comma-separated list of allowed origins

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    @property
    def supported_languages_list(self) -> List[str]:
        """Return parsed list of supported languages."""
        return [lang.strip().lower() for lang in self.supported_languages.split(",") if lang.strip()]

    @property
    def coverage_countries_list(self) -> List[str]:
        """Return parsed list of allowed country codes (uppercase)."""
        if not self.coverage_countries:
            return []
        return [code.strip().upper() for code in self.coverage_countries.split(",") if code.strip()]

    @property
    def allowed_origins_list(self) -> List[str]:
        """Return parsed list of allowed origins."""
        if not self.allowed_origins:
            return [self.frontend_url]
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @field_validator("default_language", mode="before")
    @classmethod
    def _normalize_default_language(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def _ensure_default_language_allowed(self) -> "Settings":
        if self.default_language not in self.supported_languages_list:
            raise ValueError(
                f"DEFAULT_LANGUAGE '{self.default_language}' must exist inside SUPPORTED_LANGUAGES ({self.supported_languages})"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""

    return Settings()  # type: ignore[call-arg]

