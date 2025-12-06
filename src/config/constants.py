"""Static constants shared across the agent service."""

from datetime import timedelta

SERVICE_NAME = "Auphere Agent"
SERVICE_DESCRIPTION = "Isolated AI agent microservice that powers query understanding and planning."
DEFAULT_TIMEOUT_SECONDS = 30
HEALTH_CACHE_TTL = timedelta(seconds=5)

MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0

LATITUDE_RANGE = (-90.0, 90.0)
LONGITUDE_RANGE = (-180.0, 180.0)

VALID_BUDGET_LEVELS = {"budget", "normal", "premium"}

CONTEXT_STAGE = "context-validation"

# Place extraction and response limits
MAX_PLACES_PER_RESPONSE = 10  # Maximum places to return to user and save to DB

