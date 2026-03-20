"""
Fetches recent news headlines for candidate tickers.
Primary source: yfinance (free, good US coverage).
Fallback: EODHD news API (better Nordic/Baltic coverage, uses existing key).
Headlines give the AI real-world context (earnings, macro events, sector
rotation) that pure price/momentum signals cannot capture.
"""
import logging
import os

import requests
import yfinance as yf

logger = logging.getLogger(__name__)

_MAX_PER_TICKER = 3
_MAX_TOTAL = 150
_EODHD_NEWS_URL = "https://eodhistoricaldata.com/api/news"


def _to_eodhd_symbol(ticker: str) -> str:
    """Convert yfinance ticker to EODHD symbol (US tickers get .US suffix)."""
    return ticker if "." in ticker else f"{ticker}.US"


def _fetch_eodhd_news(ticker: str, api_key: str) -> list[dict]:
    """Fetch up to _MAX_PER_TICKER headlines from EODHD for one ticker."""
    try:
        resp = requests.get(
            _EODHD_NEWS_URL,
            params={
                "s": _to_eodhd_symbol(ticker),
                "limit": _MAX_PER_TICKER,
                "api_token": api_key,
                "fmt": "json",
            },
            timeout=5,
        )
        if resp.status_code != 200:
            return []
        items = resp.json() or []
        results = []
        for item in items:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            results.append({
                "ticker": ticker,
                "title": title,
                "publisher": item.get("source") or "",
            })
        return results
    except Exception as exc:
        logger.debug("EODHD news skipped for %s: %s", ticker, exc)
        return []


def fetch_candidate_news(tickers: list[str], eodhd_api_key: str = "") -> list[dict]:
    """
    Fetch recent headlines for the given tickers.
    yfinance is tried first; tickers that return nothing fall back to EODHD.
    Returns list of {ticker, title, publisher} dicts, deduplicated on title.
    """
    seen_titles: set[str] = set()
    results: list[dict] = []
    eodhd_key = eodhd_api_key or os.environ.get("EODHD_API_KEY", "").strip()

    def _add(items: list[dict]) -> int:
        added = 0
        for item in items:
            if item["title"] not in seen_titles:
                seen_titles.add(item["title"])
                results.append(item)
                added += 1
        return added

    for ticker in tickers:
        if len(results) >= _MAX_TOTAL:
            break
        try:
            news = yf.Ticker(ticker).news or []
            count = 0
            yf_items = []
            for item in news[:5]:
                content = item.get("content") or item
                title = (content.get("title") or "").strip()
                if not title:
                    continue
                provider = content.get("provider") or {}
                publisher = (
                    provider.get("displayName")
                    or item.get("publisher")
                    or ""
                )
                yf_items.append({"ticker": ticker, "title": title, "publisher": publisher})
                count += 1
                if count >= _MAX_PER_TICKER:
                    break

            if yf_items:
                _add(yf_items)
            elif eodhd_key:
                # yfinance returned nothing — try EODHD (common for Nordic/Baltic)
                _add(_fetch_eodhd_news(ticker, eodhd_key))

        except Exception as exc:
            logger.debug("News fetch skipped for %s: %s", ticker, exc)
            if eodhd_key:
                _add(_fetch_eodhd_news(ticker, eodhd_key))

    return results


def format_news_for_prompt(news_items: list[dict]) -> str:
    """Format headlines as a concise block for agent prompt injection."""
    if not news_items:
        return ""
    lines = [
        "Recent headlines for candidate stocks "
        "(use for context — do not over-weight any single item):"
    ]
    for item in news_items:
        pub = f" ({item['publisher']})" if item["publisher"] else ""
        lines.append(f"• [{item['ticker']}] {item['title']}{pub}")
    return "\n".join(lines)
