-- Description: allow GPT_VISION parsing method in transactions.parsing_method check constraint

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'check_parsing_method'
          AND conrelid = 'transactions'::regclass
    ) THEN
        ALTER TABLE transactions DROP CONSTRAINT check_parsing_method;
    END IF;
END$$;

ALTER TABLE transactions
    ADD CONSTRAINT check_parsing_method
    CHECK (parsing_method IN ('REGEX_HUMO', 'REGEX_SMS', 'REGEX_SEMICOLON', 'REGEX_CARDXABAR', 'REGEX_TRANSFER', 'GPT', 'GPT_VISION'));
