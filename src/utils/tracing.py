"""
LangSmith Tracing Configuration.

LangSmith provides observability for LLM applications:
- Trace all LLM calls
- Debug agent reasoning
- Monitor latency and costs
- Analyze conversation patterns

Setup:
1. Get API key from https://smith.langchain.com/
2. Set LANGSMITH_API_KEY in environment
3. Set LANGSMITH_TRACING_ENABLED=true

The tracing is automatic once configured - no code changes needed.

Best Practices:
- Call configure_langsmith() BEFORE creating any LLM instances
- Use @trace_agent_operation decorator for custom tracing
- Set meaningful project names for different environments
"""

import os
from functools import wraps
from typing import Optional, Callable, Any

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger

logger = get_logger("tracing")

# Track if tracing has been configured
_tracing_configured = False
_tracing_enabled = False


def configure_langsmith(settings: Optional[Settings] = None) -> bool:
    """
    Configure LangSmith tracing via environment variables.
    
    LangChain/LangGraph automatically pick up these environment variables.
    This function must be called BEFORE creating any LLM instances.
    
    Args:
        settings: Application settings (optional)
        
    Returns:
        True if tracing was enabled, False otherwise
    """
    global _tracing_configured, _tracing_enabled
    
    if _tracing_configured:
        return _tracing_enabled
    
    settings = settings or get_settings()
    
    if not settings.langsmith_tracing_enabled:
        logger.info("langsmith-tracing-disabled")
        _tracing_configured = True
        _tracing_enabled = False
        return False
    
    if not settings.langsmith_api_key:
        logger.warning(
            "langsmith-api-key-not-configured",
            hint="Set LANGSMITH_API_KEY in .env to enable tracing"
        )
        _tracing_configured = True
        _tracing_enabled = False
        return False
    
    # Set environment variables that LangChain uses
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"
    
    logger.info(
        "langsmith-tracing-enabled",
        project=settings.langsmith_project,
    )
    
    _tracing_configured = True
    _tracing_enabled = True
    return True


def is_tracing_enabled() -> bool:
    """Check if LangSmith tracing is enabled."""
    return _tracing_enabled


def trace_agent_operation(
    name: str,
    run_type: str = "chain",
    metadata: Optional[dict] = None
) -> Callable:
    """
    Decorator to trace agent operations with LangSmith.
    
    Usage:
        @trace_agent_operation("recommend-agent", run_type="agent")
        async def run_recommendation(query: str) -> dict:
            ...
    
    Args:
        name: Name for the trace (e.g., "recommend-agent")
        run_type: Type of run ("chain", "agent", "tool", "retriever")
        metadata: Optional metadata to include in trace
        
    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            if not _tracing_enabled:
                return await func(*args, **kwargs)
            
            try:
                from langsmith import traceable
                traced_func = traceable(
                    name=name,
                    run_type=run_type,
                    metadata=metadata or {}
                )(func)
                return await traced_func(*args, **kwargs)
            except ImportError:
                logger.debug("langsmith-not-installed-skipping-trace")
                return await func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"tracing-failed: {e}")
                return await func(*args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            if not _tracing_enabled:
                return func(*args, **kwargs)
            
            try:
                from langsmith import traceable
                traced_func = traceable(
                    name=name,
                    run_type=run_type,
                    metadata=metadata or {}
                )(func)
                return traced_func(*args, **kwargs)
            except ImportError:
                logger.debug("langsmith-not-installed-skipping-trace")
                return func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"tracing-failed: {e}")
                return func(*args, **kwargs)
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def disable_langsmith():
    """
    Disable LangSmith tracing.
    
    Useful for tests or when you want to temporarily disable tracing.
    """
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    logger.info("langsmith-tracing-disabled")


def get_tracing_headers() -> dict:
    """
    Get headers for manual trace propagation if needed.
    
    Returns:
        Dict with tracing headers
    """
    headers = {}
    
    # Add LangSmith run ID if available
    run_id = os.environ.get("LANGCHAIN_RUN_ID")
    if run_id:
        headers["langsmith-run-id"] = run_id
    
    return headers


class TracingContext:
    """
    Context manager for custom trace spans.
    
    Usage:
        with TracingContext("my-operation", metadata={"key": "value"}):
            # Your code here
            pass
    """
    
    def __init__(self, name: str, metadata: Optional[dict] = None):
        self.name = name
        self.metadata = metadata or {}
        self._run_id = None
    
    def __enter__(self):
        """Start trace span."""
        try:
            from langsmith import Client
            
            client = Client()
            # Create a new run
            self._run_id = client.create_run(
                name=self.name,
                run_type="chain",
                inputs=self.metadata,
            )
            return self
        except Exception:
            # Tracing is optional - don't break if it fails
            return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """End trace span."""
        try:
            from langsmith import Client
            
            if self._run_id:
                client = Client()
                client.update_run(
                    self._run_id,
                    outputs={"success": exc_type is None},
                    error=str(exc_val) if exc_val else None,
                )
        except Exception:
            pass
        
        return False  # Don't suppress exceptions


# Convenience function to log custom events
def log_trace_event(
    event_type: str,
    data: dict,
    run_name: Optional[str] = None,
):
    """
    Log a custom event to LangSmith.
    
    Args:
        event_type: Type of event (e.g., "tool_call", "user_feedback")
        data: Event data
        run_name: Optional name for the run
    """
    try:
        from langsmith import Client
        
        client = Client()
        client.create_run(
            name=run_name or f"event:{event_type}",
            run_type="chain",
            inputs=data,
            outputs={"event_type": event_type},
        )
    except Exception as e:
        logger.debug("trace-event-failed", error=str(e))

