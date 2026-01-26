-- Description: expand receiver_card to store full masked/complete number

ALTER TABLE transactions
    ALTER COLUMN receiver_card TYPE VARCHAR(32);
