"""
GeminiChallenger — independent second opinion from Gemini 2.0 Flash (free tier).

Runs in parallel with OpenAIStrategist. Proposes a portfolio from the same
signal data but with a completely different model — different training, different
biases, different interpretation of momentum.

Stocks appearing in BOTH proposals have been independently validated
and should receive higher conviction weights in the final portfolio.

Free tier: 1,500 requests/day, 1M tokens/day — no cost.
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

_REGIME_GUIDANCE = {
    "BULL": (
        "Market regime: BULL (SPX above 200d SMA by ≥2%). "
        "Be aggressive — favour high-beta names, push top convictions to 20-25%."
    ),
    "BEAR": (
        "Market regime: BEAR (SPX below 200d SMA by ≥2%). "
        "Be defensive — lower beta, quality earnings visibility, cap weights at 15%."
    ),
    "NEUTRAL": (
        "Market regime: NEUTRAL. "
        "Prefer high Sharpe over raw beta. Mix of growth and quality."
    ),
}

_SYSTEM_PROMPT = """You are an independent quantitative analyst providing a second opinion on a portfolio for the Äripäev/SEB Investment Game (Estonia). Game ends 19 June 2026. Goal: highest absolute return, beating other participants.

Today: {today}.

IMPORTANT: You are providing an INDEPENDENT view. Do not try to match or second-guess any other analyst. Build the best portfolio YOU think is correct based purely on the data provided.

## Game rules
- 5 to 20 stocks.
- Each position: 5% to 25%.
- Total weight: ≤ 100%.
- Markets: US S&P 500, OMX Helsinki (Finland), OMX Stockholm (Sweden), OBX (Norway), OMX Copenhagen (Denmark), Baltic Main List.

## Strategy
- Rank primarily by Sharpe_20d (momentum / volatility) — smooth uptrends beat volatile spikes.
- vs_index > 0 = stock beat its market = pure alpha.
- pct_from_52w_high near 0% = breakout signal.
- Target 8–12 positions across at least 2 markets.
- {regime_guidance}

## Sizing — MANDATORY
Size by conviction. DO NOT equal-weight.
- Best picks: 20–25%
- Good picks: 12–18%
- Diversifiers: 5–10%
Every position must have a weight that reflects conviction. Identical weights are not allowed.

## Output — JSON only
{{
  "positions": [
    {{
      "ticker": "TICKER",
      "weight": 0.20,
      "rationale": "Why this ticker at this exact weight."
    }}
  ],
  "reasoning": "Your independent thesis in 2–3 sentences.",
  "confidence": 0.80
}}"""


class GeminiChallenger(BaseAgent):
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
                    "Challenger produced %d positions (confidence %.0f%%)",
                    len(proposal.positions),
                    proposal.confidence * 100,
                )
                return proposal
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                logger.warning("Challenger attempt %d/%d failed: %s", attempt, self.MAX_RETRIES, exc)
                if attempt == self.MAX_RETRIES:
                    logger.warning("Challenger exhausted retries — will proceed without challenger input")
                    return PortfolioProposal()  # empty = skip challenger gracefully

        return PortfolioProposal()

    def _build_user_message(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
    ) -> str:
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
            f"S&P 500 {MOMENTUM_WINDOW}-day return: {snapshot['benchmark_return']:.1%}",
            f"Regime: {regime} | SPX vs 200d SMA: {spx_vs:.1%} | VIX: {vix_str}",
            "",
            "Candidates (sorted by Sharpe_20d):",
            "",
            header,
            "-" * len(header),
        ]

        for c in snapshot["candidates"]:
            def fmt(v: float, fmt_str: str = ".1%") -> str:
                return "N/A" if math.isnan(v) else format(v, fmt_str)

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
            lines += ["", "## Yesterday's holdings (for continuity reference)"]
            for pos in prior_proposal.positions:
                lines.append(f"  {pos.ticker:<12} {pos.weight:.1%}")

        lines += ["", "Build your independent portfolio. JSON only."]
        return "\n".join(lines)

    def _call_gemini(self, user_message: str, regime: str = "NEUTRAL") -> PortfolioProposal:
        regime_guidance = _REGIME_GUIDANCE.get(regime, _REGIME_GUIDANCE["NEUTRAL"])
        system_prompt = _SYSTEM_PROMPT.format(
            today=date.today().isoformat(),
            regime_guidance=regime_guidance,
        )

        model = genai.GenerativeModel(
            model_name=self.MODEL,
            system_instruction=system_prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.8,  # slightly higher than strategist for diverse picks
            ),
        )

        response = model.generate_content(user_message)
        raw_text = response.text.strip()

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
