#!/usr/bin/env python3
"""
Phase 2 migration: mirror JSON stores into Supabase while keeping local JSON backups.

Moves data into:
- paper_account_history (from paper_account.json)
- api_costs (from cost_log.json)
- tickers (from symbol_master.json)
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.phase2_store import (
    ensure_phase2_tables,
    migrate_cost_log_json,
    migrate_paper_account_json,
    migrate_symbol_master_json,
    table_row_count,
)


def _load_json(path: Path) -> dict:
    with path.open("r") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def _validate_existing_data() -> dict[str, int]:
    paper = _load_json(ROOT / "paper_account.json")
    cost = _load_json(ROOT / "cost_log.json")
    symbol = _load_json(ROOT / "symbol_master.json")

    paper_history = paper.get("history", [])
    cost_runs = cost.get("runs", [])
    tickers = symbol.get("tickers", {})

    if not isinstance(paper_history, list):
        raise ValueError("paper_account.json: history must be a list")
    if not isinstance(cost_runs, list):
        raise ValueError("cost_log.json: runs must be a list")
    if not isinstance(tickers, dict):
        raise ValueError("symbol_master.json: tickers must be an object")

    return {
        "paper_history": len(paper_history),
        "cost_runs": len(cost_runs),
        "tickers": len(tickers),
    }


def _backup_json_files() -> Path:
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    backup_dir = ROOT / "backups" / f"phase2-{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    for name in ["paper_account.json", "cost_log.json", "symbol_master.json"]:
        shutil.copy2(ROOT / name, backup_dir / name)

    return backup_dir


def main() -> None:
    counts = _validate_existing_data()
    print("✅ Existing JSON data validated:")
    print(f"   paper_account history rows: {counts['paper_history']}")
    print(f"   cost_log runs: {counts['cost_runs']}")
    print(f"   symbol_master tickers: {counts['tickers']}")

    backup_dir = _backup_json_files()
    print(f"✅ Backup created: {backup_dir}")

    ensure_phase2_tables()

    pre_counts = {
        "paper_account_history": table_row_count("paper_account_history"),
        "api_costs": table_row_count("api_costs"),
        "tickers": table_row_count("tickers"),
    }
    print("\n📦 DB rows before migration:")
    for table, value in pre_counts.items():
        print(f"   {table}: {value}")

    migrated_paper = migrate_paper_account_json(ROOT / "paper_account.json")
    migrated_costs = migrate_cost_log_json(ROOT / "cost_log.json")
    migrated_tickers = migrate_symbol_master_json(ROOT / "symbol_master.json")

    post_counts = {
        "paper_account_history": table_row_count("paper_account_history"),
        "api_costs": table_row_count("api_costs"),
        "tickers": table_row_count("tickers"),
    }

    print("\n🚀 Migration attempted:")
    print(f"   paper_account entries processed: {migrated_paper}")
    print(f"   api_cost entries processed: {migrated_costs}")
    print(f"   ticker records processed: {migrated_tickers}")

    print("\n✅ DB rows after migration:")
    for table, value in post_counts.items():
        print(f"   {table}: {value}")


if __name__ == "__main__":
    main()
