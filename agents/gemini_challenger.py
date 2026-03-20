"""
GeminiChallenger — Catalyst Hunter (Gemini 2.5 Flash, free tier).

Independent second opinion focused on explosive near-term catalysts:
short squeeze setups, premarket gap-ups, IV spikes, vol_ratio breakouts.
Signal table shows CATALYST signals only (vol_ratio, RSI, short interest,
premarket gap, IV, ATR%, dividend yield) — complementing the momentum-only
Strategist for genuine signal divergence.

Free tier: 250 req/day — zero cost to the project.
Model: gemini-2.5-flash (best free model as of March 2026).
SDK: google-genai (replaces deprecated google.generativeai).
"""
import json
import logging
import math
import os
from datetime import date
from typing import Optional

from google import genai
from google.genai import types
from openai import OpenAI

from agents.base_agent import BaseAgent
from data.cost_tracker import log_usage
from data.fetcher import MarketSnapshot
from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)

_GROQ_MODEL = "llama-3.3-70b-versatile"

_REGIME_GUIDANCE = {
    "BULL": "BULL regime — 5-8 catalyst plays. Vol_ratio > 1.5 + RSI > 75 = ideal breakout setup. Size by conviction (20-25% for top picks).",
    "BEAR": "BEAR regime — 6-12 positions. Hunt catalysts with low correlation to broad market. Cap each at 15%.",
    "NEUTRAL": "NEUTRAL regime — 5-10 catalyst picks. Include a pick only if you have genuine conviction in its setup.",
}

_SYSTEM_PROMPT_BASE = """You are a CATALYST HUNTER for the Aripäev/SEB Investment Game (Estonia). Game ends 19 June 2026. Goal: highest absolute return by finding stocks with explosive near-term catalysts.

Today: TODAY_DATE. Your role is to identify high-momentum breakout candidates using catalyst signals.

You are a SECOND OPINION to a separate Momentum Strategist who sees trend/Sharpe signals. Your value is finding catalyst-driven opportunities — vol_ratio breakouts, short squeezes, premarket gap-ups, IV spikes — that a pure Sharpe ranker might miss. Mirroring a generic momentum portfolio is failure.

## Your mandate — find explosive setups
- Vol_ratio breakouts: vol_ratio > 1.5 = high-volume confirmation. RSI > 75 + vol_ratio > 1.5 = parabolic breakout in progress. CONFIRM these, do not avoid them.
- Short squeeze candidates: short_interest > 15% + positive momentum + vol_ratio > 1.5 = prime squeeze setup.
- Premarket gap-ups: positive premarket_gap = opening momentum confirmation — early movers beat the crowd.
- IV spike + momentum: iv_proxy spike = event-driven expectation — combine with RSI > 60 for confirmation.
- ATR%: high ATR% = volatile, active mover. Combine with positive RSI and vol_ratio for sizing decisions.
- Dividend yield edge: Baltic/Nordic stocks with 3-6% yield earn free return via auto-reinvestment. Factor into close-call decisions.

## Game rules
- 5 to 20 stocks. Each position: 5%-25%. Total weight: <=100%. No duplicates.
- Markets: US S&P 500, OMX Helsinki, OMX Stockholm, OBX Norway, OMX Copenhagen, Baltic.
- Regime-based position count: REGIME_GUIDANCE

## Signal guidance
- RSI > 75 with vol_ratio > 1.5 = confirmed breakout (bullish). RSI > 82 AND pct_from_52w_high ≥ -2% AND vol_ratio < 1.8 = exhaustion not breakout — cap at 15%.
- vol_ratio > 1.5: move confirmed by volume — strong buy signal. vol_ratio > 1.8 overrides the exhaustion warning.
- pct_from_52w_high is ALWAYS <= 0%. 0.0% = AT 52-week high. Bullish only when vol_ratio confirms. Without volume, at-peak = no pullback cushion.
- ShortInt = short % of float (N/A for Baltic/Nordic — no options chain, not a penalty).
- PreMktGap = gap vs prior close. Positive = opening momentum.
- IV = implied vol from options (US) or 20d annualized realized vol (non-US fallback). Same unit.
- Do NOT penalize non-US stocks for N/A short interest or IV — evaluate on volume breakouts and RSI.

## Baltic market guidance
Baltic stocks are underrepresented in competitor portfolios — genuine edge:
- Most liquid: LHV1T.TL (banking), TAL1T.TL (tech/growth)
- Dividend edge: 3-6% yields — game auto-reinvests, generating free return

## Sizing — MANDATORY
- Highest conviction catalyst picks: 20-25%
- Strong signals, confirmed breakout: 15-20%
- Speculative catalyst: 5-10%
Every position must have a different weight.

## What to AVOID
- Do NOT fill the portfolio with US mega-cap names just because they are large.
- At least 2 picks from non-US markets (unless US catalyst setups are overwhelmingly superior).
- Do NOT simply choose the top Sharpe-ranked names — Sharpe is already covered by the Strategist.
- Do NOT avoid high-RSI stocks — they are the momentum leaders.

## Output — valid JSON only, no other text
{"positions":[{"ticker":"X","weight":0.20,"rationale":"why this catalyst pick at this weight"}],"reasoning":"2-3 sentence catalyst thesis","confidence":0.80,"learning_reflection":"One sentence: how today's picks adapt based on recent learning context."}"""


