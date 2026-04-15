"""
Load the full game universe from official source links, with cached results and
static fallbacks for markets that are harder to scrape reliably.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from io import StringIO

import pandas as pd
import requests

from config import UNIVERSE as CURATED_UNIVERSE
from data.game_availability import filter_unavailable_tickers
from data.provider_overrides import load_provider_overrides

logger = logging.getLogger(__name__)

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_CACHE_DIR = os.path.join(_ROOT, ".cache")
_CACHE_PATH = os.path.join(_CACHE_DIR, "game_universe.json")
_CACHE_MAX_AGE = timedelta(days=30)  # OBX composition changes quarterly; monthly refresh is sufficient

_SOURCE_URLS = {
    "SP500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "OMXHLCPI": "https://indexes.nasdaqomx.com/Index/Weighting/OMXHLCPI",
    "OMXS30": "https://indexes.nasdaqomx.com/Index/Weighting/OMXS30",
    "OMXC25": "https://indexes.nasdaqomx.com/Index/Weighting/OMXC25",
    "OBX": "https://live.euronext.com/en/product/indices/NO0000000021-XOSL#index-composition",
    "BALTIC": "https://nasdaqbaltic.com/statistics/et/shares#BAMT",
}

_FALLBACK_UNIVERSE: dict[str, list[str]] = {
    "SP500": CURATED_UNIVERSE["SP500"][:],
    "OMXHLCPI": [
        "NDA-FI.HE", "NOKIA.HE", "FORTUM.HE", "SAMPO.HE", "NESTE.HE",
        "KNEBV.HE", "WRT1V.HE", "STERV.HE", "OUT1V.HE", "ELISA.HE",
        "ORNBV.HE", "UPM.HE", "METSO.HE", "KCR.HE", "VALMT.HE",
        "TIETO.HE", "KESKOB.HE", "KOJAMO.HE", "HUH1V.HE", "CGCBV.HE",
        "METSB.HE", "TYRES.HE", "YIT.HE", "DIGIA.HE", "CTY1S.HE",
        "MANTA.HE", "KALMAR.HE", "RAUT.HE", "OKDAV.HE",
    ],
    "OMXS30": [
        "ABB.ST", "ALFA.ST", "ASSA-B.ST", "ATCO-A.ST", "ATCO-B.ST",
        "AZN.ST", "BOL.ST", "ELUX-B.ST", "ERIC-B.ST", "ESSITY-B.ST",
        "EVO.ST", "GETI-B.ST", "HEXA-B.ST", "HM-B.ST", "INDU-C.ST",
        "INVE-B.ST", "NDA-SE.ST", "NIBE-B.ST", "SAND.ST", "SAAB-B.ST",
        "SEB-A.ST", "SHB-A.ST", "SKA-B.ST", "SKF-B.ST", "SSAB-A.ST",
        "SWED-A.ST", "TEL2-B.ST", "TELIA.ST", "VOLV-B.ST", "VOLCAR-B.ST",
    ],
    "OBX": [
        "AKRBP.OL", "AUTO.OL", "BAKKA.OL", "BWLPG.OL", "DNB.OL",
        "EQNR.OL", "FRO.OL", "GJF.OL", "GOGL.OL", "HAUTO.OL",
        "KOG.OL", "MOWI.OL", "NAS.OL", "NEL.OL", "NHY.OL",
        "OKEA.OL", "ORK.OL", "PGS.OL", "SALM.OL", "SCHA.OL",
        "SDRL.OL", "SUBC.OL", "TEL.OL", "TOM.OL", "YAR.OL",
    ],
    "OMXC25": [
        "AMBU-B.CO", "BAVA.CO", "CARL-B.CO", "COLO-B.CO", "DANSKE.CO",
        "DEMANT.CO", "DSV.CO", "GMAB.CO", "GN.CO", "ISS.CO",
        "JYSK.CO", "MAERSK-A.CO", "MAERSK-B.CO", "NDA-DK.CO", "NKT.CO",
        "NOVO-B.CO", "NSIS-B.CO", "ORSTED.CO", "PNDORA.CO", "RBREW.CO",
        "ROCK-B.CO", "SYDB.CO", "TRYG.CO", "VWS.CO", "ZEAL.CO",
    ],
    "BALTIC": [
        "LHV1T.TL", "PRF1T.TL", "TKM1T.TL", "MRK1T.TL", "ARC1T.TL",
        "TAL1T.TL", "GRG1L.VS", "APG1L.VS", "VLP1L.VS", "CPA1T.TL",
        "EEG1T.TL", "HAE1T.TL", "HPR1T.TL", "INF1T.TL", "NCN1T.TL",
        "TSM1T.TL", "SAB1L.VS", "TEL1L.VS",
    ],
}


def load_game_universe() -> dict[str, list[str]]:
    cached = _load_cache()
    if cached:
        return _ensure_provider_override_tickers(filter_unavailable_tickers(cached))

    universe = {
        "SP500": _load_sp500(),
        "OMXHLCPI": _load_nasdaq_index("OMXHLCPI", ".HE"),
        "OMXS30": _load_nasdaq_index("OMXS30", ".ST"),
        "OBX": _load_euronext_obx(),
        "OMXC25": _load_nasdaq_index("OMXC25", ".CO"),
        "BALTIC": _load_baltic_main_list(),
    }

    normalized = {
        market: _normalize_tickers(tickers)
        for market, tickers in universe.items()
    }
    normalized = _ensure_provider_override_tickers(filter_unavailable_tickers(normalized))
    _save_cache(normalized)
    logger.info(
        "Loaded game universe: %s (total %d)",
        {market: len(tickers) for market, tickers in normalized.items()},
        sum(len(tickers) for tickers in normalized.values()),
    )
    return normalized


def _load_cache() -> dict[str, list[str]] | None:
    if not os.path.exists(_CACHE_PATH):
        return None
    try:
        with open(_CACHE_PATH, "r") as f:
            data = json.load(f)
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        if datetime.now() - fetched_at > _CACHE_MAX_AGE:
            return None
        return data.get("universe")
    except Exception:
        return None


def _save_cache(universe: dict[str, list[str]]) -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(_CACHE_PATH, "w") as f:
        json.dump(
            {
                "fetched_at": datetime.now().isoformat(),
                "universe": universe,
                "sources": _SOURCE_URLS,
            },
            f,
            indent=2,
        )


def _fetch_html(url: str) -> str | None:
    try:
        resp = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 AlphaShark universe loader"},
        )
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        logger.warning("Universe source fetch failed for %s: %s", url, exc)
        return None


def _load_sp500() -> list[str]:
    html = _fetch_html(_SOURCE_URLS["SP500"])
    if not html:
        return _FALLBACK_UNIVERSE["SP500"][:]
    try:
        tables = pd.read_html(StringIO(html))
        table = next(
            tbl for tbl in tables
            if "Symbol" in tbl.columns and "Security" in tbl.columns
        )
        symbols = [str(symbol).replace(".", "-").strip().upper() for symbol in table["Symbol"].tolist()]
        return symbols or _FALLBACK_UNIVERSE["SP500"][:]
    except Exception as exc:
        logger.warning("Failed to parse S&P 500 constituents: %s", exc)
        return _FALLBACK_UNIVERSE["SP500"][:]


def _load_nasdaq_index(index_key: str, suffix: str) -> list[str]:
    html = _fetch_html(_SOURCE_URLS[index_key])
    if not html:
        return _FALLBACK_UNIVERSE[index_key][:]
    try:
        tables = pd.read_html(StringIO(html))
        for table in tables:
            normalized_columns = {str(col).strip(): col for col in table.columns}
            if "Security Symbol" in normalized_columns:
                column = normalized_columns["Security Symbol"]
                raw_symbols = [str(value).strip().upper() for value in table[column].tolist() if str(value).strip()]
                symbols = [_to_yahoo_symbol(symbol, suffix) for symbol in raw_symbols]
                if symbols:
                    return symbols
    except Exception as exc:
        logger.warning("Failed to parse %s constituents: %s", index_key, exc)
    return _FALLBACK_UNIVERSE[index_key][:]


def _load_euronext_obx() -> list[str]:
    html = _fetch_html(_SOURCE_URLS["OBX"])
    if not html:
        logger.warning("OBX HTML fetch failed, using fallback universe.")
        return _FALLBACK_UNIVERSE["OBX"][:]
    try:
        tables = pd.read_html(StringIO(html))
    except ValueError as exc:
        # live.euronext.com renders the index composition table via JavaScript — pd.read_html()
        # only parses static HTML and will always fail here.  The hardcoded fallback list is
        # updated manually each quarter when OBX composition changes.
        logger.info(
            "OBX page returned no static HTML tables (JavaScript-rendered — expected): %s. Using fallback universe.", exc
        )
        return _FALLBACK_UNIVERSE["OBX"][:]
    except Exception as exc:
        logger.warning("Failed to parse OBX constituents (unexpected error): %s", exc)
        return _FALLBACK_UNIVERSE["OBX"][:]

    for table in tables:
        cols = {str(col).strip().lower(): col for col in table.columns}
        symbol_col = None
        for key in ("symbol", "ticker", "mnemo", "instrument symbol", "isin"):
            if key in cols:
                symbol_col = cols[key]
                break
        if symbol_col is not None:
            symbols = [
                _to_yahoo_symbol(str(value).strip().upper(), ".OL")
                for value in table[symbol_col].tolist()
                if str(value).strip()
            ]
            if len(symbols) >= 10:
                return symbols
        # Fallback: try to extract OBX-like tickers from any column if not found
        for col in table.columns:
            values = table[col].astype(str).str.upper().str.strip()
            obx_like = [v for v in values if v.endswith('.OL') or v.endswith('-OL') or v.endswith(' OL')]
            if len(obx_like) >= 10:
                symbols = [_to_yahoo_symbol(v.replace(' ', '').replace('-', ''), ".OL") for v in obx_like]
                return symbols
    logger.warning("OBX table(s) found but no valid symbol column detected. Using fallback universe.")
    return _FALLBACK_UNIVERSE["OBX"][:]


def _load_baltic_main_list() -> list[str]:
    # Nasdaq Baltic page is dynamic and not reliably parseable without a browser session.
    # Use a maintained fallback list aligned with the main-list names we can source reliably.
    return _FALLBACK_UNIVERSE["BALTIC"][:]


def _to_yahoo_symbol(symbol: str, suffix: str) -> str:
    cleaned = symbol.replace(".", "-").replace("/", "-").replace(" ", "-").strip("-").upper()
    if cleaned.endswith(suffix):
        return cleaned
    return f"{cleaned}{suffix}"


def _normalize_tickers(tickers: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for ticker in tickers:
        if not ticker:
            continue
        normalized = ticker.strip().upper()
        if normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out


def _ensure_provider_override_tickers(universe: dict[str, list[str]]) -> dict[str, list[str]]:
    overrides = load_provider_overrides()
    if not overrides:
        return universe
    merged = {market: tickers[:] for market, tickers in universe.items()}
    for ticker, config in overrides.items():
        market = config.get("market")
        if not market:
            continue
        merged.setdefault(market, [])
        if ticker not in merged[market]:
            merged[market].append(ticker)
    return {market: _normalize_tickers(tickers) for market, tickers in merged.items()}
