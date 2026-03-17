"""
Fetches SEC EDGAR Form 4 insider buying data for US tickers.
Open-market purchases by insiders (especially executives) are the strongest
available conviction signal — insiders only buy when they expect the stock to rise.
No API key needed: uses the free federal SEC EDGAR database.
"""
import json
import logging
import os
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import requests

logger = logging.getLogger(__name__)

_EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_EDGAR_BASE        = "https://data.sec.gov"
_EDGAR_ARCHIVES    = "https://www.sec.gov/Archives/edgar/data"
_CIK_CACHE_PATH    = os.path.join(os.path.dirname(__file__), "sec_cik_cache.json")
_CIK_CACHE_TTL     = 7 * 24 * 3600   # 7 days
_HEADERS           = {"User-Agent": "AlphaShark/1.0 alphashark-bot@example.com"}
_REQUEST_DELAY     = 0.11             # < 10 req/s SEC limit
_LOOKBACK_DAYS     = 30
_MIN_VALUE_USD     = 50_000
_MAX_FILINGS_PER_TICKER = 5

# Nordic/Baltic exchange suffixes — silently skip these
_NON_US_SUFFIXES = (".HE", ".ST", ".OL", ".CO", ".TL", ".VS")


def _get_cik_map() -> dict[str, str]:
    """Load CIK map from cache, refreshing if stale or missing."""
    # Try to use valid cache
    if os.path.exists(_CIK_CACHE_PATH):
        age = time.time() - os.path.getmtime(_CIK_CACHE_PATH)
        if age < _CIK_CACHE_TTL:
            try:
                with open(_CIK_CACHE_PATH) as f:
                    return json.load(f)
            except Exception as exc:
                logger.debug("CIK cache read error: %s", exc)

    # Refresh from SEC
    try:
        resp = requests.get(_EDGAR_TICKERS_URL, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        # raw = {"0": {"cik_str": 320193, "ticker": "AAPL", ...}, ...}
        cik_map = {
            entry["ticker"].upper(): str(entry["cik_str"])
            for entry in raw.values()
            if "ticker" in entry and "cik_str" in entry
        }
        with open(_CIK_CACHE_PATH, "w") as f:
            json.dump(cik_map, f)
        logger.debug("CIK cache refreshed: %d tickers", len(cik_map))
        return cik_map
    except Exception as exc:
        logger.warning("CIK cache refresh failed: %s — using stale cache", exc)
        if os.path.exists(_CIK_CACHE_PATH):
            try:
                with open(_CIK_CACHE_PATH) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}


def _fmt_value(value_usd: float) -> str:
    if value_usd >= 1_000_000:
        return f"${value_usd / 1_000_000:.1f}M"
    return f"${int(value_usd / 1000)}k"


def _parse_form4_xml(xml_text: str, ticker: str) -> list[dict]:
    """Parse a Form 4 XML and return open-market purchases above threshold."""
    trades = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.debug("XML parse error for %s: %s", ticker, exc)
        return trades

    # Officer title — try reportingOwner first
    title = ""
    for t in root.findall(".//{*}officerTitle"):
        title = (t.text or "").strip()
        if title:
            break

    period_el = root.find(".//{*}periodOfReport")
    report_date = (period_el.text or "").strip() if period_el is not None else ""

    for tx in root.findall(".//{*}nonDerivativeTransaction"):
        code_el = tx.find(".//{*}transactionCode")
        if code_el is None or (code_el.text or "").strip() != "P":
            continue

        shares_el = tx.find(".//{*}transactionShares/{*}value")
        price_el  = tx.find(".//{*}transactionPricePerShare/{*}value")
        date_el   = tx.find(".//{*}transactionDate/{*}value")

        if shares_el is None or price_el is None:
            continue

        try:
            shares = float(shares_el.text or 0)
            price  = float(price_el.text or 0)
        except (ValueError, TypeError):
            continue

        value_usd = shares * price
        if value_usd < _MIN_VALUE_USD:
            continue

        tx_date = (date_el.text or report_date or "").strip() if date_el is not None else report_date

        trades.append({
            "ticker":           ticker,
            "date":             tx_date,
            "insider_title":    title or "Insider",
            "shares":           int(shares),
            "value_usd":        value_usd,
            "transaction_type": "P",
        })

    return trades


