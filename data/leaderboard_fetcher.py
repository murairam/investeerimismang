"""Manual-link competitor snapshot fetcher for public game profile pages.

This module intentionally avoids broad crawling. It only fetches pages from an
explicitly provided list of profile URLs (manual watchlist) and extracts concise
portfolio signals for strategy context.
"""

from __future__ import annotations

import html
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)


_RANK_RE = re.compile(r"(\d+)\.\s*koht\s*(\d+)\s*m[äa]ngija\s*hulgas", re.IGNORECASE)
_VALUE_RE = re.compile(r"V[äa]rtus\s*([\d\s]+)\s*EUR", re.IGNORECASE)
_RETURNS_RE = re.compile(
    r"T[äa]na\s*([−\-]?\d+,\d+)%\s*N[äa]dal\s*([−\-]?\d+,\d+)%\s*Kuu\s*([−\-]?\d+,\d+)%",
    re.IGNORECASE,
)
_HOLDINGS_TOTAL_RE = re.compile(r"1\s*-\s*5\s*(\d+)-st")
_HOLDING_RE = re.compile(
    r"(\d{1,3})%\s*([^%]+?)\s*Aktsiad\s*T[äa]na\s*([−\-]?\d+,\d+)%",
    re.IGNORECASE,
)

_MAX_TEXT = 80_000
_REQUEST_TIMEOUT = 12
_REQUEST_SLEEP_SEC = 2.5
_MAX_RETRIES = 3
_MAX_URLS_PER_RUN = 15
_ALLOWED_HOSTS = {"www.aripaev.ee", "aripaev.ee"}


@dataclass(frozen=True)
class HoldingView:
    name: str
    weight_pct: float
    today_return_pct: float


@dataclass(frozen=True)
class CompetitorSnapshot:
    url: str
    portfolio_name: str
    rank: int | None
    total_players: int | None
    value_eur: float | None
    today_return_pct: float | None
    week_return_pct: float | None
    month_return_pct: float | None
    visible_holdings: list[HoldingView]
    holdings_total_count: int | None


