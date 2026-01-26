-- Migration: Add REGEX_CARDXABAR to parsing_method constraint
-- This allows the regex parser to use the CARDXABAR parsing method

-- Drop the old constraint
ALTER TABLE transactions
DROP CONSTRAINT IF EXISTS check_parsing_method;

-- Add the new constraint with REGEX_CARDXABAR included
ALTER TABLE transactions
ADD CONSTRAINT check_parsing_method
CHECK (parsing_method IN ('REGEX_HUMO', 'REGEX_SMS', 'REGEX_SEMICOLON', 'REGEX_CARDXABAR', 'GPT'));

-- Also update the old constraint name if it exists
ALTER TABLE transactions
DROP CONSTRAINT IF EXISTS transactions_parsing_method_check;

-- Ensure the new constraint is in place
ALTER TABLE transactions
ADD CONSTRAINT transactions_parsing_method_check
CHECK (parsing_method IN ('REGEX_HUMO', 'REGEX_SMS', 'REGEX_SEMICOLON', 'REGEX_CARDXABAR', 'GPT'));
