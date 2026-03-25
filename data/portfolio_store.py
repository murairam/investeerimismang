"""
Persist and load portfolio proposals and structured daily decision history
from a PostgreSQL database.
"""
from __future__ import annotations

import json
import logging
import math
import os
import psycopg2
from psycopg2.extras import Json, RealDictCursor
from contextlib import contextmanager
from copy import deepcopy
from typing import Optional, Generator

from dotenv import load_dotenv
from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)

RATIONALE_TAGS: tuple[str, ...] = (
    "momentum",
    "high_sharpe",
    "breakout",
    "consensus",
    "catalyst",
    "diversifier",
    "earnings_risk",
    "non_us_differentiator",
    "overbought",           # RSI > 80 at entry — tracks whether buying overbought names hurts returns
    "at_52w_high",          # within 2% of 52-week high at entry — tracks exhaustion/pullback risk
    "pre_earnings_setup",   # earnings 2–6 days out + strong momentum — tracks pre-earnings drift outcomes
)


load_dotenv()
_DB_URL = os.environ.get("SUPABASE_CONNECTION_STRING")
_db_conn = None

def _get_db_connection():
    """Lazy-load a singleton database connection to avoid connection latency."""
    global _db_conn
    if _db_conn is None or _db_conn.closed:
        if not _DB_URL:
            raise ConnectionError("SUPABASE_CONNECTION_STRING is not set in the environment.")
        _db_conn = psycopg2.connect(_DB_URL)
    return _db_conn

@contextmanager
def get_db_cursor(commit: bool = False) -> Generator[psycopg2.extensions.cursor, None, None]:
    """Provides a database cursor. Commits transaction if commit=True."""
    conn = _get_db_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        yield cur
    if commit:
        conn.commit()

def _portfolio_to_dict(proposal: PortfolioProposal, signal_map: Optional[dict[str, dict]] = None) -> dict:
    signal_map = signal_map or {}
    positions = []
    for pos in proposal.positions:
        signal = signal_map.get(pos.ticker, {})
        positions.append(
            {
                "ticker": pos.ticker,
                "weight": round(float(pos.weight), 6),
                "rationale": pos.rationale,
                "tags": derive_rationale_tags(pos.ticker, pos.rationale, signal),
            }
        )
    return {
        "positions": positions,
        "reasoning": proposal.reasoning,
        "confidence": float(proposal.confidence),
        "learning_reflection": proposal.learning_reflection,
    }


def _build_signal_map(signal_snapshot: Optional[dict]) -> dict[str, dict]:
    if not signal_snapshot:
        return {}
    return {
        ticker: values for ticker, values in signal_snapshot.items()
        if isinstance(values, dict)
    }


def derive_rationale_tags(ticker: str, rationale: str, signal: Optional[dict] = None) -> list[str]:
    text = (rationale or "").lower()
    signal = signal or {}
    tags: list[str] = []

    def as_number(value: object) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            numeric = float(value)
            return None if math.isnan(numeric) else numeric
        return None

    def add(tag: str, cond: bool) -> None:
        if cond and tag not in tags:
            tags.append(tag)

    _momentum = as_number(signal.get("momentum"))
    _sharpe = as_number(signal.get("sharpe_20d"))
    _vol_ratio = as_number(signal.get("vol_ratio"))
    _rsi = as_number(signal.get("rsi_14"))
    _pct_high_breakout = as_number(signal.get("pct_from_52w_high"))

    add("momentum", "momentum" in text or (_momentum is not None and _momentum > 0))
    add("high_sharpe", "sharpe" in text or (_sharpe is not None and _sharpe >= 0.35))
    _at_breakout = (
        _pct_high_breakout is not None
        and _pct_high_breakout >= -0.03
    )
    add(
        "breakout",
        any(token in text for token in ("breakout", "52-week", "52 week", "parabolic"))
        or (_vol_ratio is not None and _vol_ratio >= 1.5 and _at_breakout),
    )
    add("consensus", "consensus" in text)
    _si = signal.get("short_interest")
    _si_valid = _si is not None and not (isinstance(_si, float) and math.isnan(_si))
    add(
        "catalyst",
        any(token in text for token in ("catalyst", "premarket", "gap", "squeeze", "iv spike", "event"))
        or "short interest" in text or _si_valid,
    )
    add("diversifier", "diversif" in text or "defensive" in text)
    add("earnings_risk", "earnings" in text or bool(signal.get("has_earnings_warning")))
    add(
        "non_us_differentiator",
        "." in ticker or any(token in text for token in ("baltic", "nordic", "non-us", "non us")),
    )
    add(
        "overbought",
        any(token in text for token in ("overbought", "rsi", "extended"))
        or (_rsi is not None and _rsi > 80),
    )
    _pct_high_at = as_number(signal.get("pct_from_52w_high"))
    _at_52w = (
        _pct_high_at is not None
        and _pct_high_at >= -0.02
    )
    add(
        "at_52w_high",
        any(token in text for token in ("52-week high", "52w high", "52 week high", "all-time high"))
        or _at_52w,
    )
    add(
        "pre_earnings_setup",
        any(token in text for token in ("pre_earnings", "pre-earnings", "pre earnings", "earnings setup"))
        or bool(signal.get("has_pre_earnings_setup")),
    )

    return tags


