"""
Fetches upcoming earnings dates for top candidate tickers via yfinance.
Earnings events carry binary risk (gap up or down) — injected into agent
prompts as a warning so the AI can factor this into sizing decisions.
"""
import logging
from datetime import date, timedelta

import yfinance as yf

logger = logging.getLogger(__name__)

_DAYS_AHEAD = 7        # warn if earnings within this many calendar days
_MAX_TICKERS = 20      # only check top candidates to keep run time short


def fetch_upcoming_earnings(tickers: list[str]) -> list[dict]:
    """
    Return list of {ticker, earnings_date} for stocks with earnings
    expected within the next _DAYS_AHEAD calendar days.
    Silently skips any ticker that fails or has no upcoming data.
    """
    today = date.today()
    cutoff = today + timedelta(days=_DAYS_AHEAD)
    results: list[dict] = []

    for ticker in tickers[:_MAX_TICKERS]:
        try:
            cal = yf.Ticker(ticker).calendar
            if cal is None:
                continue

            # yfinance may return a dict or a DataFrame depending on version
            if isinstance(cal, dict):
                earn_dates = cal.get("Earnings Date") or []
            elif hasattr(cal, "loc") and "Earnings Date" in cal.index:
                raw = cal.loc["Earnings Date"]
                earn_dates = list(raw) if hasattr(raw, "__iter__") else [raw]
            else:
                continue

            if not earn_dates:
                continue

            for d in earn_dates:
                if d is None:
                    continue
                try:
                    if hasattr(d, "date"):
                        d = d.date()
                    elif isinstance(d, str):
                        from datetime import datetime
                        d = datetime.strptime(d[:10], "%Y-%m-%d").date()
                    if today <= d <= cutoff:
                        results.append({"ticker": ticker, "earnings_date": str(d)})
                        break
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("Earnings fetch skipped for %s: %s", ticker, exc)

    return results


def format_earnings_warning(earnings: list[dict]) -> str:
    """Format upcoming earnings as a risk warning block for agent prompts."""
    if not earnings:
        return ""
    items = ", ".join(f"{e['ticker']} ({e['earnings_date']})" for e in earnings)
    return (
        f"EARNINGS RISK (next 7 days): {items}. "
        "These carry binary gap risk — factor into sizing (reduce or avoid if low conviction)."
    )
