-- Add chat type and filter fields to MonitoredBotChat for Telegram groups support
-- Migration: 002_add_chat_filters.sql
-- Description: Enable monitoring of Telegram groups with message filtering

-- Add chat_type column (private, group, supergroup, channel)
ALTER TABLE monitored_bot_chats
ADD COLUMN IF NOT EXISTS chat_type VARCHAR(50) DEFAULT 'private';

-- Add filter_mode column (all, whitelist, blacklist)
ALTER TABLE monitored_bot_chats
ADD COLUMN IF NOT EXISTS filter_mode VARCHAR(20) DEFAULT 'all'
CHECK (filter_mode IN ('all', 'whitelist', 'blacklist'));

-- Add filter_keywords column (JSON array of keywords for filtering)
ALTER TABLE monitored_bot_chats
ADD COLUMN IF NOT EXISTS filter_keywords TEXT;

-- Add chat_title column for caching (avoid repeated TDLib calls)
ALTER TABLE monitored_bot_chats
ADD COLUMN IF NOT EXISTS chat_title VARCHAR(255);

-- Index for filtering active monitors by chat type
CREATE INDEX IF NOT EXISTS idx_monitored_chats_type
ON monitored_bot_chats(chat_type) WHERE enabled = true;

-- Comments for documentation
COMMENT ON COLUMN monitored_bot_chats.chat_type IS 'Telegram chat type: private, group, supergroup, channel';
COMMENT ON COLUMN monitored_bot_chats.filter_mode IS 'Message filtering mode: all (no filter), whitelist (only keywords), blacklist (exclude keywords)';
COMMENT ON COLUMN monitored_bot_chats.filter_keywords IS 'JSON array of keywords for message filtering, e.g., ["чек", "квитанция", "UZS"]';
COMMENT ON COLUMN monitored_bot_chats.chat_title IS 'Cached chat title from TDLib to avoid repeated API calls';