def load_last() -> Optional[PortfolioProposal]:
    """Load the most recent saved portfolio, or None if no history exists."""
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT date, decision_metrics FROM daily_runs ORDER BY date DESC LIMIT 1")
            latest_run = cur.fetchone()
            if not latest_run:
                return None

            latest_date = latest_run["date"]
            cur.execute("SELECT ticker, weight, rationale FROM portfolio_positions WHERE date = %s", (latest_date,))
            positions_data = cur.fetchall()

            positions = [Position(**p) for p in positions_data]
            if not positions:
                return None

            proposal = PortfolioProposal(
                positions=positions,
                reasoning="Loaded from database.",
                confidence=0.5,
                learning_reflection="",
            )
            logger.info(
                "Loaded previous portfolio (%d positions) from %s",
                len(positions),
                latest_date,
            )
            return proposal
    except Exception as exc:
        logger.error("Failed to load last portfolio from DB: %s", exc)
        return None


def load_performance_history(max_days: int = 5) -> list[dict]:
    """Load last N days of performance records from the database."""
    return [h.get("performance", {}) for h in load_decision_history(max_days)]


def load_decision_history(max_days: Optional[int] = None) -> list[dict]:
    """Load structured per-day decision records from the database."""
    query = """
        SELECT r.date, r.source AS provenance, r.regime, r.signal_snapshot, r.decision_metrics,
               r.bear_cases, r.benchmark_return_1d, r.portfolio_return_1d, r.alpha_1d
        FROM daily_runs r
        ORDER BY r.date DESC
    """
    if max_days:
        query += f" LIMIT {int(max_days)}"

    try:
        with get_db_cursor() as cur:
            cur.execute(query)
            runs = cur.fetchall()
            if not runs:
                return []

            dates = [run['date'] for run in runs]
            placeholders = ','.join(['%s'] * len(dates))

            cur.execute(f"SELECT date, ticker, weight, rationale, tags, return_1d FROM portfolio_positions WHERE date IN ({placeholders})", dates)
            all_positions = cur.fetchall()

            cur.execute(f"SELECT date, agent, ticker, weight, rationale, tags FROM agent_proposals WHERE date IN ({placeholders})", dates)
            all_agent_proposals = cur.fetchall()

            cur.execute(f"SELECT date, rank, total_participants FROM competition_standings WHERE date IN ({placeholders})", dates)
            all_standings = cur.fetchall()

            pos_by_date = {d: [] for d in dates}
            for p in all_positions:
                pos_by_date[p['date']].append(p)

            agent_prop_by_date = {d: {} for d in dates}
            for ap in all_agent_proposals:
                agent_prop_by_date[ap['date']].setdefault(ap['agent'], []).append(ap)

            standings_by_date = {s['date']: s for s in all_standings}

            history = []
            for run in reversed(runs):
                run_date = run['date']
                positions = pos_by_date.get(run_date, [])
                agent_proposals = agent_prop_by_date.get(run_date, {})

                record = {
                    "date": run_date.isoformat(),
                    "provenance": run.get('provenance'),
                    "regime": run.get('regime'),
                    "final_portfolio": {
                        "positions": positions,
                        "reasoning": "",
                        "confidence": 0.5,
                        "learning_reflection": "",
                    },
                    "strategist_proposal": {"positions": agent_proposals.get("strategist", [])},
                    "challenger_proposal": {"positions": agent_proposals.get("challenger", [])},
                    "full_analyst_proposal": {"positions": agent_proposals.get("full_analyst", [])},
                    "signal_snapshot": run.get('signal_snapshot'),
                    "decision_metrics": run.get('decision_metrics'),
                    "bear_cases": run.get('bear_cases'),
                    "competition_standing": standings_by_date.get(run_date),
                    "performance": {
                        "date": run_date.isoformat(),
                        "portfolio_return_1d": run.get('portfolio_return_1d'),
                        "benchmark_return_1d": run.get('benchmark_return_1d'),
                        "alpha_1d": run.get('alpha_1d'),
                        "position_returns": {p['ticker']: p.get('return_1d') for p in positions if p.get('return_1d') is not None}
                    },
                    "outcomes": {
                        "1d": {
                            "portfolio_return": run.get('portfolio_return_1d'),
                            "benchmark_return": run.get('benchmark_return_1d'),
                            "alpha": run.get('alpha_1d'),
                            "position_returns": {p['ticker']: p.get('return_1d') for p in positions if p.get('return_1d') is not None}
                        }
                    }
                }
                history.append(record)
            return history
    except Exception as exc:
        logger.error("Failed to load decision history from DB: %s", exc)
        return []


