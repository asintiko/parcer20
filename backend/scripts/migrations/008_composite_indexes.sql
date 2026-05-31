-- Migration 008: composite indexes for analytics + agent + receipt tasks
-- Read-side optimisation. Each index is concurrent + IF NOT EXISTS so it's safe to re-run.

-- Analytics: top operators / applications / sources per period
CREATE INDEX IF NOT EXISTS idx_transactions_app_date
    ON transactions (application_mapped, transaction_date);

CREATE INDEX IF NOT EXISTS idx_transactions_source_chat_date
    ON transactions (source_chat_id, transaction_date);

CREATE INDEX IF NOT EXISTS idx_transactions_currency_date
    ON transactions (currency, transaction_date);

-- Keyset paging tie-breaker
CREATE INDEX IF NOT EXISTS idx_transactions_date_id
    ON transactions (transaction_date, id);

-- Agent: watchdog sweep (status + updated_at)
CREATE INDEX IF NOT EXISTS idx_agent_runs_status_updated
    ON agent_runs (status, updated_at);

-- Agent: "is there an active run on this thread?" check
CREATE INDEX IF NOT EXISTS idx_agent_runs_thread_status
    ON agent_runs (thread_id, status);

-- Agent: history replay (thread + role filter + chronological)
CREATE INDEX IF NOT EXISTS idx_agent_messages_thread_role_created
    ON agent_messages (thread_id, role, created_at DESC);

-- Receipt processing: single-delete cleanup uses transaction_id; bulk delete needs same
CREATE INDEX IF NOT EXISTS idx_receipt_tasks_transaction_id
    ON receipt_processing_tasks (transaction_id);

-- Receipt watchdog: status + updated_at
CREATE INDEX IF NOT EXISTS idx_receipt_tasks_status_updated
    ON receipt_processing_tasks (status, updated_at);

-- Logs page: parsing failures by recency
CREATE INDEX IF NOT EXISTS idx_parsing_logs_status_created
    ON parsing_logs (success, created_at DESC);
