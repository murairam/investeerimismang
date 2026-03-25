#!/usr/bin/env python3
"""
Migration: add run_time TIMESTAMPTZ column to daily_runs, portfolio_positions, and agent_proposals.

This allows time-based fetching within a single date — critical for distinguishing
multiple pipeline runs on the same day and ensuring verify.py shows the latest AI proposal.

Safe to run multiple times (uses ADD COLUMN IF NOT EXISTS).

Usage:
    python scripts/migrate_add_run_time.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from data.portfolio_store import get_db_cursor


def main() -> None:
    print("Adding run_time columns to daily_runs, portfolio_positions, and agent_proposals...")

    with get_db_cursor(commit=True) as cur:
        cur.execute("""
            ALTER TABLE daily_runs
                ADD COLUMN IF NOT EXISTS run_time TIMESTAMPTZ DEFAULT now();
        """)
        print("  daily_runs.run_time: OK")

        cur.execute("""
            ALTER TABLE portfolio_positions
                ADD COLUMN IF NOT EXISTS run_time TIMESTAMPTZ DEFAULT now();
        """)
        print("  portfolio_positions.run_time: OK")

        cur.execute("""
            ALTER TABLE agent_proposals
                ADD COLUMN IF NOT EXISTS run_time TIMESTAMPTZ DEFAULT now();
        """)
        print("  agent_proposals.run_time: OK")

        # verified_positions stores the user-confirmed game portfolio as JSONB so
        # the AI proposal in portfolio_positions is never overwritten by verification.
        cur.execute("""
            ALTER TABLE daily_runs
                ADD COLUMN IF NOT EXISTS verified_positions JSONB;
        """)
        print("  daily_runs.verified_positions: OK")

        # Backfill: set existing rows to a stable past timestamp so NULL checks are clean.
        # Using '2000-01-01' as sentinel for "pre-timestamp era" rows.
        cur.execute("""
            UPDATE daily_runs SET run_time = '2000-01-01 00:00:00+00'
            WHERE run_time IS NULL;
        """)
        cur.execute("""
            UPDATE portfolio_positions SET run_time = '2000-01-01 00:00:00+00'
            WHERE run_time IS NULL;
        """)
        cur.execute("""
            UPDATE agent_proposals SET run_time = '2000-01-01 00:00:00+00'
            WHERE run_time IS NULL;
        """)
        print("  Backfilled existing rows with sentinel timestamp.")

        # Migrate existing verified-source rows: copy their portfolio_positions into
        # verified_positions JSONB so load_latest_verified still works for past dates.
        cur.execute("""
            UPDATE daily_runs dr
            SET verified_positions = (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'ticker', pp.ticker,
                        'weight', pp.weight,
                        'rationale', pp.rationale,
                        'tags', COALESCE(pp.tags, '[]'::jsonb)
                    )
                )
                FROM portfolio_positions pp
                WHERE pp.date = dr.date
            )
            WHERE dr.source = 'verified'
              AND dr.verified_positions IS NULL;
        """)
        print("  Migrated existing verified rows to verified_positions JSONB.")

    print("\nMigration complete.")
    print("Next: run the pipeline (python main.py) and all new writes will carry real timestamps.")


if __name__ == "__main__":
    main()
