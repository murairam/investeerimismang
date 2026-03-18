"""
Paper-trading account for pre-game training.

Tracks a virtual account that starts with fixed cash and is rebalanced daily
to the latest agent proposal. This lets us practice execution and evaluate the
decision quality before the real game starts.

All equity values are denominated in EUR. Non-EUR holdings are converted using
live FX rates fetched from yfinance (EURUSD=X, EURDKK=X, EURSEK=X, EURNOK=X).
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

# yfinance pair → quote currency per 1 EUR (e.g. EURUSD=X ≈ 1.09 means 1 EUR = 1.09 USD)
_FX_PAIRS: dict[str, str] = {
    "USD": "EURUSD=X",
    "DKK": "EURDKK=X",
    "SEK": "EURSEK=X",
    "NOK": "EURNOK=X",
}

# Ticker suffix → ISO currency code
_SUFFIX_CURRENCY: dict[str, str] = {
    "HE": "EUR",  # Helsinki
    "TL": "EUR",  # Tallinn
    "RI": "EUR",  # Riga
    "VS": "EUR",  # Vilnius
    "DE": "EUR",  # Frankfurt
    "ST": "SEK",  # Stockholm
    "OL": "NOK",  # Oslo
    "CO": "DKK",  # Copenhagen
}


def _ticker_currency(ticker: str) -> str:
    """Return the ISO currency code for a ticker based on its exchange suffix."""
    if "." in ticker:
        suffix = ticker.rsplit(".", 1)[-1].upper()
        return _SUFFIX_CURRENCY.get(suffix, "USD")
    return "USD"  # no suffix → US market


def _fetch_fx_to_eur() -> dict[str, float]:
    """
    Return {currency: eur_per_1_unit} for all non-EUR currencies.
    Falls back to 1.0 (no conversion) on any fetch failure.
    EUR is always 1.0.
    """
    import yfinance as yf

    rates: dict[str, float] = {"EUR": 1.0}
    try:
        pairs = list(_FX_PAIRS.values())
        raw = yf.download(pairs, period="2d", auto_adjust=True, progress=False)
        close = raw["Close"] if "Close" in raw else raw
        for currency, pair in _FX_PAIRS.items():
            col = close.get(pair) if hasattr(close, "get") else (close[pair] if pair in close.columns else None)
            if col is not None:
                series = col.dropna()
                if not series.empty:
                    # EURUSD=X gives USD-per-EUR → invert to get EUR-per-USD
                    rates[currency] = round(1.0 / float(series.iloc[-1]), 6)
        fetched = [c for c in rates if c != "EUR"]
        logger.info("FX rates (EUR per unit): %s", {c: rates[c] for c in fetched})
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
    """
    Compute total equity (EUR) and per-holding EUR values.

    shares are stored in native units; fx_rates converts native→EUR.
    cash is always EUR.
    """
    holdings_value: dict[str, float] = {}
    equity = cash
    for ticker, shares in positions.items():
        px = price_map.get(ticker)
        if px is None:
            continue
        fx = 1.0
        if fx_rates:
            currency = _ticker_currency(ticker)
            fx = fx_rates.get(currency, 1.0)
        value_eur = shares * px * fx
        holdings_value[ticker] = value_eur
        equity += value_eur
    return equity, holdings_value


def sync_verified_positions(
    positions: list[dict],
    equity: float,
    as_of_date: str,
    price_map: dict[str, float],
) -> None:
    """
    Overwrite paper account with manually verified game positions.

    Called from verify.py after the user confirms their actual holdings.
    positions: list of {"ticker": str, "weight": float}
    equity:    actual game portfolio value in EUR
    price_map: {ticker: native_price} — used to derive share counts
    """
    state = _load_raw()
    initial_capital = float(state.get("initial_capital", equity))

    fx_rates = _fetch_fx_to_eur()

    target_positions: dict[str, float] = {}
    for pos in positions:
        ticker = pos["ticker"]
        px = price_map.get(ticker)
        if px and px > 0:
            fx = fx_rates.get(_ticker_currency(ticker), 1.0)
            # shares (native units) = EUR target value / (native price × EUR-per-native)
            target_positions[ticker] = round((equity * pos["weight"]) / (px * fx), 8)
        else:
            logger.warning("No price for %s — skipping in paper account sync", ticker)

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
        "source": "verified",
    }
    if history and history[-1].get("date") == as_of_date:
        history[-1] = history_entry
    else:
        history.append(history_entry)
    history = history[-60:]

    new_state = {
        "start_date": state.get("start_date") or as_of_date,
        "initial_capital": initial_capital,
        "cash": 0.0,
        "positions": target_positions,
        "history": history,
        "last_rebalanced_date": as_of_date,
        "last_equity": round(equity, 8),
    }
    _save_raw(new_state)
    logger.info(
        "Paper account synced from verified game positions: %d holdings, equity €%.2f",
        len(target_positions),
        equity,
    )


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

    All monetary values are in EUR. Non-EUR stocks use live FX rates for
    conversion; shares are stored in native currency units.

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

    fx_rates = _fetch_fx_to_eur()

    current_positions: dict[str, float] = {
        ticker: float(shares)
        for ticker, shares in state.get("positions", {}).items()
    }
    current_cash = float(state.get("cash", 0.0))
    prev_equity = float(state.get("last_equity", state.get("initial_capital", start_capital)))

    equity_before, holding_values_before = _mark_to_market(current_positions, current_cash, price_map, fx_rates)
    if equity_before <= 0:
        logger.warning("Paper account equity is non-positive (%.2f) — skipping rebalance", equity_before)
        return None

    target_positions: dict[str, float] = {}
    traded_value = 0.0
    for pos in proposal.positions:
        px = price_map.get(pos.ticker)
        if px is None or px <= 0:
            continue
        fx = fx_rates.get(_ticker_currency(pos.ticker), 1.0)
        target_value_eur = equity_before * pos.weight
        current_value_eur = holding_values_before.get(pos.ticker, 0.0)
        traded_value += abs(target_value_eur - current_value_eur)
        # shares (native) = EUR target / (native price × EUR-per-native)
        target_positions[pos.ticker] = target_value_eur / (px * fx)

    invested_after_eur = sum(
        shares * price_map[ticker] * fx_rates.get(_ticker_currency(ticker), 1.0)
        for ticker, shares in target_positions.items()
        if ticker in price_map
    )

    cash_after = equity_before - invested_after_eur
    if cash_after < -1e-6:
        logger.warning("Paper account rebalance produced negative cash %.6f — clipping to zero", cash_after)
        cash_after = 0.0

    equity_after, _ = _mark_to_market(target_positions, cash_after, price_map, fx_rates)
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
