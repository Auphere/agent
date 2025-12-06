"""
Performance metrics tracking and cost estimation.
Provides real-time monitoring of agent performance and API costs.
"""

from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Dict, List, Optional
from uuid import UUID

from src.config.models_config import MODEL_PROFILES
from src.utils.logger import get_logger


@dataclass
class QueryMetrics:
    """Metrics for a single query execution."""

    query_id: str
    user_id: UUID
    session_id: UUID

    # Timing
    start_time: float = field(default_factory=perf_counter)
    end_time: Optional[float] = None
    processing_time_ms: int = 0

    # Classification
    intention: Optional[str] = None
    confidence: float = 0.0
    complexity: str = "unknown"

    # Routing
    model_used: Optional[str] = None
    model_provider: Optional[str] = None

    # Execution
    tool_calls: int = 0
    reasoning_steps: int = 0
    places_found: int = 0

    # Costs (estimated)
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0

    # Status
    success: bool = True
    error: Optional[str] = None

    def mark_end(self) -> None:
        """Mark the end time and calculate processing time."""
        self.end_time = perf_counter()
        self.processing_time_ms = int((self.end_time - self.start_time) * 1000)

    def estimate_cost(self) -> float:
        """
        Estimate API cost based on model and token usage.

        Returns:
            Estimated cost in USD
        """
        if not self.model_used:
            return 0.0

        profile = MODEL_PROFILES.get(self.model_used)
        if not profile:
            return 0.0

        # Calculate total tokens (input + output)
        total_tokens = self.input_tokens + self.output_tokens

        # Calculate cost (cost_per_1k * tokens / 1000)
        cost = profile.cost_per_1k * (total_tokens / 1000)

        self.estimated_cost_usd = cost
        return cost

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "query_id": self.query_id,
            "user_id": str(self.user_id),
            "session_id": str(self.session_id),
            "processing_time_ms": self.processing_time_ms,
            "intention": self.intention,
            "confidence": self.confidence,
            "complexity": self.complexity,
            "model_used": self.model_used,
            "model_provider": self.model_provider,
            "tool_calls": self.tool_calls,
            "reasoning_steps": self.reasoning_steps,
            "places_found": self.places_found,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "success": self.success,
            "error": self.error,
        }


class MetricsCollector:
    """
    Collects and aggregates metrics over time.
    Provides real-time statistics and cost tracking.
    """

    def __init__(self):
        """Initialize metrics collector."""
        self.logger = get_logger("metrics")
        self.queries: List[QueryMetrics] = []
        self._start_time = datetime.utcnow()

    def record_query(self, metrics: QueryMetrics) -> None:
        """
        Record a completed query's metrics.

        Args:
            metrics: Query metrics to record
        """
        self.queries.append(metrics)

        self.logger.info(
            "query_metrics_recorded",
            query_id=metrics.query_id,
            processing_time_ms=metrics.processing_time_ms,
            intention=metrics.intention,
            model=metrics.model_used,
            cost=metrics.estimated_cost_usd,
            success=metrics.success,
        )

    def get_summary(self, last_n: Optional[int] = None) -> dict:
        """
        Get aggregated metrics summary.

        Args:
            last_n: Optional limit to last N queries

        Returns:
            Summary dict with aggregated statistics
        """
        queries = self.queries[-last_n:] if last_n else self.queries

        if not queries:
            return {
                "total_queries": 0,
                "uptime_seconds": (datetime.utcnow() - self._start_time).seconds,
            }

        successful = [q for q in queries if q.success]
        failed = [q for q in queries if not q.success]

        # Calculate averages
        avg_processing_time = (
            sum(q.processing_time_ms for q in queries) / len(queries)
            if queries
            else 0
        )
        avg_confidence = (
            sum(q.confidence for q in queries) / len(queries) if queries else 0
        )
        total_cost = sum(q.estimated_cost_usd for q in queries)

        # Count by intention
        by_intention = {}
        for q in queries:
            if q.intention:
                by_intention[q.intention] = by_intention.get(q.intention, 0) + 1

        # Count by model
        by_model = {}
        for q in queries:
            if q.model_used:
                by_model[q.model_used] = by_model.get(q.model_used, 0) + 1

        # Calculate success rate
        success_rate = len(successful) / len(queries) if queries else 0

        return {
            "total_queries": len(queries),
            "successful_queries": len(successful),
            "failed_queries": len(failed),
            "success_rate": round(success_rate, 3),
            "avg_processing_time_ms": round(avg_processing_time, 2),
            "avg_confidence": round(avg_confidence, 3),
            "total_cost_usd": round(total_cost, 4),
            "avg_cost_per_query_usd": round(
                total_cost / len(queries) if queries else 0, 6
            ),
            "by_intention": by_intention,
            "by_model": by_model,
            "uptime_seconds": (datetime.utcnow() - self._start_time).seconds,
        }

    def get_cost_breakdown(self) -> Dict[str, float]:
        """
        Get cost breakdown by model.

        Returns:
            Dict mapping model names to total costs
        """
        costs = {}
        for q in self.queries:
            if q.model_used:
                costs[q.model_used] = (
                    costs.get(q.model_used, 0.0) + q.estimated_cost_usd
                )
        return costs

    def get_performance_stats(self) -> dict:
        """
        Get detailed performance statistics.

        Returns:
            Dict with P50, P95, P99 latencies and other stats
        """
        if not self.queries:
            return {}

        processing_times = sorted([q.processing_time_ms for q in self.queries])
        n = len(processing_times)

        def percentile(p: float) -> int:
            idx = int(n * p)
            return processing_times[min(idx, n - 1)]

        return {
            "latency_p50_ms": percentile(0.5),
            "latency_p95_ms": percentile(0.95),
            "latency_p99_ms": percentile(0.99),
            "min_latency_ms": min(processing_times),
            "max_latency_ms": max(processing_times),
            "total_tool_calls": sum(q.tool_calls for q in self.queries),
            "total_reasoning_steps": sum(q.reasoning_steps for q in self.queries),
            "total_places_found": sum(q.places_found for q in self.queries),
        }

    def clear(self) -> None:
        """Clear all recorded metrics."""
        self.queries.clear()
        self._start_time = datetime.utcnow()
        self.logger.info("metrics_cleared")


# Global metrics collector instance
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """
    Get or create global metrics collector.

    Returns:
        Singleton MetricsCollector instance
    """
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector

