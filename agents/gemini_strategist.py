"""
GeminiStrategist — Gemini-powered alpha generator.
Uses gemini-2.0-flash (free tier: 1,500 req/day, 1M tokens/day).
"""
import json
import logging
import math
import os
from datetime import date
from typing import Optional

import google.generativeai as genai

from agents.base_agent import BaseAgent
from config import MOMENTUM_WINDOW
from data.fetcher import MarketSnapshot
from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)

# ── Regime guidance ────────────────────────────────────────────────────────────
_REGIME_GUIDANCE = {
    "BULL": (
        "Market regime: BULL (SPX above 200d SMA by ≥2%). "
        "Be aggressive — favour high-beta names, concentrate positions, push weights toward 20-25% for top convictions."
    ),
    "BEAR": (
        "Market regime: BEAR (SPX below 200d SMA by ≥2%). "
        "Be defensive — favour low-beta, quality names; cap individual weights at 10-15%; "
        "prefer sectors with earnings visibility (healthcare, staples, utilities)."
    ),
    "NEUTRAL": (
        "Market regime: NEUTRAL (SPX near 200d SMA). "
        "Balanced approach — prefer quality momentum (high Sharpe) over raw beta; "
        "mix of growth and defensive names."
    ),
}

# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM_PROMPT_TEMPLATE = """You are AlphaShark, an elite quantitative portfolio manager competing in the Äripäev/SEB Investment Game (Estonia). Your mandate is to build a high-conviction, momentum-driven portfolio that maximises returns by game end (19 June 2026).

Today's date: {today}. The market snapshot provided below is your ONLY source of truth for current price action — do not rely on training-data knowledge of stock prices or recent news.

## Game rules you MUST follow
- Portfolio must hold between 5 and 20 different stocks.
- Each position must be allocated between 5% and 25% of the portfolio (inclusive).
- Total allocation must be ≤ 100%.
- Orders submitted before 10:00 EET execute at the same day's open price.
- Available markets: Baltic Main List, US S&P 500, OMX Helsinki Large Cap (Finland), OMX Stockholm 30 (Sweden), OBX (Norway), OMX Copenhagen 25 (Denmark).

## Investment strategy
Focus on MOMENTUM + HIGH-BETA BREAKOUT:
- Favour stocks with the strongest risk-adjusted momentum (Sharpe_20d = 20d return / annualised vol).
- High Sharpe means a smooth, persistent uptrend — much better than a volatile spike.
- Prefer high-beta names in bull-market conditions — they amplify gains.
- Concentrate in 8–12 positions; diversify across at least 2 markets to reduce single-market risk.
- Size winners higher (up to 25%); cap speculative names at 5–10%.
- Stocks near 52-week highs (pct_from_52w_high close to 0%) are breaking out — favour them.
- vs_index > 0 means the stock beat its own market — pure alpha signal.

## Market regime
{regime_guidance}

## Output format
Respond ONLY with a valid JSON object in this exact structure:

{
  "positions": [
    {
      "ticker": "TICKER",
      "weight": 0.15,
      "rationale": "One-sentence reason for inclusion and sizing."
    }
  ],
  "reasoning": "2-3 sentence portfolio-level thesis.",
  "confidence": 0.75
}

