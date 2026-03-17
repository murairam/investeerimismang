"""
GeminiChallenger — independent second opinion from Gemini 2.0 Flash (free tier).

If Gemini is unavailable (quota exceeded, API error), the challenger returns
an empty proposal and the pipeline continues with the strategist output only.

Free tier: 1,500 requests/day — resets daily at midnight Pacific time.
"""
import json
import logging
import math
import os
import time
from datetime import date
from typing import Optional

from google import genai
from google.genai import types
from openai import OpenAI

from agents.base_agent import BaseAgent
from config import MOMENTUM_WINDOW
from data.fetcher import MarketSnapshot
from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)

_REGIME_GUIDANCE = {
    "BULL": "BULL regime — even as a contrarian, acknowledge the trend; but look for LAGGARDS within the bull market that haven't yet moved (low mom_20d but recovering RSI, positive vs_index just turning positive).",
    "BEAR": "BEAR regime — be contrarian and defensive. Hunt for stocks that are ALREADY bottoming: RSI between 30–45 and rising, positive vs_index despite the downturn, near 52w low not 52w high.",
    "NEUTRAL": "NEUTRAL regime — pure contrarian play. Avoid the obvious top-Sharpe names. Find hidden gems: mid-Sharpe stocks with improving 5d momentum that haven't been bid up yet.",
}

_SYSTEM_PROMPT = """You are a CONTRARIAN quantitative analyst for the Äripäev/SEB Investment Game (Estonia). Game ends 19 June 2026. Goal: highest absolute return by DISAGREEING with the consensus momentum crowd.

Today: {today}. Your role is to find stocks that other momentum-following participants are IGNORING or UNDERWEIGHTING.

## Your mandate — be different
In a competition, everyone runs the same momentum screen. You MUST differentiate:
- Avoid names that are obvious top-Sharpe leaders (they are already crowded).
- Prefer stocks with RECOVERING momentum: RSI between 30–55, mom_5d > mom_20d (accelerating), vs_index just turned positive.
- Look for breakouts that haven't happened yet: pct_from_52w_high between -10% and -2% (approaching but not yet at high).
- Favour markets and sectors that are out of favour but showing early rotation signs.

## Game rules
- 5 to 20 stocks. Each position: 5%–25%. Total weight: ≤100%. No duplicates.
- Markets: US S&P 500, OMX Helsinki, OMX Stockholm, OBX Norway, OMX Copenhagen, Baltic.
- Regime-based position count target: BULL 6–8, NEUTRAL 8–10, BEAR 10–12.

## Regime context
{regime_guidance}

## Sizing — MANDATORY, NO EQUAL-WEIGHTING
- Highest conviction contrarian picks: 18–25%
- Good recovering momentum picks: 12–18%
- Speculative diversifiers: 5–10%
Every position must have a different weight. Equal-weighting means you are not thinking.

## What to AVOID
- Do NOT pick the top-3 stocks by Sharpe_20d — those are the crowded consensus trades.
- Do NOT fill the portfolio with US mega-cap tech if they dominate the Sharpe ranking.
- At least 3 of your picks must be from non-US markets.

## Output — valid JSON only, no other text
{{"positions":[{{"ticker":"X","weight":0.20,"rationale":"why this contrarian pick at this weight"}}],"reasoning":"2-3 sentence contrarian thesis — what the crowd is missing","confidence":0.80}}"""


class GeminiChallenger(BaseAgent):
    MAX_RETRIES = 2
    MODEL = "gemini-2.0-flash"

    def __init__(self) -> None:
        self._gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self._openai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

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
                    "Challenger (Gemini) produced %d positions (confidence %.0f%%)",
                    len(proposal.positions),
                    proposal.confidence * 100,
                )
                return proposal
            except Exception as exc:
                logger.warning(
                    "Gemini challenger attempt %d/%d failed: %s",
                    attempt, self.MAX_RETRIES, type(exc).__name__
                )
                if attempt < self.MAX_RETRIES:
                    sleep_time = 2**attempt
                    logger.info("Retrying in %d seconds …", sleep_time)
                    time.sleep(sleep_time)

        # Fallback: use gpt-4o-mini as challenger with higher temperature for diverse picks
        logger.info("Gemini unavailable — falling back to OpenAI challenger (gpt-4o-mini) …")
        try:
            proposal = self._call_openai_fallback(user_message, regime)
            logger.info(
                "Challenger (OpenAI fallback) produced %d positions (confidence %.0f%%)",
                len(proposal.positions),
                proposal.confidence * 100,
            )
            return proposal
        except Exception as exc:
            logger.warning("OpenAI fallback challenger also failed: %s", exc)
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
            f"{'52wH%':>7} {'Beta':>6} {'VolRatio':>9} {'Price':>10}"
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

        def fmt(v: float, fmt_str: str = ".1%") -> str:
            return "N/A" if math.isnan(v) else format(v, fmt_str)

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
                f"{fmt(c['vol_ratio'], '.2f'):>9} "
                f"{c['last_price']:>10.2f}"
            )

        if prior_proposal and prior_proposal.positions:
            lines += ["", "Yesterday's holdings (for continuity reference):"]
            for pos in prior_proposal.positions:
                lines.append(f"  {pos.ticker:<12} {pos.weight:.1%}")

        if snapshot.get("learning_context"):
            lines += ["", snapshot["learning_context"]]

        if snapshot.get("news_headlines"):
            lines += ["", snapshot["news_headlines"]]

        lines += ["", "Build your independent portfolio. Return valid JSON only."]
        return "\n".join(lines)

    def _call_openai_fallback(self, user_message: str, regime: str = "NEUTRAL") -> PortfolioProposal:
        """GPT-4o-mini as challenger fallback. Higher temperature = more diverse picks."""
        regime_guidance = _REGIME_GUIDANCE.get(regime, _REGIME_GUIDANCE["NEUTRAL"])
        system_prompt = _SYSTEM_PROMPT.format(
            today=date.today().isoformat(),
            regime_guidance=regime_guidance,
        )
        response = self._openai.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            temperature=1.0,  # high temp = diverse from the main GPT-4o strategist
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)

        # Handle both {"positions": [...]} and bare [...] responses
        raw_positions = data if isinstance(data, list) else data["positions"]
        if any(float(p["weight"]) > 1.0 for p in raw_positions):
            for p in raw_positions:
                p["weight"] = float(p["weight"]) / 100.0

        positions = [
            Position(
                ticker=p["ticker"],
                weight=float(p["weight"]),
                rationale=p.get("rationale", ""),
            )
            for p in raw_positions
        ]
        return PortfolioProposal(
            positions=positions,
            reasoning=data.get("reasoning", ""),
            confidence=float(data.get("confidence", 0.5)),
        )

    def _call_gemini(self, user_message: str, regime: str = "NEUTRAL") -> PortfolioProposal:
        regime_guidance = _REGIME_GUIDANCE.get(regime, _REGIME_GUIDANCE["NEUTRAL"])
        system_prompt = _SYSTEM_PROMPT.format(
            today=date.today().isoformat(),
            regime_guidance=regime_guidance,
        )

        response = self._gemini.models.generate_content(
            model=self.MODEL,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                temperature=0.8,
            ),
        )

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
