-- Migration: Change transaction_date and timestamp columns from timestamptz to timestamp (timezone-aware to naive)
-- This aligns Transaction model with Check model behavior

-- Drop view that depends on transaction_date
DROP VIEW IF EXISTS recent_transactions CASCADE;

-- Change transaction_date from timestamptz to timestamp (without timezone)
-- Convert existing data: keep the same local time representation
ALTER TABLE transactions
ALTER COLUMN transaction_date TYPE timestamp without time zone
USING transaction_date AT TIME ZONE 'Asia/Tashkent';

-- Change parsed_at from timestamptz to timestamp
ALTER TABLE transactions
ALTER COLUMN parsed_at TYPE timestamp without time zone
USING parsed_at AT TIME ZONE 'Asia/Tashkent';

-- Change created_at from timestamptz to timestamp
ALTER TABLE transactions
ALTER COLUMN created_at TYPE timestamp without time zone
USING created_at AT TIME ZONE 'Asia/Tashkent';

-- Change updated_at from timestamptz to timestamp
ALTER TABLE transactions
ALTER COLUMN updated_at TYPE timestamp without time zone
USING updated_at AT TIME ZONE 'Asia/Tashkent';

-- Recreate the view
CREATE OR REPLACE VIEW recent_transactions AS
SELECT
    id,
    to_char(transaction_date, 'DD.MM.YYYY HH24:MI') AS formatted_date,
    to_char(transaction_date, 'Dy') AS day_of_week,
    amount,
    currency,
    card_last_4 AS pk,
    operator_raw,
    application_mapped,
    transaction_type,
    balance_after,
    source_type,
    parsing_method
FROM transactions
ORDER BY transaction_date DESC;
