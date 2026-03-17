"""
Market data fetching and momentum signal computation.
"""
import logging
import math
from typing import TypedDict

import numpy as np
import pandas as pd
import yfinance as yf

from config import (
    BETA_BENCHMARK,
    BETA_WINDOW,
    CORR_THRESHOLD,
    CORR_WINDOW,
    MOMENTUM_WINDOW,
    MOM_LONG,
    MOM_SHORT,
    OTHER_MARKET_CAP,
    REGIME_THRESHOLD,
    RSI_WINDOW,
    SMA_REGIME_WINDOW,
    SP500_MARKET_CAP,
    TOP_N_CANDIDATES,
    UNIVERSE,
)

logger = logging.getLogger(__name__)


class CandidateInfo(TypedDict):
    ticker: str
    market: str
    momentum: float       # 20d return
    mom_5d: float         # 5d return
    mom_60d: float        # 60d return
    vol_20d: float        # annualised 20d volatility
    sharpe_20d: float     # momentum / vol_20d
    rsi_14: float         # 14-day RSI
    vs_index: float       # stock 20d return minus benchmark 20d return
    pct_from_52w_high: float  # (last_price / 52w_high) - 1
    beta: float
    last_price: float
    vol_ratio: float      # today's volume / 20d avg volume (>1.5 = high-volume confirmation)


class MarketSnapshot(TypedDict):
    candidates: list[CandidateInfo]
    benchmark_return: float
    as_of_date: str
    regime: str           # "BULL" | "BEAR" | "NEUTRAL"
    spx_vs_200d: float    # % above/below 200-day SMA
    vix_level: float      # VIX spot price
    price_map: dict       # {ticker: last_close_price} for ALL fetched tickers
    returns_1d: dict      # {ticker: 1-day return} for ALL fetched tickers
    benchmark_return_1d: float  # S&P 500 1-day return


