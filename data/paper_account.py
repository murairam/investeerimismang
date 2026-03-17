"""
Paper-trading account for pre-game training.

Tracks a virtual account that starts with fixed cash and is rebalanced daily
to the latest agent proposal. This lets us practice execution and evaluate the
decision quality before the real game starts.
"""
import json
import logging
import os
from datetime import date
from typing import Optional

from portfolio.models import PortfolioProposal

logger = logging.getLogger(__name__)

_PAPER_STORE_PATH = os.path.join(os.path.dirname(__file__), "..", "paper_account.json")
_DEFAULT_START_CAPITAL = 10000.0


def _load_raw() -> dict:
    path = os.path.abspath(_PAPER_STORE_PATH)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Could not load paper account state: %s", exc)
        return {}


def _save_raw(data: dict) -> None:
    path = os.path.abspath(_PAPER_STORE_PATH)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _mark_to_market(positions: dict[str, float], cash: float, price_map: dict[str, float]) -> tuple[float, dict[str, float]]:
    holdings_value: dict[str, float] = {}
    equity = cash
    for ticker, shares in positions.items():
        px = price_map.get(ticker)
        if px is None:
            continue
        value = shares * px
        holdings_value[ticker] = value
        equity += value
    return equity, holdings_value


def reset_for_live(start_date: str) -> None:
    """
    Reset the paper account to €10,000 on the first LIVE run (April 6).
    The game wipes all pre-game gains/losses and restarts everyone at 10,000.
    """
    state = {
        "start_date": start_date,
        "initial_capital": _DEFAULT_START_CAPITAL,
        "cash": _DEFAULT_START_CAPITAL,
        "positions": {},
        "history": [],
        "last_rebalanced_date": None,
        "last_equity": _DEFAULT_START_CAPITAL,
    }
    _save_raw(state)
    logger.info(
        "Paper account reset to €%.0f for LIVE mode start (%s)",
        _DEFAULT_START_CAPITAL,
        start_date,
    )


def rebalance_to_proposal(
    proposal: PortfolioProposal,
    as_of_date: str,
    price_map: dict[str, float],
    start_capital: float = _DEFAULT_START_CAPITAL,
) -> Optional[dict]:
    """
    Rebalance the paper account to proposal weights and persist state.

    Returns summary metrics dict, or None when rebalance cannot be applied.
    """
    state = _load_raw()
    if not state:
        state = {
            "start_date": as_of_date,
            "initial_capital": float(start_capital),
            "cash": float(start_capital),
            "positions": {},
            "history": [],
            "last_rebalanced_date": None,
            "last_equity": float(start_capital),
        }

    if state.get("last_rebalanced_date") == as_of_date:
        logger.info("Paper account already rebalanced for %s — skipping duplicate run", as_of_date)
        return {
            "as_of_date": as_of_date,
            "equity": float(state.get("last_equity", state.get("initial_capital", start_capital))),
            "initial_capital": float(state.get("initial_capital", start_capital)),
            "daily_return": 0.0,
            "return_since_start": (
                float(state.get("last_equity", start_capital)) / float(state.get("initial_capital", start_capital))
            ) - 1,
            "turnover": 0.0,
            "positions": state.get("positions", {}),
            "skipped_duplicate": True,
        }

    current_positions: dict[str, float] = {
        ticker: float(shares)
        for ticker, shares in state.get("positions", {}).items()
    }
    current_cash = float(state.get("cash", 0.0))
    prev_equity = float(state.get("last_equity", state.get("initial_capital", start_capital)))

    equity_before, holding_values_before = _mark_to_market(current_positions, current_cash, price_map)
    if equity_before <= 0:
        logger.warning("Paper account equity is non-positive (%.2f) — skipping rebalance", equity_before)
        return None

    target_positions: dict[str, float] = {}
    traded_value = 0.0
    for pos in proposal.positions:
        px = price_map.get(pos.ticker)
        if px is None or px <= 0:
            continue
        target_value = equity_before * pos.weight
        current_value = holding_values_before.get(pos.ticker, 0.0)
        traded_value += abs(target_value - current_value)
        target_positions[pos.ticker] = target_value / px

    invested_after = 0.0
    for ticker, shares in target_positions.items():
        px = price_map.get(ticker)
        if px is None:
            continue
        invested_after += shares * px

    cash_after = equity_before - invested_after
    if cash_after < -1e-6:
        logger.warning("Paper account rebalance produced negative cash %.6f — clipping to zero", cash_after)
        cash_after = 0.0

    equity_after, _ = _mark_to_market(target_positions, cash_after, price_map)
    daily_return = (equity_after / prev_equity - 1) if prev_equity > 0 else 0.0
    initial_capital = float(state.get("initial_capital", start_capital))
    return_since_start = (equity_after / initial_capital - 1) if initial_capital > 0 else 0.0
    turnover = (traded_value / equity_before) if equity_before > 0 else 0.0

    history = state.get("history", [])
    history_entry = {
        "date": as_of_date,
        "equity": round(equity_after, 2),
        "cash": round(cash_after, 2),
        "daily_return": round(daily_return, 6),
        "return_since_start": round(return_since_start, 6),
        "turnover": round(turnover, 6),
        "positions": {
            ticker: round(shares, 8)
            for ticker, shares in target_positions.items()
        },
    }
    if history and history[-1].get("date") == as_of_date:
        history[-1] = history_entry
    else:
        history.append(history_entry)
    history = history[-60:]

    new_state = {
        "start_date": state.get("start_date") or date.today().isoformat(),
        "initial_capital": initial_capital,
        "cash": round(cash_after, 8),
        "positions": {
            ticker: round(shares, 8)
            for ticker, shares in target_positions.items()
        },
        "history": history,
        "last_rebalanced_date": as_of_date,
        "last_equity": round(equity_after, 8),
    }
    _save_raw(new_state)

    return {
        "as_of_date": as_of_date,
        "equity": equity_after,
        "initial_capital": initial_capital,
        "daily_return": daily_return,
        "return_since_start": return_since_start,
        "turnover": turnover,
        "cash": cash_after,
        "positions": target_positions,
        "skipped_duplicate": False,
    }