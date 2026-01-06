-- LangGraph Checkpoints for Plan-and-Execute Agent
-- This enables persistent agent state across restarts and multiple workers

CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    parent_id TEXT,
    checkpoint BYTEA NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (thread_id, checkpoint_id)
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_thread ON langgraph_checkpoints(thread_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_parent ON langgraph_checkpoints(parent_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_created ON langgraph_checkpoints(created_at);

-- Cleanup old checkpoints (optional, run periodically)
-- DELETE FROM langgraph_checkpoints WHERE created_at < NOW() - INTERVAL '7 days';

