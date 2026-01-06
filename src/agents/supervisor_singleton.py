"""Process-wide singleton accessor for SupervisorAgent.

Why: Creating SupervisorAgent (and its specialized agents) per-request can lead to:
- Repeated LangGraph checkpointer pool creation
- Pending background tasks on shutdown/GC (psycopg_pool workers)

This keeps the existing architecture (SupervisorAgent + specialized agents),
but ensures a single instance per process for robustness and scalability.
"""

from __future__ import annotations

from functools import lru_cache

from src.agents.supervisor_agent import SupervisorAgent


@lru_cache
def get_supervisor_agent() -> SupervisorAgent:
    """Return a process-wide SupervisorAgent singleton."""
    return SupervisorAgent()


