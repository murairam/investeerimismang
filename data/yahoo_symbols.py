"""
Yahoo Finance symbol resolution and quarantine for game tickers.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date

import requests
import yfinance as yf

logger = logging.getLogger(__name__)

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ALIASES_PATH = os.path.join(_ROOT, "yahoo_symbol_aliases.json")
_UNAVAILABLE_PATH = os.path.join(_ROOT, ".cache", "yahoo_unavailable_tickers.json")
_EODHD_USAGE_PATH = os.path.join(_ROOT, ".cache", "eodhd_usage.json")
_EODHD_SEARCH_URL = "https://eodhd.com/api/search/{query}"
_DEFAULT_EODHD_DAILY_LOOKUP_CAP = 8
_EXPECTED_SUFFIX = {
    "SP500": "",
    "OMXHLCPI": ".HE",
    "OMXS30": ".ST",
    "OBX": ".OL",
    "OMXC25": ".CO",
    "BALTIC": ".VS",
}


def load_aliases() -> dict[str, str]:
    if not os.path.exists(_ALIASES_PATH):
        return {}
    try:
        with open(_ALIASES_PATH, "r") as f:
            data = json.load(f)
        aliases = data.get("aliases", {})
        return {
            str(ticker).upper(): str(alias).upper()
            for ticker, alias in aliases.items()
            if str(ticker).strip() and str(alias).strip()
        }
    except Exception as exc:
        logger.warning("Could not load Yahoo aliases: %s", exc)
        return {}


def resolve_yahoo_ticker(game_ticker: str) -> str:
    aliases = load_aliases()
    return aliases.get(game_ticker.upper(), game_ticker.upper())


def save_aliases(aliases: dict[str, str]) -> None:
    normalized = {
        str(ticker).upper(): str(alias).upper()
        for ticker, alias in aliases.items()
        if str(ticker).strip() and str(alias).strip()
    }
    with open(_ALIASES_PATH, "w") as f:
        json.dump({"aliases": normalized}, f, indent=2, sort_keys=True)


def upsert_aliases(new_aliases: dict[str, str]) -> None:
    if not new_aliases:
        return
    aliases = load_aliases()
    aliases.update({
        str(ticker).upper(): str(alias).upper()
        for ticker, alias in new_aliases.items()
    })
    save_aliases(aliases)


def load_unavailable_yahoo_tickers() -> dict[str, dict]:
    if not os.path.exists(_UNAVAILABLE_PATH):
        return {}
    try:
        with open(_UNAVAILABLE_PATH, "r") as f:
            data = json.load(f)
        return {
            str(ticker).upper(): value
            for ticker, value in data.get("tickers", {}).items()
        }
    except Exception as exc:
        logger.warning("Could not load Yahoo unavailable ticker cache: %s", exc)
        return {}


def save_unavailable_yahoo_tickers(cache: dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(_UNAVAILABLE_PATH), exist_ok=True)
    with open(_UNAVAILABLE_PATH, "w") as f:
        json.dump({"tickers": cache}, f, indent=2)


def mark_unavailable(game_tickers: list[str], reason: str = "no_data") -> None:
    if not game_tickers:
        return
    cache = load_unavailable_yahoo_tickers()
    for ticker in game_tickers:
        cache[ticker.upper()] = {"reason": reason}
    save_unavailable_yahoo_tickers(cache)


def filter_known_unavailable(game_tickers: list[str]) -> tuple[list[str], list[str]]:
    cache = load_unavailable_yahoo_tickers()
    aliases = load_aliases()
    kept = [
        ticker for ticker in game_tickers
        if ticker.upper() not in cache or ticker.upper() in aliases
    ]
    removed = [
        ticker for ticker in game_tickers
        if ticker.upper() in cache and ticker.upper() not in aliases
    ]
    return kept, removed


def auto_resolve_aliases(
    game_tickers: list[str],
    market_map: dict[str, str],
    *,
    use_eodhd: bool = False,
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for ticker in game_tickers:
        market = market_map.get(ticker, "")
        metadata = lookup_symbol_metadata(ticker, market, use_eodhd=use_eodhd)
        alias = metadata.get("yahoo_ticker")
        if alias and alias != ticker.upper():
            resolved[ticker.upper()] = alias

    if resolved:
        upsert_aliases(resolved)
        logger.info("Auto-resolved %d Yahoo aliases: %s", len(resolved), resolved)

    return resolved


def lookup_symbol_metadata(game_ticker: str, market: str, *, use_eodhd: bool = True) -> dict[str, str]:
    direct_alias = resolve_yahoo_ticker(game_ticker)
    api_key = os.getenv("EODHD_API_KEY", "").strip()
    eodhd_record = (
        _search_eodhd_best_record(game_ticker.upper().split(".")[0], market, api_key)
        if api_key and use_eodhd else None
    )
    eodhd_name = ""
    eodhd_exchange = ""
    eodhd_isin = ""
    if eodhd_record:
        eodhd_name = str(eodhd_record.get("Name") or eodhd_record.get("name") or "").strip()
        eodhd_exchange = str(eodhd_record.get("Exchange") or eodhd_record.get("exchange") or "").strip()
        eodhd_isin = str(eodhd_record.get("ISIN") or eodhd_record.get("isin") or "").strip().upper()

    base = game_ticker.upper().split(".")[0]
    queries = [direct_alias, base]
    if eodhd_name:
        queries.insert(0, eodhd_name)
    candidates = _run_search_queries(queries)
    expected_suffix = _EXPECTED_SUFFIX.get(market, "")
    if candidates:
        ranked = sorted(
            candidates,
            key=lambda quote: _score_quote(quote, game_ticker.upper(), base, expected_suffix),
            reverse=True,
        )
        best = ranked[0]
        score = _score_quote(best, game_ticker.upper(), base, expected_suffix)
        if score >= 4:
            return {
                "game_ticker": game_ticker.upper(),
                "yahoo_ticker": str(best.get("symbol", direct_alias)).upper(),
                "company_name": str(best.get("longname") or best.get("shortname") or eodhd_name or "").strip(),
                "exchange": str(best.get("exchDisp") or best.get("exchange") or eodhd_exchange or "").strip(),
                "isin": eodhd_isin,
                "resolution_source": "eodhd+yahoo_search" if eodhd_name else "yahoo_search",
                "status": "active",
            }

    if eodhd_name:
        return {
            "game_ticker": game_ticker.upper(),
            "yahoo_ticker": direct_alias,
            "company_name": eodhd_name,
            "exchange": eodhd_exchange,
            "isin": eodhd_isin,
            "resolution_source": "eodhd_metadata",
            "status": "unverified",
        }

    return {
        "game_ticker": game_ticker.upper(),
        "yahoo_ticker": direct_alias,
        "company_name": "",
        "exchange": "",
        "isin": "",
        "resolution_source": "manual_alias" if direct_alias != game_ticker.upper() else "direct",
        "status": "unverified",
    }


def _search_best_alias(game_ticker: str, market: str) -> str | None:
    base = game_ticker.upper().split(".")[0]
    candidates = _run_search_queries([game_ticker.upper(), base])
    if not candidates:
        return None

    expected_suffix = _EXPECTED_SUFFIX.get(market, "")
    ranked = sorted(
        candidates,
        key=lambda quote: _score_quote(quote, game_ticker.upper(), base, expected_suffix),
        reverse=True,
    )
    best = ranked[0]
    score = _score_quote(best, game_ticker.upper(), base, expected_suffix)
    if score < 5:
        return None

    symbol = str(best.get("symbol", "")).upper()
    return symbol or None


def _search_eodhd_best_record(base: str, market: str, api_key: str) -> dict | None:
    if not api_key or not _consume_eodhd_budget():
        return None
    queries = [base]
    suffix = _EXPECTED_SUFFIX.get(market, "")
    if suffix:
        queries.append(f"{base}{suffix}")

    for query in queries:
        try:
            response = requests.get(
                _EODHD_SEARCH_URL.format(query=query),
                params={"api_token": api_key, "fmt": "json"},
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.debug("EODHD search failed for %s: %s", query, exc)
            continue

        if not isinstance(payload, list):
            continue

        ranked = sorted(
            payload,
            key=lambda item: _score_eodhd_item(item, base, market),
            reverse=True,
        )
        if ranked and _score_eodhd_item(ranked[0], base, market) >= 4:
            return ranked[0]
    return None


def get_eodhd_budget_status() -> dict[str, int]:
    cap = _get_eodhd_daily_lookup_cap()
    usage = _load_eodhd_usage()
    today = date.today().isoformat()
    used = int(usage.get(today, 0))
    return {"used": used, "cap": cap, "remaining": max(0, cap - used)}


def _get_eodhd_daily_lookup_cap() -> int:
    raw = os.getenv("EODHD_DAILY_LOOKUP_CAP", "").strip()
    if raw.isdigit():
        return max(0, int(raw))
    return _DEFAULT_EODHD_DAILY_LOOKUP_CAP


def _load_eodhd_usage() -> dict[str, int]:
    if not os.path.exists(_EODHD_USAGE_PATH):
        return {}
    try:
        with open(_EODHD_USAGE_PATH, "r") as f:
            data = json.load(f)
        return {str(day): int(count) for day, count in data.get("usage", {}).items()}
    except Exception:
        return {}


def _save_eodhd_usage(usage: dict[str, int]) -> None:
    os.makedirs(os.path.dirname(_EODHD_USAGE_PATH), exist_ok=True)
    with open(_EODHD_USAGE_PATH, "w") as f:
        json.dump({"usage": usage}, f, indent=2, sort_keys=True)


def _consume_eodhd_budget() -> bool:
    cap = _get_eodhd_daily_lookup_cap()
    if cap <= 0:
        return False
    usage = _load_eodhd_usage()
    today = date.today().isoformat()
    used = int(usage.get(today, 0))
    if used >= cap:
        return False
    usage[today] = used + 1
    _save_eodhd_usage(usage)
    return True


def _score_eodhd_item(item: dict, base: str, market: str) -> int:
    code = str(item.get("Code") or item.get("code") or "").upper()
    exchange = str(item.get("Exchange") or item.get("exchange") or "").upper()
    name = str(item.get("Name") or item.get("name") or "").upper()
    expected_suffix = _EXPECTED_SUFFIX.get(market, "")

    score = 0
    if code == base:
        score += 10
    if code.startswith(base):
        score += 4
    if market == "OMXHLCPI" and "HELSINKI" in exchange:
        score += 4
    if market == "OMXS30" and "STOCKHOLM" in exchange:
        score += 4
    if market == "OBX" and "OSLO" in exchange:
        score += 4
    if market == "OMXC25" and "COPENHAGEN" in exchange:
        score += 4
    if market == "BALTIC" and any(term in exchange for term in ("VILNIUS", "TALLINN", "RIGA")):
        score += 4
    if market == "SP500" and "US" in exchange:
        score += 4
    if base in name:
        score += 1
    if expected_suffix and code.endswith(expected_suffix.replace(".", "")):
        score += 1
    return score


def _run_search_queries(queries: list[str]) -> list[dict]:
    seen: dict[str, dict] = {}
    for query in queries:
        if not query:
            continue
        try:
            search = yf.Search(query, max_results=8, news_count=0, lists_count=0, raise_errors=False)
            for quote in search.quotes:
                symbol = str(quote.get("symbol", "")).upper()
                if symbol and symbol not in seen:
                    seen[symbol] = quote
        except Exception as exc:
            logger.debug("Yahoo search failed for %s: %s", query, exc)
    return list(seen.values())


def _score_quote(quote: dict, game_ticker: str, base: str, expected_suffix: str) -> int:
    symbol = str(quote.get("symbol", "")).upper()
    exchange = str(quote.get("exchange", "")).upper()
    exch_disp = str(quote.get("exchDisp", "")).upper()
    shortname = str(quote.get("shortname", "")).upper()
    longname = str(quote.get("longname", "")).upper()

    score = 0
    if symbol == game_ticker:
        score += 20
    if symbol.startswith(base):
        score += 8
    if base in shortname or base in longname:
        score += 2
    if expected_suffix and symbol.endswith(expected_suffix):
        score += 6
    if expected_suffix == ".HE" and ("HEL" in exchange or "HEL" in exch_disp):
        score += 4
    if expected_suffix == ".ST" and ("STO" in exchange or "STO" in exch_disp or "STOCKHOLM" in exch_disp):
        score += 4
    if expected_suffix == ".OL" and ("OSL" in exchange or "OSL" in exch_disp or "OSLO" in exch_disp):
        score += 4
    if expected_suffix == ".CO" and ("CPH" in exchange or "COPENHAGEN" in exch_disp):
        score += 4
    if expected_suffix == ".VS" and ("VILNIUS" in exch_disp or "TALLINN" in exch_disp or "RIGA" in exch_disp):
        score += 4
    return score
