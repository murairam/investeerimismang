"""
GeminiDevil — Devil's advocate pressure-tester (free Gemini tier).

Receives the merged strategist + challenger proposals and argues AGAINST
each top pick. Forces the Risk Manager to confront the bear case before
committing to a weight.

Free tier: runs on gemini-2.0-flash, same quota as the Challenger.
Cost: $0.00 per run.
"""
import json
import logging
import math
import os
import time
from typing import Optional

from google import genai
from google.genai import types

from data.fetcher import MarketSnapshot
from portfolio.models import PortfolioProposal

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a BEAR-CASE analyst. Your ONLY job is to find reasons why each stock pick might FAIL or UNDERPERFORM.

You are NOT building a portfolio. You are stress-testing someone else's picks.

For each ticker provided, give:
1. The single strongest bear case (1-2 sentences max)
2. A risk level: HIGH, MEDIUM, or LOW

Be specific — cite the actual signal data (momentum, RSI, vol_ratio, beta, pct_from_52w_high) to justify your bear case.

Examples of good bear cases:
- "RSI at 71 — approaching overbought; the 20d run may already be priced in. Vol_ratio 0.6 suggests low conviction."
- "Beta 1.8 in NEUTRAL regime — high sensitivity to any market reversal. Mom_60d negative (-4%) shows longer-term weakness."
- "Near 52-week high (+0.2%) with no earnings catalyst — limited upside from here, asymmetric downside."

Bad bear cases (too vague, not useful):
- "Market conditions could change" — no, cite specific numbers
- "Risky investment" — not helpful

Output ONLY valid JSON, no other text:
{"bears": [{"ticker": "X", "bear_case": "...", "risk": "HIGH|MEDIUM|LOW"}, ...]}"""


class GeminiDevil:
    MODEL = "gemini-2.0-flash"
    MAX_RETRIES = 1

    def __init__(self) -> None:
        self._gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    def challenge(
        self,
        strategist: PortfolioProposal,
        challenger: PortfolioProposal,
        snapshot: MarketSnapshot,
    ) -> dict[str, dict]:
        """
        Returns {ticker: {"bear_case": str, "risk": "HIGH|MEDIUM|LOW"}}
        for the union of top picks from both proposals.
        Returns empty dict on failure (non-fatal).
        """
        # Collect unique tickers from both proposals, ranked by weight
        seen: dict[str, float] = {}
        for p in strategist.positions:
            seen[p.ticker] = seen.get(p.ticker, 0.0) + p.weight
        for p in (challenger.positions or []):
            seen[p.ticker] = seen.get(p.ticker, 0.0) + p.weight

        # Take the top picks by combined weight — these are the ones worth challenging
        top_tickers = sorted(seen, key=lambda t: -seen[t])[:12]

        if not top_tickers:
            return {}

        user_message = self._build_message(top_tickers, snapshot)

        for attempt in range(1, self.MAX_RETRIES + 2):
            try:
                result = self._call_gemini(user_message)
                logger.info(
                    "Devil's advocate challenged %d picks: %d HIGH, %d MEDIUM, %d LOW risk",
                    len(result),
                    sum(1 for v in result.values() if v["risk"] == "HIGH"),
                    sum(1 for v in result.values() if v["risk"] == "MEDIUM"),
                    sum(1 for v in result.values() if v["risk"] == "LOW"),
                )
                return result
            except Exception as exc:
                logger.warning("Devil's advocate attempt %d failed: %s", attempt, type(exc).__name__)
                if attempt <= self.MAX_RETRIES:
                    time.sleep(2)

        logger.info("Devil's advocate unavailable — Risk Manager will proceed without bear cases")
        return {}

    def _build_message(self, tickers: list[str], snapshot: MarketSnapshot) -> str:
        # Build a compact signal table for just these tickers
        signal_map = {c["ticker"]: c for c in snapshot["candidates"]}

        lines = [
            f"Stress-test these {len(tickers)} picks. Give the bear case for each.",
            "",
            f"{'Ticker':<12} {'20d Ret':>8} {'Sharpe':>7} {'RSI':>6} {'vs Idx':>8} "
            f"{'52wH%':>7} {'Beta':>6} {'VolR':>6} {'Mom5d':>7}",
            "-" * 75,
        ]

        def fmt(v: float, f: str = ".1%") -> str:
            return "N/A" if math.isnan(v) else format(v, f)

        for ticker in tickers:
            c = signal_map.get(ticker)
            if c:
                lines.append(
                    f"{ticker:<12} {fmt(c['momentum']):>8} {fmt(c['sharpe_20d'], '.2f'):>7} "
                    f"{fmt(c['rsi_14'], '.1f'):>6} {fmt(c['vs_index']):>8} "
                    f"{fmt(c['pct_from_52w_high']):>7} {fmt(c['beta'], '.2f'):>6} "
                    f"{fmt(c['vol_ratio'], '.2f'):>6} {fmt(c['mom_5d']):>7}"
                )
            else:
                lines.append(f"{ticker:<12} (not in today's candidate list)")

        lines += ["", "For each ticker, give the strongest reason it might FAIL. Cite the numbers."]
        return "\n".join(lines)

    def _call_gemini(self, user_message: str) -> dict[str, dict]:
        response = self._gemini.models.generate_content(
            model=self.MODEL,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )

        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        data = json.loads(raw)
        bears = data.get("bears", data) if isinstance(data, dict) else data

        return {
            item["ticker"]: {
                "bear_case": item.get("bear_case", ""),
                "risk": item.get("risk", "MEDIUM").upper(),
            }
            for item in (bears if isinstance(bears, list) else [])
            if "ticker" in item
        }
