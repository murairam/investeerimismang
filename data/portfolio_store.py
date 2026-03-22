"""
Persist and load the latest portfolio proposal plus structured daily decision history.
"""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from copy import deepcopy
from typing import Optional

from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)

_STORE_PATH = os.path.join(os.path.dirname(__file__), "..", "portfolio_history.json")

RATIONALE_TAGS = (
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


def _safe_read() -> dict:
    path = os.path.abspath(_STORE_PATH)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Could not load portfolio history: %s", exc)
        return {}


def _sanitize(obj):
    """Recursively replace float NaN/Inf with None so json.dump produces valid JSON."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _safe_write(data: dict) -> None:
    path = os.path.abspath(_STORE_PATH)
    try:
        dir_ = os.path.dirname(path)
        with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp") as f:
            json.dump(_sanitize(data), f, indent=2)
            tmp = f.name
        os.replace(tmp, path)
        logger.info("Saved portfolio to %s", path)
    except Exception as exc:
        logger.warning("Could not save portfolio history: %s", exc)


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


def _legacy_entry_from_root(data: dict) -> Optional[dict]:
    if not data.get("date"):
        return None

    positions = data.get("positions", [])
    performance = None
    perf_history = data.get("performance_history", [])
    for entry in reversed(perf_history):
        if entry.get("date") == data.get("date"):
            performance = deepcopy(entry)
            break

    return {
        "date": data.get("date"),
        "provenance": data.get("source", "ai_proposed"),
        "final_portfolio": {
            "positions": deepcopy(positions),
            "reasoning": data.get("reasoning", ""),
            "confidence": float(data.get("confidence", 0.5)),
            "learning_reflection": data.get("learning_reflection", ""),
        },
        "performance": performance or {},
        "signal_snapshot": {},
        "validation": {},
    }


def _ensure_history(data: dict) -> list[dict]:
    history = data.get("history")
    if isinstance(history, list):
        return history
    legacy = _legacy_entry_from_root(data)
    return [legacy] if legacy else []


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

    def add(tag: str, cond: bool) -> None:
        if cond and tag not in tags:
            tags.append(tag)

    add("momentum", "momentum" in text or signal.get("momentum", 0.0) > 0)
    add("high_sharpe", "sharpe" in text or signal.get("sharpe_20d", 0.0) >= 0.35)
    _pct_high_breakout = signal.get("pct_from_52w_high")
    _at_breakout = (
        _pct_high_breakout is not None
        and not math.isnan(_pct_high_breakout)
        and _pct_high_breakout >= -0.03
    )
    add(
        "breakout",
        any(token in text for token in ("breakout", "52-week", "52 week", "parabolic"))
        or (signal.get("vol_ratio", 0.0) >= 1.5 and _at_breakout),
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
        or signal.get("rsi_14", 0.0) > 80,
    )
    _pct_high_at = signal.get("pct_from_52w_high")
    _at_52w = (
        _pct_high_at is not None
        and not math.isnan(_pct_high_at)
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
    data = _safe_read()
    positions = [
        Position(
            ticker=p["ticker"],
            weight=float(p["weight"]),
            rationale=p.get("rationale", ""),
        )
        for p in data.get("positions", [])
    ]
    if not positions:
        return None
    proposal = PortfolioProposal(
        positions=positions,
        reasoning=data.get("reasoning", ""),
        confidence=float(data.get("confidence", 0.5)),
        learning_reflection=data.get("learning_reflection", ""),
    )
    logger.info(
        "Loaded previous portfolio (%d positions) from %s",
        len(positions),
        data.get("date", "?"),
    )
    return proposal


def load_performance_history(max_days: int = 5) -> list[dict]:
    """Load last N days of legacy performance records."""
    data = _safe_read()
    return data.get("performance_history", [])[-max_days:]


def load_decision_history(max_days: Optional[int] = None) -> list[dict]:
    """Load structured per-day decision records, falling back to legacy root data."""
    data = _safe_read()
    history = _ensure_history(data)
    if max_days is not None:
        history = history[-max_days:]
    return deepcopy(history)


def load_yesterday_prices() -> dict:
    """Return saved close_prices from the last portfolio save, or empty dict."""
    data = _safe_read()
    return data.get("close_prices", {})


def save_verified(
    positions: list[dict],
    date: str,
    close_prices: Optional[dict] = None,
) -> None:
    """Save the user's actual game portfolio as verified source of truth."""
    existing = _safe_read()
    performance_history = existing.get("performance_history", [])
    history = _ensure_history(existing)

    def _clean_tags(raw_tags) -> list[str]:
        if not isinstance(raw_tags, list):
            return []
        cleaned: list[str] = []
        for tag in raw_tags:
            if isinstance(tag, str) and tag in RATIONALE_TAGS and tag not in cleaned:
                cleaned.append(tag)
        return cleaned

    previous_tags: dict[str, list[str]] = {}
    for entry in existing.get("positions", []):
        ticker = entry.get("ticker")
        if isinstance(ticker, str):
            tags = _clean_tags(entry.get("tags", []))
            if tags:
                previous_tags[ticker] = tags

    previous_signal_map: dict[str, dict] = {}
    if history:
        latest_history = history[-1]
        latest_positions = latest_history.get("final_portfolio", {}).get("positions", [])
        for entry in latest_positions:
            ticker = entry.get("ticker")
            if isinstance(ticker, str):
                tags = _clean_tags(entry.get("tags", []))
                if tags and ticker not in previous_tags:
                    previous_tags[ticker] = tags
        signal_snapshot = latest_history.get("signal_snapshot", {})
        if isinstance(signal_snapshot, dict):
            previous_signal_map = _build_signal_map(signal_snapshot)

    final_positions = [
        {
            "ticker": p["ticker"],
            "weight": round(float(p["weight"]), 6),
            "rationale": (p.get("rationale") or f"verified from game portfolio {date}"),
            "tags": (
                _clean_tags(p.get("tags", []))
                or derive_rationale_tags(
                    p["ticker"],
                    p.get("rationale") or f"verified from game portfolio {date}",
                    previous_signal_map.get(p["ticker"], {}),
                )
                or previous_tags.get(p["ticker"], [])
            ),
        }
        for p in positions
    ]

    data: dict = {
        "date": date,
        "source": "verified",
        "positions": final_positions,
        "reasoning": existing.get("reasoning", "Verified game portfolio"),
        "confidence": existing.get("confidence", 1.0),
        "learning_reflection": existing.get("learning_reflection", ""),
        "performance_history": performance_history,
        "history": history,
    }

    record = {
        "date": date,
        "provenance": "verified",
        "final_portfolio": {
            "positions": deepcopy(final_positions),
            "reasoning": data["reasoning"],
            "confidence": float(data["confidence"]),
            "learning_reflection": data["learning_reflection"],
        },
        "performance": {},
        "signal_snapshot": {},
        "validation": {"verified_override": True},
    }

    _upsert_history_record(data["history"], record)

    if close_prices is not None:
        data["close_prices"] = close_prices
    elif "close_prices" in existing:
        data["close_prices"] = existing["close_prices"]

    _safe_write(data)
    logger.info("Verified portfolio saved: %d positions for %s", len(positions), date)


def _upsert_history_record(history: list[dict], record: dict) -> None:
    if history and history[-1].get("date") == record.get("date"):
        history[-1] = record
    else:
        history.append(record)
    del history[:-60]


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
    history: list[dict],
    current_date: str,
    daily_performance: Optional[dict],
    returns_lookup: Optional[dict[str, float]] = None,
) -> None:
    if not history or not daily_performance:
        return

    prior_record = None
    for record in reversed(history):
        if record.get("date") != current_date:
            prior_record = record
            break
    if prior_record is None:
        return

    prior_record["performance"] = {
        "date": current_date,
        "portfolio_return_1d": round(daily_performance.get("portfolio_return_1d", 0.0), 6),
        "benchmark_return_1d": round(daily_performance.get("benchmark_return_1d", 0.0), 6),
        "alpha_1d": round(daily_performance.get("alpha_1d", 0.0), 6),
        "position_returns": {
            t: round(r, 6) for t, r in daily_performance.get("position_returns", {}).items()
        },
    }
    prior_record["outcomes"] = {
        "1d": {
            "portfolio_return": round(daily_performance.get("portfolio_return_1d", 0.0), 6),
            "benchmark_return": round(daily_performance.get("benchmark_return_1d", 0.0), 6),
            "alpha": round(daily_performance.get("alpha_1d", 0.0), 6),
            "position_returns": {
                t: round(r, 6) for t, r in daily_performance.get("position_returns", {}).items()
            },
        }
    }

    returns_lookup = returns_lookup or {}
    decision_metrics = prior_record.get("decision_metrics", {})
    new_returns = [returns_lookup[t] for t in decision_metrics.get("new_tickers", []) if t in returns_lookup]
    dropped_returns = [returns_lookup[t] for t in decision_metrics.get("dropped_tickers", []) if t in returns_lookup]
    selected_returns = [
        returns_lookup[t] for t in decision_metrics.get("selected_tickers", []) if t in returns_lookup
    ]
    alt_returns = [
        returns_lookup[item["ticker"]]
        for item in decision_metrics.get("candidate_alternatives", [])
        if item.get("ticker") in returns_lookup
    ]
    evaluation = {
        "new_avg_return_1d": round(sum(new_returns) / len(new_returns), 6) if new_returns else None,
        "dropped_avg_return_1d": round(sum(dropped_returns) / len(dropped_returns), 6) if dropped_returns else None,
        "hold_vs_replace_1d": round((sum(new_returns) / len(new_returns)) - (sum(dropped_returns) / len(dropped_returns)), 6)
        if new_returns and dropped_returns else None,
        "selected_avg_return_1d": round(sum(selected_returns) / len(selected_returns), 6) if selected_returns else None,
        "alternatives_avg_return_1d": round(sum(alt_returns) / len(alt_returns), 6) if alt_returns else None,
        "slot_opportunity_cost_1d": round((sum(alt_returns) / len(alt_returns)) - (sum(selected_returns) / len(selected_returns)), 6)
        if alt_returns and selected_returns else None,
    }
    prior_record["decision_evaluation"] = evaluation


