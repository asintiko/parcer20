-- Uzbek Receipt Parser Database Schema
-- PostgreSQL 15+

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Table: transactions
-- Stores all parsed receipt data
CREATE TABLE IF NOT EXISTS transactions (
    id BIGSERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    
    -- Raw Data
    raw_message TEXT NOT NULL,
    source_type VARCHAR(20) CHECK (source_type IN ('MANUAL', 'AUTO', 'SMS')) NOT NULL,
    source_chat_id BIGINT NOT NULL,
    source_message_id BIGINT,
    
    -- Parsed Transaction Data
    transaction_date TIMESTAMPTZ NOT NULL,
    amount NUMERIC(18, 2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'UZS' NOT NULL,
    card_last_4 VARCHAR(4),
    operator_raw TEXT,
    application_mapped VARCHAR(100),
    receiver_name VARCHAR(255),
    receiver_card VARCHAR(32),
    transaction_type VARCHAR(20) CHECK (transaction_type IN ('DEBIT', 'CREDIT', 'CONVERSION', 'REVERSAL')) NOT NULL,
    balance_after NUMERIC(18, 2),
    
    -- Metadata
    parsed_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    is_gpt_parsed BOOLEAN DEFAULT FALSE,
    parsing_confidence FLOAT CHECK (parsing_confidence >= 0 AND parsing_confidence <= 1),
    parsing_method VARCHAR(20) CHECK (parsing_method IN ('REGEX_HUMO', 'REGEX_SMS', 'REGEX_SEMICOLON', 'REGEX_CARDXABAR', 'REGEX_TRANSFER', 'GPT', 'GPT_VISION')),
    
    -- Indexing for common queries
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Indexes for performance
CREATE INDEX idx_transactions_date ON transactions(transaction_date DESC);
CREATE INDEX idx_transactions_card ON transactions(card_last_4) WHERE card_last_4 IS NOT NULL;
CREATE INDEX idx_transactions_app ON transactions(application_mapped) WHERE application_mapped IS NOT NULL;
CREATE INDEX idx_transactions_source ON transactions(source_type, source_chat_id);
CREATE INDEX idx_transactions_source_msg ON transactions(source_chat_id, source_message_id);
CREATE INDEX idx_transactions_updated_id ON transactions(updated_at, id);
CREATE INDEX idx_transactions_raw_message_trgm ON transactions USING gin (raw_message gin_trgm_ops);
CREATE INDEX idx_transactions_parsed_at ON transactions(parsed_at DESC);
CREATE INDEX idx_transactions_receiver_card ON transactions(receiver_card) WHERE receiver_card IS NOT NULL;
CREATE INDEX idx_transactions_receiver_name ON transactions(receiver_name) WHERE receiver_name IS NOT NULL;

-- Table: operator_mappings
-- Stores mapping rules from raw operator names to application names
CREATE TABLE IF NOT EXISTS operator_mappings (
    id SERIAL PRIMARY KEY,
    pattern VARCHAR(200) NOT NULL,
    app_name VARCHAR(100) NOT NULL,
    priority INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    
    UNIQUE(pattern)
);

-- Index for fast lookup
CREATE INDEX idx_operator_mappings_pattern ON operator_mappings(pattern) WHERE is_active = TRUE;
CREATE INDEX idx_operator_mappings_priority ON operator_mappings(priority DESC) WHERE is_active = TRUE;

-- Table: parsing_logs
-- Tracks parsing attempts for monitoring and debugging
CREATE TABLE IF NOT EXISTS parsing_logs (
    id BIGSERIAL PRIMARY KEY,
    raw_message TEXT NOT NULL,
    parsing_method VARCHAR(20),
    success BOOLEAN NOT NULL,
    error_message TEXT,
    processing_time_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Index for monitoring recent failures
CREATE INDEX idx_parsing_logs_failures ON parsing_logs(created_at DESC) WHERE success = FALSE;

-- Table: hourly_reports
-- Stores generated hourly reports for audit trail
CREATE TABLE IF NOT EXISTS hourly_reports (
    id BIGSERIAL PRIMARY KEY,
    report_hour TIMESTAMPTZ NOT NULL,
    transaction_count INTEGER NOT NULL,
    total_volume_uzs NUMERIC(18, 2),
    top_application VARCHAR(100),
    top_application_count INTEGER,
    gpt_insight TEXT,
    sent_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    
    UNIQUE(report_hour)
);

-- Table: tg_chat_messages
-- Persisted streamed history for Telegram chats
CREATE TABLE IF NOT EXISTS tg_chat_messages (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    message_date TIMESTAMPTZ,
    is_outgoing BOOLEAN NOT NULL DEFAULT FALSE,
    sender_id BIGINT,
    text TEXT,
    raw_json TEXT NOT NULL,
    receipt_transaction_id BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT uq_tg_chat_messages_chat_message UNIQUE (chat_id, message_id)
);

CREATE INDEX idx_tg_chat_messages_chat_msg ON tg_chat_messages(chat_id, message_id);
CREATE INDEX idx_tg_chat_messages_chat_date ON tg_chat_messages(chat_id, message_date);
CREATE INDEX idx_tg_chat_messages_updated ON tg_chat_messages(updated_at);
CREATE INDEX idx_tg_chat_messages_receipt_tx ON tg_chat_messages(receipt_transaction_id);

-- Table: tg_history_cursors
-- Progress/state per chat for background history load jobs
CREATE TABLE IF NOT EXISTS tg_history_cursors (
    chat_id BIGINT PRIMARY KEY,
    status VARCHAR(20) NOT NULL DEFAULT 'idle',
    cursor_message_id BIGINT NOT NULL DEFAULT 0,
    loaded_count BIGINT NOT NULL DEFAULT 0,
    error TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_tg_history_cursors_status ON tg_history_cursors(status);
CREATE INDEX idx_tg_history_cursors_updated ON tg_history_cursors(updated_at);

-- Full audit v1.3.0: optimistic lock version on automation tasks
ALTER TABLE IF EXISTS automation_tasks
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

-- Reconciliation agent: task_type for automation_tasks
ALTER TABLE IF EXISTS automation_tasks
    ADD COLUMN IF NOT EXISTS task_type VARCHAR(30) DEFAULT 'mapping';

-- Table: reconciliation_suggestions
CREATE TABLE IF NOT EXISTS reconciliation_suggestions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID NOT NULL,
    chat_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    transaction_id BIGINT,
    category VARCHAR(30) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    confidence FLOAT,
    reasoning TEXT,
    payload_json TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT check_reconcile_suggestion_status CHECK (status IN ('pending', 'approved', 'rejected'))
);
CREATE INDEX IF NOT EXISTS idx_reconcile_sug_task ON reconciliation_suggestions(task_id);
CREATE INDEX IF NOT EXISTS idx_reconcile_sug_chat_msg ON reconciliation_suggestions(chat_id, message_id);
CREATE INDEX IF NOT EXISTS idx_reconcile_sug_category ON reconciliation_suggestions(category);
CREATE INDEX IF NOT EXISTS idx_reconcile_sug_tx ON reconciliation_suggestions(transaction_id);

-- Table: duplicate_suggestions
CREATE TABLE IF NOT EXISTS duplicate_suggestions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID,
    primary_transaction_id BIGINT NOT NULL,
    duplicate_transaction_id BIGINT NOT NULL,
    confidence FLOAT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    reasoning TEXT,
    payload_json TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT check_duplicate_suggestion_status CHECK (status IN ('pending', 'approved', 'rejected')),
    CONSTRAINT uq_duplicate_pair UNIQUE (primary_transaction_id, duplicate_transaction_id)
);
CREATE INDEX IF NOT EXISTS idx_duplicate_sug_task ON duplicate_suggestions(task_id);
CREATE INDEX IF NOT EXISTS idx_duplicate_sug_status ON duplicate_suggestions(status);
CREATE INDEX IF NOT EXISTS idx_duplicate_sug_primary ON duplicate_suggestions(primary_transaction_id);
CREATE INDEX IF NOT EXISTS idx_duplicate_sug_dup ON duplicate_suggestions(duplicate_transaction_id);

-- Table: automation_agent_configs
CREATE TABLE IF NOT EXISTS automation_agent_configs (
    id BIGSERIAL PRIMARY KEY,
    agent_name VARCHAR(80) NOT NULL UNIQUE,
    config_json TEXT NOT NULL DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_automation_agent_cfg_name ON automation_agent_configs(agent_name);
CREATE INDEX IF NOT EXISTS idx_automation_agent_cfg_active ON automation_agent_configs(is_active);

-- Sync-deletion cleanup path indexes (safe for IF EXISTS environments)
DO $$
BEGIN
    IF to_regclass('public.sync_deletions') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS idx_sync_deletions_table_deleted_id
            ON sync_deletions(table_name, deleted_at, id);
        CREATE INDEX IF NOT EXISTS idx_sync_deletions_cleanup
            ON sync_deletions(deleted_at, id);
    END IF;
END $$;

-- Table: users
-- Stores RBAC users and per-user permissions snapshot
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(512) NOT NULL,
    salt VARCHAR(128) NOT NULL,
    hash_method VARCHAR(50) NOT NULL DEFAULT 'pbkdf2_sha256',
    role VARCHAR(20) NOT NULL DEFAULT 'operator',
    display_name VARCHAR(100),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    allowed_tabs TEXT NOT NULL DEFAULT '["dashboard"]',
    allowed_folders TEXT NOT NULL DEFAULT '[]',
    forbidden_periods TEXT NOT NULL DEFAULT '[]',
    allowed_sources TEXT NOT NULL DEFAULT '[]',
    can_toggle_sources BOOLEAN NOT NULL DEFAULT FALSE,
    force_2fa BOOLEAN NOT NULL DEFAULT FALSE,
    session_ttl_days INTEGER NOT NULL DEFAULT 7,
    totp_secret VARCHAR(128),
    totp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    totp_confirmed_at TIMESTAMPTZ,
    backup_codes TEXT,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ,
    permissions_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT check_user_role CHECK (role IN ('admin', 'operator')),
    CONSTRAINT check_user_session_ttl_days CHECK (session_ttl_days >= 1 AND session_ttl_days <= 90)
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_role_active ON users(role, is_active);

-- Table: system_settings
-- Runtime global security toggles (single-row table, id=1)
CREATE TABLE IF NOT EXISTS system_settings (
    id INTEGER PRIMARY KEY DEFAULT 1,
    otp_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    bot_control_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    totp_2fa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    launch_gate_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_by INTEGER
);

-- Function: Update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger: Auto-update updated_at on transactions
CREATE TRIGGER update_transactions_updated_at
    BEFORE UPDATE ON transactions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- View: Recent transactions with human-readable formatting
CREATE OR REPLACE VIEW recent_transactions AS
SELECT 
    id,
    to_char(transaction_date, 'DD.MM.YYYY HH24:MI') as formatted_date,
    to_char(transaction_date, 'Dy') as day_of_week,
    amount,
    currency,
    card_last_4 as pk,
    operator_raw,
    application_mapped,
    transaction_type,
    balance_after,
    source_type,
    parsing_method
FROM transactions
ORDER BY transaction_date DESC;

-- Table: agent_threads
CREATE TABLE IF NOT EXISTS agent_threads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_by_user_id BIGINT NOT NULL,
    title VARCHAR(255) NOT NULL DEFAULT 'Новый диалог',
    context_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_threads_user_updated ON agent_threads(created_by_user_id, updated_at);

-- Table: agent_messages
CREATE TABLE IF NOT EXISTS agent_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    thread_id UUID NOT NULL,
    run_id UUID,
    role VARCHAR(20) NOT NULL,
    message_type VARCHAR(30) NOT NULL DEFAULT 'text',
    content_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT check_agent_message_role CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    CONSTRAINT check_agent_message_type CHECK (message_type IN ('text', 'tool_run', 'report', 'confirmation', 'warning', 'navigation'))
);
CREATE INDEX IF NOT EXISTS idx_agent_messages_thread_created ON agent_messages(thread_id, created_at);
CREATE INDEX IF NOT EXISTS ix_agent_messages_run_id ON agent_messages(run_id);

-- Table: agent_runs
CREATE TABLE IF NOT EXISTS agent_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    thread_id UUID NOT NULL,
    created_by_user_id BIGINT NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'queued',
    tool_name VARCHAR(80),
    progress_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,
    error_text TEXT,
    requires_confirmation BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT check_agent_run_status CHECK (status IN ('queued', 'processing', 'awaiting_confirmation', 'completed', 'failed', 'cancelled'))
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_thread_updated ON agent_runs(thread_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_agent_runs_user_created ON agent_runs(created_by_user_id, created_at);

-- Table: agent_reports
CREATE TABLE IF NOT EXISTS agent_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_by_user_id BIGINT NOT NULL,
    thread_id UUID,
    scope VARCHAR(20) NOT NULL DEFAULT 'personal',
    title VARCHAR(255) NOT NULL,
    period_start TIMESTAMPTZ,
    period_end TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'ready',
    summary_json TEXT NOT NULL DEFAULT '{}',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT check_agent_report_scope CHECK (scope IN ('personal', 'team')),
    CONSTRAINT check_agent_report_status CHECK (status IN ('draft', 'ready', 'published', 'archived'))
);
CREATE INDEX IF NOT EXISTS idx_agent_reports_scope_created ON agent_reports(scope, created_at);
CREATE INDEX IF NOT EXISTS ix_agent_reports_thread_id ON agent_reports(thread_id);

-- Table: agent_report_items
CREATE TABLE IF NOT EXISTS agent_report_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    report_id UUID NOT NULL,
    issue_type VARCHAR(80) NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'medium',
    entity_type VARCHAR(80) NOT NULL,
    entity_id VARCHAR(255),
    confidence FLOAT,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    title VARCHAR(255) NOT NULL,
    description TEXT,
    suggested_action_json TEXT NOT NULL DEFAULT '{}',
    assignee_user_id BIGINT,
    claimed_at TIMESTAMPTZ,
    released_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    CONSTRAINT check_agent_report_item_severity CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT check_agent_report_item_status CHECK (status IN ('open', 'claimed', 'released', 'resolved'))
);
CREATE INDEX IF NOT EXISTS idx_agent_report_items_report_status ON agent_report_items(report_id, status);
CREATE INDEX IF NOT EXISTS idx_agent_report_items_assignee_status ON agent_report_items(assignee_user_id, status);

-- Table: agent_notifications
CREATE TABLE IF NOT EXISTS agent_notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    scope VARCHAR(20) NOT NULL DEFAULT 'personal',
    user_id BIGINT,
    report_id UUID,
    report_item_id UUID,
    type VARCHAR(80) NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    read_at TIMESTAMPTZ,
    CONSTRAINT check_agent_notification_scope CHECK (scope IN ('personal', 'team'))
);
CREATE INDEX IF NOT EXISTS idx_agent_notifications_scope_created ON agent_notifications(scope, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_notifications_user_unread ON agent_notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS ix_agent_notifications_report_id ON agent_notifications(report_id);
CREATE INDEX IF NOT EXISTS ix_agent_notifications_report_item_id ON agent_notifications(report_item_id);
