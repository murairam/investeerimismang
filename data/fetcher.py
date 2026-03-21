"""
Market data fetching and momentum signal computation.
"""
import logging
import math
import os
from datetime import date, timedelta
from typing import Optional, TypedDict

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from config import (
    BETA_BENCHMARK,
    BETA_WINDOW,
    COMPETITION_SORT_WEIGHTS,
    CORR_THRESHOLD,
    CORR_WINDOW,
    MOMENTUM_WINDOW,
    MOM_LONG,
    MOM_SHORT,
    REGIME_THRESHOLD,
    RSI_WINDOW,
    SECTOR_MAP,
    SMA_REGIME_WINDOW,
    TOP_N_CANDIDATES,
)
from data.provider_overrides import get_provider_override
from data.universe_loader import load_game_universe
from data.symbol_master import upsert_symbol_records
from data.yahoo_symbols import (
    auto_resolve_aliases,
    filter_known_unavailable,
    mark_unavailable,
    resolve_yahoo_ticker,
)

logger = logging.getLogger(__name__)
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_EODHD_CACHE_DIR = os.path.join(_ROOT, ".cache", "eodhd_prices")


class CandidateInfo(TypedDict):
    ticker: str
    market: str
    sector: str           # abbreviated sector tag from SECTOR_MAP
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
    macd_hist: float      # MACD histogram / last_price (positive = bullish, negative = bearish)
    atr_pct: float        # 14-day ATR as % of price (daily expected move)
    dividend_yield: float # trailing 12-month dividend yield (game auto-reinvests — free return)
    analyst_rating: float # analyst consensus 1.0=Strong Buy → 5.0=Strong Sell (NaN if unavailable)
    analyst_upside: float # (target_mean_price / last_price) - 1; NaN if no coverage
    competition_score: float  # Z-score weighted competition rank (regime-specific: BULL favours momentum×beta)


class MarketSnapshot(TypedDict):
    candidates: list[CandidateInfo]
    benchmark_return: float
    as_of_date: str
    regime: str           # "BULL" | "BEAR" | "NEUTRAL"
    regime_score: int     # composite 0-100: 0-30=defensive, 31-49=cautious, 50-69=neutral, 70+=bullish
    spx_vs_200d: float    # % above/below 200-day SMA
    vix_level: float      # VIX spot price
    vix_term_ratio: float # VIX3M/VIX: >1=contango (calm), <0.9=backwardation (fear)
    breadth_pct: float    # % of universe stocks above their 50d SMA
    credit_change: float  # 20d change in HYG/LQD ratio (positive=risk-on, negative=risk-off)
    price_map: dict       # {ticker: last_close_price} for ALL fetched tickers
    returns_1d: dict      # {ticker: 1-day return} for ALL fetched tickers
    benchmark_return_1d: float  # S&P 500 1-day return
    short_interest: dict  # {ticker: float | None} short % of float; None for Baltic/Nordic
    premarket_gap: dict   # {ticker: float | None} gap vs prior close; US=after-hours, EU=morning gap
    iv_proxy: dict        # {ticker: float | None} implied volatility; None if no options chain
    sector_momentum: dict # {sector: {avg_mom_20d, avg_mom_5d, avg_rsi, breadth, count}}
    rotation_risk: dict  # {sector: {"level": "HIGH"|"MEDIUM", "reason": str}} for exhausted leading sectors


def _compute_competition_scores(records: list[dict], regime: str) -> None:
    """Compute regime-specific competition scores using Z-normalized features.

    BULL: rewards high momentum × high beta (competition winners in bull runs).
    NEUTRAL: rewards risk-adjusted Sharpe + relative strength.
    BEAR: rewards Sharpe + inv_beta (low-vol defensive plays).

    Modifies records in-place by adding a 'competition_score' key.
    """
    weights = COMPETITION_SORT_WEIGHTS.get(regime, COMPETITION_SORT_WEIGHTS["NEUTRAL"])

    # Maps weight key names → record field names
    _field = {
        "mom_20d": "momentum",
        "mom_5d": "mom_5d",
        "sharpe_20d": "sharpe_20d",
        "vs_index": "vs_index",
        "beta": "beta",
        "inv_beta": "inv_beta",
    }

    # BEAR regime: compute inv_beta = 1 - beta BEFORE Z-scoring
    if regime == "BEAR":
        for r in records:
            b = r.get("beta", float("nan"))
            r["inv_beta"] = (1.0 - b) if not math.isnan(b) else float("nan")

    # Compute mean + std for each feature used in this regime
    stats: dict[str, tuple[float, float]] = {}
    for feat in weights:
        field = _field.get(feat, feat)
        vals = [r.get(field, float("nan")) for r in records]
        vals = [v for v in vals if not math.isnan(v)]
        if not vals:
            stats[feat] = (0.0, 1.0)
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        stats[feat] = (mean, var ** 0.5 if var > 0 else 1.0)

    # Score each record
    for r in records:
        score = 0.0
        for feat, w in weights.items():
            field = _field.get(feat, feat)
            val = r.get(field, float("nan"))
            if math.isnan(val):
                z = 0.0  # missing → neutral Z-score, not penalised
            else:
                mean, std = stats[feat]
                z = max(-3.0, min(3.0, (val - mean) / std))
            score += w * z
        r["competition_score"] = score


