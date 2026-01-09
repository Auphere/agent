## Production rollout checklist (auphere-agent)

### 1) Rotate and lock down Google API keys (required)
- Rotate the key that appeared in logs.
- Restrict the key:
  - **API restrictions**: enable only the required APIs (at minimum Distance Matrix / Places as used).
  - **Application restrictions**: IP allowlist (server IPs / NAT egress) for backend usage.
- Verify no logs contain `key=` after deploy (logs are now scrubbed, but treat this as defense-in-depth).

### 2) Deploy + verify partial-plan behavior on timeouts
- Trigger a slow PLAN request (e.g., heavy tool usage / external slowness).
- Expected behavior:
  - If the Supervisor times out, the response should still include the latest `plan` from LangGraph checkpoints (`agent_type=plan_partial`).
  - PostHog event `agent_degraded` should fire with `reason=timeout` and `has_partial_plan=true`.

### 3) PostHog dashboards (recommended)
Create dashboards/insights based on these events:
- **`agent_stage_timing`**: p50/p95 `latency_ms` by `stage` and `intent`
- **`agent_degraded`**: rate over time + breakdown by `intent`
- **Total latency**: use `metadata.processing_time_ms` from the SSE `end` payload if you also send it to PostHog (optional),
  or derive from stage timings.

Suggested alerts:
- `agent_degraded` rate over 5m > threshold
- p95 `agent_stage_timing` where `stage=agent_execution` > threshold

### 4) Dev verification commands
These require installing dependencies in the environment:

```bash
cd auphere-agent
python -m pip install -r requirements.txt
pytest -q
```


