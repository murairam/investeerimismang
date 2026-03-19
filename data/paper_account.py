"""
Paper-trading account for pre-game training with one-day delayed target application.
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

_FX_PAIRS: dict[str, str] = {
    "USD": "EURUSD=X",
    "DKK": "EURDKK=X",
    "SEK": "EURSEK=X",
    "NOK": "EURNOK=X",
}

_SUFFIX_CURRENCY: dict[str, str] = {
    "HE": "EUR",
    "TL": "EUR",
    "RI": "EUR",
    "VS": "EUR",
    "DE": "EUR",
    "ST": "SEK",
    "OL": "NOK",
    "CO": "DKK",
}


def _ticker_currency(ticker: str) -> str:
    if "." in ticker:
        return _SUFFIX_CURRENCY.get(ticker.rsplit(".", 1)[-1].upper(), "USD")
    return "USD"


def _fetch_fx_to_eur() -> dict[str, float]:
    import yfinance as yf

    rates: dict[str, float] = {"EUR": 1.0}
    try:
        raw = yf.download(list(_FX_PAIRS.values()), period="2d", auto_adjust=True, progress=False)
        close = raw["Close"] if "Close" in raw else raw
        for currency, pair in _FX_PAIRS.items():
            col = close.get(pair) if hasattr(close, "get") else None
            if col is not None:
                series = col.dropna()
                if not series.empty:
                    rates[currency] = round(1.0 / float(series.iloc[-1]), 6)
    except Exception as exc:
        logger.warning("FX fetch failed — equity will use native prices as EUR fallback: %s", exc)
    return rates


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


def _mark_to_market(
    positions: dict[str, float],
    cash: float,
    price_map: dict[str, float],
    fx_rates: Optional[dict[str, float]] = None,
) -> tuple[float, dict[str, float]]:
    holdings_value: dict[str, float] = {}
    equity = cash
    for ticker, shares in positions.items():
        px = price_map.get(ticker)
        if px is None:
            continue
        fx = fx_rates.get(_ticker_currency(ticker), 1.0) if fx_rates else 1.0
        value_eur = shares * px * fx
        holdings_value[ticker] = value_eur
        equity += value_eur
    return equity, holdings_value


def _proposal_targets(proposal: PortfolioProposal) -> list[dict]:
    return [{"ticker": pos.ticker, "weight": round(float(pos.weight), 6)} for pos in proposal.positions]


def _execute_pending_order(
    state: dict,
    as_of_date: str,
    price_map: dict[str, float],
    fx_rates: dict[str, float],
) -> tuple[dict[str, float], float, float]:
    positions = {ticker: float(shares) for ticker, shares in state.get("positions", {}).items()}
    cash = float(state.get("cash", 0.0))
    pending = state.get("pending_order")
    if not pending or pending.get("submitted_date") == as_of_date:
        return positions, cash, 0.0

    equity_before, holding_values_before = _mark_to_market(positions, cash, price_map, fx_rates)
    if equity_before <= 0:
        return positions, cash, 0.0

    target_positions: dict[str, float] = {}
    traded_value = 0.0
    for target in pending.get("positions", []):
        ticker = target["ticker"]
        px = price_map.get(ticker)
        if px is None or px <= 0:
            continue
        fx = fx_rates.get(_ticker_currency(ticker), 1.0)
        target_value_eur = equity_before * float(target["weight"])
        current_value_eur = holding_values_before.get(ticker, 0.0)
        traded_value += abs(target_value_eur - current_value_eur)
        target_positions[ticker] = target_value_eur / (px * fx)

    invested_after_eur = sum(
        shares * price_map[ticker] * fx_rates.get(_ticker_currency(ticker), 1.0)
        for ticker, shares in target_positions.items()
        if ticker in price_map
    )
    cash_after = max(0.0, equity_before - invested_after_eur)
    return target_positions, cash_after, traded_value / equity_before if equity_before > 0 else 0.0


def sync_verified_positions(
    positions: list[dict],
    equity: float,
    as_of_date: str,
    price_map: dict[str, float],
) -> None:
    state = _load_raw()
    initial_capital = float(state.get("initial_capital", equity))
    fx_rates = _fetch_fx_to_eur()

    target_positions: dict[str, float] = {}
    for pos in positions:
        ticker = pos["ticker"]
        px = price_map.get(ticker)
        if px and px > 0:
            fx = fx_rates.get(_ticker_currency(ticker), 1.0)
            target_positions[ticker] = round((equity * pos["weight"]) / (px * fx), 8)

    history = state.get("history", [])
    return_since_start = (equity / initial_capital - 1) if initial_capital > 0 else 0.0
    history_entry = {
        "date": as_of_date,
        "equity": round(equity, 2),
        "cash": 0.0,
        "daily_return": 0.0,
        "return_since_start": round(return_since_start, 6),
        "turnover": 1.0,
        "positions": target_positions,
        "pending_order": None,
        "source": "verified",
    }
    if history and history[-1].get("date") == as_of_date:
        history[-1] = history_entry
    else:
        history.append(history_entry)
    history = history[-60:]

    _save_raw(
        {
            "start_date": state.get("start_date") or as_of_date,
            "initial_capital": initial_capital,
            "cash": 0.0,
            "positions": target_positions,
            "pending_order": None,
            "history": history,
            "last_rebalanced_date": as_of_date,
            "last_equity": round(equity, 8),
        }
    )


def reset_for_live(start_date: str) -> None:
    _save_raw(
        {
            "start_date": start_date,
            "initial_capital": _DEFAULT_START_CAPITAL,
            "cash": _DEFAULT_START_CAPITAL,
            "positions": {},
            "pending_order": None,
            "history": [],
            "last_rebalanced_date": None,
            "last_equity": _DEFAULT_START_CAPITAL,
        }
    )
    logger.info("Paper account reset to €%.0f for LIVE mode start (%s)", _DEFAULT_START_CAPITAL, start_date)


def rebalance_to_proposal(
    proposal: PortfolioProposal,
    as_of_date: str,
    price_map: dict[str, float],
    start_capital: float = _DEFAULT_START_CAPITAL,
) -> Optional[dict]:
    state = _load_raw()
    if not state:
        state = {
            "start_date": as_of_date,
            "initial_capital": float(start_capital),
            "cash": float(start_capital),
            "positions": {},
            "pending_order": None,
            "history": [],
            "last_rebalanced_date": None,
            "last_equity": float(start_capital),
        }

    if state.get("last_rebalanced_date") == as_of_date:
        logger.info("Paper account already processed for %s — skipping duplicate run", as_of_date)
        return {
            "as_of_date": as_of_date,
            "equity": float(state.get("last_equity", state.get("initial_capital", start_capital))),
            "initial_capital": float(state.get("initial_capital", start_capital)),
            "daily_return": 0.0,
            "return_since_start": (
                float(state.get("last_equity", start_capital)) / float(state.get("initial_capital", start_capital))
            ) - 1,
            "turnover": 0.0,
            "cash": float(state.get("cash", 0.0)),
            "positions": state.get("positions", {}),
            "pending_order_submitted": False,
            "executed_pending": False,
            "skipped_duplicate": True,
        }

    fx_rates = _fetch_fx_to_eur()
    active_positions, active_cash, turnover = _execute_pending_order(state, as_of_date, price_map, fx_rates)
    executed_pending = bool(state.get("pending_order")) and state.get("pending_order", {}).get("submitted_date") != as_of_date
    equity_after_execution, _ = _mark_to_market(active_positions, active_cash, price_map, fx_rates)
    if equity_after_execution <= 0:
        logger.warning("Paper account equity is non-positive (%.2f) — skipping rebalance", equity_after_execution)
        return None

    prev_equity = float(state.get("last_equity", state.get("initial_capital", start_capital)))
    daily_return = (equity_after_execution / prev_equity - 1) if prev_equity > 0 else 0.0
    initial_capital = float(state.get("initial_capital", start_capital))
    return_since_start = (equity_after_execution / initial_capital - 1) if initial_capital > 0 else 0.0

    pending_order = {
        "submitted_date": as_of_date,
        "positions": _proposal_targets(proposal),
    }

    history = state.get("history", [])
    history_entry = {
        "date": as_of_date,
        "equity": round(equity_after_execution, 2),
        "cash": round(active_cash, 2),
        "daily_return": round(daily_return, 6),
        "return_since_start": round(return_since_start, 6),
        "turnover": round(turnover, 6),
        "positions": {ticker: round(shares, 8) for ticker, shares in active_positions.items()},
        "pending_order": pending_order,
        "executed_pending": executed_pending,
    }
    if history and history[-1].get("date") == as_of_date:
        history[-1] = history_entry
    else:
        history.append(history_entry)
    history = history[-60:]

    _save_raw(
        {
            "start_date": state.get("start_date") or date.today().isoformat(),
            "initial_capital": initial_capital,
            "cash": round(active_cash, 8),
            "positions": {ticker: round(shares, 8) for ticker, shares in active_positions.items()},
            "pending_order": pending_order,
            "history": history,
            "last_rebalanced_date": as_of_date,
            "last_equity": round(equity_after_execution, 8),
        }
    )

    return {
        "as_of_date": as_of_date,
        "equity": equity_after_execution,
        "initial_capital": initial_capital,
        "daily_return": daily_return,
        "return_since_start": return_since_start,
        "turnover": turnover,
        "cash": active_cash,
        "positions": active_positions,
        "pending_order_submitted": True,
        "executed_pending": executed_pending,
        "skipped_duplicate": False,
    }
