-- Migration: Add receiver fields to transactions table
-- Description: Add receiver_name and receiver_card columns for P2P transfer tracking
-- Date: 2026-01-26
-- Author: Claude Code

-- Add receiver fields to transactions table
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS receiver_name VARCHAR(255);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS receiver_card VARCHAR(4);

-- Comment on new columns
COMMENT ON COLUMN transactions.receiver_name IS 'Full name of payment receiver (for P2P transfers)';
COMMENT ON COLUMN transactions.receiver_card IS 'Last 4 digits of receiver card (for P2P transfers)';

-- Indexes for fast filtering and searching
CREATE INDEX IF NOT EXISTS idx_transactions_receiver_card
  ON transactions(receiver_card) WHERE receiver_card IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_transactions_receiver_name
  ON transactions(receiver_name) WHERE receiver_name IS NOT NULL;

-- The existing update trigger automatically handles updated_at for new fields
-- No additional trigger configuration needed