def save(
    proposal: PortfolioProposal,
    date: str,
    benchmark_return: Optional[float] = None,
    close_prices: Optional[dict] = None,
    daily_performance: Optional[dict] = None,
    decision_context: Optional[dict] = None,
) -> None:
    """Save portfolio plus structured per-day decision record."""
    existing = _safe_read()

    is_verified_today = existing.get("date") == date and existing.get("source") == "verified"
    already_saved_today = existing.get("date") == date and existing.get("positions")
    if is_verified_today:
        logger.info("Verified portfolio exists for %s — AI proposal will not overwrite it", date)
    elif already_saved_today:
        logger.info("Portfolio already saved for %s — skipping proposal overwrite, updating performance only", date)

    performance_history: list[dict] = existing.get("performance_history", [])
    if not performance_history or performance_history[-1].get("date") != date:
        entry: dict = {"date": date}
        if benchmark_return is not None:
            entry["benchmark_return_20d"] = round(benchmark_return, 4)
        if daily_performance is not None:
            entry["portfolio_return_1d"] = round(daily_performance.get("portfolio_return_1d", 0.0), 6)
            entry["benchmark_return_1d"] = round(daily_performance.get("benchmark_return_1d", 0.0), 6)
            entry["alpha_1d"] = round(daily_performance.get("alpha_1d", 0.0), 6)
            entry["position_returns"] = {
                t: round(r, 6) for t, r in daily_performance.get("position_returns", {}).items()
            }
        performance_history.append(entry)
    else:
        entry = performance_history[-1]
        if benchmark_return is not None:
            entry["benchmark_return_20d"] = round(benchmark_return, 4)
        if daily_performance is not None:
            entry["portfolio_return_1d"] = round(daily_performance.get("portfolio_return_1d", 0.0), 6)
            entry["benchmark_return_1d"] = round(daily_performance.get("benchmark_return_1d", 0.0), 6)
            entry["alpha_1d"] = round(daily_performance.get("alpha_1d", 0.0), 6)
            entry["position_returns"] = {
                t: round(r, 6) for t, r in daily_performance.get("position_returns", {}).items()
            }
    performance_history = performance_history[-60:]

    signal_snapshot = _build_signal_map((decision_context or {}).get("signal_snapshot"))
    final_portfolio = _portfolio_to_dict(proposal, signal_snapshot)
    history = _ensure_history(existing)
    _attach_outcomes_to_prior_record(
        history,
        date,
        daily_performance,
        (decision_context or {}).get("returns_1d", {}),
    )
    decision_metrics = _build_decision_metrics(
        proposal,
        (decision_context or {}).get("prior_portfolio"),
        candidate_alternatives=(decision_context or {}).get("candidate_alternatives"),
    )
    record = {
        "date": date,
        "provenance": "ai_proposed",
        "final_portfolio": final_portfolio,
        "strategist_proposal": _portfolio_to_dict((decision_context or {}).get("strategist_proposal"), signal_snapshot)
        if (decision_context or {}).get("strategist_proposal") else None,
        "challenger_proposal": _portfolio_to_dict((decision_context or {}).get("challenger_proposal"), signal_snapshot)
        if (decision_context or {}).get("challenger_proposal") else None,
        "bear_cases": deepcopy((decision_context or {}).get("bear_cases", {})),
        "validation": deepcopy((decision_context or {}).get("validation", {})),
        "signal_snapshot": signal_snapshot,
        "decision_metrics": decision_metrics,
        "performance": {},
        "outcomes": {},
    }
    _upsert_history_record(history, record)

    if is_verified_today or already_saved_today:
        data: dict = {
            "date": existing["date"],
            "positions": existing["positions"],
            "reasoning": existing.get("reasoning", proposal.reasoning),
            "confidence": existing.get("confidence", proposal.confidence),
            "learning_reflection": existing.get("learning_reflection", proposal.learning_reflection),
            "performance_history": performance_history,
            "history": history,
        }
        if existing.get("source"):
            data["source"] = existing["source"]
    else:
        data = {
            "date": date,
            "positions": final_portfolio["positions"],
            "reasoning": proposal.reasoning,
            "confidence": proposal.confidence,
            "learning_reflection": proposal.learning_reflection,
            "performance_history": performance_history,
            "history": history,
            "source": "ai_proposed",
        }

    if close_prices is not None:
        data["close_prices"] = close_prices
    elif "close_prices" in existing:
        data["close_prices"] = existing["close_prices"]

    _safe_write(data)