def fetch_insider_trades(tickers: list[str]) -> list[dict]:
    """
    Fetch recent insider open-market purchases for US tickers only.
    Nordic/Baltic tickers (.HE/.ST/.OL/.CO/.TL/.VS) are silently skipped.
    Returns list of dicts sorted by value_usd descending:
        {"ticker", "date", "insider_title", "shares", "value_usd", "transaction_type"}
    Non-fatal: any per-ticker/per-filing failure is caught and logged at DEBUG.
    """
    us_tickers = [t for t in tickers if not any(t.upper().endswith(s) for s in _NON_US_SUFFIXES)]
    if not us_tickers:
        return []

    cik_map = _get_cik_map()
    cutoff  = (date.today() - timedelta(days=_LOOKBACK_DAYS)).isoformat()
    all_trades: list[dict] = []

    for ticker in us_tickers:
        cik = cik_map.get(ticker.upper())
        if not cik:
            logger.debug("No CIK for %s — skipping", ticker)
            continue

        cik_padded = cik.zfill(10)
        try:
            url = f"{_EDGAR_BASE}/submissions/CIK{cik_padded}.json"
            resp = requests.get(url, headers=_HEADERS, timeout=15)
            time.sleep(_REQUEST_DELAY)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("Submissions fetch failed for %s: %s", ticker, exc)
            continue

        try:
            recent = data.get("filings", {}).get("recent", {})
            forms        = recent.get("form", [])
            filing_dates = recent.get("filingDate", [])
            accessions   = recent.get("accessionNumber", [])
        except Exception as exc:
            logger.debug("Submissions parse error for %s: %s", ticker, exc)
            continue

        # Filter Form 4/4A within lookback window
        qualifying = [
            acc
            for form, fd, acc in zip(forms, filing_dates, accessions)
            if form in ("4", "4/A") and fd >= cutoff
        ][:_MAX_FILINGS_PER_TICKER]

        for acc in qualifying:
            acc_nodashes = acc.replace("-", "")
            xml_url = f"{_EDGAR_ARCHIVES}/{cik}/{acc_nodashes}/{acc_nodashes}.xml"
            try:
                resp = requests.get(xml_url, headers=_HEADERS, timeout=15)
                time.sleep(_REQUEST_DELAY)
                resp.raise_for_status()
                trades = _parse_form4_xml(resp.text, ticker)
                all_trades.extend(trades)
            except Exception as exc:
                logger.debug("Form4 fetch/parse failed for %s acc %s: %s", ticker, acc, exc)

    all_trades.sort(key=lambda x: x["value_usd"], reverse=True)
    return all_trades


def format_insider_context(trades: list[dict]) -> str:
    """
    Returns "" if no trades. Otherwise formats a concise block with cluster detection.
    """
    if not trades:
        return ""

    # Count trades per ticker for cluster detection
    ticker_counts: dict[str, int] = {}
    for t in trades:
        ticker_counts[t["ticker"]] = ticker_counts.get(t["ticker"], 0) + 1

    lines = ["INSIDER BUYING (last 30 days — strongest conviction signal):"]
    for t in trades:
        cluster_prefix = "CLUSTER BUY — " if ticker_counts[t["ticker"]] >= 2 else ""
        val = _fmt_value(t["value_usd"])
        title = t["insider_title"]
        lines.append(
            f"• {t['ticker']}: {cluster_prefix}{title} bought {t['shares']:,} shares "
            f"({val}) on {t['date']} — strong insider conviction"
        )

    lines.append("(No recent insider selling flagged — absence of selling is a mild positive)")
    return "\n".join(lines)
