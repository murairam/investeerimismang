"""Fetches global macro intelligence from a local worldmonitor instance."""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

_WORLDMONITOR_BRIEFS_URL = "http://localhost:5173/api/services/finance/briefs"
_WORLDMONITOR_BRIEFS_URL_ALT = "http://localhost:3000/api/services/finance/briefs"
_WORLDMONITOR_REGION_IDS = [
    "europe",
    "north-america",
    "east-asia",
    "mena",
    "south-asia",
    "latam",
    "sub-saharan-africa",
]


def _parse_macro_payload(payload: object) -> str:
    """Extract macro context from supported worldmonitor payload shapes."""
    if not isinstance(payload, dict):
        return ""

    synthesis = payload.get("synthesis")
    if isinstance(synthesis, str) and synthesis.strip():
        return synthesis.strip()

    brief = payload.get("brief")
    if isinstance(brief, str) and brief.strip():
        return brief.strip()

    if isinstance(brief, dict):
        parts: list[str] = []
        recap = brief.get("situationRecap")
        if isinstance(recap, str) and recap.strip():
            parts.append(recap.strip())

        trajectory = brief.get("regimeTrajectory")
        if isinstance(trajectory, str) and trajectory.strip():
            parts.append(f"Regime trajectory: {trajectory.strip()}")

        developments = brief.get("keyDevelopments")
        if isinstance(developments, list):
            bullets = [d.strip() for d in developments if isinstance(d, str) and d.strip()]
            if bullets:
                parts.append("Key developments: " + "; ".join(bullets[:5]))

        outlook = brief.get("riskOutlook")
        if isinstance(outlook, str) and outlook.strip():
            parts.append(f"Risk outlook: {outlook.strip()}")

        return "\n".join(parts)

    return ""


def fetch_macro_intelligence(timeout: int = 5) -> str:
    """
    Fetch AI-generated macro brief from local worldmonitor.

    Returns a formatted block for prompt injection or an empty string when
    unavailable. Any network/JSON parsing errors are swallowed so callers can
    continue without interruption.
    """
    env_url = os.environ.get("WORLDMONITOR_BRIEFS_URL", "").strip()
    regional_urls = [
        f"http://localhost:3000/api/intelligence/v1/get-regional-brief?region_id={region_id}"
        for region_id in _WORLDMONITOR_REGION_IDS
    ]
    urls = [
        u for u in [env_url, _WORLDMONITOR_BRIEFS_URL, _WORLDMONITOR_BRIEFS_URL_ALT, *regional_urls]
        if u
    ]

    for url in urls:
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            payload = response.json()

            # Some worldmonitor endpoints can return a clean outage signal.
            if isinstance(payload, dict) and payload.get("upstreamUnavailable") is True:
                logger.debug("Macro endpoint upstream unavailable: %s", url)
                continue

            synthesis = _parse_macro_payload(payload)
            if synthesis:
                return f"GLOBAL MACRO CONTEXT:\n{synthesis}"

            logger.debug("Macro endpoint returned no usable synthesis: %s", url)

        except requests.Timeout:
            logger.debug("Macro intelligence fetch timed out: %s", url)
        except requests.ConnectionError:
            logger.debug("Macro intelligence service unavailable: %s", url)
        except requests.RequestException as exc:
            logger.debug("Macro intelligence request failed (%s): %s", url, exc)
        except ValueError as exc:
            logger.debug("Macro intelligence response is not valid JSON (%s): %s", url, exc)

    return ""


def fetch_global_risk_metrics(timeout: int = 2) -> str:
    """
    Fetch quantitative global risk gauges from local worldmonitor.

    Safety-critical behavior: never raise exceptions to callers. Any failure
    returns an empty string so the main pipeline can continue.
    """
    env_url = os.environ.get("WORLDMONITOR_RISK_METRICS_URL", "").strip()
    urls = [
        u for u in [
            env_url,
            "http://localhost:5173/api/services/finance/metrics",
            "http://localhost:3000/api/services/finance/metrics",
        ] if u
    ]

    payload: dict = {}
    for url in urls:
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                payload = data
                break
        except requests.Timeout:
            logger.debug("Risk metrics fetch timed out: %s", url)
        except requests.ConnectionError:
            logger.debug("Risk metrics service unavailable: %s", url)
        except requests.RequestException as exc:
            logger.debug("Risk metrics request failed (%s): %s", url, exc)
        except ValueError as exc:
            logger.debug("Risk metrics response is not valid JSON (%s): %s", url, exc)

    if not payload:
        logger.warning("WorldMonitor risk metrics unavailable, skipping...")
        return ""

    try:
        vix = payload.get("vix", payload.get("vix_level", "N/A"))
        market_health = payload.get("market_health", payload.get("regime", "N/A"))
        market_stress = payload.get("market_stress", payload.get("stress_level", "N/A"))
        breadth = payload.get("breadth", payload.get("breadth_pct", "N/A"))

        lines = [
            "GLOBAL RISK GAUGES:",
            f"- VIX: {vix}",
            f"- Market Health: {market_health}",
            f"- Market Stress: {market_stress}",
            f"- Breadth: {breadth}",
        ]
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Error parsing risk metrics: %s", e)
        return ""