class GeminiChallenger(BaseAgent):
    MAX_RETRIES = 3
    MODEL = "gemini-2.5-flash"

    def __init__(self) -> None:
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        groq_key = os.environ.get("GROQ_API_KEY", "")
        self._groq = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1") if groq_key else None

    def propose(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
    ) -> PortfolioProposal:
        regime = snapshot.get("regime", "NEUTRAL")
        learning_context = snapshot.get("learning_context", "")
        user_message = self._build_user_message(snapshot, prior_proposal)

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                proposal = self._call_gemini(user_message, regime, learning_context)
                logger.info(
                    "GeminiChallenger produced %d positions (confidence %.0f%%)",
                    len(proposal.positions),
                    proposal.confidence * 100,
                )
                return proposal
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                logger.warning("GeminiChallenger attempt %d/%d failed: %s", attempt, self.MAX_RETRIES, exc)
                if attempt == self.MAX_RETRIES:
                    if self._groq:
                        logger.info("Gemini bad output — falling back to Groq (%s)", _GROQ_MODEL)
                        return self._call_groq_fallback(user_message, regime, learning_context)
                    logger.warning("GeminiChallenger exhausted retries — returning empty proposal")
                    return PortfolioProposal()
            except Exception as exc:
                logger.warning("GeminiChallenger attempt %d/%d API error: %s", attempt, self.MAX_RETRIES, exc)
                if attempt == self.MAX_RETRIES:
                    if self._groq:
                        logger.info("Gemini unavailable — falling back to Groq (%s)", _GROQ_MODEL)
                        return self._call_groq_fallback(user_message, regime, learning_context)
                    logger.warning("GeminiChallenger exhausted retries — returning empty proposal")
                    return PortfolioProposal()

        return PortfolioProposal()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_user_message(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
    ) -> str:
        regime = snapshot.get("regime", "NEUTRAL")
        vix = snapshot.get("vix_level", float("nan"))
        spx_vs = snapshot.get("spx_vs_200d", 0.0)
        vix_str = f"{vix:.1f}" if not math.isnan(vix) else "N/A"
        rscore = snapshot.get("regime_score", 50)
        score_label = (
            "DEFENSIVE" if rscore < 30 else
            "CAUTIOUS"  if rscore < 50 else
            "NEUTRAL"   if rscore < 70 else
            "BULLISH"
        )

        short_interest = snapshot.get("short_interest", {})
        premarket_gap = snapshot.get("premarket_gap", {})
        iv_proxy = snapshot.get("iv_proxy", {})

        catalyst_ranked = self._rank_candidates(snapshot)

        header = (
            f"{'Ticker':<12} {'Market':<12} {'Sector':<7} {'5d Ret':>7} {'RSI':>6} "
            f"{'vs Idx':>8} {'52wH%':>7} {'VolRatio':>9} {'ShortInt':>9} "
            f"{'PreMktGap':>10} {'IV':>7} {'ATR%':>6} {'DivYld':>7} {'CatScore':>9} {'Price':>10}"
        )

        lines = [
            f"Market snapshot as of {snapshot['as_of_date']}",
            f"Regime: {regime} | SPX vs 200d SMA: {spx_vs:.1%} | VIX: {vix_str}",
            f"Composite regime score: {rscore}/100 — {score_label}",
            "",
            "Top candidates (sorted by catalyst score) — CATALYST signals only:",
            "ShortInt = short % of float (N/A for Baltic/Nordic — no data, not a penalty).",
            "PreMktGap = gap vs prior close (EU=morning gap, US=after-hours).",
            "IV = implied vol from options (US) or 20d annualized realized vol (non-US fallback).",
            "CatScore = internal catalyst ranking. Use this as your primary ordering.",
            "",
            header,
            "-" * len(header),
        ]

        def fmt(v: float, fmt_str: str = ".1%") -> str:
            return "N/A" if (v is None or (isinstance(v, float) and math.isnan(v))) else format(v, fmt_str)

        def fmt_opt(v: "float | None", fmt_str: str = ".1%") -> str:
            return "N/A" if v is None else format(v, fmt_str)

        for c in catalyst_ranked:
            t = c["ticker"]
            si = short_interest.get(t)
            pm = premarket_gap.get(t)
            iv = iv_proxy.get(t)
            lines.append(
                f"{t:<12} {c['market']:<12} {c.get('sector', '?'):<7} "
                f"{fmt(c['mom_5d']):>7} "
                f"{fmt(c['rsi_14'], '.1f'):>6} "
                f"{fmt(c['vs_index']):>8} "
                f"{fmt(c['pct_from_52w_high']):>7} "
                f"{fmt(c['vol_ratio'], '.2f'):>9} "
                f"{fmt_opt(si, '.1%'):>9} "
                f"{fmt_opt(pm, '+.1%'):>10} "
                f"{fmt_opt(iv, '.2f'):>7} "
                f"{fmt(c.get('atr_pct', float('nan'))):>6} "
                f"{fmt(c.get('dividend_yield', float('nan'))):>7} "
                f"{self._catalyst_score(c, si, pm, iv):>9.2f} "
                f"{c['last_price']:>10.2f}"
            )

        if prior_proposal and prior_proposal.positions:
            lines += ["", "Yesterday's holdings (for continuity reference):"]
            for pos in prior_proposal.positions:
                lines.append(f"  {pos.ticker:<12} {pos.weight:.1%}")

        if snapshot.get("earnings_warning"):
            lines += ["", snapshot["earnings_warning"]]

        if snapshot.get("news_headlines"):
            lines += ["", snapshot["news_headlines"]]

        lines += ["", "Build your catalyst-driven portfolio. Return valid JSON only."]
        return "\n".join(lines)

    def _rank_candidates(self, snapshot: MarketSnapshot) -> list[dict]:
        short_interest = snapshot.get("short_interest", {})
        premarket_gap = snapshot.get("premarket_gap", {})
        iv_proxy = snapshot.get("iv_proxy", {})

        def sort_key(candidate: dict) -> tuple:
            ticker = candidate["ticker"]
            return (
                self._catalyst_score(
                    candidate,
                    short_interest.get(ticker),
                    premarket_gap.get(ticker),
                    iv_proxy.get(ticker),
                ),
                candidate.get("vol_ratio", float("-inf")),
                candidate.get("mom_5d", float("-inf")),
            )

        return sorted(snapshot["candidates"], key=sort_key, reverse=True)

    @staticmethod
    def _catalyst_score(
        candidate: dict,
        short_interest: Optional[float],
        premarket_gap: Optional[float],
        iv_proxy: Optional[float],
    ) -> float:
        score = 0.0

        mom_5d = candidate.get("mom_5d", float("nan"))
        if not math.isnan(mom_5d):
            score += max(-1.0, min(2.0, mom_5d * 15.0))

        vs_index = candidate.get("vs_index", float("nan"))
        if not math.isnan(vs_index):
            score += max(-1.0, min(2.0, vs_index * 12.0))

        vol_ratio = candidate.get("vol_ratio", float("nan"))
        if not math.isnan(vol_ratio):
            score += max(-1.0, min(2.5, (vol_ratio - 1.0) * 2.5))

        rsi = candidate.get("rsi_14", float("nan"))
        if not math.isnan(rsi):
            score += 1.0 if rsi >= 75 else (0.5 if rsi >= 60 else 0.0)

        if short_interest is not None:
            score += max(0.0, min(2.0, short_interest * 8.0))

        if premarket_gap is not None:
            score += max(-0.5, min(2.0, premarket_gap * 25.0))

        if iv_proxy is not None:
            score += max(0.0, min(1.0, (iv_proxy - 0.35) * 2.0))

        # Small bonus for non-US tickers (differentiated alpha vs competitors)
        if "." in candidate["ticker"]:
            score += 0.25

        return score

    def _call_groq_fallback(
        self,
        user_message: str,
        regime: str = "NEUTRAL",
        learning_context: str = "",
    ) -> PortfolioProposal:
        """Groq (Llama 3.3 70B) fallback when Gemini is unavailable. Free tier, OpenAI-compatible API."""
        regime_guidance = _REGIME_GUIDANCE.get(regime, _REGIME_GUIDANCE["NEUTRAL"])
        system_prompt = (
            _SYSTEM_PROMPT_BASE
            .replace("TODAY_DATE", date.today().isoformat())
            .replace("REGIME_GUIDANCE", regime_guidance)
        )
        if learning_context:
            system_prompt += f"\n\nLive learning — MANDATORY overrides from past runs:\n{learning_context}"

        for attempt in range(1, 3):
            try:
                response = self._groq.chat.completions.create(
                    model=_GROQ_MODEL,
                    response_format={"type": "json_object"},
                    temperature=0.4,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                )
                usage = response.usage
                cost = log_usage(
                    agent_name="GroqChallenger",
                    model=_GROQ_MODEL,
                    input_tokens=usage.prompt_tokens,
                    output_tokens=usage.completion_tokens,
                )
                logger.info(
                    "Groq fallback tokens — in: %d, out: %d (cost: $%.5f)",
                    usage.prompt_tokens, usage.completion_tokens, cost,
                )
                data = json.loads(response.choices[0].message.content)
                raw_positions = data.get("positions", [])
                if any(float(p["weight"]) > 1.0 for p in raw_positions):
                    for p in raw_positions:
                        p["weight"] = float(p["weight"]) / 100.0
                positions = [
                    Position(ticker=p["ticker"], weight=float(p["weight"]), rationale=p.get("rationale", ""))
                    for p in raw_positions
                ]
                logger.info("Groq fallback produced %d positions", len(positions))
                return PortfolioProposal(
                    positions=positions,
                    reasoning=data.get("reasoning", ""),
                    confidence=float(data.get("confidence", 0.5)),
                    learning_reflection=data.get("learning_reflection", ""),
                )
            except Exception as exc:
                logger.warning("Groq fallback attempt %d/2 failed: %s", attempt, exc)

        logger.warning("Groq fallback also failed — returning empty proposal")
        return PortfolioProposal()

    def _call_gemini(
        self,
        user_message: str,
        regime: str = "NEUTRAL",
        learning_context: str = "",
    ) -> PortfolioProposal:
        regime_guidance = _REGIME_GUIDANCE.get(regime, _REGIME_GUIDANCE["NEUTRAL"])
        system_prompt = (
            _SYSTEM_PROMPT_BASE
            .replace("TODAY_DATE", date.today().isoformat())
            .replace("REGIME_GUIDANCE", regime_guidance)
        )
        if learning_context:
            system_prompt += f"\n\nLive learning — MANDATORY overrides from past runs:\n{learning_context}"

        response = self.client.models.generate_content(
            model=self.MODEL,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                temperature=0.4,
            ),
        )

        raw_text = response.text.strip()

        # Strip accidental markdown fences
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        data = json.loads(raw_text)
        raw_positions = data.get("positions", [])

        # Auto-fix: if any weight > 1.0 the model output percentages
        if any(float(p["weight"]) > 1.0 for p in raw_positions):
            logger.warning("GeminiChallenger returned percentage weights — auto-converting to decimals")
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
            learning_reflection=data.get("learning_reflection", ""),
        )