def load_yesterday_prices() -> dict:
    """Return saved close_prices from the last portfolio save, or empty dict."""
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT price_map FROM daily_runs WHERE price_map IS NOT NULL ORDER BY date DESC LIMIT 1")
            result = cur.fetchone()
            return result['price_map'] if result else {}
    except Exception as exc:
        logger.error("Failed to load yesterday's prices from DB: %s", exc)
        return {}


def save_competition_standing(rank: int, total: int, date: str) -> None:
    """Patch today's history record with competition rank and total participants."""
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO competition_standings (date, rank, total_participants)
                VALUES (%s, %s, %s)
                ON CONFLICT (date) DO UPDATE SET
                    rank = EXCLUDED.rank,
                    total_participants = EXCLUDED.total_participants;
            """, (date, rank, total))
        logger.info("Competition standing saved: rank %d/%d for %s", rank, total, date)
    except Exception as exc:
        logger.error("Failed to save competition standing to DB: %s", exc)


def load_competition_standing_history(max_days: int = 10) -> list[dict]:
    """Return the last N days of competition standings recorded in history."""
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT date, rank, total_participants FROM competition_standings ORDER BY date DESC LIMIT %s", (max_days,))
            return cur.fetchall()
    except Exception as exc:
        logger.error("Failed to load competition standing history from DB: %s", exc)
        return []


def load_last_known_participant_count() -> Optional[int]:
    """Return the most recently recorded total participant count, or None."""
    standings = load_competition_standing_history(max_days=30)
    if standings:
        return standings[-1].get("total")
    return None


def save_verified(
    positions: list[dict],
    date: str,
    close_prices: Optional[dict] = None,
) -> None:
    """Save the user's actual game portfolio as verified source of truth."""
    final_positions = [
        {
            "ticker": p["ticker"],
            "weight": round(float(p["weight"]), 6),
            "rationale": (p.get("rationale") or f"verified from game portfolio {date}"),
            "tags": p.get("tags", []),
        }
        for p in positions
    ]

    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO daily_runs (date, source, price_map) VALUES (%s, 'verified', %s)
                ON CONFLICT (date) DO UPDATE SET source = 'verified', price_map = COALESCE(EXCLUDED.price_map, daily_runs.price_map)
            """, (date, Json(close_prices) if close_prices else None))

            cur.execute("DELETE FROM portfolio_positions WHERE date = %s", (date,))
            for pos in final_positions:
                cur.execute("""
                    INSERT INTO portfolio_positions (date, ticker, weight, rationale, tags)
                    VALUES (%s, %s, %s, %s, %s)
                """, (date, pos['ticker'], pos['weight'], pos['rationale'], Json(pos['tags'])))
        logger.info("Verified portfolio saved to DB: %d positions for %s", len(positions), date)
    except Exception as exc:
        logger.error("Failed to save verified portfolio to DB: %s", exc)


def build_signal_snapshot(candidates: list[dict], tickers: set[str], earnings_warning: str = "") -> dict[str, dict]:
    def _clean_number(value):
        try:
            if value is None or math.isnan(value):
                return None
        except TypeError:
            return None
        return round(float(value), 6)

    snapshot: dict[str, dict] = {}
    warning_text = (earnings_warning or "").upper()
    for candidate in candidates:
        ticker = candidate.get("ticker")
        if ticker not in tickers:
            continue
        snapshot[ticker] = {
            "market": candidate.get("market"),
            "sector": candidate.get("sector"),
            "momentum": _clean_number(candidate.get("momentum")),
            "mom_5d": _clean_number(candidate.get("mom_5d")),
            "mom_60d": _clean_number(candidate.get("mom_60d")),
            "sharpe_20d": _clean_number(candidate.get("sharpe_20d")),
            "rsi_14": _clean_number(candidate.get("rsi_14")),
            "vs_index": _clean_number(candidate.get("vs_index")),
            "pct_from_52w_high": _clean_number(candidate.get("pct_from_52w_high")),
            "beta": _clean_number(candidate.get("beta")),
            "vol_ratio": _clean_number(candidate.get("vol_ratio")),
            "macd_hist": _clean_number(candidate.get("macd_hist")),
            "atr_pct": _clean_number(candidate.get("atr_pct")),
            "dividend_yield": _clean_number(candidate.get("dividend_yield")),
            "last_price": _clean_number(candidate.get("last_price")),
            "has_earnings_warning": ticker.upper() in warning_text,
        }
    return snapshot


def _normalize_signal_snapshot(
    signal_snapshot: Optional[object],
    tickers: set[str],
    earnings_warning: str = "",
) -> dict[str, dict]:
    if isinstance(signal_snapshot, dict):
        normalized: dict[str, dict] = {}
        for ticker, payload in signal_snapshot.items():
            if ticker in tickers and isinstance(payload, dict):
                normalized[ticker] = payload
        return normalized
    if isinstance(signal_snapshot, list):
        return build_signal_snapshot(signal_snapshot, tickers, earnings_warning=earnings_warning)
    return {}


def _build_decision_metrics(
    proposal: PortfolioProposal,
    prior_portfolio: Optional[PortfolioProposal],
    candidate_alternatives: Optional[list[dict]] = None,
) -> dict:
    current_weights = {pos.ticker: float(pos.weight) for pos in proposal.positions}
    prior_weights = {
        pos.ticker: float(pos.weight) for pos in prior_portfolio.positions
    } if prior_portfolio else {}

    selected = set(current_weights)
    prior = set(prior_weights)
    held = sorted(selected & prior)
    new = sorted(selected - prior)
    dropped = sorted(prior - selected)
    overlap_weight = sum(min(current_weights.get(t, 0.0), prior_weights.get(t, 0.0)) for t in held)
    turnover_estimate = max(0.0, 1.0 - overlap_weight)

    return {
        "selected_tickers": sorted(selected),
        "held_tickers": held,
        "new_tickers": new,
        "dropped_tickers": dropped,
        "held_count": len(held),
        "new_count": len(new),
        "dropped_count": len(dropped),
        "overlap_weight": round(overlap_weight, 6),
        "turnover_estimate": round(turnover_estimate, 6),
        "candidate_alternatives": deepcopy(candidate_alternatives or []),
    }


def _attach_outcomes_to_prior_record(
    cur: psycopg2.extensions.cursor,
    current_date: str,
    daily_performance: Optional[dict],
    returns_lookup: Optional[dict[str, float]] = None,
) -> None:
    if not daily_performance:
        return

    cur.execute("SELECT date FROM daily_runs WHERE date < %s ORDER BY date DESC LIMIT 1", (current_date,))
    prior_date_record = cur.fetchone()
    if not prior_date_record:
        return
    prior_date = prior_date_record['date']

    cur.execute("""
        UPDATE daily_runs SET
            portfolio_return_1d = %s,
            benchmark_return_1d = %s,
            alpha_1d = %s
        WHERE date = %s
    """, (
        daily_performance.get("portfolio_return_1d"),
        daily_performance.get("benchmark_return_1d"),
        daily_performance.get("alpha_1d"),
        prior_date
    ))

    returns_lookup = returns_lookup or {}
    for ticker, ret in returns_lookup.items():
        cur.execute("""
            UPDATE portfolio_positions SET return_1d = %s
            WHERE date = %s AND ticker = %s
        """, (ret, prior_date, ticker))


def save(
    proposal: PortfolioProposal,
    date: str,
    benchmark_return: Optional[float] = None,
    close_prices: Optional[dict] = None,
    daily_performance: Optional[dict] = None,
    decision_context: Optional[dict] = None,
) -> None:
    """Save portfolio plus structured per-day decision record to the database."""
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT 1 FROM daily_runs WHERE date = %s AND source = 'verified'", (date,))
            if cur.fetchone():
                logger.info("Verified portfolio exists for %s — AI proposal will not overwrite", date)
                _attach_outcomes_to_prior_record(cur, date, daily_performance, (decision_context or {}).get("returns_1d", {}))
                return

            _attach_outcomes_to_prior_record(cur, date, daily_performance, (decision_context or {}).get("returns_1d", {}))

            decision_context = decision_context or {}
            signal_snapshot = _normalize_signal_snapshot(
                decision_context.get("signal_snapshot"),
                {p.ticker for p in proposal.positions},
                earnings_warning=decision_context.get("earnings_warning", ""),
            )
            final_portfolio_dict = _portfolio_to_dict(proposal, signal_snapshot)

            decision_metrics = _build_decision_metrics(
                proposal,
                decision_context.get("prior_portfolio"),
                candidate_alternatives=decision_context.get("candidate_alternatives"),
            )

            cur.execute("""
                INSERT INTO daily_runs (date, source, regime, signal_snapshot, decision_metrics, bear_cases, price_map)
                VALUES (%s, 'ai_proposed', %s, %s, %s, %s, %s)
                ON CONFLICT (date) DO UPDATE SET
                    source = 'ai_proposed', regime = EXCLUDED.regime, signal_snapshot = EXCLUDED.signal_snapshot,
                    decision_metrics = EXCLUDED.decision_metrics, bear_cases = EXCLUDED.bear_cases, price_map = EXCLUDED.price_map;
            """, (date, decision_context.get("regime"), Json(signal_snapshot), Json(decision_metrics), Json(decision_context.get("bear_cases")), Json(close_prices)))

            cur.execute("DELETE FROM portfolio_positions WHERE date = %s", (date,))
            for pos in final_portfolio_dict.get("positions", []):
                cur.execute("INSERT INTO portfolio_positions (date, ticker, weight, rationale, tags) VALUES (%s, %s, %s, %s, %s)",
                            (date, pos['ticker'], pos['weight'], pos['rationale'], Json(pos['tags'])))

            cur.execute("DELETE FROM agent_proposals WHERE date = %s", (date,))
            for agent_key, agent_name in [("strategist_proposal", "strategist"), ("challenger_proposal", "challenger"), ("full_analyst_proposal", "full_analyst")]:
                agent_proposal = decision_context.get(agent_key)
                if agent_proposal:
                    agent_dict = _portfolio_to_dict(agent_proposal, signal_snapshot)
                    for pos in agent_dict.get("positions", []):
                        cur.execute("INSERT INTO agent_proposals (date, agent, ticker, weight, rationale, tags) VALUES (%s, %s, %s, %s, %s, %s)",
                                    (date, agent_name, pos['ticker'], pos['weight'], pos['rationale'], Json(pos['tags'])))
        logger.info("Saved AI proposal to DB for %s", date)
    except Exception as exc:
        logger.error("Failed to save portfolio to DB: %s", exc)


def save_learning_state_to_db(state: dict) -> None:
    """Persist learning state JSONB to DB (upsert single keyed row)."""
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS learning_cache (
                    key TEXT PRIMARY KEY,
                    state JSONB NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT now()
                )
            """)
            cur.execute("""
                INSERT INTO learning_cache (key, state, updated_at)
                VALUES ('main', %s, now())
                ON CONFLICT (key) DO UPDATE SET
                    state = EXCLUDED.state,
                    updated_at = now()
            """, (Json(state),))
        logger.info("Learning state saved to DB")
    except Exception as exc:
        logger.error("Failed to save learning state to DB: %s", exc)


def load_learning_state_from_db() -> Optional[dict]:
    """Load the most recent learning state from DB. Returns None if unavailable."""
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS learning_cache (
                    key TEXT PRIMARY KEY,
                    state JSONB NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT now()
                )
            """)
            cur.execute("SELECT state FROM learning_cache WHERE key = 'main'")
            row = cur.fetchone()
            if row:
                return dict(row["state"])
            return None
    except Exception as exc:
        logger.error("Failed to load learning state from DB: %s", exc)
        return None


def load_ai_proposal(date: str) -> Optional[list[dict]]:
    """Load today's AI-proposed positions from the DB. Returns None if not found."""
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT 1 FROM daily_runs WHERE date = %s", (date,))
            if not cur.fetchone():
                return None
            cur.execute(
                "SELECT ticker, weight, rationale FROM portfolio_positions WHERE date = %s ORDER BY weight DESC",
                (date,),
            )
            rows = cur.fetchall()
            if not rows:
                return None
            return [{"ticker": r["ticker"], "weight": float(r["weight"]), "rationale": r.get("rationale", "")} for r in rows]
    except Exception as exc:
        logger.error("Failed to load AI proposal from DB: %s", exc)
        return None
