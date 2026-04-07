"""
Fetch and format earnings context for agent prompts.
"""
import logging
import math
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_DAYS_AHEAD = 7        # warn if earnings within this many calendar days
_MAX_TICKERS = 20      # only check top candidates to keep run time short
_PEAD_LOOKBACK_DAYS = 3


def _to_date(value: object) -> date | None:
    """Convert yfinance earnings date values to date."""
    if value is None:
        return None
    if hasattr(value, "date"):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _extract_earnings_dates(cal: object) -> list[date]:
    """Extract earnings dates from yfinance calendar payload."""
    if cal is None:
        return []
    if isinstance(cal, dict):
        raw_dates = cal.get("Earnings Date") or []
    elif hasattr(cal, "loc") and "Earnings Date" in cal.index:
        raw = cal.loc["Earnings Date"]
        raw_dates = list(raw) if hasattr(raw, "__iter__") else [raw]
    else:
        return []
    out: list[date] = []
    for raw_value in raw_dates:
        converted = _to_date(raw_value)
        if converted is not None:
            out.append(converted)
    return out


def _latest_daily_frame(ticker: str, period: str) -> pd.DataFrame:
    """Download daily OHLCV and normalize to simple columns."""
    df = yf.download(
        ticker,
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="column",
        threads=False,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(-1, axis=1)
    return df


def fetch_upcoming_earnings(tickers: list[str]) -> list[dict]:
    """
    Return list of {ticker, earnings_date} for stocks with earnings
    expected within the next _DAYS_AHEAD calendar days.
    """
    today = date.today()
    cutoff = today + timedelta(days=_DAYS_AHEAD)
    results: list[dict] = []

    for ticker in tickers[:_MAX_TICKERS]:
        try:
            dates = _extract_earnings_dates(yf.Ticker(ticker).calendar)
            for earnings_date in dates:
                if today <= earnings_date <= cutoff:
                    results.append({"ticker": ticker, "earnings_date": earnings_date.isoformat()})
                    break
        except Exception as exc:
            logger.debug("Earnings fetch skipped for %s: %s", ticker, exc)

    return results


def scan_pead_candidates(tickers: list[str]) -> list[dict]:
    """
    Hunt post-earnings drift setups from the latest session:
    - earnings in last 3 days
    - latest open gapped up >5% vs prior close
    - latest volume >3x prior 20-day average volume
    """
    today = date.today()
    lookback_start = today - timedelta(days=_PEAD_LOOKBACK_DAYS)
    candidates: list[dict] = []

    for ticker in tickers[:_MAX_TICKERS]:
        try:
            earnings_dates = _extract_earnings_dates(yf.Ticker(ticker).calendar)
            if not any(lookback_start <= d <= today for d in earnings_dates):
                continue

            recent = _latest_daily_frame(ticker, "2mo")
            if recent.empty or len(recent) < 22:
                continue

            latest = recent.iloc[-1]
            prev = recent.iloc[-2]
            prev_close = float(prev.get("Close", float("nan")))
            latest_open = float(latest.get("Open", float("nan")))
            latest_vol = float(latest.get("Volume", float("nan")))
            avg_vol_20 = float(recent["Volume"].iloc[-21:-1].mean())
            if any(math.isnan(v) for v in [prev_close, latest_open, latest_vol, avg_vol_20]):
                continue
            if prev_close <= 0 or avg_vol_20 <= 0:
                continue

            gap_pct = (latest_open - prev_close) / prev_close
            vol_ratio = latest_vol / avg_vol_20
            if gap_pct > 0.05 and vol_ratio >= 3.0:
                candidates.append(
                    {
                        "ticker": ticker,
                        "gap_pct": gap_pct,
                        "vol_ratio": vol_ratio,
                        "as_of": recent.index[-1].date().isoformat(),
                    }
                )
        except Exception as exc:
            logger.debug("PEAD scan skipped for %s: %s", ticker, exc)

    return candidates


def format_pead_signals(signals: list[dict]) -> str:
    """Format PEAD candidates for prompt context."""
    if not signals:
        return ""
    lines = [
        "PEAD OPPORTUNITIES (post-earnings drift setup: gap >5% and volume >=3x):",
    ]
    for signal in signals:
        lines.append(
            f"  {signal['ticker']}: as_of {signal['as_of']}, gap {signal['gap_pct']:+.1%}, "
            f"vol {signal['vol_ratio']:.1f}x"
        )
    return "\n".join(lines)


def format_earnings_opportunity(candidates: list[dict], earnings: list[dict]) -> str:
    """Tag strong-momentum stocks with earnings in 2–6 days as PRE_EARNINGS_SETUP."""
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
        # Use trading days (Mon–Fri) so that a Friday earnings date is 1 trading day
        # away on Thursday, not 1 calendar day — aligns with actual pre-earnings drift window.
        days_out = int(np.busday_count(today.isoformat(), earn_date.isoformat()))
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

    from collections import Counter
    week_dates = Counter(e["earnings_date"] for e in earnings)
    cluster_dates = {d: n for d, n in week_dates.items() if n >= 2}

    lines = ["PRE-EARNINGS SETUP (academic drift: +3–8% in 2–4 days before announcement):"]
    for ticker, earn_date, mom_5d, mom_20d, rsi, days_out in opportunities:
        m5 = f"{mom_5d:+.1%}" if not math.isnan(mom_5d) else "N/A"
        m20 = f"{mom_20d:+.1%}" if not math.isnan(mom_20d) else "N/A"
        lines.append(
            f"  {ticker}: earnings {earn_date} ({days_out}d out), "
            f"5d {m5}, 20d {m20}, RSI {rsi:.0f} -> PRE_EARNINGS_SETUP"
        )
    lines.append(
        "  Sizing limits: max 20% per pre-earnings position, max 40% total, <=2 names same week."
    )
    if cluster_dates:
        cstr = ", ".join(f"{d} ({n} names)" for d, n in cluster_dates.items())
        lines.append(f"  Cluster risk: {cstr}")
    return "\n".join(lines)


def format_earnings_warning(earnings: list[dict], candidates: list[dict] | None = None) -> str:
    """Format upcoming earnings as a risk warning block for agent prompts."""
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
        "Binary gap risk - reduce weight or avoid if low conviction."
    )
