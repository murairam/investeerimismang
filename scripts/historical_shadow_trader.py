"""
Historical Shadow Trader — Open-to-Open backtester.

Simulates AlphaShark's portfolio decisions over a historical date range
using only data available up to T-1 close (strict no-lookahead).
Executes at Open[T+1] and measures ROI as Open[T+1] → Open[T+2].

Usage:
    python scripts/historical_shadow_trader.py --start 2024-04-01 --end 2024-06-21

Output:
    scripts/backtest_results/shadow_{start}_{end}.csv
    Console summary: daily return, cumulative ROI, max drawdown, Sharpe, win rate
"""
import argparse
import csv
import logging
import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

import numpy as np
import pandas as pd
import yfinance as yf

# Allow importing from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.full_analyst import OpenAIChallenger
from agents.risk_manager import OpenAIRiskManager
from agents.strategist import OpenAIStrategist
from config import (
    BETA_BENCHMARK,
    BETA_WINDOW,
    CORR_THRESHOLD,
    CORR_WINDOW,
    MOMENTUM_WINDOW,
    MOM_LONG,
    MOM_SHORT,
    RSI_WINDOW,
    SECTOR_MAP,
    UNIVERSE,
)
from data.fetcher import CandidateInfo, MarketSnapshot
from portfolio.models import PortfolioProposal
from portfolio.validator import PortfolioValidator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent / "backtest_results"


def _trading_days(start: date, end: date) -> list[date]:
    """Return Mon–Fri dates between start and end inclusive."""
    days = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _compute_rsi(close: pd.Series, window: int = RSI_WINDOW) -> float:
    if len(close) < window + 1:
        return float("nan")
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else float("nan")


def _compute_macd_hist(close: pd.Series, last_price: float) -> float:
    if len(close) < 35:
        return float("nan")
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = (macd_line - signal_line).iloc[-1]
    return float(hist / last_price) if last_price > 0 else float("nan")


