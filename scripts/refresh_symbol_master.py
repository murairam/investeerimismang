#!/usr/bin/env python3
"""
Refresh the symbol master and verify Yahoo-resolvable mappings outside the main pipeline.
"""
from __future__ import annotations

import os
import sys
import argparse

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import MOMENTUM_WINDOW
from data.fetcher import DataFetcher
from data.symbol_master import load_symbol_master, refresh_symbol_master, save_symbol_master
from data.yahoo_symbols import get_eodhd_budget_status, save_unavailable_yahoo_tickers


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="Refresh the full universe instead of unresolved names only")
    parser.add_argument("--include-stale", action="store_true", help="Also refresh stale verified records")
    parser.add_argument("--max-tickers", type=int, default=None, help="Maximum tickers to refresh this run")
    parser.add_argument("--stale-days", type=int, default=7, help="Refresh verified records older than this many days")
    args = parser.parse_args()

    mode = "full" if args.full else ("stale_or_unresolved" if args.include_stale else "unresolved_only")
    budget = get_eodhd_budget_status()
    print(f"EODHD budget: {budget['used']}/{budget['cap']} used today ({budget['remaining']} remaining)")
    stats = refresh_symbol_master(mode=mode, stale_after_days=args.stale_days, max_tickers=args.max_tickers)
    print(f"Symbol master refreshed: {stats['refreshed']} tickers this run")
    print(f"Symbol master total: {stats['total']} tickers")
    print(f"Status counts: {stats['status_counts']}")
    print(f"Aliases upserted: {stats['aliases_upserted']}")

    master = load_symbol_master()
    records = master.get("tickers", {})
    yahoo_tickers = sorted({record["yahoo_ticker"] for record in records.values() if record.get("yahoo_ticker")})
    fetcher = DataFetcher()
    close, *_ = fetcher.fetch_ohlcv(yahoo_tickers, period="1y")
    min_rows = MOMENTUM_WINDOW + 5

    quarantined: dict[str, dict] = {}
    for game_ticker, record in records.items():
        yahoo_ticker = record.get("yahoo_ticker", game_ticker)
        valid = yahoo_ticker in close.columns and len(close[yahoo_ticker].dropna()) >= min_rows
        if valid:
            record["status"] = "verified"
        elif record.get("status") != "aliased":
            record["status"] = "quarantined"
            quarantined[game_ticker] = {"reason": "symbol_refresh_no_data"}

    save_symbol_master(master)
    save_unavailable_yahoo_tickers(quarantined)

    print(f"Verified tickers: {sum(1 for r in records.values() if r.get('status') == 'verified')}")
    print(f"Quarantined tickers: {len(quarantined)}")


if __name__ == "__main__":
    main()
