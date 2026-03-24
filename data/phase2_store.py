"""
Phase 2 persistence helpers for Supabase/PostgreSQL.

This module adds database-backed storage for:
- paper_account.json -> paper_account_history
- cost_log.json -> api_costs
- symbol_master.json -> tickers
"""
from __future__ import annotations

import json
import logging
import hashlib
from pathlib import Path
from typing import Optional

from psycopg2.extras import Json

from data.portfolio_store import get_db_cursor

logger = logging.getLogger(__name__)


def _compute_paper_entry_fingerprint(
    run_date: str,
    source: str,
    initial_capital: Optional[float],
    equity: float,
    cash: float,
    daily_return: float,
    return_since_start: float,
    turnover: float,
    positions: dict,
    pending_order: Optional[dict],
    executed_pending: Optional[bool],
) -> str:
    payload = {
        "date": run_date,
        "source": source,
        "initial_capital": initial_capital,
        "equity": equity,
        "cash": cash,
        "daily_return": daily_return,
        "return_since_start": return_since_start,
        "turnover": turnover,
        "positions": positions,
        "pending_order": pending_order,
        "executed_pending": executed_pending,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _backfill_paper_history_fingerprints() -> None:
    with get_db_cursor(commit=True) as cur:
        cur.execute(
            """
            SELECT id, run_date, source, initial_capital, equity, cash, daily_return,
                   return_since_start, turnover, positions, pending_order, executed_pending
            FROM paper_account_history
            WHERE entry_fingerprint IS NULL
            ORDER BY id ASC
            """
        )
        rows = cur.fetchall()
        for row in rows:
            run_date = row["run_date"].isoformat() if row.get("run_date") else ""
            source = str(row.get("source") or "ai")
            fingerprint = _compute_paper_entry_fingerprint(
                run_date=run_date,
                source=source,
                initial_capital=float(row.get("initial_capital")) if row.get("initial_capital") is not None else None,
                equity=float(row.get("equity") or 0.0),
                cash=float(row.get("cash") or 0.0),
                daily_return=float(row.get("daily_return") or 0.0),
                return_since_start=float(row.get("return_since_start") or 0.0),
                turnover=float(row.get("turnover") or 0.0),
                positions=row.get("positions") or {},
                pending_order=row.get("pending_order"),
                executed_pending=row.get("executed_pending"),
            )
            cur.execute(
                """
                UPDATE paper_account_history
                SET entry_fingerprint = %s
                WHERE id = %s
                """,
                (fingerprint, row["id"]),
            )


def ensure_phase2_tables() -> None:
    """Create Phase 2 tables if they do not already exist."""
    with get_db_cursor(commit=True) as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_account_history (
                id BIGSERIAL PRIMARY KEY,
                run_date DATE NOT NULL,
                source VARCHAR(32) NOT NULL DEFAULT 'ai',
                entry_fingerprint VARCHAR(64),
                initial_capital DOUBLE PRECISION,
                equity DOUBLE PRECISION NOT NULL,
                cash DOUBLE PRECISION NOT NULL,
                daily_return DOUBLE PRECISION,
                return_since_start DOUBLE PRECISION,
                turnover DOUBLE PRECISION,
                positions JSONB NOT NULL DEFAULT '{}'::jsonb,
                pending_order JSONB,
                executed_pending BOOLEAN,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            ALTER TABLE paper_account_history
                DROP CONSTRAINT IF EXISTS paper_account_history_run_date_source_key;

            ALTER TABLE paper_account_history
                ADD COLUMN IF NOT EXISTS entry_fingerprint VARCHAR(64);

            CREATE INDEX IF NOT EXISTS idx_paper_account_history_run_date
                ON paper_account_history (run_date DESC);

            CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_account_history_entry_fingerprint
                ON paper_account_history (entry_fingerprint);

            CREATE TABLE IF NOT EXISTS api_costs (
                id BIGSERIAL PRIMARY KEY,
                run_date DATE NOT NULL,
                agent VARCHAR(64) NOT NULL,
                model VARCHAR(128) NOT NULL,
                input_tokens BIGINT NOT NULL,
                output_tokens BIGINT NOT NULL,
                cost_usd DOUBLE PRECISION NOT NULL,
                entry_fingerprint VARCHAR(64),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            ALTER TABLE api_costs
                ADD COLUMN IF NOT EXISTS entry_fingerprint VARCHAR(64);

            CREATE INDEX IF NOT EXISTS idx_api_costs_run_date
                ON api_costs (run_date DESC);

            CREATE INDEX IF NOT EXISTS idx_api_costs_agent
                ON api_costs (agent);

            CREATE UNIQUE INDEX IF NOT EXISTS idx_api_costs_entry_fingerprint
                ON api_costs (entry_fingerprint);

            CREATE TABLE IF NOT EXISTS tickers (
                game_ticker VARCHAR(20) PRIMARY KEY,
                yahoo_ticker VARCHAR(20) NOT NULL,
                company_name TEXT,
                exchange TEXT,
                isin VARCHAR(20),
                market VARCHAR(32),
                status VARCHAR(32),
                resolution_source VARCHAR(64),
                last_verified_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_tickers_status
                ON tickers (status);

            CREATE INDEX IF NOT EXISTS idx_tickers_market
                ON tickers (market);
            """
        )
    _backfill_paper_history_fingerprints()


def upsert_paper_account_entry(entry: dict, initial_capital: Optional[float] = None) -> None:
    """Insert one paper-account row, deduplicated by content fingerprint."""
    ensure_phase2_tables()
    run_date = entry.get("date")
    if not run_date:
        return

    source = str(entry.get("source") or "ai")
    entry_fingerprint = _compute_paper_entry_fingerprint(
        run_date=run_date,
        source=source,
        initial_capital=float(initial_capital) if initial_capital is not None else None,
        equity=float(entry.get("equity", 0.0)),
        cash=float(entry.get("cash", 0.0)),
        daily_return=float(entry.get("daily_return", 0.0)),
        return_since_start=float(entry.get("return_since_start", 0.0)),
        turnover=float(entry.get("turnover", 0.0)),
        positions=entry.get("positions", {}),
        pending_order=entry.get("pending_order"),
        executed_pending=entry.get("executed_pending"),
    )

    with get_db_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO paper_account_history (
                run_date,
                source,
                entry_fingerprint,
                initial_capital,
                equity,
                cash,
                daily_return,
                return_since_start,
                turnover,
                positions,
                pending_order,
                executed_pending
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (entry_fingerprint) DO NOTHING;
            """,
            (
                run_date,
                source,
                entry_fingerprint,
                float(initial_capital) if initial_capital is not None else None,
                float(entry.get("equity", 0.0)),
                float(entry.get("cash", 0.0)),
                float(entry.get("daily_return", 0.0)),
                float(entry.get("return_since_start", 0.0)),
                float(entry.get("turnover", 0.0)),
                Json(entry.get("positions", {})),
                Json(entry.get("pending_order")) if entry.get("pending_order") is not None else None,
                bool(entry.get("executed_pending")) if entry.get("executed_pending") is not None else None,
            ),
        )


def insert_api_cost(
    run_date: str,
    agent: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    entry_fingerprint: Optional[str] = None,
) -> None:
    """Insert one API usage row."""
    ensure_phase2_tables()
    with get_db_cursor(commit=True) as cur:
        if entry_fingerprint:
            cur.execute(
                """
                INSERT INTO api_costs (run_date, agent, model, input_tokens, output_tokens, cost_usd, entry_fingerprint)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (entry_fingerprint) DO NOTHING
                """,
                (run_date, agent, model, int(input_tokens), int(output_tokens), float(cost_usd), entry_fingerprint),
            )
        else:
            cur.execute(
                """
                INSERT INTO api_costs (run_date, agent, model, input_tokens, output_tokens, cost_usd)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (run_date, agent, model, int(input_tokens), int(output_tokens), float(cost_usd)),
            )


def upsert_ticker_records(records: dict[str, dict]) -> int:
    """Upsert ticker rows. Returns number of processed records."""
    if not records:
        return 0

    ensure_phase2_tables()
    processed = 0
    with get_db_cursor(commit=True) as cur:
        for game_ticker, record in records.items():
            last_verified_raw = record.get("last_verified_at")
            last_verified = None
            if isinstance(last_verified_raw, str) and last_verified_raw.strip():
                last_verified = last_verified_raw.replace("Z", "+00:00")

            cur.execute(
                """
                INSERT INTO tickers (
                    game_ticker,
                    yahoo_ticker,
                    company_name,
                    exchange,
                    isin,
                    market,
                    status,
                    resolution_source,
                    last_verified_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (game_ticker) DO UPDATE SET
                    yahoo_ticker = EXCLUDED.yahoo_ticker,
                    company_name = EXCLUDED.company_name,
                    exchange = EXCLUDED.exchange,
                    isin = EXCLUDED.isin,
                    market = EXCLUDED.market,
                    status = EXCLUDED.status,
                    resolution_source = EXCLUDED.resolution_source,
                    last_verified_at = EXCLUDED.last_verified_at,
                    updated_at = NOW();
                """,
                (
                    game_ticker.upper(),
                    str(record.get("yahoo_ticker") or game_ticker).upper(),
                    record.get("company_name", ""),
                    record.get("exchange", ""),
                    record.get("isin", ""),
                    record.get("market", ""),
                    record.get("status", "unknown"),
                    record.get("resolution_source", ""),
                    last_verified,
                ),
            )
            processed += 1
    return processed


def load_ticker_records() -> dict[str, dict]:
    """Load all ticker rows as a symbol-master compatible mapping."""
    ensure_phase2_tables()
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT
                game_ticker,
                yahoo_ticker,
                company_name,
                exchange,
                isin,
                market,
                status,
                resolution_source,
                last_verified_at,
                updated_at
            FROM tickers
            ORDER BY game_ticker ASC
            """
        )
        rows = cur.fetchall()

    records: dict[str, dict] = {}
    for row in rows:
        last_verified_at = row.get("last_verified_at")
        last_verified = None
        if last_verified_at is not None:
            last_verified = last_verified_at.isoformat().replace("+00:00", "Z")

        records[row["game_ticker"]] = {
            "game_ticker": row["game_ticker"],
            "yahoo_ticker": row["yahoo_ticker"],
            "company_name": row.get("company_name") or "",
            "exchange": row.get("exchange") or "",
            "isin": row.get("isin") or "",
            "market": row.get("market") or "",
            "status": row.get("status") or "unknown",
            "resolution_source": row.get("resolution_source") or "",
            "last_verified_at": last_verified,
        }
    return records


def migrate_paper_account_json(path: str | Path) -> int:
    """Backfill paper_account_history rows from paper_account.json history."""
    source_path = Path(path)
    if not source_path.exists():
        return 0

    payload = json.loads(source_path.read_text())
    history = payload.get("history", []) if isinstance(payload, dict) else []
    initial_capital = payload.get("initial_capital") if isinstance(payload, dict) else None
    written = 0
    for entry in history:
        if not isinstance(entry, dict):
            continue
        try:
            upsert_paper_account_entry(entry, initial_capital=initial_capital)
            written += 1
        except Exception as exc:
            logger.warning("Skipping paper-account entry migration due to error: %s", exc)
    return written


def migrate_cost_log_json(path: str | Path) -> int:
    """Backfill api_costs rows from cost_log.json runs."""
    source_path = Path(path)
    if not source_path.exists():
        return 0

    payload = json.loads(source_path.read_text())
    runs = payload.get("runs", []) if isinstance(payload, dict) else []
    written = 0
    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            continue
        run_date = run.get("date")
        if not run_date:
            continue
        fingerprint_payload = {
            "index": index,
            "run_date": run_date,
            "agent": str(run.get("agent") or "unknown"),
            "model": str(run.get("model") or "unknown"),
            "input_tokens": int(run.get("input_tokens") or 0),
            "output_tokens": int(run.get("output_tokens") or 0),
            "cost_usd": float(run.get("cost_usd") or 0.0),
        }
        entry_fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        try:
            with get_db_cursor() as cur:
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
                    continue

            insert_api_cost(
                run_date=run_date,
                agent=str(run.get("agent") or "unknown"),
                model=str(run.get("model") or "unknown"),
                input_tokens=int(run.get("input_tokens") or 0),
                output_tokens=int(run.get("output_tokens") or 0),
                cost_usd=float(run.get("cost_usd") or 0.0),
                entry_fingerprint=entry_fingerprint,
            )
            written += 1
        except Exception as exc:
            logger.warning("Skipping cost-log entry migration due to error: %s", exc)
    return written


def migrate_symbol_master_json(path: str | Path) -> int:
    """Backfill ticker rows from symbol_master.json tickers mapping."""
    source_path = Path(path)
    if not source_path.exists():
        return 0

    payload = json.loads(source_path.read_text())
    tickers = payload.get("tickers", {}) if isinstance(payload, dict) else {}
    if not isinstance(tickers, dict):
        return 0
    return upsert_ticker_records(tickers)


def table_row_count(table_name: str) -> int:
    """Return row count for a table in the public schema."""
    ensure_phase2_tables()
    with get_db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM {table_name}")
        row = cur.fetchone()
    return int(row["c"] if row else 0)