def _compute_atr_pct(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> float:
    if len(close) < window + 1:
        return float("nan")
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1, sort=False).max(axis=1)
    atr = tr.rolling(window, min_periods=window // 2).mean().iloc[-1]
    last = float(close.iloc[-1])
    return float(atr / last) if last > 0 else float("nan")


def build_mock_snapshot(
    as_of_date: date,
    all_close: pd.DataFrame,
    all_high: pd.DataFrame,
    all_low: pd.DataFrame,
    all_volume: pd.DataFrame,
    market_map: dict[str, str],
) -> Optional[MarketSnapshot]:
    """
    Build a MarketSnapshot using only data with date <= as_of_date - 1 trading day.
    Strict no-lookahead: signals computed from close[..., T-1].
    """
    # Use data up to and including as_of_date (T-1 close is the last available)
    # We are simulating the state at market close on as_of_date
    # Order will execute at Open[T+1]
    date_mask = all_close.index <= pd.Timestamp(as_of_date)
    close_slice = all_close[date_mask].ffill()
    high_slice = all_high[date_mask] if not all_high.empty else pd.DataFrame()
    low_slice = all_low[date_mask] if not all_low.empty else pd.DataFrame()
    vol_slice = all_volume[date_mask] if not all_volume.empty else pd.DataFrame()

    if len(close_slice) < MOMENTUM_WINDOW + 5:
        logger.warning("Insufficient history for %s — skipping", as_of_date)
        return None

    # Benchmark
    if BETA_BENCHMARK not in close_slice.columns:
        logger.warning("Benchmark %s not in data", BETA_BENCHMARK)
        return None

    bench = close_slice[BETA_BENCHMARK].dropna()
    if len(bench) < 202:
        return None

    # Regime
    sma_200 = bench.iloc[-200:].mean()
    last_bench = float(bench.iloc[-1])
    spx_vs_sma = last_bench / sma_200 - 1
    if spx_vs_sma >= 0.02:
        regime = "BULL"
    elif spx_vs_sma <= -0.02:
        regime = "BEAR"
    else:
        regime = "NEUTRAL"

    bench_momentum = float(bench.iloc[-1] / bench.iloc[-MOMENTUM_WINDOW - 1] - 1) if len(bench) > MOMENTUM_WINDOW else 0.0

    all_tickers: list[tuple[str, str]] = [
        (t, m) for m, tickers in UNIVERSE.items() for t in tickers
    ]

    records: list[dict] = []
    for ticker, market in all_tickers:
        if ticker not in close_slice.columns:
            continue
        s = close_slice[ticker].dropna()
        if len(s) < MOMENTUM_WINDOW + 5:
            continue

        last_price = float(s.iloc[-1])
        mom_20 = float(s.iloc[-1] / s.iloc[-MOMENTUM_WINDOW - 1] - 1) if len(s) > MOMENTUM_WINDOW else float("nan")
        mom_5 = float(s.iloc[-1] / s.iloc[-MOM_SHORT - 1] - 1) if len(s) > MOM_SHORT else float("nan")
        mom_60 = float(s.iloc[-1] / s.iloc[-MOM_LONG - 1] - 1) if len(s) > MOM_LONG else float("nan")

        daily_ret = s.iloc[-MOMENTUM_WINDOW:].pct_change().dropna()
        vol = float(daily_ret.std() * math.sqrt(252)) if len(daily_ret) >= 2 else float("nan")
        sharpe = mom_20 / vol if (not math.isnan(vol) and vol > 0) else 0.0

        # Beta vs benchmark
        bench_ret = bench.pct_change().dropna()
        stock_ret = s.pct_change().dropna()
        bench_w = min(len(bench_ret), len(stock_ret), BETA_WINDOW)
        if bench_w >= 20:
            b_r = bench_ret.iloc[-bench_w:]
            s_r = stock_ret.iloc[-bench_w:]
            b_r, s_r = b_r.align(s_r, join="inner")
            bench_var = b_r.var()
            beta = float(s_r.cov(b_r) / bench_var) if bench_var > 0 else float("nan")
        else:
            beta = float("nan")

        rsi_val = _compute_rsi(s, RSI_WINDOW)

        # Volume ratio
        if ticker in vol_slice.columns and not vol_slice[ticker].dropna().empty:
            v = vol_slice[ticker].dropna()
            if len(v) >= MOMENTUM_WINDOW + 1:
                avg_vol = float(v.iloc[-MOMENTUM_WINDOW - 1:-1].mean())
                latest_vol = float(v.iloc[-1])
                vol_ratio = (latest_vol / avg_vol) if avg_vol > 0 else float("nan")
            else:
                vol_ratio = float("nan")
        else:
            vol_ratio = float("nan")

        # MACD
        macd_hist = _compute_macd_hist(s, last_price)

        # ATR
        if (not high_slice.empty and ticker in high_slice.columns and
                not low_slice.empty and ticker in low_slice.columns):
            h_s = high_slice[ticker].dropna()
            l_s = low_slice[ticker].dropna()
            h_s, l_s = h_s.align(s, join="inner")
            atr_pct = _compute_atr_pct(h_s, l_s, s)
        else:
            atr_pct = float("nan")

        # 52-week high
        high_52w = float(s.rolling(min(252, len(s)), min_periods=60).max().iloc[-1]) if len(s) >= 60 else float("nan")
        pct_from_high = (last_price / high_52w - 1) if (not math.isnan(high_52w) and high_52w > 0) else float("nan")

        vs_index = mom_20 - bench_momentum if not math.isnan(mom_20) else float("nan")

        records.append({
            "ticker": ticker,
            "market": market,
            "sector": SECTOR_MAP.get(ticker, "?"),
            "momentum": mom_20,
            "mom_5d": mom_5,
            "mom_60d": mom_60,
            "vol_20d": vol,
            "sharpe_20d": sharpe,
            "rsi_14": rsi_val,
            "vs_index": vs_index,
            "pct_from_52w_high": pct_from_high,
            "beta": beta,
            "last_price": last_price,
            "vol_ratio": vol_ratio,
            "macd_hist": macd_hist,
            "atr_pct": atr_pct,
            "dividend_yield": float("nan"),
        })

    if not records:
        return None

    records.sort(key=lambda x: x["sharpe_20d"], reverse=True)
    top = records[:50]  # top 50 candidates

    candidates = [CandidateInfo(**r) for r in top]

    return MarketSnapshot(
        candidates=candidates,
        benchmark_return=bench_momentum,
        as_of_date=as_of_date.isoformat(),
        regime=regime,
        regime_score=50,
        spx_vs_sma=spx_vs_sma,
        vix_level=float("nan"),
        vix_term_ratio=float("nan"),
        breadth_pct=float("nan"),
        credit_change=float("nan"),
        price_map={t: float(close_slice[t].dropna().iloc[-1]) for t in close_slice.columns if not close_slice[t].dropna().empty},
        returns_1d={},
        benchmark_return_1d=float("nan"),
        short_interest={},
        premarket_gap={},
        iv_proxy={},
    )


def run_backtest(start: date, end: date) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    trading_days = _trading_days(start, end)
    if len(trading_days) < 3:
        logger.error("Need at least 3 trading days for Open-to-Open ROI calculation")
        sys.exit(1)

    # Download all data for the full period + lookback (252 days before start)
    lookback_start = start - timedelta(days=400)
    all_tickers = [t for tickers in UNIVERSE.values() for t in tickers] + [BETA_BENCHMARK]
    logger.info("Downloading %d tickers from %s to %s …", len(all_tickers), lookback_start, end)

    raw = yf.download(
        all_tickers,
        start=lookback_start.isoformat(),
        end=(end + timedelta(days=7)).isoformat(),
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if raw.empty:
        logger.error("yfinance returned empty data")
        sys.exit(1)

    if isinstance(raw.columns, pd.MultiIndex):
        close_all = raw["Close"]
        open_all = raw["Open"] if "Open" in raw.columns.get_level_values(0) else pd.DataFrame()
        high_all = raw["High"] if "High" in raw.columns.get_level_values(0) else pd.DataFrame()
        low_all = raw["Low"] if "Low" in raw.columns.get_level_values(0) else pd.DataFrame()
        vol_all = raw["Volume"] if "Volume" in raw.columns.get_level_values(0) else pd.DataFrame()
    else:
        logger.error("Single-ticker data — need full universe")
        sys.exit(1)

    strategist = OpenAIStrategist()
    challenger = OpenAIChallenger()
    risk_manager = OpenAIRiskManager()
    validator = PortfolioValidator()

    results: list[dict] = []
    cumulative_return = 1.0

    logger.info("Starting backtest: %d trading days", len(trading_days))

    for i, day_t in enumerate(trading_days[:-2]):  # need T+1 and T+2 opens
        day_t1 = trading_days[i + 1]
        day_t2 = trading_days[i + 2]

        logger.info("Day %d/%d: T=%s, exec@Open[%s], exit@Open[%s]",
                    i + 1, len(trading_days) - 2, day_t, day_t1, day_t2)

        # Build snapshot using data up to T (T-1 close = last available, T = as_of)
        snapshot = build_mock_snapshot(day_t, close_all, high_all, low_all, vol_all,
                                       {t: m for m, tickers in UNIVERSE.items() for t in tickers})
        if snapshot is None:
            logger.warning("Skipping %s — insufficient snapshot data", day_t)
            continue

        # Call agents
        try:
            strategist_proposal = strategist.propose(snapshot)
        except Exception as exc:
            logger.warning("Strategist failed on %s: %s", day_t, exc)
            continue

        try:
            challenger_proposal = challenger.propose(snapshot)
        except Exception as exc:
            logger.warning("Challenger failed (non-fatal): %s", exc)
            challenger_proposal = PortfolioProposal()

        try:
            final_proposal = risk_manager.propose(
                snapshot,
                prior_proposal=strategist_proposal,
                challenger_proposal=challenger_proposal if challenger_proposal.positions else None,
            )
        except Exception as exc:
            logger.warning("Risk manager failed on %s: %s — using strategist", day_t, exc)
            final_proposal = strategist_proposal

        # Validate
        result = validator.validate(final_proposal, regime=snapshot["regime"])
        if not result.ok:
            final_proposal = validator.normalize(final_proposal)

        final_proposal = validator.round_to_whole_pct(final_proposal)

        # Compute Open-to-Open ROI: Open[T+1] → Open[T+2]
        t1_ts = pd.Timestamp(day_t1)
        t2_ts = pd.Timestamp(day_t2)

        # Find actual trading rows closest to T+1 and T+2
        open_dates = open_all.index
        t1_rows = open_dates[open_dates >= t1_ts]
        t2_rows = open_dates[open_dates >= t2_ts]

        if t1_rows.empty or t2_rows.empty:
            logger.warning("No open data for T+1=%s or T+2=%s — skipping", day_t1, day_t2)
            continue

        t1_row = t1_rows[0]
        t2_row = t2_rows[0]

        position_returns: dict[str, float] = {}
        portfolio_return = 0.0
        for pos in final_proposal.positions:
            t = pos.ticker
            if t in open_all.columns:
                o1 = open_all[t].get(t1_row)
                o2 = open_all[t].get(t2_row)
                if o1 is not None and o2 is not None and not math.isnan(o1) and not math.isnan(o2) and o1 > 0:
                    ret = float(o2) / float(o1) - 1
                    position_returns[t] = ret
                    portfolio_return += pos.weight * ret

        cumulative_return *= (1 + portfolio_return)

        results.append({
            "date": day_t.isoformat(),
            "exec_date": day_t1.isoformat(),
            "exit_date": day_t2.isoformat(),
            "regime": snapshot["regime"],
            "n_positions": len(final_proposal.positions),
            "portfolio_return": portfolio_return,
            "cumulative_return": cumulative_return - 1,
            "tickers": "|".join(f"{p.ticker}:{p.weight:.0%}" for p in final_proposal.positions),
            "position_returns": "|".join(f"{t}:{r:+.2%}" for t, r in position_returns.items()),
        })

        logger.info(
            "  Portfolio: %d positions, daily return %+.2f%%, cumulative %+.2f%%",
            len(final_proposal.positions),
            portfolio_return * 100,
            (cumulative_return - 1) * 100,
        )

    if not results:
        logger.error("No results produced")
        sys.exit(1)

    # Summary stats
    daily_returns = [r["portfolio_return"] for r in results]
    n = len(daily_returns)
    avg_ret = sum(daily_returns) / n if n > 0 else 0.0
    cumret = results[-1]["cumulative_return"] if results else 0.0
    win_rate = sum(1 for r in daily_returns if r > 0) / n if n > 0 else 0.0

    # Max drawdown
    peak = 1.0
    max_dd = 0.0
    equity = 1.0
    for r in daily_returns:
        equity *= (1 + r)
        peak = max(peak, equity)
        dd = (peak - equity) / peak
        max_dd = max(max_dd, dd)

    # Sharpe (annualised, assuming 252 trading days, 0% risk-free)
    if n >= 2:
        std_ret = float(pd.Series(daily_returns).std())
        sharpe = (avg_ret / std_ret * math.sqrt(252)) if std_ret > 0 else float("nan")
    else:
        sharpe = float("nan")

    print("\n" + "=" * 60)
    print(f"SHADOW TRADER BACKTEST: {start} → {end}")
    print("=" * 60)
    print(f"  Trading days:     {n}")
    print(f"  Cumulative ROI:   {cumret:+.2%}")
    print(f"  Avg daily return: {avg_ret:+.3%}")
    print(f"  Win rate:         {win_rate:.1%}")
    print(f"  Max drawdown:     {max_dd:.2%}")
    print(f"  Sharpe (ann.):    {sharpe:.2f}" if not math.isnan(sharpe) else "  Sharpe (ann.):    N/A")
    print("=" * 60)

    # Save CSV
    csv_path = OUTPUT_DIR / f"shadow_{start.isoformat()}_{end.isoformat()}.csv"
    with open(csv_path, "w", newline="") as f:
        if results:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)

    logger.info("Results saved to %s", csv_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="AlphaShark historical shadow trader")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end <= start:
        print("--end must be after --start")
        sys.exit(1)

    run_backtest(start, end)


if __name__ == "__main__":
    main()