class DataFetcher:
    def fetch_ohlcv(self, tickers: list[str], period: str = "1y") -> tuple[pd.DataFrame, pd.DataFrame]:
        """Download adjusted close prices and volume for *tickers* from yfinance.
        Returns (close_df, volume_df)."""
        if not tickers:
            return pd.DataFrame(), pd.DataFrame()
        data = yf.download(
            tickers,
            period=period,
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        if isinstance(data.columns, pd.MultiIndex):
            close = data["Close"]
            volume = data["Volume"] if "Volume" in data.columns.get_level_values(0) else pd.DataFrame()
        else:
            close = data[["Close"]].rename(columns={"Close": tickers[0]})
            volume = data[["Volume"]].rename(columns={"Volume": tickers[0]}) if "Volume" in data.columns else pd.DataFrame()
        return close.dropna(how="all"), volume.dropna(how="all") if not volume.empty else pd.DataFrame()

    def compute_vol_ratio(self, volume: pd.DataFrame, window: int = MOMENTUM_WINDOW) -> pd.Series:
        """Ratio of latest volume to prior 20d average volume. >1.5 = high-volume confirmation."""
        if volume.empty or len(volume) < window + 1:
            return pd.Series(dtype=float)
        # Use iloc[-window-1:-1] to get the prior 20d avg (excluding today), then compare to today
        avg_vol = volume.iloc[-window - 1:-1].mean()
        latest_vol = volume.iloc[-1]
        ratio = latest_vol / avg_vol.replace(0, np.nan)
        return ratio.rename("vol_ratio")

    def compute_momentum(self, close: pd.DataFrame, window: int = MOMENTUM_WINDOW) -> pd.Series:
        """N-day price return for each ticker."""
        if len(close) < window + 1:
            return pd.Series(dtype=float)
        returns = close.iloc[-1] / close.iloc[-window - 1] - 1
        return returns.rename("momentum")

    def compute_rsi(self, close: pd.DataFrame, window: int = RSI_WINDOW) -> pd.Series:
        """14-day RSI for each ticker."""
        if len(close) < window + 1:
            return pd.Series(np.nan, index=close.columns, name="rsi")
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window).mean()
        loss = (-delta.clip(upper=0)).rolling(window).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1].rename("rsi")

    def compute_vol(self, close: pd.DataFrame, window: int = MOMENTUM_WINDOW) -> pd.Series:
        """Annualised volatility of daily returns over *window* days."""
        if len(close) < window + 1:
            return pd.Series(np.nan, index=close.columns, name="vol")
        daily_ret = close.iloc[-window:].pct_change(fill_method=None).dropna()
        vol = daily_ret.std() * math.sqrt(252)
        return vol.rename("vol")

    def compute_beta(
        self, close: pd.DataFrame, benchmark_close: pd.Series, window: int = BETA_WINDOW
    ) -> pd.Series:
        """Rolling beta of each ticker vs benchmark over the last *window* days."""
        if len(close) < window:
            return pd.Series(np.nan, index=close.columns, name="beta")

        stock_returns = close.iloc[-window:].pct_change(fill_method=None).dropna()
        bench_returns = benchmark_close.iloc[-window:].pct_change(fill_method=None).dropna()
        bench_returns, stock_returns = bench_returns.align(stock_returns, join="inner", axis=0)
        bench_var = bench_returns.var()
        if bench_var == 0:
            return pd.Series(np.nan, index=close.columns, name="beta")

        betas: dict[str, float] = {}
        for ticker in stock_returns.columns:
            cov = stock_returns[ticker].cov(bench_returns)
            betas[ticker] = cov / bench_var
        return pd.Series(betas, name="beta")

    def compute_regime(self, bench_close: pd.Series) -> tuple[str, float]:
        """
        Determine market regime from SPX vs its 200d SMA.
        Returns (regime_str, pct_vs_200d).
        """
        if len(bench_close) < SMA_REGIME_WINDOW:
            return "NEUTRAL", 0.0
        sma_200 = bench_close.iloc[-SMA_REGIME_WINDOW:].mean()
        last = bench_close.iloc[-1]
        pct = (last / sma_200) - 1
        if pct >= REGIME_THRESHOLD:
            regime = "BULL"
        elif pct <= -REGIME_THRESHOLD:
            regime = "BEAR"
        else:
            regime = "NEUTRAL"
        return regime, float(pct)

    def fetch_vix(self) -> float:
        """Fetch current VIX level."""
        try:
            vix_close, _ = self.fetch_ohlcv(["^VIX"], period="5d")
            if not vix_close.empty:
                return float(vix_close.iloc[-1, 0])
        except Exception as exc:
            logger.warning("Failed to fetch VIX: %s", exc)
        return float("nan")

    def apply_correlation_filter(
        self, records: list[dict], close: pd.DataFrame
    ) -> list[dict]:
        """
        Remove highly correlated pairs (>CORR_THRESHOLD over CORR_WINDOW days),
        keeping the one with higher sharpe_20d.
        """
        tickers = [r["ticker"] for r in records]
        available = [t for t in tickers if t in close.columns]
        if len(available) < 2:
            return records

        price_slice = close[available].iloc[-CORR_WINDOW:]
        ret_slice = price_slice.pct_change(fill_method=None).dropna()
        if ret_slice.empty or len(ret_slice) < 10:
            return records

        corr_matrix = ret_slice.corr()
        sharpe_map = {r["ticker"]: r["sharpe_20d"] for r in records}
        to_remove: set[str] = set()

        for i, t1 in enumerate(available):
            if t1 in to_remove:
                continue
            for t2 in available[i + 1:]:
                if t2 in to_remove:
                    continue
                if t1 not in corr_matrix.index or t2 not in corr_matrix.columns:
                    continue
                if corr_matrix.loc[t1, t2] > CORR_THRESHOLD:
                    # Keep the one with higher Sharpe
                    if sharpe_map.get(t1, 0) >= sharpe_map.get(t2, 0):
                        to_remove.add(t2)
                    else:
                        to_remove.add(t1)

        filtered = [r for r in records if r["ticker"] not in to_remove]
        if to_remove:
            logger.info("Correlation filter removed %d tickers: %s", len(to_remove), sorted(to_remove))
        return filtered

    def apply_market_cap(self, records: list[dict]) -> list[dict]:
        """
        Cap candidates per market: SP500 max 15, all others max 5 each.
        Records must already be sorted by sharpe_20d descending.
        """
        counts: dict[str, int] = {}
        result = []
        for r in records:
            market = r["market"]
            limit = SP500_MARKET_CAP if market == "SP500" else OTHER_MARKET_CAP
            if counts.get(market, 0) < limit:
                result.append(r)
                counts[market] = counts.get(market, 0) + 1
        return result

    def get_market_snapshot(self) -> MarketSnapshot:
        """
        Downloads price data for the full universe, computes rich signals,
        and returns the TOP_N_CANDIDATES best-Sharpe stocks as a MarketSnapshot.
        """
        all_tickers: list[tuple[str, str]] = [
            (ticker, market)
            for market, tickers in UNIVERSE.items()
            for ticker in tickers
        ]
        flat_tickers = [t for t, _ in all_tickers]
        market_map = {t: m for t, m in all_tickers}

        logger.info("Fetching OHLCV for %d tickers …", len(flat_tickers))
        close, volume = self.fetch_ohlcv(flat_tickers, period="1y")

        returned = set(close.columns)
        missing = [t for t in flat_tickers if t not in returned]
        if missing:
            logger.warning(
                "%d/%d tickers returned no data from yfinance: %s",
                len(missing), len(flat_tickers), missing,
            )

        # Benchmark + regime
        logger.info("Fetching benchmark %s …", BETA_BENCHMARK)
        bench_raw, _ = self.fetch_ohlcv([BETA_BENCHMARK], period="1y")
        bench_close: pd.Series = bench_raw.iloc[:, 0]

        regime, spx_vs_200d = self.compute_regime(bench_close)
        vix_level = self.fetch_vix()
        logger.info("Regime: %s (SPX vs 200d: %.1f%%), VIX: %.1f", regime, spx_vs_200d * 100, vix_level if not math.isnan(vix_level) else 0)

        # Compute all signals
        momentum_20d = self.compute_momentum(close, MOMENTUM_WINDOW)
        momentum_5d = self.compute_momentum(close, MOM_SHORT)
        momentum_60d = self.compute_momentum(close, MOM_LONG)
        vol_20d = self.compute_vol(close, MOMENTUM_WINDOW)
        rsi = self.compute_rsi(close, RSI_WINDOW)
        beta = self.compute_beta(close, bench_close)
        vol_ratio = self.compute_vol_ratio(volume, MOMENTUM_WINDOW)
        bench_momentum = float(
            bench_close.iloc[-1] / bench_close.iloc[-MOMENTUM_WINDOW - 1] - 1
        ) if len(bench_close) > MOMENTUM_WINDOW else 0.0

        # 52-week high
        high_52w = close.rolling(252, min_periods=60).max().iloc[-1]

        # Valid tickers: must have 20d momentum
        valid_tickers = momentum_20d.dropna().index.tolist()
        dropped = len(flat_tickers) - len(valid_tickers)
        if dropped:
            logger.warning(
                "Universe shrank: %d/%d tickers dropped (insufficient history)",
                dropped, len(flat_tickers),
            )

        records: list[dict] = []
        for ticker in valid_tickers:
            mom = float(momentum_20d.get(ticker, 0.0))
            vol = float(vol_20d.get(ticker, np.nan))
            rsi_val = float(rsi.get(ticker, np.nan)) if ticker in rsi.index else float("nan")

            # Skip overbought
            if not math.isnan(rsi_val) and rsi_val > 75:
                continue

            sharpe = mom / vol if (not math.isnan(vol) and vol > 0) else 0.0
            last_price = float(close[ticker].dropna().iloc[-1]) if ticker in close.columns else 0.0
            high = float(high_52w.get(ticker, np.nan)) if ticker in high_52w.index else float("nan")
            pct_from_high = (last_price / high - 1) if (not math.isnan(high) and high > 0) else float("nan")

            vr = float(vol_ratio.get(ticker, np.nan)) if not vol_ratio.empty and ticker in vol_ratio.index else float("nan")
            records.append({
                "ticker": ticker,
                "market": market_map.get(ticker, "UNKNOWN"),
                "momentum": mom,
                "mom_5d": float(momentum_5d.get(ticker, np.nan)) if ticker in momentum_5d.index else float("nan"),
                "mom_60d": float(momentum_60d.get(ticker, np.nan)) if ticker in momentum_60d.index else float("nan"),
                "vol_20d": vol,
                "sharpe_20d": sharpe,
                "rsi_14": rsi_val,
                "vs_index": mom - bench_momentum,
                "pct_from_52w_high": pct_from_high,
                "beta": float(beta.get(ticker, np.nan)),
                "last_price": last_price,
                "vol_ratio": vr,
            })

        # Sort by Sharpe descending, apply market cap, correlation filter, take top N
        records.sort(key=lambda x: x["sharpe_20d"], reverse=True)
        records = self.apply_market_cap(records)
        after_cap = records[:]
        records = self.apply_correlation_filter(records, close)
        # Guard: if filtering left too few candidates, fall back to pre-correlation set
        _MIN_CANDIDATES = 10
        if len(records) < _MIN_CANDIDATES:
            logger.warning(
                "Correlation filter left only %d candidates (< %d) — using pre-filter set",
                len(records), _MIN_CANDIDATES,
            )
            records = after_cap
        records.sort(key=lambda x: x["sharpe_20d"], reverse=True)
        top = records[:TOP_N_CANDIDATES]

        as_of = str(close.index[-1].date()) if len(close) > 0 else "unknown"

        # 1-day returns for ALL tickers (for P&L computation)
        returns_1d_series = (close.iloc[-1] / close.iloc[-2] - 1) if len(close) >= 2 else pd.Series(dtype=float)
        returns_1d: dict = returns_1d_series.dropna().to_dict()
        price_map: dict = {t: float(close[t].dropna().iloc[-1]) for t in close.columns if t in close.columns and not close[t].dropna().empty}
        benchmark_return_1d = float(bench_close.iloc[-1] / bench_close.iloc[-2] - 1) if len(bench_close) >= 2 else 0.0

        logger.info(
            "Snapshot ready: %d candidates, as of %s, benchmark %.1f%%",
            len(top), as_of, bench_momentum * 100,
        )

        candidates: list[CandidateInfo] = [CandidateInfo(**r) for r in top]
        return MarketSnapshot(
            candidates=candidates,
            benchmark_return=bench_momentum,
            as_of_date=as_of,
            regime=regime,
            spx_vs_200d=spx_vs_200d,
            vix_level=vix_level,
            price_map=price_map,
            returns_1d=returns_1d,
            benchmark_return_1d=benchmark_return_1d,
        )
