#!/usr/bin/env python3
"""
FormFlow DB Setup — Supabase migration and table creation for the
FormFlow Knowledge Base. Creates the formflow_kb and formflow_sessions
tables with Row Level Security policies.

Usage:
    python scripts/formflow_db_setup.py --migrate
    python scripts/formflow_db_setup.py --check
    python scripts/formflow_db_setup.py --seed --email user@example.com
"""

import argparse
import json
import os
import sys
from datetime import datetime


def get_supabase_client():
    try:
        from supabase import create_client
    except ImportError:
        print("ERROR: supabase package not installed.")
        print("Run: pip install supabase")
        sys.exit(1)

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY environment variables required.")
        sys.exit(1)

    return create_client(url, key)


MIGRATION_SQL = """
-- FormFlow Knowledge Base table
CREATE TABLE IF NOT EXISTS formflow_kb (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_email TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    field_name TEXT NOT NULL,
    field_value TEXT,
    field_type TEXT DEFAULT 'text',
    confidence INTEGER DEFAULT 100,
    source TEXT DEFAULT 'manual',
    alternates JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_formflow_kb_user ON formflow_kb(user_email);
CREATE INDEX IF NOT EXISTS idx_formflow_kb_category ON formflow_kb(category);
CREATE INDEX IF NOT EXISTS idx_formflow_kb_field ON formflow_kb(field_name);

-- FormFlow Sessions table
CREATE TABLE IF NOT EXISTS formflow_sessions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_email TEXT NOT NULL,
    form_name TEXT,
    fields_total INTEGER DEFAULT 0,
    fields_filled INTEGER DEFAULT 0,
    confidence_avg REAL DEFAULT 0.0,
    issues JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_formflow_sessions_user ON formflow_sessions(user_email);

-- Enable Row Level Security
ALTER TABLE formflow_kb ENABLE ROW LEVEL SECURITY;
ALTER TABLE formflow_sessions ENABLE ROW LEVEL SECURITY;

-- RLS Policies: users can only access their own data
CREATE POLICY IF NOT EXISTS formflow_kb_user_policy ON formflow_kb
    FOR ALL USING (user_email = current_setting('request.jwt.claim.email', true));

CREATE POLICY IF NOT EXISTS formflow_sessions_user_policy ON formflow_sessions
    FOR ALL USING (user_email = current_setting('request.jwt.claim.email', true));

-- Service role bypass for script access
CREATE POLICY IF NOT EXISTS formflow_kb_service_policy ON formflow_kb
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY IF NOT EXISTS formflow_sessions_service_policy ON formflow_sessions
    FOR ALL USING (true) WITH CHECK (true);
"""


def run_migration(client):
    print("Running FormFlow database migration...")
    try:
        client.postgrest.schema("public")
        result = client.table("formflow_kb").select("id").limit(1).execute()
        print("Tables already exist. Migration skipped.")
        return True
    except Exception:
        pass

    print("Creating tables via Supabase SQL editor...")
    print("=" * 60)
    print("Copy and run this SQL in your Supabase SQL Editor:")
    print("(Dashboard > SQL Editor > New Query)")
    print("=" * 60)
    print(MIGRATION_SQL)
    print("=" * 60)
    print("\nAfter running the SQL, re-run this script with --check")
    return False


def check_connection(client):
    print("Checking Supabase connection...")
    try:
        result = client.table("formflow_kb").select("id").limit(1).execute()
        print("  formflow_kb table: OK")
    except Exception as e:
        print(f"  formflow_kb table: MISSING ({e})")
        return False

    try:
        result = client.table("formflow_sessions").select("id").limit(1).execute()
        print("  formflow_sessions table: OK")
    except Exception as e:
        print(f"  formflow_sessions table: MISSING ({e})")
        return False

    print("All tables verified.")
    return True


def seed_kb(client, email):
    print(f"Seeding initial KB entries for {email}...")
    seed_data = [
        {"category": "personal", "field_name": "full_name", "field_type": "text"},
        {"category": "personal", "field_name": "first_name", "field_type": "text"},
        {"category": "personal", "field_name": "last_name", "field_type": "text"},
        {"category": "personal", "field_name": "date_of_birth", "field_type": "date"},
        {"category": "personal", "field_name": "gender", "field_type": "text"},
        {"category": "contact", "field_name": "email", "field_type": "email"},
        {"category": "contact", "field_name": "phone", "field_type": "phone"},
        {"category": "address", "field_name": "street_address", "field_type": "text"},
        {"category": "address", "field_name": "city", "field_type": "text"},
        {"category": "address", "field_name": "state", "field_type": "text"},
        {"category": "address", "field_name": "zip_code", "field_type": "zip"},
        {"category": "address", "field_name": "country", "field_type": "text"},
        {"category": "employment", "field_name": "employer", "field_type": "text"},
        {"category": "employment", "field_name": "job_title", "field_type": "text"},
        {"category": "education", "field_name": "school", "field_type": "text"},
        {"category": "education", "field_name": "degree", "field_type": "text"},
    ]

    for entry in seed_data:
        entry["user_email"] = email
        entry["field_value"] = ""
        entry["confidence"] = 0
        entry["source"] = "seed"

    try:
        client.table("formflow_kb").insert(seed_data).execute()
        print(f"  Seeded {len(seed_data)} KB entry templates.")
    except Exception as e:
        print(f"  Seed failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="FormFlow DB Setup")
    parser.add_argument("--migrate", action="store_true", help="Run database migration")
    parser.add_argument("--check", action="store_true", help="Check connection and tables")
    parser.add_argument("--seed", action="store_true", help="Seed initial KB templates")
    parser.add_argument("--email", type=str, help="User email for seeding")
    args = parser.parse_args()

    if not any([args.migrate, args.check, args.seed]):
        parser.print_help()
        sys.exit(1)

    client = get_supabase_client()

    if args.migrate:
        run_migration(client)
    if args.check:
        check_connection(client)
    if args.seed:
        if not args.email:
            print("ERROR: --email required with --seed")
            sys.exit(1)
        seed_kb(client, args.email)


if __name__ == "__main__":
    main()
