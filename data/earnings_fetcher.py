"""
Fetches upcoming earnings dates for top candidate tickers via yfinance.
Earnings events carry binary risk (gap up or down) — injected into agent
prompts as a warning so the AI can factor this into sizing decisions.
"""
import logging
import math
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


def format_earnings_opportunity(candidates: list[dict], earnings: list[dict]) -> str:
    """Tag strong-momentum stocks with earnings in 2–6 days as PRE_EARNINGS_SETUP.

    Academic pre-earnings drift: stocks with strong recent momentum tend to drift
    +3–8% in the 2–4 days before their announcement. This is an OPPORTUNITY, not
    just risk — size accordingly (max 20% per name, 40% total, ≤2 same week).
    """
    if not earnings or not candidates:
        return ""
    today = date.today()
    candidate_map = {c["ticker"]: c for c in candidates}
    opportunities = []
    for e in earnings:
        ticker = e["ticker"]
        try:
            earn_date = date.fromisoformat(e["earnings_date"])
        except (ValueError, KeyError):
            continue
        days_out = (earn_date - today).days
        if not (2 <= days_out <= 6):
            continue
        c = candidate_map.get(ticker, {})
        if not c:
            continue
        mom_5d = c.get("mom_5d", float("nan"))
        mom_20d = c.get("momentum", float("nan"))
        rsi = c.get("rsi_14", float("nan"))
        strong_mom = (
            (not math.isnan(mom_5d) and mom_5d >= 0.04)
            or (not math.isnan(mom_20d) and mom_20d >= 0.10)
        )
        rsi_ok = not math.isnan(rsi) and 50 <= rsi <= 75
        if strong_mom and rsi_ok:
            opportunities.append((ticker, e["earnings_date"], mom_5d, mom_20d, rsi, days_out))

    if not opportunities:
        return ""

    # Count cluster risk: names with earnings in the same calendar week
    from collections import Counter
    week_dates = Counter(e["earnings_date"] for e in earnings)
    cluster_dates = {d: n for d, n in week_dates.items() if n >= 2}

    lines = ["PRE-EARNINGS SETUP (academic drift: +3–8% in 2–4 days before announcement):"]
    for ticker, earn_date, mom_5d, mom_20d, rsi, days_out in opportunities:
        m5 = f"{mom_5d:+.1%}" if not math.isnan(mom_5d) else "N/A"
        m20 = f"{mom_20d:+.1%}" if not math.isnan(mom_20d) else "N/A"
        lines.append(
            f"  {ticker}: earnings {earn_date} ({days_out}d out), "
            f"5d {m5}, 20d {m20}, RSI {rsi:.0f} → PRE_EARNINGS_SETUP"
        )
    lines.append(
        "  Sizing limits: max 20% per pre-earnings position, max 40% total, ≤2 names same week."
    )
    if cluster_dates:
        cstr = ", ".join(f"{d} ({n} names)" for d, n in cluster_dates.items())
        lines.append(f"  ⚠️ Cluster risk: {cstr}")
    return "\n".join(lines)


def format_earnings_warning(earnings: list[dict], candidates: list[dict] | None = None) -> str:
    """Format upcoming earnings as a risk warning block for agent prompts.

    When candidates are provided, stocks already tagged as PRE_EARNINGS_SETUP
    (strong momentum, earnings 2–6 days out) are excluded from the warning —
    they are framed as opportunities in format_earnings_opportunity() instead.
    """
    if not earnings:
        return ""

    warn_earnings = earnings
    if candidates:
        today = date.today()
        candidate_map = {c["ticker"]: c for c in candidates}
        warn_earnings = []
        for e in earnings:
            ticker = e["ticker"]
            try:
                earn_date = date.fromisoformat(e["earnings_date"])
            except (ValueError, KeyError):
                warn_earnings.append(e)
                continue
            days_out = (earn_date - today).days
            c = candidate_map.get(ticker, {})
            mom_5d = c.get("mom_5d", float("nan"))
            mom_20d = c.get("momentum", float("nan"))
            rsi = c.get("rsi_14", float("nan"))
            is_opportunity = (
                2 <= days_out <= 6
                and ((not math.isnan(mom_5d) and mom_5d >= 0.04)
                     or (not math.isnan(mom_20d) and mom_20d >= 0.10))
                and not math.isnan(rsi) and 50 <= rsi <= 75
            )
            if not is_opportunity:
                warn_earnings.append(e)

    if not warn_earnings:
        return ""
    items = ", ".join(f"{e['ticker']} ({e['earnings_date']})" for e in warn_earnings)
    return (
        f"EARNINGS RISK (next 7 days): {items}. "
        "Binary gap risk — reduce weight or avoid if low conviction."
    )
