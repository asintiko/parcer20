-- Migration: Change transaction_date and timestamp columns from timestamptz to timestamp (timezone-aware to naive)
-- This aligns Transaction model with Check model behavior

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
