"""Reddit/WSB ticker mention momentum via free ApeWisdom API.

Single network call per pipeline run — fetches top-100 by mentions, then a
per-ticker lookup is a dict access. No per-ticker API hits. 1-hour cache.

Output fields per ticker:
- reddit_hype_score: 0-100, normalised by rank in top list (rank 1 → 100, off-list → NaN)
- momentum_trajectory: 'rising', 'falling', 'flat' from current_24h vs previous_24h mentions
- mentions: raw current 24h count
- rank: rank in WSB top list (1-100), None if not listed
"""
from __future__ import annotations

import logging
import math
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/wallstreetbets/page/1"
_CACHE_TTL_S = 3600
_TIMEOUT_S = 10

_cache: dict = {"fetched_at": 0.0, "data": {}}


def _fetch_top_list(force: bool = False) -> dict[str, dict]:
    """Fetch ApeWisdom top-100. Cache for 1 hour. Returns dict keyed by ticker symbol."""
    now = time.time()
    if not force and _cache["data"] and (now - _cache["fetched_at"]) < _CACHE_TTL_S:
        return _cache["data"]
    try:
        resp = requests.get(_APEWISDOM_URL, timeout=_TIMEOUT_S)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        logger.warning("ApeWisdom fetch failed: %s — using cached/empty data", exc)
        return _cache["data"]
    except (ValueError, KeyError) as exc:
        logger.warning("ApeWisdom payload malformed: %s", exc)
        return _cache["data"]

    results = payload.get("results") or []
    out: dict[str, dict] = {}
    for entry in results:
        ticker = (entry.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        try:
            rank = int(entry.get("rank") or 0)
            mentions = int(entry.get("mentions") or 0)
            mentions_prev = int(entry.get("mentions_24h_ago") or 0)
        except (TypeError, ValueError):
            continue
        out[ticker] = {
            "rank": rank,
            "mentions": mentions,
            "mentions_24h_ago": mentions_prev,
        }
    if out:
        _cache["data"] = out
        _cache["fetched_at"] = now
        logger.info("ApeWisdom: fetched %d WSB tickers (top mention=%d)", len(out), max(e["mentions"] for e in out.values()))
    return out


def _trajectory(curr: int, prev: int) -> str:
    """Classify mention trajectory between consecutive 24h windows."""
    if prev == 0 and curr == 0:
        return "flat"
    if prev == 0:
        return "rising"
    ratio = curr / prev
    if ratio >= 1.30:
        return "rising"
    if ratio <= 0.70:
        return "falling"
    return "flat"


def get_social_momentum(ticker: str, top_data: Optional[dict[str, dict]] = None) -> dict:
    """Return reddit_hype_score (0-100) + momentum_trajectory for ticker.

    Pass top_data from a single _fetch_top_list() call to avoid per-ticker fetches.
    Score formula: linear by rank within top-100. Off-list returns NaN score.
    Non-US tickers (with '.' in symbol) get NaN — WSB is US-centric.
    """
    if not ticker:
        return _empty()
    sym = ticker.upper().split(".")[0]
    if "." in ticker:  # ".OL", ".HE", ".CO", ".ST", ".TL", ".RG"
        return _empty()
    data = top_data if top_data is not None else _fetch_top_list()
    if not data:
        return _empty()
    entry = data.get(sym)
    if not entry:
        return {
            "reddit_hype_score": 0.0,
            "momentum_trajectory": "flat",
            "mentions": 0,
            "rank": None,
        }
    rank = entry["rank"]
    mentions = entry["mentions"]
    mentions_prev = entry["mentions_24h_ago"]
    # Linear score: rank 1 → 100, rank 100 → 1
    if rank > 0:
        score = max(0.0, 101.0 - rank)
    else:
        score = 0.0
    return {
        "reddit_hype_score": round(score, 2),
        "momentum_trajectory": _trajectory(mentions, mentions_prev),
        "mentions": mentions,
        "rank": rank,
    }


def _empty() -> dict:
    return {
        "reddit_hype_score": float("nan"),
        "momentum_trajectory": "flat",
        "mentions": 0,
        "rank": None,
    }


def fetch_for_universe(tickers: list[str]) -> dict[str, dict]:
    """One API hit + bulk lookup. Returns {ticker: social_momentum_dict}."""
    top = _fetch_top_list()
    return {t: get_social_momentum(t, top) for t in tickers}
