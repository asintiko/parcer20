-- Migration 007: enforce unique fingerprint on transactions
-- Closes race-condition where two workers could insert the same receipt with
-- identical fingerprints. Pre-condition: no current duplicates exist.

-- Pre-check (run manually to verify before applying):
--   SELECT fingerprint, COUNT(*)
--   FROM transactions
--   WHERE fingerprint IS NOT NULL
--   GROUP BY fingerprint
--   HAVING COUNT(*) > 1;
-- Should return 0 rows. If not, dedupe first.

CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_fingerprint
    ON transactions (fingerprint)
    WHERE fingerprint IS NOT NULL;
