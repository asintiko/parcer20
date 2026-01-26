-- Create reference table for operators/sellers and applications
-- Used for P2P detection and parsing

CREATE TABLE IF NOT EXISTS operator_reference (
    id SERIAL PRIMARY KEY,
    operator_name VARCHAR(500) NOT NULL,
    application_name VARCHAR(200) NOT NULL,
    is_p2p BOOLEAN DEFAULT false,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Ensure no duplicates
    UNIQUE(operator_name, application_name)
);

-- Create indexes for fast search
CREATE INDEX IF NOT EXISTS idx_operator_ref_operator ON operator_reference(operator_name);
CREATE INDEX IF NOT EXISTS idx_operator_ref_app ON operator_reference(application_name);
CREATE INDEX IF NOT EXISTS idx_operator_ref_active ON operator_reference(is_active) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_operator_ref_p2p ON operator_reference(is_p2p) WHERE is_p2p = true;

-- Ensure default stays false even on existing deployments
ALTER TABLE operator_reference
    ALTER COLUMN is_p2p SET DEFAULT false;

-- Add trigger for updated_at
CREATE OR REPLACE FUNCTION update_operator_reference_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_operator_reference_updated_at
    BEFORE UPDATE ON operator_reference
    FOR EACH ROW
    EXECUTE FUNCTION update_operator_reference_updated_at();

-- Comment on table
COMMENT ON TABLE operator_reference IS 'Справочник операторов/продавцов и приложений для определения P2P транзакций';
COMMENT ON COLUMN operator_reference.operator_name IS 'Название оператора/продавца из чека';
COMMENT ON COLUMN operator_reference.application_name IS 'Приложение к которому относится оператор';
COMMENT ON COLUMN operator_reference.is_p2p IS 'Является ли P2P транзакцией';
COMMENT ON COLUMN operator_reference.is_active IS 'Активна ли запись';
