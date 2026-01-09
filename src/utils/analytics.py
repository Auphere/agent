"""
PostHog Analytics for Auphere Agent

Handles agent-specific analytics tracking:
- Agent invocation events
- LLM request/response metrics
- Tool call tracking
- Plan generation metrics
- Language detection events
- Response consistency tracking

Environment modes:
- Development (ENVIRONMENT=development): Console logging only (no PostHog)
- Production (ENVIRONMENT=production): PostHog Cloud tracking

Usage:
    from src.utils.analytics import agent_analytics, track_agent_event
    
    # Track agent invocation
    track_agent_invoked(session_id='123', agent_type='recommend', intent='search')
    
    # Track LLM request
    track_llm_request(model='gpt-4o-mini', tokens_in=500, temperature=0.5)
"""

import json
import time
from typing import Any, Dict, List, Optional
from functools import wraps

from src.config.settings import get_settings
from src.utils.logger import get_logger

logger = get_logger("analytics")

# PostHog Python SDK (optional in development)
try:
    from posthog import Posthog
    POSTHOG_AVAILABLE = True
except ImportError:
    POSTHOG_AVAILABLE = False
    Posthog = None


# Initialize PostHog client
_posthog_client: Optional["Posthog"] = None
_is_production: bool = False


def _init_analytics() -> None:
    """Initialize analytics based on environment."""
    global _posthog_client, _is_production
    
    settings = get_settings()
    _is_production = settings.environment.lower() == "production"
    
    if not _is_production:
        logger.info("analytics-mode", mode="development", action="console_logging")
        return
    
    if not POSTHOG_AVAILABLE:
        logger.warning("posthog-sdk-not-installed", mode="production")
        return
    
    if not settings.posthog_enabled:
        logger.info("posthog-disabled-by-config")
        return
    
    api_key = settings.posthog_api_key
    if not api_key:
        logger.warning("posthog-api-key-missing", mode="production")
        return
    
    host = settings.posthog_host
    
    _posthog_client = Posthog(
        api_key=api_key,
        host=host,
        debug=False,
    )
    
    logger.info("posthog-initialized", host=host)


def get_posthog_client() -> Optional["Posthog"]:
    """Get or initialize the PostHog client singleton."""
    global _posthog_client
    
    if _posthog_client is None and _is_production:
        _init_analytics()
    
    return _posthog_client


def is_analytics_enabled() -> bool:
    """Check if analytics is configured and enabled."""
    return _is_production and get_posthog_client() is not None


def _log_event_local(event_name: str, user_id: Optional[str], properties: Dict[str, Any]) -> None:
    """Log event to console in development mode."""
    logger.info(
        f"📊 analytics-event: {event_name}",
        user_id=user_id or "anonymous",
        properties=properties,
    )


# =============================================================================
# Core Tracking Functions
# =============================================================================

