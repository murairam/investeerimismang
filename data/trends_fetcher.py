"""
Fetches Google Trends search interest for stock tickers via pytrends.
High retail search interest = crowded trade = move may already be priced in.
This is a contrarian signal: low interest = flying under the radar = opportunity.
Useful as a tie-breaker between otherwise equal candidates.
"""
import logging
import time

logger = logging.getLogger(__name__)

_SEARCH_TIMEFRAME        = "today 1-m"   # last 30 days
_MAX_TICKERS_BATCH       = 5             # pytrends max per request
_MAX_TICKERS_TOTAL       = 20
_REQUEST_DELAY           = 1.5           # Google throttles aggressively
_HIGH_INTEREST_THRESHOLD = 70            # crowded
_LOW_INTEREST_THRESHOLD  = 25            # under the radar

# Nordic/Baltic exchange suffixes to strip before querying Google
_EXCHANGE_SUFFIXES = (".HE", ".ST", ".OL", ".CO", ".TL", ".VS")


def _strip_suffix(ticker: str) -> str:
    for suffix in _EXCHANGE_SUFFIXES:
        if ticker.upper().endswith(suffix.upper()):
            return ticker[: -len(suffix)]
    return ticker


def fetch_search_interest(tickers: list[str]) -> list[dict]:
    """
    Fetch Google Trends interest scores for top candidates.
    Caps to 20 tickers to stay within time budget.
    Returns list of dicts sorted by avg_interest descending:
        {"ticker": str, "avg_interest": float, "signal": "crowded"|"radar"|"neutral"}
    Non-fatal: returns [] on any pytrends failure.
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        logger.warning("pytrends not installed — skipping Google Trends signal")
        return []

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

    try:
        pytrends = TrendReq(hl="en-US", tz=120)

        batches = [
            search_terms[i : i + _MAX_TICKERS_BATCH]
            for i in range(0, len(search_terms), _MAX_TICKERS_BATCH)
        ]

        for i, batch in enumerate(batches):
            if i > 0:
                time.sleep(_REQUEST_DELAY)
            try:
                pytrends.build_payload(batch, cat=7, timeframe=_SEARCH_TIMEFRAME)
                df = pytrends.interest_over_time()
                if df is not None and not df.empty:
                    for term in batch:
                        if term in df.columns:
                            results[term] = float(df[term].mean())
            except Exception as exc:
                logger.debug("Trends batch %d failed: %s", i, exc)

    except Exception as exc:
        logger.warning("Google Trends fetch failed (non-fatal): %s", exc)
        return []

    output = []
    for term, avg in results.items():
        ticker = term_to_ticker.get(term, term)
        if avg >= _HIGH_INTEREST_THRESHOLD:
            signal = "crowded"
        elif avg <= _LOW_INTEREST_THRESHOLD:
            signal = "radar"
        else:
            signal = "neutral"
        output.append({"ticker": ticker, "avg_interest": avg, "signal": signal})

    output.sort(key=lambda x: x["avg_interest"], reverse=True)
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