def _safe_float(value: str) -> float | None:
    if not value:
        return None
    normalized = value.replace("−", "-").replace(" ", "").replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def _normalize_text(raw_html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", raw_html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_MAX_TEXT]


def _extract_portfolio_name(text: str) -> str:
    match = re.search(r"([A-Za-z0-9ÕÄÖÜõäöü ._\-]{2,60})\s+\d+\.\s*koht", text)
    if match:
        return match.group(1).strip()
    return "unknown"


def _parse_holdings(text: str) -> list[HoldingView]:
    holdings: list[HoldingView] = []
    for weight_str, name_raw, ret_str in _HOLDING_RE.findall(text):
        weight = _safe_float(weight_str)
        today_ret = _safe_float(ret_str)
        name = re.sub(r"\s+", " ", name_raw).strip(" -")
        if weight is None or today_ret is None or not name:
            continue
        holdings.append(HoldingView(name=name, weight_pct=weight, today_return_pct=today_ret))
    return holdings


def _fetch_text(url: str, session: requests.Session) -> str:
    delay = _REQUEST_SLEEP_SEC
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            response = session.get(url, timeout=_REQUEST_TIMEOUT)
            if response.status_code in (429, 502, 503, 504):
                raise requests.HTTPError(f"Transient status {response.status_code}")
            response.raise_for_status()
            return _normalize_text(response.text)
        except Exception as exc:
            last_exc = exc
            if attempt >= _MAX_RETRIES - 1:
                break
            jitter = random.uniform(0.2, 0.8)
            time.sleep(delay + jitter)
            delay *= 1.8
    assert last_exc is not None
    raise last_exc


def _is_allowed_profile_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        if parsed.netloc.lower() not in _ALLOWED_HOSTS:
            return False
        return "/investeerimismang/mangija/" in parsed.path
    except Exception:
        return False


def fetch_competitor_snapshots(profile_urls: list[str]) -> list[CompetitorSnapshot]:
    """Fetch snapshots from explicitly provided public profile links.

    Args:
        profile_urls: Manual list of URLs to fetch.

    Returns:
        Parsed competitor snapshots; invalid/unreachable pages are skipped.
    """
    filtered_urls = [url for url in profile_urls if _is_allowed_profile_url(url)]
    deduped_urls = list(dict.fromkeys(filtered_urls))[:_MAX_URLS_PER_RUN]
    snapshots: list[CompetitorSnapshot] = []

    with requests.Session() as session:
        session.headers.update({"User-Agent": "AlphaShark/1.0 (manual competitor snapshot)"})

        for index, url in enumerate(deduped_urls):
            try:
                text = _fetch_text(url, session)
                rank_match = _RANK_RE.search(text)
                value_match = _VALUE_RE.search(text)
                returns_match = _RETURNS_RE.search(text)
                holdings_count_match = _HOLDINGS_TOTAL_RE.search(text)

                visible_holdings = _parse_holdings(text)
                snapshot = CompetitorSnapshot(
                    url=url,
                    portfolio_name=_extract_portfolio_name(text),
                    rank=int(rank_match.group(1)) if rank_match else None,
                    total_players=int(rank_match.group(2)) if rank_match else None,
                    value_eur=_safe_float(value_match.group(1)) if value_match else None,
                    today_return_pct=_safe_float(returns_match.group(1)) if returns_match else None,
                    week_return_pct=_safe_float(returns_match.group(2)) if returns_match else None,
                    month_return_pct=_safe_float(returns_match.group(3)) if returns_match else None,
                    visible_holdings=visible_holdings,
                    holdings_total_count=int(holdings_count_match.group(1)) if holdings_count_match else None,
                )
                snapshots.append(snapshot)
            except Exception as exc:
                logger.warning("Competitor snapshot skipped for %s: %s", url, exc)

            if index < len(deduped_urls) - 1:
                time.sleep(_REQUEST_SLEEP_SEC + random.uniform(0.2, 0.6))

    return snapshots


def summarize_crowding(snapshots: list[CompetitorSnapshot]) -> dict[str, object]:
    """Build simple crowding stats from parsed snapshots."""
    ticker_counts: dict[str, int] = {}
    holdings_counts: list[int] = []
    concentrated = 0

    for snapshot in snapshots:
        if snapshot.holdings_total_count is not None:
            holdings_counts.append(snapshot.holdings_total_count)

        heavy_count = sum(1 for item in snapshot.visible_holdings if item.weight_pct >= 20)
        if heavy_count >= 4:
            concentrated += 1

        for item in snapshot.visible_holdings:
            ticker_counts[item.name] = ticker_counts.get(item.name, 0) + 1

    repeated = sorted(
        ((name, count) for name, count in ticker_counts.items() if count >= 2),
        key=lambda pair: (-pair[1], pair[0]),
    )

    avg_holdings = (sum(holdings_counts) / len(holdings_counts)) if holdings_counts else None

    return {
        "snapshots": len(snapshots),
        "avg_holdings_count": avg_holdings,
        "concentrated_portfolios": concentrated,
        "repeated_names": repeated,
    }


def _fmt_rank(snapshot: CompetitorSnapshot) -> str:
    if snapshot.rank is None:
        return "n/a"
    return f"#{snapshot.rank}"


def _fmt_value(snapshot: CompetitorSnapshot) -> str:
    if snapshot.value_eur is None:
        return "n/a"
    return f"{snapshot.value_eur:,.0f} EUR".replace(",", " ")


def _has_meaningful_snapshot_data(snapshots: list[CompetitorSnapshot]) -> bool:
    return any(
        (snap.rank is not None)
        or (snap.value_eur is not None)
        or bool(snap.visible_holdings)
        or (snap.holdings_total_count is not None)
        for snap in snapshots
    )


def _compose_competitor_intel_markdown(
    profile_urls: list[str],
    snapshots: list[CompetitorSnapshot],
    as_of: str | None = None,
) -> str:
    crowd = summarize_crowding(snapshots)
    as_of_str = as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines: list[str] = [
        "# Competitor Intelligence Snapshot",
        "",
        f"Date: {as_of_str}",
        "Source: manual public profile links (respectful rate-limited fetch)",
        "",
        "## Watchlist",
    ]

    for url in list(dict.fromkeys(profile_urls))[:_MAX_URLS_PER_RUN]:
        lines.append(f"- {url}")

    lines.extend(["", "## Parsed snapshots"]) 
    for snap in sorted(snapshots, key=lambda item: (item.rank or 999999, -(item.value_eur or 0.0))):
        lines.append(f"- {_fmt_rank(snap)} {snap.portfolio_name} — {_fmt_value(snap)}")

    lines.extend(["", "## Crowding / structure"])
    avg_holdings = crowd.get("avg_holdings_count")
    if isinstance(avg_holdings, (int, float)):
        lines.append(f"- Average holdings count: {avg_holdings:.1f}")
    lines.append(f"- Concentrated portfolios (>=4 visible positions with >=20% weight): {crowd.get('concentrated_portfolios', 0)}")

    repeated = crowd.get("repeated_names", [])
    if repeated:
        joined = ", ".join(f"{name} ({count})" for name, count in repeated[:10])
        lines.append(f"- Repeated visible names: {joined}")
    else:
        lines.append("- Repeated visible names: none")

    lines.extend([
        "",
        "## Usage note",
        "- This file is generated from a manual watchlist only; do not expand to broad crawling.",
        "- Keep request rates low and update no more than needed for daily decision support.",
    ])

    return "\n".join(lines) + "\n"


def build_competitor_intel_markdown(profile_urls: list[str], as_of: str | None = None) -> str:
    snapshots = fetch_competitor_snapshots(profile_urls)
    return _compose_competitor_intel_markdown(profile_urls, snapshots, as_of=as_of)


def refresh_competitor_intel_file(
    profile_urls: list[str],
    output_path: str,
    min_refresh_hours: float = 12.0,
    force: bool = False,
) -> bool:
    """Refresh competitor intel markdown if stale.

    Returns True if file was written, False if skipped due to freshness.
    """
    abs_path = os.path.abspath(output_path)
    if (not force) and os.path.exists(abs_path):
        age_seconds = time.time() - os.path.getmtime(abs_path)
        if age_seconds < max(0.0, min_refresh_hours) * 3600:
            return False

    snapshots = fetch_competitor_snapshots(profile_urls)
    if not _has_meaningful_snapshot_data(snapshots):
        logger.warning(
            "Competitor intel refresh returned no parseable portfolio data; keeping existing file: %s",
            abs_path,
        )
        return False

    markdown = _compose_competitor_intel_markdown(profile_urls, snapshots)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as handle:
        handle.write(markdown)
    return True