def track_event(
    event_name: str,
    user_id: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Track a custom event.
    
    In development: logs to console
    In production: sends to PostHog Cloud
    
    Args:
        event_name: Name of the event
        user_id: User identifier (optional for anonymous events)
        properties: Event properties
    """
    props = properties or {}
    
    # Development: console logging
    if not _is_production:
        _log_event_local(event_name, user_id, props)
        return
    
    # Production: PostHog Cloud
    client = get_posthog_client()
    if not client:
        return
    
    try:
        client.capture(
            distinct_id=user_id or 'anonymous',
            event=event_name,
            properties=props,
        )
    except Exception as e:
        logger.error("posthog-capture-failed", event=event_name, error=str(e))


# =============================================================================
# Agent-Specific Events
# =============================================================================

def track_agent_invoked(
    session_id: str,
    agent_type: str,
    intent: str,
    user_id: Optional[str] = None,
    query_length: int = 0,
    language: str = "unknown",
    query_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> None:
    """Track agent invocation."""
    track_event(
        'agent_invoked',
        user_id=user_id,
        properties={
            'session_id': session_id,
            'agent_type': agent_type,
            'intent': intent,
            'query_length': query_length,
            'language': language,
            'query_id': query_id,
            'request_id': request_id,
        },
    )


def track_llm_request(
    model: str,
    tokens_in: int,
    temperature: float,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    query_id: Optional[str] = None,
) -> None:
    """Track LLM request (before call)."""
    track_event(
        'llm_request',
        user_id=user_id,
        properties={
            'model': model,
            'tokens_in': tokens_in,
            'temperature': temperature,
            'session_id': session_id,
            'query_id': query_id,
        },
    )


def track_llm_response(
    model: str,
    tokens_out: int,
    latency_ms: float,
    cost: Optional[float] = None,
    success: bool = True,
    error: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    query_id: Optional[str] = None,
) -> None:
    """Track LLM response (after call)."""
    track_event(
        'llm_response',
        user_id=user_id,
        properties={
            'model': model,
            'tokens_out': tokens_out,
            'latency_ms': latency_ms,
            'cost': cost,
            'success': success,
            'error': error,
            'session_id': session_id,
            'query_id': query_id,
        },
    )


def track_tool_called(
    tool_name: str,
    success: bool,
    latency_ms: float,
    error: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    query_id: Optional[str] = None,
) -> None:
    """Track tool call execution."""
    track_event(
        'tool_called',
        user_id=user_id,
        properties={
            'tool_name': tool_name,
            'success': success,
            'latency_ms': latency_ms,
            'error': error,
            'session_id': session_id,
            'query_id': query_id,
        },
    )


def track_plan_generated(
    stops_count: int,
    city: str,
    vibes: Optional[List[str]] = None,
    budget: Optional[float] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    latency_ms: Optional[float] = None,
    query_id: Optional[str] = None,
) -> None:
    """Track plan generation."""
    track_event(
        'plan_generated',
        user_id=user_id,
        properties={
            'stops_count': stops_count,
            'city': city,
            'vibes': vibes or [],
            'budget': budget,
            'session_id': session_id,
            'latency_ms': latency_ms,
            'query_id': query_id,
        },
    )


def track_missing_info_asked(
    fields_missing: List[str],
    turn_number: int,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """Track when agent asks for missing information."""
    track_event(
        'missing_info_asked',
        user_id=user_id,
        properties={
            'fields_missing': fields_missing,
            'turn_number': turn_number,
            'session_id': session_id,
        },
    )


def track_language_detected(
    detected_lang: str,
    is_supported: bool,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    query_id: Optional[str] = None,
) -> None:
    """Track language detection."""
    track_event(
        'language_detected',
        user_id=user_id,
        properties={
            'detected_lang': detected_lang,
            'is_supported': is_supported,
            'session_id': session_id,
            'query_id': query_id,
        },
    )


def track_language_fallback(
    original_lang: str,
    fallback_to: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """Track language fallback (unsupported -> English)."""
    track_event(
        'language_fallback',
        user_id=user_id,
        properties={
            'original_lang': original_lang,
            'fallback_to': fallback_to,
            'session_id': session_id,
        },
    )


def track_response_count_mismatch(
    mentioned: int,
    actual: int,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """Track response count mismatch (consistency bug)."""
    track_event(
        'response_count_mismatch',
        user_id=user_id,
        properties={
            'mentioned': mentioned,
            'actual': actual,
            'session_id': session_id,
        },
    )


def track_results_returned(
    count: int,
    query_type: str,
    ranking_threshold: float,
    user_requested_count: Optional[int] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """Track results returned count."""
    track_event(
        'results_returned',
        user_id=user_id,
        properties={
            'count': count,
            'query_type': query_type,
            'ranking_threshold': ranking_threshold,
            'user_requested_count': user_requested_count,
            'session_id': session_id,
        },
    )


def track_agent_error(
    agent_type: str,
    error_type: str,
    error_message: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    query_id: Optional[str] = None,
) -> None:
    """Track agent error."""
    track_event(
        'agent_error',
        user_id=user_id,
        properties={
            'agent_type': agent_type,
            'error_type': error_type,
            'error_message': error_message,
            'session_id': session_id,
            'query_id': query_id,
        },
    )


def track_stage_timing(
    *,
    stage: str,
    latency_ms: float,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    query_id: Optional[str] = None,
    agent_type: Optional[str] = None,
    intent: Optional[str] = None,
) -> None:
    """Track timing for a single pipeline stage (for latency breakdown)."""
    track_event(
        "agent_stage_timing",
        user_id=user_id,
        properties={
            "stage": stage,
            "latency_ms": float(latency_ms),
            "session_id": session_id,
            "query_id": query_id,
            "agent_type": agent_type,
            "intent": intent,
        },
    )


def track_agent_degraded(
    *,
    reason: str,
    total_ms: float,
    has_partial_plan: bool,
    steps_completed: Optional[int] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    query_id: Optional[str] = None,
    agent_type: Optional[str] = None,
    intent: Optional[str] = None,
) -> None:
    """Track when the agent degrades (e.g., timeout -> partial plan)."""
    track_event(
        "agent_degraded",
        user_id=user_id,
        properties={
            "reason": reason,
            "total_ms": float(total_ms),
            "has_partial_plan": bool(has_partial_plan),
            "steps_completed": steps_completed,
            "session_id": session_id,
            "query_id": query_id,
            "agent_type": agent_type,
            "intent": intent,
        },
    )


# =============================================================================
# Decorator for LLM Call Tracking
# =============================================================================

def track_llm_call(model: str):
    """
    Decorator to track LLM calls.
    
    Usage:
        @track_llm_call(model='gpt-4o-mini')
        async def my_llm_function(...):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            error = None
            result = None
            
            # Try to extract session_id and user_id from kwargs
            session_id = kwargs.get('session_id')
            user_id = kwargs.get('user_id')
            
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                error = str(e)
                raise
            finally:
                latency_ms = (time.time() - start_time) * 1000
                
                track_llm_response(
                    model=model,
                    tokens_out=0,  # Would need to extract from result
                    latency_ms=latency_ms,
                    success=error is None,
                    error=error,
                    user_id=user_id,
                    session_id=session_id,
                )
        
        return wrapper
    return decorator


def track_tool_execution(tool_name: str):
    """
    Decorator to track tool execution.
    
    Usage:
        @track_tool_execution(tool_name='places_search_tool')
        async def search_places(...):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            error = None
            
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                error = str(e)
                raise
            finally:
                latency_ms = (time.time() - start_time) * 1000
                
                track_tool_called(
                    tool_name=tool_name,
                    success=error is None,
                    latency_ms=latency_ms,
                    error=error,
                )
        
        return wrapper
    return decorator


# =============================================================================
# Shutdown Handler
# =============================================================================

def shutdown_analytics() -> None:
    """
    Flush and shutdown PostHog client.
    Call this on application shutdown.
    """
    global _posthog_client
    if _posthog_client:
        _posthog_client.shutdown()
        _posthog_client = None
        logger.info("posthog-shutdown")


# =============================================================================
# Analytics Object (convenient interface)
# =============================================================================

class AgentAnalytics:
    """Convenient interface for agent analytics tracking."""
    
    @staticmethod
    def is_enabled() -> bool:
        return is_analytics_enabled()
    
    @staticmethod
    def track(event_name: str, user_id: Optional[str] = None, properties: Optional[Dict[str, Any]] = None) -> None:
        track_event(event_name, user_id, properties)
    
    # Agent-specific
    track_agent_invoked = staticmethod(track_agent_invoked)
    track_llm_request = staticmethod(track_llm_request)
    track_llm_response = staticmethod(track_llm_response)
    track_tool_called = staticmethod(track_tool_called)
    track_plan_generated = staticmethod(track_plan_generated)
    track_missing_info_asked = staticmethod(track_missing_info_asked)
    track_language_detected = staticmethod(track_language_detected)
    track_language_fallback = staticmethod(track_language_fallback)
    track_response_count_mismatch = staticmethod(track_response_count_mismatch)
    track_results_returned = staticmethod(track_results_returned)
    track_agent_error = staticmethod(track_agent_error)
    
    @staticmethod
    def shutdown() -> None:
        shutdown_analytics()


agent_analytics = AgentAnalytics()


# Initialize on module load
_init_analytics()