Rules:
- "weight" is a decimal fraction (0.15 = 15%).
- "confidence" is between 0.0 and 1.0.
- Weights must sum to ≤ 1.00.
- Every position weight must be ≥ 0.05 and ≤ 0.25.
- Include between 5 and 20 positions.
- No duplicate tickers.
"""


class GeminiStrategist(BaseAgent):
    MAX_RETRIES = 3
    MODEL = "gemini-2.0-flash"

    def __init__(self) -> None:
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])

    def propose(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
    ) -> PortfolioProposal:
        user_message = self._build_user_message(snapshot, prior_proposal)
        regime = snapshot.get("regime", "NEUTRAL")

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                proposal = self._call_gemini(user_message, regime)
                logger.info(
                    "Strategist produced %d positions (confidence %.0f%%)",
                    len(proposal.positions),
                    proposal.confidence * 100,
                )
                return proposal
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                logger.warning("Attempt %d/%d failed to parse response: %s", attempt, self.MAX_RETRIES, exc)
                if attempt == self.MAX_RETRIES:
                    raise RuntimeError("GeminiStrategist: exhausted retries") from exc

        raise RuntimeError("GeminiStrategist: unreachable")

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_user_message(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
    ) -> str:
        def fmt(v: float, fmt_str: str = ".1%") -> str:
            return "N/A" if math.isnan(v) else format(v, fmt_str)

        vix = snapshot.get("vix_level", float("nan"))
        spx_vs = snapshot.get("spx_vs_200d", 0.0)
        regime = snapshot.get("regime", "NEUTRAL")
        vix_str = f"{vix:.1f}" if not math.isnan(vix) else "N/A"

        header = (
            f"{'Ticker':<12} {'Market':<12} {'20d Ret':>8} {'Sharpe':>7} "
            f"{'5d Ret':>7} {'60d Ret':>8} {'RSI':>6} {'vs Idx':>8} "
            f"{'52wH%':>7} {'Beta':>6} {'Price':>10}"
        )
        lines = [
            f"Market snapshot as of {snapshot['as_of_date']}",
            f"Benchmark (S&P 500) {MOMENTUM_WINDOW}-day return: {snapshot['benchmark_return']:.1%}",
            f"Regime: {regime} | SPX vs 200d SMA: {spx_vs:.1%} | VIX: {vix_str}",
            "",
            "Top candidates (sorted by Sharpe_20d, RSI>75 filtered out):",
            "",
            header,
            "-" * len(header),
        ]

        for c in snapshot["candidates"]:
            lines.append(
                f"{c['ticker']:<12} {c['market']:<12} "
                f"{fmt(c['momentum']):>8} "
                f"{fmt(c['sharpe_20d'], '.2f'):>7} "
                f"{fmt(c['mom_5d']):>7} "
                f"{fmt(c['mom_60d']):>8} "
                f"{fmt(c['rsi_14'], '.1f'):>6} "
                f"{fmt(c['vs_index']):>8} "
                f"{fmt(c['pct_from_52w_high']):>7} "
                f"{fmt(c['beta'], '.2f'):>6} "
                f"{c['last_price']:>10.2f}"
            )

        if prior_proposal and prior_proposal.positions:
            lines += [
                "",
                "## Current holdings (from yesterday's portfolio)",
                f"{'Ticker':<12} {'Weight':>8}",
                "-" * 22,
            ]
            for pos in prior_proposal.positions:
                lines.append(f"{pos.ticker:<12} {pos.weight:>8.1%}")
            lines += [
                "",
                "When reviewing changes: prefer to HOLD winners (momentum confirmed); "
                "EXIT only if momentum has reversed or a clearly better opportunity exists. "
                "Explain key changes in your reasoning.",
            ]

        lines += [
            "",
            "Generate a portfolio from the candidates above following the game rules and "
            "strategy mandate in your system prompt. Respond ONLY with the JSON object.",
        ]
        return "\n".join(lines)

    def _call_gemini(self, user_message: str, regime: str = "NEUTRAL") -> PortfolioProposal:
        regime_guidance = _REGIME_GUIDANCE.get(regime, _REGIME_GUIDANCE["NEUTRAL"])
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            today=date.today().isoformat(),
            regime_guidance=regime_guidance,
        )

        model = genai.GenerativeModel(
            model_name=self.MODEL,
            system_instruction=system_prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.7,
            ),
        )

        response = model.generate_content(user_message)
        raw_text = response.text.strip()

        # Strip accidental markdown fences just in case
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        data = json.loads(raw_text)

        positions = [
            Position(
                ticker=p["ticker"],
                weight=float(p["weight"]),
                rationale=p.get("rationale", ""),
            )
            for p in data["positions"]
        ]
        return PortfolioProposal(
            positions=positions,
            reasoning=data.get("reasoning", ""),
            confidence=float(data.get("confidence", 0.5)),
        )