def detect_rotation_risk(
    sector_momentum: dict[str, dict],
    sector_records: dict[str, list[dict]],
) -> dict[str, dict]:
    """Detect exhaustion signals for leading sectors.

    Returns {sector_name: {"level": "HIGH"|"MEDIUM", "reason": str}}
    for sectors with avg_mom_20d > 5% that show exhaustion triggers.
    Only MEDIUM and HIGH levels are returned (LOW is suppressed to reduce noise).
    """
    result: dict[str, dict] = {}
    for sector, sm in sector_momentum.items():
        avg_mom_20d = sm.get("avg_mom_20d", float("nan"))
        if math.isnan(avg_mom_20d) or avg_mom_20d <= 0.05:
            continue  # only leading sectors worth watching

        breadth = sm.get("breadth", float("nan"))
        avg_mom_5d = sm.get("avg_mom_5d", float("nan"))
        srecs = sector_records.get(sector, [])

        reasons: list[str] = []
        triggers: list[str] = []

        # Trigger 1: breadth deterioration
        if not math.isnan(breadth):
            if breadth < 0.50:
                triggers.append("breadth_high")
                reasons.append(f"breadth {breadth:.0%}")
            elif breadth < 0.65:
                triggers.append("breadth_medium")
                reasons.append(f"breadth {breadth:.0%}")

        # Trigger 2: top-3 exhaustion (RSI overbought at 52w high with low volume)
        if srecs:
            sorted_recs = sorted(srecs, key=lambda r: r.get("momentum", 0.0), reverse=True)
            top3 = sorted_recs[:3]
            high_count = sum(
                1 for r in top3
                if r.get("rsi_14", float("nan")) > 80
                and r.get("pct_from_52w_high", float("nan")) > -0.03
                and r.get("vol_ratio", float("nan")) < 1.2
            )
            med_count = sum(
                1 for r in top3
                if r.get("rsi_14", float("nan")) > 75
                and r.get("pct_from_52w_high", float("nan")) > -0.05
            )
            if high_count == len(top3) and len(top3) >= 2:
                triggers.append("exhaustion_high")
                reasons.append(f"top {len(top3)} RSI>80 at 52w-high, vol<1.2")
            elif med_count >= 2:
                triggers.append("exhaustion_medium")
                reasons.append(f"{med_count}/{len(top3)} leaders RSI>75 near 52w-high")

        # Trigger 3: deceleration (5d pace < half of 20d trend)
        if not math.isnan(avg_mom_5d) and not math.isnan(avg_mom_20d) and avg_mom_20d > 0:
            if avg_mom_5d < avg_mom_20d * 0.5:
                triggers.append("deceleration")
                reasons.append(f"decelerating (5d {avg_mom_5d:+.1%} vs 20d {avg_mom_20d:+.1%})")

        # Count HIGH-severity triggers
        high_triggers = [t for t in triggers if t.endswith("_high")]
        med_triggers = [t for t in triggers if not t.endswith("_high")]
        total_triggers = len(high_triggers) + len(med_triggers)

        if len(high_triggers) >= 2 or (len(high_triggers) >= 1 and total_triggers >= 2):
            level = "HIGH"
        elif total_triggers >= 2:
            level = "MEDIUM"
        elif total_triggers == 1:
            level = "MEDIUM"
        else:
            continue  # clean — skip

        result[sector] = {"level": level, "reason": ", ".join(reasons)}

    return result


