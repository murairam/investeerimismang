"""
Fetches recent news headlines for top candidate tickers via yfinance.
Headlines give the AI real-world context (earnings, macro events, sector
rotation) that pure price/momentum signals cannot capture.
"""
import logging

import yfinance as yf

logger = logging.getLogger(__name__)

_MAX_PER_TICKER = 3
_MAX_TOTAL = 45


def fetch_candidate_news(tickers: list[str]) -> list[dict]:
    """
    Fetch recent headlines for the given tickers.
    Returns list of {ticker, title, publisher} dicts.
    Deduplicates on title. Silently skips any ticker that fails.
    """
    seen_titles: set[str] = set()
    results: list[dict] = []

    for ticker in tickers:
        if len(results) >= _MAX_TOTAL:
            break
        try:
            news = yf.Ticker(ticker).news or []
            count = 0
            for item in news[:5]:
                # yfinance v0.2.50+ nests content under item["content"]
                content = item.get("content") or item
                title = (content.get("title") or "").strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                provider = content.get("provider") or {}
                publisher = (
                    provider.get("displayName")
                    or item.get("publisher")
                    or ""
                )
                results.append({
                    "ticker": ticker,
                    "title": title,
                    "publisher": publisher,
                })
                count += 1
                if count >= _MAX_PER_TICKER:
                    break
        except Exception as exc:
            logger.debug("News fetch skipped for %s: %s", ticker, exc)

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
