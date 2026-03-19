"""
Fetches Google Trends search interest for stock tickers via pytrends.
High retail search interest = crowded trade = move may already be priced in.
This is a contrarian signal: low interest = flying under the radar = opportunity.
Useful as a tie-breaker between otherwise equal candidates.
"""
import json
import logging
import os
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_SEARCH_TIMEFRAME        = "today 1-m"   # last 30 days
_MAX_TICKERS_BATCH       = 5             # pytrends max per request
_MAX_TICKERS_TOTAL       = 15            # Reduced from 20 to 15 (25% fewer API calls)
_REQUEST_DELAY           = 3.0           # Base delay between batches
_HIGH_INTEREST_THRESHOLD = 70            # crowded
_LOW_INTEREST_THRESHOLD  = 25            # under the radar
_MAX_RETRIES             = 2             # Retry on 429
_RETRY_BACKOFF           = 5.0           # Wait 5s on retry
_CACHE_TTL_HOURS         = 6             # Cache results for 6 hours
_MAX_CONSECUTIVE_FAILURES = 2            # Stop after N consecutive batch failures

# Nordic/Baltic exchange suffixes to strip before querying Google
_EXCHANGE_SUFFIXES = (".HE", ".ST", ".OL", ".CO", ".TL", ".VS")

# Rotate user agents to reduce bot detection
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
]

_CACHE_DIR = Path(__file__).parent.parent / ".cache"
_CACHE_FILE = _CACHE_DIR / "trends_cache.json"


def _strip_suffix(ticker: str) -> str:
    for suffix in _EXCHANGE_SUFFIXES:
        if ticker.upper().endswith(suffix.upper()):
            return ticker[: -len(suffix)]
    return ticker


def _load_cache() -> dict:
    """Load cached trends data if it exists and is fresh (<6 hours old)."""
    if not _CACHE_FILE.exists():
        return {}
    try:
        with open(_CACHE_FILE) as f:
            cache = json.load(f)
        cache_time = datetime.fromisoformat(cache.get("timestamp", "2000-01-01T00:00:00"))
        ttl_hours = _CACHE_TTL_HOURS
        # If cache is marked as "failed", use shorter 30-min TTL
        if cache.get("failed"):
            ttl_hours = 0.5
        if datetime.now() - cache_time < timedelta(hours=ttl_hours):
            logger.info("Using cached Google Trends data (age: %.1fh%s)",
                       (datetime.now() - cache_time).total_seconds() / 3600,
                       " [failed fetch]" if cache.get("failed") else "")
            return cache.get("data", {})
        else:
            logger.debug("Cache expired (%.1fh old), will refresh", (datetime.now() - cache_time).total_seconds() / 3600)
    except Exception as exc:
        logger.debug("Failed to load trends cache: %s", exc)
    return {}


def _save_cache(data: dict, failed: bool = False) -> None:
    """Save trends data to cache with current timestamp. If failed=True, use shorter TTL."""
    try:
        _CACHE_DIR.mkdir(exist_ok=True, parents=True)
        with open(_CACHE_FILE, "w") as f:
            json.dump({"timestamp": datetime.now().isoformat(), "data": data, "failed": failed}, f)
    except Exception as exc:
        logger.warning("Failed to save trends cache: %s", exc)


