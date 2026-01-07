"""
Structured metrics collection for agent monitoring.

This module provides structured metrics collection that can be:
- Logged as structured JSON
- Exported to monitoring systems (Prometheus, DataDog, etc.)
- Used for debugging and performance analysis

Metrics collected:
- Agent execution time
- Tool call duration
- LLM call latency
- Error rates
- Cache hit rates
- Token usage
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from time import perf_counter
from typing import Any, Dict, List, Optional, Callable
from functools import wraps

from src.utils.logger import get_logger

logger = get_logger("metrics")


@dataclass
class MetricEvent:
    """A single metric event."""
    name: str
    value: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    tags: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
            "tags": self.tags,
        }


@dataclass  
class AgentMetrics:
    """Metrics for a single agent execution."""
    agent_type: str
    query_hash: str  # Anonymized query identifier
    start_time: datetime
    end_time: Optional[datetime] = None
    
    # Timing
    total_duration_ms: float = 0.0
    llm_duration_ms: float = 0.0
    tool_duration_ms: float = 0.0
    
    # Counts
    llm_calls: int = 0
    tool_calls: int = 0
    retry_count: int = 0
    
    # Results
    success: bool = False
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    places_found: int = 0
    
    # Model info
    model_used: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["start_time"] = self.start_time.isoformat() if self.start_time else None
        data["end_time"] = self.end_time.isoformat() if self.end_time else None
        return data


@dataclass
class QueryMetrics:
    """
    Metrics for a single API query request.
    
    Tracks the full lifecycle of a query from receipt to response,
    including classification, model selection, and cost estimation.
    """
    query_id: str
    user_id: str
    session_id: Any  # UUID
    
    # Timing
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    processing_time_ms: float = 0.0
    
    # Classification
    intention: Optional[str] = None
    confidence: float = 0.0
    complexity: Optional[str] = None
    
    # Model info
    model_used: Optional[str] = None
    model_provider: Optional[str] = None
    
    # Execution
    tool_calls: int = 0
    reasoning_steps: int = 0
    places_found: int = 0
    
    # Tokens (estimated)
    input_tokens: float = 0.0
    output_tokens: float = 0.0
    
    # Cost
    estimated_cost_usd: float = 0.0
    
    # Result
    success: bool = True
    error: Optional[str] = None
    
    def mark_end(self) -> None:
        """Mark the end time of the query."""
        self.end_time = datetime.utcnow()
        if self.start_time:
            delta = (self.end_time - self.start_time).total_seconds() * 1000
            if self.processing_time_ms == 0:
                self.processing_time_ms = delta
    
    def estimate_cost(self) -> None:
        """
        Estimate the cost of the query based on tokens and model.
        
        Pricing (approximate, per 1M tokens):
        - gpt-4o: $2.50 input, $10.00 output
        - gpt-4o-mini: $0.15 input, $0.60 output
        - gpt-4-turbo: $10.00 input, $30.00 output
        """
        model = self.model_used or "gpt-4o-mini"
        
        # Cost per 1K tokens
        pricing = {
            "gpt-4o": {"input": 0.0025, "output": 0.01},
            "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
            "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        }
        
        rates = pricing.get(model, pricing["gpt-4o-mini"])
        
        input_cost = (self.input_tokens / 1000) * rates["input"]
        output_cost = (self.output_tokens / 1000) * rates["output"]
        
        self.estimated_cost_usd = round(input_cost + output_cost, 6)
    
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["start_time"] = self.start_time.isoformat() if self.start_time else None
        data["end_time"] = self.end_time.isoformat() if self.end_time else None
        data["session_id"] = str(self.session_id) if self.session_id else None
        return data


class MetricsCollector:
    """
    Collects and manages metrics for the agent system.
    
    Usage:
        collector = get_metrics_collector()
        
        # Record a timing metric
        collector.record_timing("agent.recommend.execution", 1234.5, {"intent": "recommend"})
        
        # Record a counter
        collector.increment("agent.recommend.success", {"model": "gpt-4o-mini"})
        
        # Context manager for timing
        with collector.timer("llm_call", tags={"model": "gpt-4o"}):
            result = await llm.ainvoke(messages)
    """
    
    def __init__(self):
        self._timings: Dict[str, List[float]] = defaultdict(list)
        self._counters: Dict[str, int] = defaultdict(int)
        self._current_metrics: Optional[AgentMetrics] = None
    
    def record_timing(
        self, 
        name: str, 
        value_ms: float,
        tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Record a timing metric in milliseconds."""
        self._timings[name].append(value_ms)
        
        logger.debug(
            "metric-timing",
            name=name,
            value_ms=round(value_ms, 2),
            **(tags or {})
        )
    
    def increment(
        self,
        name: str,
        tags: Optional[Dict[str, str]] = None,
        value: int = 1
    ) -> None:
        """Increment a counter metric."""
        self._counters[name] += value
        
        logger.debug(
            "metric-counter",
            name=name,
            value=self._counters[name],
            **(tags or {})
        )
    
    def timer(self, name: str, tags: Optional[Dict[str, str]] = None):
        """Context manager for timing operations."""
        return TimerContext(self, name, tags)
    
    def start_agent_execution(
        self,
        agent_type: str,
        query: str,
    ) -> AgentMetrics:
        """Start tracking metrics for an agent execution."""
        import hashlib
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:8]
        
        self._current_metrics = AgentMetrics(
            agent_type=agent_type,
            query_hash=query_hash,
            start_time=datetime.utcnow(),
        )
        return self._current_metrics
    
    def end_agent_execution(
        self,
        metrics: AgentMetrics,
        success: bool,
        error: Optional[Exception] = None
    ) -> AgentMetrics:
        """Complete tracking for an agent execution."""
        metrics.end_time = datetime.utcnow()
        metrics.success = success
        
        if error:
            metrics.error_type = type(error).__name__
            metrics.error_message = str(error)[:200]  # Truncate for logging
        
        if metrics.start_time:
            duration = (metrics.end_time - metrics.start_time).total_seconds() * 1000
            metrics.total_duration_ms = duration
        
        # Log the complete metrics
        logger.info(
            "agent-execution-complete",
            **metrics.to_dict()
        )
        
        # Record aggregate metrics
        self.record_timing(
            f"agent.{metrics.agent_type}.duration",
            metrics.total_duration_ms,
            {"success": str(success)}
        )
        
        status = "success" if success else "error"
        self.increment(
            f"agent.{metrics.agent_type}.{status}",
            {"model": metrics.model_used}
        )
        
        return metrics
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics for all collected metrics."""
        summary = {}
        
        for name, values in self._timings.items():
            if values:
                summary[f"{name}_count"] = len(values)
                summary[f"{name}_avg_ms"] = sum(values) / len(values)
                summary[f"{name}_min_ms"] = min(values)
                summary[f"{name}_max_ms"] = max(values)
        
        for name, count in self._counters.items():
            summary[name] = count
        
        return summary
    
    def reset(self) -> None:
        """Reset all metrics."""
        self._timings.clear()
        self._counters.clear()
        self._current_metrics = None
    
    def record_query(self, query_metrics: QueryMetrics) -> None:
        """
        Record metrics for a completed query.
        
        Args:
            query_metrics: The completed QueryMetrics object
        """
        # Record timing
        self.record_timing(
            "query.processing",
            query_metrics.processing_time_ms,
            {
                "intention": query_metrics.intention or "unknown",
                "model": query_metrics.model_used or "unknown",
                "success": str(query_metrics.success),
            }
        )
        
        # Record counters
        status = "success" if query_metrics.success else "error"
        self.increment(f"query.{status}")
        
        if query_metrics.tool_calls > 0:
            self.increment("query.with_tools")
        
        # Log the query metrics
        logger.info(
            "query-metrics-recorded",
            query_id=query_metrics.query_id,
            intention=query_metrics.intention,
            model=query_metrics.model_used,
            processing_time_ms=round(query_metrics.processing_time_ms, 2),
            tool_calls=query_metrics.tool_calls,
            places_found=query_metrics.places_found,
            estimated_cost=query_metrics.estimated_cost_usd,
            success=query_metrics.success,
        )


class TimerContext:
    """Context manager for timing operations."""
    
    def __init__(
        self, 
        collector: MetricsCollector, 
        name: str,
        tags: Optional[Dict[str, str]] = None
    ):
        self.collector = collector
        self.name = name
        self.tags = tags or {}
        self.start_time: float = 0
    
    def __enter__(self) -> 'TimerContext':
        self.start_time = perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        duration_ms = (perf_counter() - self.start_time) * 1000
        
        if exc_type:
            self.tags["error"] = exc_type.__name__
        
        self.collector.record_timing(self.name, duration_ms, self.tags)
    
    async def __aenter__(self) -> 'TimerContext':
        return self.__enter__()
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.__exit__(exc_type, exc_val, exc_tb)


# Singleton instance
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector instance."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def timed(name: Optional[str] = None, tags: Optional[Dict[str, str]] = None) -> Callable:
    """
    Decorator to time function execution.
    
    Usage:
        @timed("my_function")
        async def my_function():
            ...
    """
    def decorator(func: Callable) -> Callable:
        metric_name = name or f"function.{func.__name__}"
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            collector = get_metrics_collector()
            start = perf_counter()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration_ms = (perf_counter() - start) * 1000
                collector.record_timing(metric_name, duration_ms, tags)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            collector = get_metrics_collector()
            start = perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration_ms = (perf_counter() - start) * 1000
                collector.record_timing(metric_name, duration_ms, tags)
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator
