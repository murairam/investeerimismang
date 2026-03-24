#!/usr/bin/env python3
"""
Database audit utility for AlphaShark Supabase persistence.

Checks:
- Core Phase 1 tables
- Phase 2 tables
- Row counts compared to JSON source files
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.phase2_store import ensure_phase2_tables, table_row_count
from data.portfolio_store import get_db_cursor


def _json_count(path: Path, key: str) -> int:
    payload = json.loads(path.read_text())
    value = payload.get(key)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return 0


def _load_json(path: Path) -> dict:
    payload = json.loads(path.read_text())
    return payload if isinstance(payload, dict) else {}


def main() -> None:
    ensure_phase2_tables()

    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema='public'
            ORDER BY table_name
            """
        )
        tables = [row["table_name"] for row in cur.fetchall()]

    print("📋 Public tables:")
    for table in tables:
        print(f"   - {table}")

    print("\n📊 Row counts:")
    for table in [
        "daily_runs",
        "portfolio_positions",
        "agent_proposals",
        "competition_standings",
        "paper_account_history",
        "api_costs",
        "tickers",
    ]:
        exists = table in tables
        count = table_row_count(table) if exists else 0
        exists_flag = "present" if exists else "missing"
        print(f"   - {table}: {count} ({exists_flag})")

    json_paper = _json_count(ROOT / "paper_account.json", "history")
    json_cost = _json_count(ROOT / "cost_log.json", "runs")
    json_tickers = _json_count(ROOT / "symbol_master.json", "tickers")

    db_paper = table_row_count("paper_account_history")
    db_cost = table_row_count("api_costs")
    db_tickers = table_row_count("tickers")

    cost_payload = _load_json(ROOT / "cost_log.json")
    cost_runs = cost_payload.get("runs", []) if isinstance(cost_payload, dict) else []
    covered = 0
    if isinstance(cost_runs, list):
        with get_db_cursor() as cur:
            for run in cost_runs:
                if not isinstance(run, dict):
                    continue
                run_date = run.get("date")
                if not run_date:
                    continue
                cur.execute(
                    """
                    SELECT 1
                    FROM api_costs
                    WHERE run_date = %s
                      AND agent = %s
                      AND model = %s
                      AND input_tokens = %s
                      AND output_tokens = %s
                      AND ABS(cost_usd - %s) < 1e-9
                    LIMIT 1
                    """,
                    (
                        run_date,
                        str(run.get("agent") or "unknown"),
                        str(run.get("model") or "unknown"),
                        int(run.get("input_tokens") or 0),
                        int(run.get("output_tokens") or 0),
                        float(run.get("cost_usd") or 0.0),
                    ),
                )
                if cur.fetchone():
                    covered += 1

    print("\n🔎 JSON vs DB parity:")
    print(f"   - paper_account history: JSON={json_paper} DB={db_paper}")
    print(f"   - cost_log runs: JSON={json_cost} DB_raw={db_cost} JSON_covered_in_DB={covered}")
    print(f"   - symbol_master tickers: JSON={json_tickers} DB={db_tickers}")


if __name__ == "__main__":
    main()