def fetch_search_interest(tickers: list[str]) -> list[dict]:
    """
    Fetch Google Trends interest scores for top candidates.
    Caps to 15 tickers to stay within time budget. Results cached for 6 hours.
    Returns list of dicts sorted by avg_interest descending:
        {"ticker": str, "avg_interest": float, "signal": "crowded"|"radar"|"neutral"}
    Non-fatal: returns [] on any pytrends failure.
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        logger.warning("pytrends not installed — skipping Google Trends signal")
        return []

    # Check cache first
    cached = _load_cache()
    if cached:
        # Filter to requested tickers only
        return [v for k, v in cached.items() if k in tickers[:_MAX_TICKERS_TOTAL]]

    capped = tickers[:_MAX_TICKERS_TOTAL]
    # Map search_term → original ticker (ticker may differ from search term)
    term_to_ticker: dict[str, str] = {}
    search_terms: list[str] = []
    for ticker in capped:
        term = _strip_suffix(ticker)
        if term not in term_to_ticker:
            term_to_ticker[term] = ticker
            search_terms.append(term)

    results: dict[str, float] = {}
    consecutive_failures = 0

    try:
        # Rotate user agent to reduce bot detection
        user_agent = random.choice(_USER_AGENTS)
        pytrends = TrendReq(hl="en-US", tz=120, timeout=(5, 10), requests_args={"headers": {"User-Agent": user_agent}})

        batches = [
            search_terms[i : i + _MAX_TICKERS_BATCH]
            for i in range(0, len(search_terms), _MAX_TICKERS_BATCH)
        ]

        for i, batch in enumerate(batches):
            # Early exit if too many consecutive failures (Google is blocking us)
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                logger.warning("Stopping trends fetch after %d consecutive batch failures", consecutive_failures)
                break

            if i > 0:
                # Exponential backoff: each batch waits progressively longer
                delay = _REQUEST_DELAY * (1.5 ** i) + random.uniform(0, 1.0)
                time.sleep(delay)

            batch_succeeded = False
            # Retry logic for 429 rate limits
            for attempt in range(_MAX_RETRIES + 1):
                try:
                    pytrends.build_payload(batch, cat=7, timeframe=_SEARCH_TIMEFRAME)
                    df = pytrends.interest_over_time()
                    if df is not None and not df.empty:
                        for term in batch:
                            if term in df.columns:
                                results[term] = float(df[term].mean())
                    batch_succeeded = True
                    consecutive_failures = 0  # Reset on success
                    break  # Success, exit retry loop
                except Exception as exc:
                    error_msg = str(exc).lower()
                    # Check if it's a 429 rate limit error
                    if "429" in error_msg and attempt < _MAX_RETRIES:
                        wait_time = _RETRY_BACKOFF * (attempt + 1)
                        logger.info("Trends batch %d hit rate limit (429), retrying in %.1fs (attempt %d/%d)",
                                   i, wait_time, attempt + 1, _MAX_RETRIES)
                        time.sleep(wait_time)
                    else:
                        # Non-rate-limit error or final attempt — log and move on
                        logger.warning("Trends batch %d failed: %s", i, exc)
                        break

            if not batch_succeeded:
                consecutive_failures += 1

    except Exception as exc:
        logger.warning("Google Trends fetch failed (non-fatal): %s", exc)
        return []

    output = []
    cache_data = {}
    for term, avg in results.items():
        ticker = term_to_ticker.get(term, term)
        if avg >= _HIGH_INTEREST_THRESHOLD:
            signal = "crowded"
        elif avg <= _LOW_INTEREST_THRESHOLD:
            signal = "radar"
        else:
            signal = "neutral"
        entry = {"ticker": ticker, "avg_interest": avg, "signal": signal}
        output.append(entry)
        cache_data[ticker] = entry

    output.sort(key=lambda x: x["avg_interest"], reverse=True)

    # Save to cache if we got any results
    if cache_data:
        _save_cache(cache_data)
    else:
        # Save "failed" marker with 30-min TTL to avoid hammering Google
        logger.info("No trends data — caching failed state for 30min to avoid rate limits")
        _save_cache({}, failed=True)

    return output


def format_trends_context(trends: list[dict]) -> str:
    """
    Returns "" if trends list is empty. Otherwise produces a concise crowding indicator block.
    """
    if not trends:
        return ""

    crowded = [t for t in trends if t["signal"] == "crowded"]
    radar   = [t for t in trends if t["signal"] == "radar"]
    neutral = [t for t in trends if t["signal"] == "neutral"]

    lines = ["GOOGLE SEARCH INTEREST (last 30 days — retail crowding indicator):"]

    if crowded:
        names = ", ".join(f"{t['ticker']} ({int(t['avg_interest'])})" for t in crowded)
        lines.append(f"WARNING HIGH INTEREST (crowded trades — risk of priced-in): {names}")

    if radar:
        names = ", ".join(f"{t['ticker']} ({int(t['avg_interest'])})" for t in radar)
        lines.append(f"LOW INTEREST (flying under radar — contrarian opportunity): {names}")

    if neutral:
        names = ", ".join(f"{t['ticker']} ({int(t['avg_interest'])})" for t in neutral)
        lines.append(f"Neutral: {names}")

    lines.append("Note: high interest = retail crowding = move may already be priced in")
    return "\n".join(lines)
