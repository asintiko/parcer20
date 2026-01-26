-- Uzbek Receipt Parser Database Schema
-- PostgreSQL 15+

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Table: transactions
-- Stores all parsed receipt data
CREATE TABLE IF NOT EXISTS transactions (
    id BIGSERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    
    -- Raw Data
    raw_message TEXT NOT NULL,
    source_type VARCHAR(20) CHECK (source_type IN ('MANUAL', 'AUTO')) NOT NULL,
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
