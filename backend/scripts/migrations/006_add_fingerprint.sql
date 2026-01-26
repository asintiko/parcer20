-- Migration: Add fingerprint column for duplicate detection
-- Description: SHA256 hash of amount|date|card to detect duplicate receipts

ALTER TABLE transactions ADD COLUMN IF NOT EXISTS fingerprint VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_transactions_fingerprint 
    ON transactions(fingerprint) 
    WHERE fingerprint IS NOT NULL;
