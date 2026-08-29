-- FormFlow Supabase Migration
-- Run this in your Supabase SQL Editor (Dashboard > SQL Editor > New Query)
-- Creates the formflow_kb and formflow_sessions tables for cloud KB persistence

-- ============================================================
-- Table: formflow_kb
-- Stores Knowledge Base entries with category organization,
-- field type hints, confidence scoring, and alternate values.
-- ============================================================

CREATE TABLE IF NOT EXISTS formflow_kb (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_email TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    field_name TEXT NOT NULL,
    field_value TEXT,
    field_type TEXT DEFAULT 'text',
    confidence INTEGER DEFAULT 100
        CHECK (confidence >= 0 AND confidence <= 100),
    source TEXT DEFAULT 'manual',
    alternates JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

COMMENT ON TABLE formflow_kb IS 'FormFlow Knowledge Base — evolving field/value store';
COMMENT ON COLUMN formflow_kb.category IS 'personal, contact, address, employment, education, financial, medical, legal, business, other';
COMMENT ON COLUMN formflow_kb.field_type IS 'text, date, email, phone, zip, ssn';
COMMENT ON COLUMN formflow_kb.confidence IS '0-100 confidence score; 100=user-entered, lower=auto-parsed';
COMMENT ON COLUMN formflow_kb.alternates IS 'JSON array of {value, source, date} alternate values';

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_formflow_kb_user
    ON formflow_kb(user_email);
CREATE INDEX IF NOT EXISTS idx_formflow_kb_category
    ON formflow_kb(category);
CREATE INDEX IF NOT EXISTS idx_formflow_kb_field
    ON formflow_kb(field_name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_formflow_kb_user_field
    ON formflow_kb(user_email, field_name);

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION formflow_update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS formflow_kb_updated ON formflow_kb;
CREATE TRIGGER formflow_kb_updated
    BEFORE UPDATE ON formflow_kb
    FOR EACH ROW
    EXECUTE FUNCTION formflow_update_timestamp();


-- ============================================================
-- Table: formflow_sessions
-- Tracks form filling sessions for historical reporting.
-- ============================================================

CREATE TABLE IF NOT EXISTS formflow_sessions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_email TEXT NOT NULL,
    form_name TEXT,
    fields_total INTEGER DEFAULT 0,
    fields_filled INTEGER DEFAULT 0,
    confidence_avg REAL DEFAULT 0.0,
    issues JSONB DEFAULT '[]'::jsonb,
    filled_fields JSONB DEFAULT '[]'::jsonb,
    categories JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

COMMENT ON TABLE formflow_sessions IS 'FormFlow fill session history and reports';

CREATE INDEX IF NOT EXISTS idx_formflow_sessions_user
    ON formflow_sessions(user_email);
CREATE INDEX IF NOT EXISTS idx_formflow_sessions_date
    ON formflow_sessions(created_at DESC);


-- ============================================================
-- Row Level Security
-- ============================================================

ALTER TABLE formflow_kb ENABLE ROW LEVEL SECURITY;
ALTER TABLE formflow_sessions ENABLE ROW LEVEL SECURITY;

-- Authenticated users can only access their own data
CREATE POLICY formflow_kb_select ON formflow_kb
    FOR SELECT USING (
        user_email = coalesce(
            current_setting('request.jwt.claim.email', true),
            current_setting('request.jwt.claims', true)::jsonb->>'email'
        )
    );

CREATE POLICY formflow_kb_insert ON formflow_kb
    FOR INSERT WITH CHECK (
        user_email = coalesce(
            current_setting('request.jwt.claim.email', true),
            current_setting('request.jwt.claims', true)::jsonb->>'email'
        )
    );

CREATE POLICY formflow_kb_update ON formflow_kb
    FOR UPDATE USING (
        user_email = coalesce(
            current_setting('request.jwt.claim.email', true),
            current_setting('request.jwt.claims', true)::jsonb->>'email'
        )
    );

CREATE POLICY formflow_kb_delete ON formflow_kb
    FOR DELETE USING (
        user_email = coalesce(
            current_setting('request.jwt.claim.email', true),
            current_setting('request.jwt.claims', true)::jsonb->>'email'
        )
    );

CREATE POLICY formflow_sessions_select ON formflow_sessions
    FOR SELECT USING (
        user_email = coalesce(
            current_setting('request.jwt.claim.email', true),
            current_setting('request.jwt.claims', true)::jsonb->>'email'
        )
    );

CREATE POLICY formflow_sessions_insert ON formflow_sessions
    FOR INSERT WITH CHECK (
        user_email = coalesce(
            current_setting('request.jwt.claim.email', true),
            current_setting('request.jwt.claims', true)::jsonb->>'email'
        )
    );

-- Service role can access all rows (for Python scripts using service key)
CREATE POLICY formflow_kb_service ON formflow_kb
    FOR ALL TO service_role
    USING (true) WITH CHECK (true);

CREATE POLICY formflow_sessions_service ON formflow_sessions
    FOR ALL TO service_role
    USING (true) WITH CHECK (true);
