-- Migration 010: dead-letter queue for receipt tasks that exceeded max retries
-- Stores task payload + last error so admins can manually replay or investigate.

CREATE TABLE IF NOT EXISTS receipt_task_dlq (
    id BIGSERIAL PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    chat_id BIGINT,
    message_id BIGINT,
    payload_json TEXT NOT NULL,
    error_text TEXT,
    traceback TEXT,
    retries INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    replayed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_receipt_task_dlq_task_id ON receipt_task_dlq (task_id);
CREATE INDEX IF NOT EXISTS idx_receipt_task_dlq_created ON receipt_task_dlq (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_receipt_task_dlq_chat_msg
    ON receipt_task_dlq (chat_id, message_id)
    WHERE chat_id IS NOT NULL AND message_id IS NOT NULL;
