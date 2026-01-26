-- Migration: Rename check_id to transaction_id in receipt_processing_tasks
-- This aligns the tracking table with the new unified transactions table

-- Rename the column
ALTER TABLE receipt_processing_tasks
RENAME COLUMN check_id TO transaction_id;

-- Update the comment to reflect the new reference
COMMENT ON COLUMN receipt_processing_tasks.transaction_id IS 'References transactions.id (formerly check_id)';
