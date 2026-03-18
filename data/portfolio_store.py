"""
Persist and load the last accepted portfolio proposal.
Also tracks daily performance vs benchmark for the feedback loop.
"""
import json
import logging
import os
from typing import Optional

from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)

_STORE_PATH = os.path.join(os.path.dirname(__file__), "..", "portfolio_history.json")


def load_last() -> Optional[PortfolioProposal]:
    """Load the most recent saved portfolio, or None if no history exists."""
    path = os.path.abspath(_STORE_PATH)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            data = json.load(f)
        positions = [
            Position(
                ticker=p["ticker"],
                weight=float(p["weight"]),
                rationale=p.get("rationale", ""),
            )
            for p in data.get("positions", [])
        ]
        proposal = PortfolioProposal(
            positions=positions,
            reasoning=data.get("reasoning", ""),
            confidence=float(data.get("confidence", 0.5)),
        )
        logger.info("Loaded previous portfolio (%d positions) from %s", len(positions), data.get("date", "?"))
        return proposal
    except Exception as exc:
        logger.warning("Could not load portfolio history: %s", exc)
        return None


def load_performance_history(max_days: int = 5) -> list[dict]:
    """Load last N days of performance records from portfolio_history.json."""
    path = os.path.abspath(_STORE_PATH)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data.get("performance_history", [])[-max_days:]
    except Exception:
        return []


def load_yesterday_prices() -> dict:
    """Return saved close_prices from the last portfolio save, or empty dict."""
    path = os.path.abspath(_STORE_PATH)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data.get("close_prices", {})
    except Exception:
        return {}


def save(
    proposal: PortfolioProposal,
    date: str,
    benchmark_return: Optional[float] = None,
    close_prices: Optional[dict] = None,
    daily_performance: Optional[dict] = None,
) -> None:
    """Save portfolio to portfolio_history.json.

    Args:
        proposal: The portfolio to save.
        date: The as-of date string.
        benchmark_return: 20d benchmark return for trend tracking.
        close_prices: {ticker: price} for all positions (used next day for P&L).
        daily_performance: dict with portfolio_return_1d, benchmark_return_1d,
            alpha_1d, position_returns — recorded in performance_history.
    """
    path = os.path.abspath(_STORE_PATH)

    # Load existing data to preserve performance history
    existing: dict = {}
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                existing = json.load(f)
        except Exception:
            existing = {}

    # Idempotency guard: if today's proposal is already saved, only update
    # performance_history — don't overwrite positions/reasoning/confidence.
    # This prevents a second orchestrator run from replacing the morning proposal.
    already_saved_today = (
        existing.get("date") == date and existing.get("positions")
    )
    if already_saved_today:
        logger.info(
            "Portfolio already saved for %s — skipping proposal overwrite, updating performance only",
            date,
        )

    performance_history: list[dict] = existing.get("performance_history", [])

    # Build today's performance history entry
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
        # Update the existing entry for today
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

    # Keep only last 10 entries
    performance_history = performance_history[-10:]

    if already_saved_today:
        # Preserve the original morning proposal; only refresh performance + prices
        data: dict = {
            "date": existing["date"],
            "positions": existing["positions"],
            "reasoning": existing.get("reasoning", proposal.reasoning),
            "confidence": existing.get("confidence", proposal.confidence),
            "performance_history": performance_history,
        }
        if close_prices is not None:
            data["close_prices"] = close_prices
        elif "close_prices" in existing:
            data["close_prices"] = existing["close_prices"]
    else:
        data = {
            "date": date,
            "positions": [
                {"ticker": p.ticker, "weight": p.weight, "rationale": p.rationale}
                for p in proposal.positions
            ],
            "reasoning": proposal.reasoning,
            "confidence": proposal.confidence,
            "performance_history": performance_history,
        }
        if close_prices is not None:
            data["close_prices"] = close_prices

    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Saved portfolio to %s", path)
    except Exception as exc:
        logger.warning("Could not save portfolio history: %s", exc)
