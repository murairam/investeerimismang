"""
Persistent symbol master for game tickers and their market-data mappings.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta

from data.phase2_store import load_ticker_records, upsert_ticker_records
from data.universe_loader import load_game_universe
from data.yahoo_symbols import load_unavailable_yahoo_tickers, lookup_symbol_metadata, upsert_aliases

logger = logging.getLogger(__name__)

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MASTER_PATH = os.path.join(_ROOT, "symbol_master.json")


def load_symbol_master() -> dict:
    try:
        db_records = load_ticker_records()
        if db_records:
            return {
                "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "tickers": db_records,
            }
    except Exception as exc:
        logger.warning("Could not load symbol master from DB, falling back to JSON: %s", exc)

    if not os.path.exists(_MASTER_PATH):
        return {"generated_at": None, "tickers": {}}
    try:
        with open(_MASTER_PATH, "r") as f:
            data = json.load(f)
        if "tickers" not in data:
            data["tickers"] = {}
        return data
    except Exception as exc:
        logger.warning("Could not load symbol master: %s", exc)
        return {"generated_at": None, "tickers": {}}


def save_symbol_master(master: dict) -> None:
    with open(_MASTER_PATH, "w") as f:
        json.dump(master, f, indent=2, sort_keys=True)

    try:
        records = master.get("tickers", {}) if isinstance(master, dict) else {}
        if isinstance(records, dict):
            upsert_ticker_records(records)
    except Exception as exc:
        logger.warning("Failed to mirror symbol master to DB (JSON backup still saved): %s", exc)


def get_symbol_record(game_ticker: str) -> dict | None:
    master = load_symbol_master()
    return master.get("tickers", {}).get(game_ticker.upper())


def refresh_symbol_master(
    universe: dict[str, list[str]] | None = None,
    mode: str = "unresolved_only",
    stale_after_days: int = 7,
    max_tickers: int | None = None,
) -> dict:
    universe = universe or load_game_universe()
    unavailable = load_unavailable_yahoo_tickers()
    existing = load_symbol_master().get("tickers", {})
    records: dict[str, dict] = dict(existing)
    aliases_to_upsert: dict[str, str] = {}
    refreshed = 0
    candidates_to_refresh: list[tuple[str, str]] = []

    for market, tickers in universe.items():
        for ticker in tickers:
            if _should_refresh(ticker, existing.get(ticker.upper()), unavailable, mode, stale_after_days):
                candidates_to_refresh.append((ticker, market))

    if max_tickers is not None:
        candidates_to_refresh = candidates_to_refresh[:max_tickers]

    for ticker, market in candidates_to_refresh:
            metadata = lookup_symbol_metadata(ticker, market, use_eodhd=True)
            status = metadata.get("status", "unverified")
            if ticker.upper() in unavailable and metadata.get("yahoo_ticker", ticker.upper()) == ticker.upper():
                status = "quarantined"
            elif metadata.get("yahoo_ticker", ticker.upper()) != ticker.upper():
                status = "aliased"
                aliases_to_upsert[ticker.upper()] = metadata["yahoo_ticker"]
            elif status == "unverified":
                status = "direct"

            records[ticker.upper()] = {
                "game_ticker": ticker.upper(),
                "yahoo_ticker": metadata.get("yahoo_ticker", ticker.upper()),
                "company_name": metadata.get("company_name", ""),
                "exchange": metadata.get("exchange", ""),
                "isin": metadata.get("isin", ""),
                "market": market,
                "status": status,
                "resolution_source": metadata.get("resolution_source", "direct"),
                "last_verified_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            }
            refreshed += 1

    if aliases_to_upsert:
        upsert_aliases(aliases_to_upsert)

    master = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "tickers": records,
    }
    save_symbol_master(master)

    status_counts: dict[str, int] = {}
    for record in records.values():
        status = record["status"]
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "total": len(records),
        "refreshed": refreshed,
        "status_counts": status_counts,
        "aliases_upserted": len(aliases_to_upsert),
    }


def summarize_symbol_master() -> dict:
    master = load_symbol_master()
    records = master.get("tickers", {})
    counts: dict[str, int] = {}
    for record in records.values():
        status = record.get("status", "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {
        "generated_at": master.get("generated_at"),
        "total": len(records),
        "status_counts": counts,
    }


def upsert_symbol_records(records_to_merge: dict[str, dict]) -> None:
    if not records_to_merge:
        return
    master = load_symbol_master()
    records = master.setdefault("tickers", {})
    for ticker, incoming in records_to_merge.items():
        existing = records.get(ticker, {})
        merged = dict(existing)
        merged.update(incoming)
        if not merged.get("company_name"):
            merged["company_name"] = existing.get("company_name", "")
        if not merged.get("exchange"):
            merged["exchange"] = existing.get("exchange", "")
        if not merged.get("isin"):
            merged["isin"] = existing.get("isin", "")
        records[ticker] = merged
    master["generated_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    save_symbol_master(master)


def _should_refresh(
    ticker: str,
    existing_record: dict | None,
    unavailable: dict[str, dict],
    mode: str,
    stale_after_days: int,
) -> bool:
    if mode == "full":
        return True
    if existing_record is None:
        return True
    if ticker.upper() in unavailable:
        return True
    status = existing_record.get("status", "")
    if mode == "unresolved_only":
        return status in {"quarantined", "unverified", "unknown"}
    if mode == "stale_or_unresolved":
        if status in {"quarantined", "unverified", "unknown"}:
            return True
        return _is_stale(existing_record.get("last_verified_at"), stale_after_days)
    return False


def _is_stale(last_verified_at: str | None, stale_after_days: int) -> bool:
    if not last_verified_at:
        return True
    try:
        ts = datetime.fromisoformat(last_verified_at.replace("Z", "+00:00"))
    except Exception:
        return True
    return datetime.now(ts.tzinfo) - ts >= timedelta(days=stale_after_days)
