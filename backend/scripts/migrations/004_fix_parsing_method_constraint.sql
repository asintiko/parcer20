-- Description: normalize parsing_method constraint to include REGEX_TRANSFER and GPT_VISION

DO $$
DECLARE
    cname text;
BEGIN
    FOR cname IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'transactions'::regclass
          AND contype = 'c'
          AND conname ILIKE '%parsing_method%'
    LOOP
        EXECUTE format('ALTER TABLE transactions DROP CONSTRAINT %I', cname);
    END LOOP;
END$$;

ALTER TABLE transactions
    ADD CONSTRAINT transactions_parsing_method_check
    CHECK (parsing_method IN ('REGEX_HUMO', 'REGEX_SMS', 'REGEX_SEMICOLON', 'REGEX_CARDXABAR', 'REGEX_TRANSFER', 'GPT', 'GPT_VISION'));
