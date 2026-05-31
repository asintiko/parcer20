-- Migration 009: drop duplicate indexes + add safety indexes
-- Each statement is idempotent.

-- 1. Drop duplicates: UNIQUE constraints already create btree indexes.
DROP INDEX IF EXISTS idx_transactions_source_msg;        -- duplicate of uq_transactions_source_msg
DROP INDEX IF EXISTS idx_transactions_fingerprint;       -- replaced by partial uq_transactions_fingerprint (mig 007)
DROP INDEX IF EXISTS idx_tg_chat_messages_chat_msg;      -- duplicate of uq_tg_chat_messages_chat_message

-- 2. Replace heavy full b-tree on nullable cols with partial WHERE NOT NULL.
-- Postgres-only: skipped silently if index already partial.
DROP INDEX IF EXISTS idx_transactions_card;
CREATE INDEX IF NOT EXISTS idx_transactions_card
    ON transactions (card_last_4)
    WHERE card_last_4 IS NOT NULL;

DROP INDEX IF EXISTS idx_transactions_app;
CREATE INDEX IF NOT EXISTS idx_transactions_app
    ON transactions (application_mapped)
    WHERE application_mapped IS NOT NULL;

DROP INDEX IF EXISTS idx_transactions_receiver_card;
CREATE INDEX IF NOT EXISTS idx_transactions_receiver_card
    ON transactions (receiver_card)
    WHERE receiver_card IS NOT NULL;

DROP INDEX IF EXISTS idx_transactions_receiver_name;
CREATE INDEX IF NOT EXISTS idx_transactions_receiver_name
    ON transactions (receiver_name)
    WHERE receiver_name IS NOT NULL;

-- 3. Partial unique on message_hash to avoid race-condition duplicate ingestion
--    while keeping NULL-tolerant inserts (legacy rows).
CREATE UNIQUE INDEX IF NOT EXISTS uq_tg_chat_messages_message_hash
    ON tg_chat_messages (message_hash)
    WHERE message_hash IS NOT NULL;

-- 4. Index for `parsing_logs` failure analysis page.
DROP INDEX IF EXISTS idx_parsing_logs_failures;
CREATE INDEX IF NOT EXISTS idx_parsing_logs_failures
    ON parsing_logs (created_at DESC)
    WHERE success = FALSE;