class DataFetcher:
    @staticmethod
    def _sector_tag(ticker: str, market: str) -> str:
        if ticker in SECTOR_MAP:
            return SECTOR_MAP[ticker]
        fallback = {
            "SP500": "US",
            "OMXHLCPI": "Fin",
            "OMXS30": "Swe",
            "OBX": "Nor",
            "OMXC25": "Den",
            "BALTIC": "Baltic",
        }
        return fallback.get(market, "Other")

    @staticmethod
    def _selection_score(record: dict, regime_score: int = 50) -> float:
        score = 0.0
        sharpe = record.get("sharpe_20d", float("nan"))
        if not math.isnan(sharpe):
            score += max(-1.0, min(2.0, sharpe))

        mom_5d = record.get("mom_5d", float("nan"))
        if not math.isnan(mom_5d):
            score += max(-1.5, min(2.5, mom_5d * 18.0))

        vs_index = record.get("vs_index", float("nan"))
        if not math.isnan(vs_index):
            score += max(-1.0, min(2.0, vs_index * 10.0))

        vol_ratio = record.get("vol_ratio", float("nan"))
        if not math.isnan(vol_ratio):
            score += max(-1.0, min(2.0, (vol_ratio - 1.0) * 1.8))

        macd_hist = record.get("macd_hist", float("nan"))
        if not math.isnan(macd_hist):
            score += max(-0.8, min(0.8, macd_hist * 900.0))

        pct_from_high = record.get("pct_from_52w_high", float("nan"))
        if not math.isnan(pct_from_high):
            score += max(-0.5, min(0.5, (0.02 + pct_from_high) * 8.0))

        beta = record.get("beta", float("nan"))
        if not math.isnan(beta) and beta < 0.25:
            score -= 0.3

        rsi = record.get("rsi_14", float("nan"))
        if not math.isnan(rsi):
            if 55 <= rsi <= 78:
                score += 0.25
            elif rsi > 88 and regime_score < 50:
                score -= 0.45

        atr_pct = record.get("atr_pct", float("nan"))
        if not math.isnan(atr_pct) and atr_pct < 0.012:
            score -= 0.2

        dead_money = (
            not math.isnan(vol_ratio) and vol_ratio < 0.9 and
            not math.isnan(mom_5d) and mom_5d <= 0.01
        )
        if dead_money:
            score -= 1.2 if regime_score < 50 else 0.8

        if regime_score < 50 and not math.isnan(mom_5d) and mom_5d < 0:
            score -= 0.6
        if regime_score >= 60 and not math.isnan(beta) and beta >= 0.8 and not math.isnan(mom_5d) and mom_5d > 0:
            score += 0.3

        return score

    def fetch_ohlcv(
        self, tickers: list[str], period: str = "1y", actions: bool = False
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Download OHLCV for *tickers* from yfinance.
        Returns (close, volume, high, low, dividends).
        dividends is non-empty only when actions=True.
        """
        if not tickers:
            empty = pd.DataFrame()
            return empty, empty, empty, empty, empty
        data = yf.download(
            tickers,
            period=period,
            auto_adjust=True,
            actions=actions,
            progress=False,
            threads=True,
        )
        empty = pd.DataFrame()
        if isinstance(data.columns, pd.MultiIndex):
            lvl = data.columns.get_level_values(0)
            close     = data["Close"]
            volume    = data["Volume"]    if "Volume"    in lvl else empty
            high      = data["High"]      if "High"      in lvl else empty
            low       = data["Low"]       if "Low"       in lvl else empty
            dividends = data["Dividends"] if "Dividends" in lvl else empty
        else:
            close     = data[["Close"]].rename(columns={"Close":     tickers[0]})
            volume    = data[["Volume"]].rename(columns={"Volume":    tickers[0]}) if "Volume"    in data.columns else empty
            high      = data[["High"]].rename(columns={"High":       tickers[0]}) if "High"      in data.columns else empty
            low       = data[["Low"]].rename(columns={"Low":         tickers[0]}) if "Low"       in data.columns else empty
            dividends = data[["Dividends"]].rename(columns={"Dividends": tickers[0]}) if "Dividends" in data.columns else empty

        def _clean(df: pd.DataFrame) -> pd.DataFrame:
            return df.dropna(how="all") if not df.empty else df

        return _clean(close), _clean(volume), _clean(high), _clean(low), dividends

    def fetch_eodhd_ohlcv(
        self,
        tickers: list[str],
        period: str = "1y",
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        api_key = os.environ.get("EODHD_API_KEY", "").strip()
        if not api_key or not tickers:
            empty = pd.DataFrame()
            return empty, empty, empty, empty

        from_date = (date.today() - timedelta(days=370)).isoformat() if period == "1y" else (date.today() - timedelta(days=60)).isoformat()
        to_date = date.today().isoformat()

        close_map: dict[str, pd.Series] = {}
        volume_map: dict[str, pd.Series] = {}
        high_map: dict[str, pd.Series] = {}
        low_map: dict[str, pd.Series] = {}

        for ticker in tickers:
            override = get_provider_override(ticker)
            provider_symbol = override.get("provider_symbol", ticker)
            rows = self._load_eodhd_series(provider_symbol, from_date, to_date, api_key)
            if not rows:
                continue
            frame = pd.DataFrame(rows)
            if "date" not in frame.columns:
                continue
            frame["date"] = pd.to_datetime(frame["date"])
            frame = frame.set_index("date").sort_index()

            close_col = "adjusted_close" if "adjusted_close" in frame.columns else "close"
            if close_col in frame.columns:
                close_map[ticker] = pd.to_numeric(frame[close_col], errors="coerce")
            if "volume" in frame.columns:
                volume_map[ticker] = pd.to_numeric(frame["volume"], errors="coerce")
            if "high" in frame.columns:
                high_map[ticker] = pd.to_numeric(frame["high"], errors="coerce")
            if "low" in frame.columns:
                low_map[ticker] = pd.to_numeric(frame["low"], errors="coerce")

        def _to_df(series_map: dict[str, pd.Series]) -> pd.DataFrame:
            if not series_map:
                return pd.DataFrame()
            return pd.DataFrame(series_map).sort_index().dropna(how="all")

        return _to_df(close_map), _to_df(volume_map), _to_df(high_map), _to_df(low_map)

    def _load_eodhd_series(self, provider_symbol: str, from_date: str, to_date: str, api_key: str) -> list[dict]:
        os.makedirs(_EODHD_CACHE_DIR, exist_ok=True)
        safe_symbol = provider_symbol.replace("/", "_").replace(".", "_")
        cache_path = os.path.join(_EODHD_CACHE_DIR, f"{safe_symbol}_{to_date}.json")
        if os.path.exists(cache_path):
            try:
                import json
                with open(cache_path, "r") as f:
                    payload = json.load(f)
                return payload.get("rows", [])
            except Exception:
                pass

        try:
            response = requests.get(
                f"https://eodhd.com/api/eod/{provider_symbol}",
                params={
                    "api_token": api_key,
                    "fmt": "json",
                    "from": from_date,
                    "to": to_date,
                    "period": "d",
                },
                timeout=20,
            )
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list):
                rows = []
        except Exception as exc:
            logger.warning("EODHD price fetch failed for %s: %s", provider_symbol, exc)
            return []

        try:
            import json
            import time
            with open(cache_path, "w") as f:
                json.dump({"provider_symbol": provider_symbol, "rows": rows}, f)
            # Clean up cache files older than 2 days to prevent accumulation
            for old_file in os.listdir(_EODHD_CACHE_DIR):
                old_path = os.path.join(_EODHD_CACHE_DIR, old_file)
                if os.path.isfile(old_path) and os.path.getmtime(old_path) < time.time() - 2 * 86400:
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass
        except Exception:
            pass
        return rows

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

    def compute_macd(self, close: pd.DataFrame) -> pd.Series:
        """MACD histogram normalised by price (hist/close). Positive = bullish, negative = bearish."""
        if len(close) < 35:
            return pd.Series(np.nan, index=close.columns, name="macd_hist")
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        hist = macd_line - signal_line
        last_close = close.iloc[-1].replace(0, np.nan)
        return (hist.iloc[-1] / last_close).rename("macd_hist")

    def compute_atr(
        self, high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, window: int = 14
    ) -> pd.Series:
        """14-day ATR as % of last close price (daily expected move).
        E.g. 0.025 = stock typically moves ±2.5% per day."""
        if high.empty or low.empty or len(close) < window + 1:
            return pd.Series(np.nan, index=close.columns, name="atr_pct")
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low  - prev_close).abs()
        # Stack along axis=2 and take element-wise max across the 3 TR components
        stacked = np.stack([tr1.values, tr2.values, tr3.values], axis=2)
        true_range = pd.DataFrame(stacked.max(axis=2), index=close.index, columns=close.columns)
        atr = true_range.rolling(window, min_periods=window // 2).mean()
        last_close = close.iloc[-1].replace(0, np.nan)
        return (atr.iloc[-1] / last_close).rename("atr_pct")

    def _fetch_in_batches(
        self, tickers: list[str], period: str = "1y", batch_size: int = 10
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Fetch OHLCV for *tickers* in small sub-batches, merging results.
        Used as a retry pass for tickers that returned NaN in the bulk download.
        """
        all_close, all_volume, all_high, all_low = (
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        )
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i : i + batch_size]
            try:
                c, v, h, l, _ = self.fetch_ohlcv(batch, period=period)
                if not c.empty:
                    all_close  = all_close.join(c, how="outer")  if not all_close.empty  else c
                    all_volume = all_volume.join(v, how="outer") if not all_volume.empty and not v.empty else (v if all_volume.empty else all_volume)
                    all_high   = all_high.join(h, how="outer")   if not all_high.empty   and not h.empty else (h if all_high.empty   else all_high)
                    all_low    = all_low.join(l, how="outer")    if not all_low.empty    and not l.empty else (l if all_low.empty    else all_low)
            except Exception as exc:
                logger.debug("Batch retry failed for %s: %s", batch, exc)
        empty = pd.DataFrame()
        return all_close, all_volume, all_high, all_low, empty

    def _fetch_dividend_yields_targeted(self, tickers: list[str], close: pd.DataFrame) -> pd.Series:
        """Trailing 12-month dividend yield for a small focused set of tickers.
        Uses auto_adjust=False to avoid NaN issues; divides raw dividends by adjusted close.
        """
        if not tickers:
            return pd.Series(dtype=float)
        game_to_yahoo = {ticker: resolve_yahoo_ticker(ticker) for ticker in tickers}
        yahoo_to_game = {yahoo: game for game, yahoo in game_to_yahoo.items()}
        try:
            data = yf.download(
                list(game_to_yahoo.values()),
                period="1y",
                auto_adjust=False,
                actions=True,
                progress=False,
                threads=True,
            )
            if data.empty:
                return pd.Series(dtype=float)

            if isinstance(data.columns, pd.MultiIndex):
                if "Dividends" not in data.columns.get_level_values(0):
                    return pd.Series(dtype=float)
                divs = data["Dividends"].fillna(0.0)
            else:
                if "Dividends" not in data.columns:
                    return pd.Series(dtype=float)
                divs = data[["Dividends"]].rename(columns={"Dividends": tickers[0]}).fillna(0.0)

            yields: dict[str, float] = {}
            for ticker in tickers:
                yahoo_ticker = game_to_yahoo[ticker]
                if yahoo_ticker not in divs.columns:
                    yields[ticker] = float("nan")
                    continue
                annual_div = float(divs[yahoo_ticker].sum())
                lp_s = close[ticker].dropna() if ticker in close.columns else pd.Series(dtype=float)
                lp = float(lp_s.iloc[-1]) if not lp_s.empty else 0.0
                yields[ticker] = annual_div / lp if lp > 0 else float("nan")
            return pd.Series(yields, name="dividend_yield")
        except Exception as exc:
            logger.warning("Dividend yield fetch failed: %s", exc)
            return pd.Series(dtype=float)

    def _fetch_analyst_consensus_targeted(
        self, tickers: list[str], price_map: dict[str, float]
    ) -> dict[str, dict]:
        """Analyst consensus rating and mean price target for a focused set of tickers.
        Uses yfinance Ticker.info: recommendationMean (1=Strong Buy, 5=Strong Sell),
        targetMeanPrice, numberOfAnalystOpinions. Coverage: good for US, partial for Nordic.
        analyst_upside is only computed for US tickers (no dot in ticker) to avoid
        currency mismatch (yfinance targets are USD, Nordic prices are local currency).
        Fail-soft: returns NaN for tickers with missing data or any exception.
        """
        results: dict[str, dict] = {}
        for ticker in tickers:
            results[ticker] = {"analyst_rating": float("nan"), "analyst_upside": float("nan")}
            try:
                yahoo_ticker = resolve_yahoo_ticker(ticker)
                info = yf.Ticker(yahoo_ticker).info
                rating = info.get("recommendationMean")
                if rating is not None:
                    results[ticker]["analyst_rating"] = float(rating)
                # Only compute analyst_upside for US tickers (no currency mismatch risk)
                is_us = "." not in ticker
                if is_us:
                    target = info.get("targetMeanPrice")
                    last_price = price_map.get(ticker, 0.0)
                    if target is not None and last_price > 0:
                        results[ticker]["analyst_upside"] = float(target) / last_price - 1
            except Exception as exc:
                logger.debug("Analyst consensus fetch failed for %s: %s", ticker, exc)
        return results

    def fetch_commodity_context(self) -> dict:
        """Fetch commodity prices and 20d/5d momentum: Brent (BZ=F), WTI (CL=F), NatGas (NG=F).
        Returns a dict with price and return fields; NaN for any failure.
        """
        result: dict = {
            "brent_price": float("nan"), "brent_20d": float("nan"), "brent_5d": float("nan"),
            "wti_price": float("nan"), "wti_20d": float("nan"),
            "natgas_price": float("nan"), "natgas_20d": float("nan"),
        }
        try:
            data, *_ = self.fetch_ohlcv(["BZ=F", "CL=F", "NG=F"], period="3mo")
            specs = [
                ("BZ=F", "brent_price", "brent_20d", "brent_5d"),
                ("CL=F", "wti_price",   "wti_20d",   None),
                ("NG=F", "natgas_price", "natgas_20d", None),
            ]
            for sym, price_key, mom20_key, mom5_key in specs:
                if sym not in data.columns:
                    continue
                col = data[sym].dropna()
                if len(col) < 2:
                    continue
                result[price_key] = float(col.iloc[-1])
                if len(col) > 21:
                    result[mom20_key] = float(col.iloc[-1] / col.iloc[-22] - 1)
                if mom5_key and len(col) > 5:
                    result[mom5_key] = float(col.iloc[-1] / col.iloc[-6] - 1)
        except Exception as exc:
            logger.warning("Commodity context fetch failed: %s", exc)
        return result

    def fetch_credit_spread(self) -> float:
        """20-day change in HYG/LQD ratio as a credit spread proxy.
        Positive = spreads tightening (risk-on). Negative = widening (risk-off).
        """
        try:
            data, *_ = self.fetch_ohlcv(["HYG", "LQD"], period="2mo")
            if "HYG" not in data.columns or "LQD" not in data.columns:
                return float("nan")
            hyg = data["HYG"].dropna()
            lqd = data["LQD"].dropna()
            hyg, lqd = hyg.align(lqd, join="inner")
            if len(hyg) < 22:
                return float("nan")
            ratio = hyg / lqd
            change = float(ratio.iloc[-1] / ratio.iloc[-22] - 1)
            return change
        except Exception as exc:
            logger.warning("Credit spread fetch failed: %s", exc)
        return float("nan")

    @staticmethod
    def compute_regime_score(
        spx_vs_200d: float,
        vix_term_ratio: float,
        breadth_pct: float,
        credit_change: float,
    ) -> int:
        """Composite regime score 0–100.
        Combines SPX trend, VIX term structure, market breadth, and credit spreads.
        0–30 = defensive/bear  |  31–49 = cautious  |  50–69 = neutral  |  70–100 = bullish/aggressive
        """
        scores: list[float] = []

        # SPX vs 200d SMA: -10% → 0, 0% → 50, +10% → 100
        if not math.isnan(spx_vs_200d):
            scores.append(max(0.0, min(100.0, 50.0 + spx_vs_200d * 500.0)))

        # VIX term ratio: 0.85 → 0, 1.00 → 50, 1.15 → 100
        if not math.isnan(vix_term_ratio):
            scores.append(max(0.0, min(100.0, (vix_term_ratio - 0.85) / 0.30 * 100.0)))

        # Breadth: 20% above 50d → 0, 50% → 50, 80% → 100
        if not math.isnan(breadth_pct):
            scores.append(max(0.0, min(100.0, (breadth_pct - 0.20) / 0.60 * 100.0)))

        # Credit spread change: -5% → 0, 0% → 50, +5% → 100
        if not math.isnan(credit_change):
            scores.append(max(0.0, min(100.0, 50.0 + credit_change * 1000.0)))

        return round(sum(scores) / len(scores)) if scores else 50

    def fetch_vix(self) -> tuple[float, float]:
        """Fetch VIX level and VIX term structure ratio (VIX3M/VIX).
        Term ratio >1 = contango (calm market), <0.9 = backwardation (fear/stress).
        Returns (vix_level, term_ratio).
        """
        try:
            data, *_ = self.fetch_ohlcv(["^VIX", "^VIX3M"], period="5d")
            vix = (
                float(data["^VIX"].dropna().iloc[-1])
                if "^VIX" in data.columns and not data["^VIX"].dropna().empty
                else float("nan")
            )
            vix3m = (
                float(data["^VIX3M"].dropna().iloc[-1])
                if "^VIX3M" in data.columns and not data["^VIX3M"].dropna().empty
                else float("nan")
            )
            term_ratio = (
                vix3m / vix
                if not math.isnan(vix) and not math.isnan(vix3m) and vix > 0
                else float("nan")
            )
            return vix, term_ratio
        except Exception as exc:
            logger.warning("Failed to fetch VIX data: %s", exc)
        return float("nan"), float("nan")

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
        record_map = {r["ticker"]: r for r in records}
        to_remove: set[str] = set()

        for i, t1 in enumerate(available):
            if t1 in to_remove:
                continue
            for t2 in available[i + 1:]:
                if t2 in to_remove:
                    continue
                if t1 not in corr_matrix.index or t2 not in corr_matrix.columns:
                    continue
                if record_map[t1]["market"] != record_map[t2]["market"]:
                    continue
                if corr_matrix.loc[t1, t2] > CORR_THRESHOLD:
                    # Keep the one with stronger composite selection score.
                    score1 = float(record_map[t1].get("selection_score", self._selection_score(record_map[t1])))
                    score2 = float(record_map[t2].get("selection_score", self._selection_score(record_map[t2])))
                    if score1 >= score2:
                        to_remove.add(t2)
                    else:
                        to_remove.add(t1)

        filtered = [r for r in records if r["ticker"] not in to_remove]
        if to_remove:
            logger.info("Correlation filter removed %d tickers: %s", len(to_remove), sorted(to_remove))
        return filtered

    def fetch_short_interest(self, tickers: list[str]) -> dict[str, Optional[float]]:
        """Short % of float for each ticker. Returns None for Baltic/Nordic (no data).
        All failures are silently caught and returned as None."""
        result: dict[str, Optional[float]] = {}
        for t in tickers:
            try:
                info = yf.Ticker(resolve_yahoo_ticker(t)).info
                val = info.get("shortPercentOfFloat")
                result[t] = float(val) if val is not None else None
            except Exception:
                result[t] = None
        return result

    def fetch_premarket_movers(self, tickers: list[str], market_map: dict[str, str]) -> dict[str, Optional[float]]:
        """Gap vs prior close. US tickers: last after-hours candle vs prior close (prepost=True).
        European/Nordic: today's open vs prior close (morning gap after early trading).
        Returns None on any failure."""
        result: dict[str, Optional[float]] = {}
        us_tickers = [t for t in tickers if market_map.get(t) == "SP500"]
        eu_tickers = [t for t in tickers if market_map.get(t) != "SP500"]
        eu_map = {ticker: resolve_yahoo_ticker(ticker) for ticker in eu_tickers}
        us_map = {ticker: resolve_yahoo_ticker(ticker) for ticker in us_tickers}

        # European/Nordic: 5d daily data, compute prior-close to latest-open gap
        if eu_tickers:
            try:
                data = yf.download(
                    list(eu_map.values()), period="5d", interval="1d",
                    auto_adjust=True, progress=False, threads=True,
                )
                if isinstance(data.columns, pd.MultiIndex):
                    opens = data["Open"] if "Open" in data.columns.get_level_values(0) else pd.DataFrame()
                    closes = data["Close"] if "Close" in data.columns.get_level_values(0) else pd.DataFrame()
                else:
                    opens = data[["Open"]].rename(columns={"Open": eu_tickers[0]}) if "Open" in data.columns else pd.DataFrame()
                    closes = data[["Close"]].rename(columns={"Close": eu_tickers[0]}) if "Close" in data.columns else pd.DataFrame()

                for t in eu_tickers:
                    yahoo_ticker = eu_map[t]
                    try:
                        if yahoo_ticker in opens.columns and yahoo_ticker in closes.columns:
                            o = opens[yahoo_ticker].dropna()
                            c = closes[yahoo_ticker].dropna()
                            if len(o) >= 1 and len(c) >= 2:
                                today_open = float(o.iloc[-1])
                                prior_close = float(c.iloc[-2])
                                result[t] = (today_open / prior_close - 1) if prior_close > 0 else None
                            else:
                                result[t] = None
                        else:
                            result[t] = None
                    except Exception:
                        result[t] = None
            except Exception as exc:
                logger.debug("EU premarket fetch failed: %s", exc)
                for t in eu_tickers:
                    result[t] = None

        # US tickers: 60m bars with prepost=True, find last after-hours candle (16:00–20:00 ET)
        if us_tickers:
            try:
                data = yf.download(
                    list(us_map.values()), period="5d", interval="60m",
                    prepost=True, auto_adjust=True, progress=False, threads=True,
                )
                if isinstance(data.columns, pd.MultiIndex):
                    closes = data["Close"] if "Close" in data.columns.get_level_values(0) else pd.DataFrame()
                else:
                    closes = data[["Close"]].rename(columns={"Close": us_tickers[0]}) if "Close" in data.columns else pd.DataFrame()

                for t in us_tickers:
                    yahoo_ticker = us_map[t]
                    try:
                        if yahoo_ticker in closes.columns:
                            s = closes[yahoo_ticker].dropna()
                            if len(s) >= 2:
                                # Last candle vs the regular-hours close two candles back (rough proxy)
                                last_price = float(s.iloc[-1])
                                prev_price = float(s.iloc[-2])
                                result[t] = (last_price / prev_price - 1) if prev_price > 0 else None
                            else:
                                result[t] = None
                        else:
                            result[t] = None
                    except Exception:
                        result[t] = None
            except Exception as exc:
                logger.debug("US premarket fetch failed: %s", exc)
                for t in us_tickers:
                    result[t] = None

        return result

    def fetch_iv_proxy(self, tickers: list[str], price_map: Optional[dict[str, float]] = None) -> dict[str, Optional[float]]:
        """ATM implied volatility from nearest options expiry.
        Returns None for Baltic/Nordic (no options chain).
        price_map: pre-computed last close prices — avoids unreliable info['regularMarketPrice'] after hours."""
        result: dict[str, Optional[float]] = {}
        prices = price_map or {}
        for t in tickers:
            try:
                ticker_obj = yf.Ticker(resolve_yahoo_ticker(t))
                expirations = ticker_obj.options
                if not expirations:
                    result[t] = None
                    continue
                last_price = prices.get(t, 0.0)
                if last_price <= 0:
                    result[t] = None
                    continue
                chain = ticker_obj.option_chain(expirations[0])
                calls = chain.calls[["strike", "impliedVolatility"]].dropna()
                puts = chain.puts[["strike", "impliedVolatility"]].dropna()
                if calls.empty and puts.empty:
                    result[t] = None
                    continue
                all_strikes = pd.concat([calls, puts])
                all_strikes = all_strikes[all_strikes["impliedVolatility"] > 0]
                if all_strikes.empty:
                    result[t] = None
                    continue
                idx = (all_strikes["strike"] - last_price).abs().idxmin()
                result[t] = float(all_strikes.loc[idx, "impliedVolatility"])
            except Exception:
                result[t] = None
        return result

    def get_market_snapshot(self) -> MarketSnapshot:
        """
        Downloads price data for the full universe, computes rich signals,
        and returns the TOP_N_CANDIDATES best-Sharpe stocks as a MarketSnapshot.
        """
        universe = load_game_universe()
        all_tickers: list[tuple[str, str]] = [
            (ticker, market)
            for market, tickers in universe.items()
            for ticker in tickers
        ]
        game_tickers = [t for t, _ in all_tickers]
        market_map = {t: m for t, m in all_tickers}
        eodhd_tickers = [
            ticker for ticker in game_tickers
            if get_provider_override(ticker).get("price_provider") == "eodhd"
        ]
        yahoo_game_tickers = [ticker for ticker in game_tickers if ticker not in eodhd_tickers]
        fetchable_game_tickers, quarantined = filter_known_unavailable(yahoo_game_tickers)
        if quarantined:
            recovered_aliases = auto_resolve_aliases(quarantined, market_map, use_eodhd=False)
            if recovered_aliases:
                recovered_tickers = sorted(recovered_aliases.keys())
                fetchable_game_tickers.extend(recovered_tickers)
                fetchable_game_tickers = list(dict.fromkeys(fetchable_game_tickers))
                quarantined = [ticker for ticker in quarantined if ticker not in recovered_aliases]
                logger.info(
                    "Recovered %d previously quarantined tickers via alias resolution: %s",
                    len(recovered_tickers),
                    recovered_aliases,
                )
            if quarantined:
                logger.info(
                    "Skipping %d game tickers quarantined from prior Yahoo failures: %s",
                    len(quarantined),
                    quarantined[:20],
                )

        game_to_yahoo = {ticker: resolve_yahoo_ticker(ticker) for ticker in fetchable_game_tickers}
        yahoo_to_game = {yahoo: game for game, yahoo in game_to_yahoo.items()}
        flat_tickers = list(game_to_yahoo.values())

        logger.info(
            "Universe loaded: %s (total %d)",
            {market: len(tickers) for market, tickers in universe.items()},
            len(game_tickers),
        )

        logger.info("Fetching OHLCV for %d tickers …", len(flat_tickers))
        # Use actions=False for the main universe download — combining auto_adjust=True + actions=True
        # in large batches causes yfinance to return NaN close prices for many tickers.
        # Dividend yields are fetched separately on just the top-N candidates after filtering.
        close, volume, high, low, _ = self.fetch_ohlcv(flat_tickers, period="1y")
        if eodhd_tickers:
            logger.info("Fetching OHLCV via EODHD fallback for %d tickers …", len(eodhd_tickers))
            e_close, e_volume, e_high, e_low = self.fetch_eodhd_ohlcv(eodhd_tickers, period="1y")
            if not e_close.empty:
                close = close.join(e_close, how="outer") if not close.empty else e_close
            if not e_volume.empty:
                volume = volume.join(e_volume, how="outer") if not volume.empty else e_volume
            if not e_high.empty:
                high = high.join(e_high, how="outer") if not high.empty else e_high
            if not e_low.empty:
                low = low.join(e_low, how="outer") if not low.empty else e_low

        # Retry tickers that returned no data OR too-short history in the batch download.
        # Large yfinance batches often return truncated/NaN history for non-US tickers.
        # Fetching in small sub-batches of 10 recovers the full 1-year history.
        _min_rows = MOMENTUM_WINDOW + 5  # need at least 25 rows for signal computation
        missing = [
            t for t in flat_tickers
            if t not in close.columns
            or len(close[t].dropna()) < _min_rows
        ]
        if missing:
            missing_game_tickers = [yahoo_to_game.get(ticker, ticker) for ticker in missing]
            resolved_aliases = auto_resolve_aliases(missing_game_tickers, market_map, use_eodhd=False)
            if resolved_aliases:
                for game_ticker, yahoo_ticker in resolved_aliases.items():
                    game_to_yahoo[game_ticker] = yahoo_ticker
                    yahoo_to_game[yahoo_ticker] = game_ticker
                missing = [game_to_yahoo.get(game_ticker, game_ticker) for game_ticker in missing_game_tickers]
                logger.info(
                    "Resolved %d failed Yahoo symbols before retry: %s",
                    len(resolved_aliases),
                    resolved_aliases,
                )
            logger.info("Retrying %d/%d failed tickers in small batches …", len(missing), len(flat_tickers))
            r_close, r_volume, r_high, r_low, _ = self._fetch_in_batches(missing, period="1y", batch_size=10)
            if not r_close.empty:
                # Drop the failed tickers from main download before merging to avoid column overlap
                close  = close.drop(columns=[t for t in missing if t in close.columns], errors="ignore")
                volume = volume.drop(columns=[t for t in missing if t in volume.columns], errors="ignore")
                high   = high.drop(columns=[t for t in missing if t in high.columns], errors="ignore")
                low    = low.drop(columns=[t for t in missing if t in low.columns], errors="ignore")
                close  = close.join(r_close,  how="outer") if not close.empty  else r_close
                volume = volume.join(r_volume, how="outer") if not volume.empty and not r_volume.empty else (r_volume if volume.empty else volume)
                high   = high.join(r_high,    how="outer") if not high.empty   and not r_high.empty   else (r_high   if high.empty   else high)
                low    = low.join(r_low,      how="outer") if not low.empty    and not r_low.empty    else (r_low    if low.empty    else low)
                recovered = [t for t in missing if t in r_close.columns and not r_close[t].dropna().empty]
                logger.info("Retry recovered %d/%d tickers: %s", len(recovered), len(missing), recovered)

        still_missing = [t for t in flat_tickers if t not in close.columns or len(close[t].dropna()) < _min_rows]
        if still_missing:
            missing_game_tickers = [yahoo_to_game.get(ticker, ticker) for ticker in still_missing]
            mark_unavailable(missing_game_tickers, reason="yahoo_no_data")
            logger.warning(
                "%d/%d tickers still missing after retry: %s",
                len(still_missing), len(flat_tickers), missing_game_tickers,
            )

        close = close.rename(columns=yahoo_to_game)
        volume = volume.rename(columns=yahoo_to_game)
        high = high.rename(columns=yahoo_to_game)
        low = low.rename(columns=yahoo_to_game)
        symbol_records = {}
        for ticker in close.columns:
            series = close[ticker].dropna()
            if len(series) < _min_rows:
                continue
            yahoo_ticker = game_to_yahoo.get(ticker, ticker)
            override = get_provider_override(ticker)
            price_provider = override.get("price_provider", "yahoo")
            provider_symbol = override.get("provider_symbol", yahoo_ticker)
            symbol_records[ticker] = {
                "game_ticker": ticker,
                "yahoo_ticker": yahoo_ticker,
                "company_name": "",
                "exchange": "",
                "isin": "",
                "market": market_map.get(ticker, "UNKNOWN"),
                "status": "verified",
                "resolution_source": "manual_alias" if yahoo_ticker != ticker else "direct_yahoo",
                "price_provider": price_provider,
                "provider_symbol": provider_symbol,
                "last_verified_at": date.today().isoformat(),
            }
        upsert_symbol_records(symbol_records)

        # Benchmark + regime
        logger.info("Fetching benchmark %s …", BETA_BENCHMARK)
        bench_raw, *_ = self.fetch_ohlcv([BETA_BENCHMARK], period="1y")
        bench_close: pd.Series = bench_raw.iloc[:, 0]

        regime, spx_vs_200d = self.compute_regime(bench_close)
        vix_level, vix_term_ratio = self.fetch_vix()
        logger.info(
            "Regime: %s (SPX vs 200d: %.1f%%), VIX: %.1f, term ratio: %.2f",
            regime, spx_vs_200d * 100,
            vix_level if not math.isnan(vix_level) else 0,
            vix_term_ratio if not math.isnan(vix_term_ratio) else 0,
        )

        # Forward-fill close prices before signal computation.
        # European/Baltic stocks don't trade on US market holidays, producing NaN gaps
        # in the aligned DataFrame. Forward-filling carries the last known price forward
        # so momentum and RSI calculations don't silently drop these tickers.
        close_ff = close.ffill()

        # Compute all signals
        momentum_20d = self.compute_momentum(close_ff, MOMENTUM_WINDOW)
        momentum_5d = self.compute_momentum(close_ff, MOM_SHORT)
        momentum_60d = self.compute_momentum(close_ff, MOM_LONG)
        vol_20d = self.compute_vol(close_ff, MOMENTUM_WINDOW)
        rsi = self.compute_rsi(close_ff, RSI_WINDOW)
        beta = self.compute_beta(close_ff, bench_close)
        vol_ratio = self.compute_vol_ratio(volume, MOMENTUM_WINDOW)
        macd_hist = self.compute_macd(close_ff)
        atr_pct = self.compute_atr(high, low, close_ff)

        # Market breadth: % of universe stocks above their 50d SMA
        sma_50 = close_ff.rolling(50, min_periods=30).mean().iloc[-1]
        above_50 = (close_ff.iloc[-1] > sma_50).sum()
        valid_breadth = int(sma_50.notna().sum())
        breadth_pct = float(above_50 / valid_breadth) if valid_breadth > 0 else float("nan")

        # Credit spread proxy and composite regime score
        credit_change = self.fetch_credit_spread()
        regime_score = self.compute_regime_score(spx_vs_200d, vix_term_ratio, breadth_pct, credit_change)
        _score_label = (
            "DEFENSIVE" if regime_score < 30 else
            "CAUTIOUS"  if regime_score < 50 else
            "NEUTRAL"   if regime_score < 70 else
            "BULLISH"
        )
        logger.info(
            "Regime score: %d/100 (%s) | Credit spread 20d: %+.2f%%",
            regime_score, _score_label,
            credit_change * 100 if not math.isnan(credit_change) else 0,
        )
        bench_momentum = float(
            bench_close.iloc[-1] / bench_close.iloc[-MOMENTUM_WINDOW - 1] - 1
        ) if len(bench_close) > MOMENTUM_WINDOW else 0.0

        # 52-week high (use forward-filled prices for consistent 52w lookback)
        high_52w = close_ff.rolling(252, min_periods=60).max().iloc[-1]

        # Dividend yields are fetched AFTER candidate filtering (targeted ~40-ticker call, not full universe)

        # Valid tickers: must have 20d momentum
        valid_tickers = momentum_20d.dropna().index.tolist()
        dropped_tickers = [t for t in game_tickers if t not in valid_tickers]
        if dropped_tickers:
            logger.warning(
                "Universe shrank: %d/%d tickers dropped (insufficient history): %s",
                len(dropped_tickers), len(game_tickers), ", ".join(dropped_tickers),
            )

        records: list[dict] = []
        for ticker in valid_tickers:
            mom = float(momentum_20d.get(ticker, 0.0))
            vol = float(vol_20d.get(ticker, np.nan))
            rsi_val = float(rsi.get(ticker, np.nan)) if ticker in rsi.index else float("nan")

            sharpe = mom / vol if (not math.isnan(vol) and vol > 0) else 0.0
            last_price = float(close_ff[ticker].dropna().iloc[-1]) if ticker in close_ff.columns else 0.0
            high = float(high_52w.get(ticker, np.nan)) if ticker in high_52w.index else float("nan")
            pct_from_high = (last_price / high - 1) if (not math.isnan(high) and high > 0) else float("nan")

            vr = float(vol_ratio.get(ticker, np.nan)) if not vol_ratio.empty and ticker in vol_ratio.index else float("nan")
            mh = float(macd_hist.get(ticker, np.nan)) if not macd_hist.empty and ticker in macd_hist.index else float("nan")
            at = float(atr_pct.get(ticker, np.nan)) if not atr_pct.empty and ticker in atr_pct.index else float("nan")
            records.append({
                "ticker": ticker,
                "market": market_map.get(ticker, "UNKNOWN"),
                "sector": self._sector_tag(ticker, market_map.get(ticker, "UNKNOWN")),
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
                "macd_hist": mh,
                "atr_pct": at,
                "dividend_yield": float("nan"),   # filled in after top-N filtering via _fetch_dividend_yields_targeted
                "analyst_rating": float("nan"),   # filled in after top-N filtering via _fetch_analyst_consensus_targeted
                "analyst_upside": float("nan"),   # filled in after top-N filtering via _fetch_analyst_consensus_targeted
                "competition_score": 0.0,         # filled in by _compute_competition_scores below
            })

        for record in records:
            record["selection_score"] = self._selection_score(record, regime_score=regime_score)

        # Compute sector momentum aggregates from ALL valid records (before top-N cut).
        # Provides sector-level rotation signals: which sectors are leading vs lagging.
        sector_records: dict[str, list] = {}
        for record in records:
            sector_records.setdefault(record.get("sector", "Other"), []).append(record)
        sector_momentum: dict[str, dict] = {}
        for sector, srecs in sector_records.items():
            mom_20d_vals = [r["momentum"] for r in srecs if not math.isnan(r.get("momentum", float("nan")))]
            mom_5d_vals = [r["mom_5d"] for r in srecs if not math.isnan(r.get("mom_5d", float("nan")))]
            rsi_vals = [r["rsi_14"] for r in srecs if not math.isnan(r.get("rsi_14", float("nan")))]
            # breadth = % of sector stocks with positive 5d momentum (proxy for above short-term SMA)
            positive_5d = sum(1 for v in mom_5d_vals if v > 0)
            sector_momentum[sector] = {
                "avg_mom_20d": float(sum(mom_20d_vals) / len(mom_20d_vals)) if mom_20d_vals else float("nan"),
                "avg_mom_5d": float(sum(mom_5d_vals) / len(mom_5d_vals)) if mom_5d_vals else float("nan"),
                "avg_rsi": float(sum(rsi_vals) / len(rsi_vals)) if rsi_vals else float("nan"),
                "breadth": float(positive_5d / len(mom_5d_vals)) if mom_5d_vals else float("nan"),
                "count": len(srecs),
            }

        rotation_risk = detect_rotation_risk(sector_momentum, sector_records)
        if rotation_risk:
            logger.info("Rotation risk detected: %s", rotation_risk)

        # Compute competition scores (Z-score normalised, regime-specific weights).
        # Separate from selection_score: selection_score filters quality, competition_score ranks for display.
        _compute_competition_scores(records, regime)

        # Sort by competition score (primary) then Sharpe (tiebreak). Pure signal meritocracy.
        records.sort(key=lambda x: (x.get("competition_score", 0.0), x["sharpe_20d"]), reverse=True)
        top = records[:TOP_N_CANDIDATES]

        # Targeted dividend yield fetch — only for the ~40 candidates, not the full 111-ticker universe.
        # Separate call with auto_adjust=False avoids the NaN issue seen with auto_adjust+actions on large batches.
        top_tickers = [r["ticker"] for r in top]
        div_yield = self._fetch_dividend_yields_targeted(top_tickers, close)
        for r in top:
            r["dividend_yield"] = float(div_yield.get(r["ticker"], float("nan"))) if not div_yield.empty and r["ticker"] in div_yield.index else float("nan")

        # Analyst consensus + price target (top-N only; NaN for most Nordic/Baltic)
        top_price_map = {r["ticker"]: r["last_price"] for r in top}
        analyst_data = self._fetch_analyst_consensus_targeted(top_tickers, top_price_map)
        for r in top:
            ad = analyst_data.get(r["ticker"], {})
            r["analyst_rating"] = ad.get("analyst_rating", float("nan"))
            r["analyst_upside"] = ad.get("analyst_upside", float("nan"))

        # New catalyst signals: short interest, premarket gap, IV proxy (all fail-soft)
        logger.info("Fetching catalyst signals (short interest, premarket gap, IV proxy) …")
        short_interest = self.fetch_short_interest(top_tickers)
        premarket_gap = self.fetch_premarket_movers(top_tickers, market_map)
        _iv_prices = {t: float(close_ff[t].dropna().iloc[-1]) for t in top_tickers if t in close_ff.columns and not close_ff[t].dropna().empty}
        iv_proxy = self.fetch_iv_proxy(top_tickers, price_map=_iv_prices)

        # For tickers without options chains (all Nordic/Baltic), fall back to
        # 20-day annualized realized HV as an IV-proxy substitute.
        # Same unit as options IV (annualized %) so catalyst scoring stays valid.
        _sqrt252 = math.sqrt(252)
        hv_filled = 0
        for t in top_tickers:
            if iv_proxy.get(t) is None and t in close_ff.columns:
                prices = close_ff[t].dropna()
                if len(prices) >= 21:
                    hv = float(prices.pct_change().dropna().iloc[-20:].std()) * _sqrt252
                    if hv > 0:
                        iv_proxy[t] = hv
                        hv_filled += 1

        si_count = sum(1 for v in short_interest.values() if v is not None)
        pm_count = sum(1 for v in premarket_gap.values() if v is not None)
        iv_count = sum(1 for v in iv_proxy.values() if v is not None)
        iv_options = iv_count - hv_filled
        logger.info(
            "Catalyst signals: short_interest=%d/%d, premarket_gap=%d/%d, iv_proxy=%d/%d (%d options, %d realized HV)",
            si_count, len(top_tickers), pm_count, len(top_tickers), iv_count, len(top_tickers), iv_options, hv_filled,
        )

        as_of = date.today().isoformat()

        # 1-day returns for ALL tickers (for P&L computation)
        returns_1d_series = (close.iloc[-1] / close.iloc[-2] - 1) if len(close) >= 2 else pd.Series(dtype=float)
        returns_1d: dict = returns_1d_series.dropna().to_dict()
        price_map: dict = {t: float(close[t].dropna().iloc[-1]) for t in close.columns if t in close.columns and not close[t].dropna().empty}
        benchmark_return_1d = float(bench_close.iloc[-1] / bench_close.iloc[-2] - 1) if len(bench_close) >= 2 else 0.0

        logger.info(
            "Snapshot ready: %d candidates, as of %s, benchmark %.1f%%, breadth %.0f%%, regime score %d",
            len(top), as_of, bench_momentum * 100,
            breadth_pct * 100 if not math.isnan(breadth_pct) else 0,
            regime_score,
        )

        candidates: list[CandidateInfo] = [CandidateInfo(**r) for r in top]
        return MarketSnapshot(
            candidates=candidates,
            benchmark_return=bench_momentum,
            as_of_date=as_of,
            regime=regime,
            regime_score=regime_score,
            spx_vs_200d=spx_vs_200d,
            vix_level=vix_level,
            vix_term_ratio=vix_term_ratio,
            breadth_pct=breadth_pct,
            credit_change=credit_change,
            price_map=price_map,
            returns_1d=returns_1d,
            benchmark_return_1d=benchmark_return_1d,
            short_interest=short_interest,
            premarket_gap=premarket_gap,
            iv_proxy=iv_proxy,
            sector_momentum=sector_momentum,
            rotation_risk=rotation_risk,
        )
