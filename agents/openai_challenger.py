"""
OpenAIFullAnalyst — Independent Full-Signal Analyst (gpt-5.4-nano).

Sees ALL signals (momentum + catalyst) and provides a completely independent
second opinion on portfolio construction. Not constrained to momentum-only or
catalyst-only — finds the best picks across every signal dimension.

Cost estimate: ~$0.01 per run (gpt-5.4-nano).
"""
import json
import logging
import math
import os
from datetime import date
from typing import Optional

from openai import OpenAI

from agents.base_agent import BaseAgent
from config import MOMENTUM_WINDOW
from data.cost_tracker import log_usage
from data.fetcher import MarketSnapshot
from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)

_REGIME_GUIDANCE = {
    "BULL": "BULL regime — 5–8 positions. High beta, high conviction. Push top picks to 20–25%. This is the regime for big gains.",
    "BEAR": "BEAR regime — 6–12 positions. Spread risk broadly. Cap individual positions at 15%. Prefer names with earnings visibility.",
    "NEUTRAL": "NEUTRAL regime — 5–10 positions. Quality over quantity — only add a position if signals are genuinely compelling.",
}

_SYSTEM_PROMPT = """You are an INDEPENDENT FULL-SIGNAL ANALYST for the Äripäev/SEB Investment Game (Estonia). Game ends 19 June 2026. Goal: highest absolute return.

Today: {today}. You provide a completely fresh second opinion — you see ALL signals (momentum, catalyst, and everything in between). Your job is to find the best portfolio across every signal dimension, not just momentum OR catalysts.

You are one of THREE independent analysts:
1. Momentum Strategist — sees only trend/Sharpe signals
2. Catalyst Hunter (Gemini) — sees only catalyst signals (vol_ratio, RSI, short interest, IV)
3. YOU — full analyst, sees everything, fresh independent view

The Risk Manager will synthesize all three. Your value is finding picks that neither specialist might surface — stocks with good all-round signals across both momentum and catalyst dimensions.

## Game rules
- 5 to 20 stocks. Each position: 5%–25%. Total weight: ≤100%. No duplicates.
- Markets: US S&P 500, OMX Helsinki, OMX Stockholm, OBX Norway, OMX Copenhagen, Baltic.
- Regime-based position count: {regime_guidance}

## Signal guide — use ALL columns
- **Sharpe_20d**: risk-adjusted 20d momentum. High Sharpe = smooth persistent uptrend.
- **5d Ret / 60d Ret**: recent acceleration vs longer trend.
- **RSI**: > 75 is BULLISH (parabolic breakout). Do NOT avoid high-RSI names.
- **vs Idx**: stock beat its own market benchmark. Pure alpha signal.
- **52wH%**: always ≤ 0%. 0.0% = AT 52-week high (bullish). -30% = 30% below.
- **Beta**: amplifies gains in bull market. Target high beta in BULL regime.
- **vol_ratio**: > 1.5 = high-volume confirmation of the move. < 0.7 = weak unconfirmed move.
- **MACD**: positive histogram = accelerating momentum. Negative = decelerating.
- **ATR%**: daily expected move. High ATR% = volatile active mover.
- **ShortInt**: short % of float. > 15% + positive momentum + vol_ratio > 1.5 = squeeze setup.
- **PreMktGap**: positive gap vs prior close = opening momentum confirmation.
- **IV**: implied vol (US options) or 20d realized vol (Nordic/Baltic fallback). Spike = event catalyst.
- **DivYld**: game auto-reinvests dividends. 4% yield = ~1.5% free return over 75 days.

## What to look for
- Perfect setups: high Sharpe + vol_ratio > 1.5 + RSI > 70 + positive MACD + vs_index > 0
- Good setups: any 3-4 of the above
- Avoid: negative vs_index AND vol_ratio < 0.8 AND negative MACD (dead momentum)
- Diversify: at least 2 picks from non-US markets (unless US signals are overwhelmingly dominant)
- Baltic/Nordic: do NOT penalize for N/A short interest or IV — evaluate on volume, momentum, RSI

## Sizing — MANDATORY
- Highest conviction (4+ positive signals): 20–25%
- Strong signals (3 positive): 12–18%
- Speculative / diversifier: 5–10%
Every position must have a different weight.

## Macro context
Follow the signals — no hardcoded sector or stock bias. Whatever has the strongest combined signal today is your focus.

## Output — valid JSON only, no other text
{{"positions":[{{"ticker":"X","weight":0.20,"rationale":"why this pick at this weight based on specific signals"}}],"reasoning":"2-3 sentence thesis","confidence":0.80,"learning_reflection":"One sentence: how today's picks adapt based on recent learning context."}}"""


class OpenAIFullAnalyst(BaseAgent):
    MAX_RETRIES = 3
    MODEL = "gpt-5.4-nano"

    def __init__(self) -> None:
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def propose(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
    ) -> PortfolioProposal:
        user_message = self._build_user_message(snapshot, prior_proposal)
        regime = snapshot.get("regime", "NEUTRAL")
        learning_context = snapshot.get("learning_context", "")

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                proposal = self._call_openai(user_message, regime, learning_context)
                logger.info(
                    "FullAnalyst produced %d positions (confidence %.0f%%)",
                    len(proposal.positions),
                    proposal.confidence * 100,
                )
                return proposal
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                logger.warning("FullAnalyst attempt %d/%d failed: %s", attempt, self.MAX_RETRIES, exc)
                if attempt == self.MAX_RETRIES:
                    logger.warning("FullAnalyst exhausted retries — returning empty proposal")
                    return PortfolioProposal()

        return PortfolioProposal()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_user_message(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
    ) -> str:
        vix = snapshot.get("vix_level", float("nan"))
        spx_vs = snapshot.get("spx_vs_200d", 0.0)
        regime = snapshot.get("regime", "NEUTRAL")
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

        # Sort by combined score (momentum + catalyst) for full analyst
        def combined_score(c: dict) -> float:
            t = c["ticker"]
            score = 0.0
            sharpe = c.get("sharpe_20d", float("nan"))
            if not math.isnan(sharpe):
                score += max(-0.5, min(1.5, sharpe))
            mom_5d = c.get("mom_5d", float("nan"))
            if not math.isnan(mom_5d):
                score += max(-1.0, min(2.0, mom_5d * 15.0))
            vs_index = c.get("vs_index", float("nan"))
            if not math.isnan(vs_index):
                score += max(-1.0, min(2.0, vs_index * 12.0))
            vol_ratio = c.get("vol_ratio", float("nan"))
            if not math.isnan(vol_ratio):
                score += max(-1.0, min(2.5, (vol_ratio - 1.0) * 2.5))
            rsi = c.get("rsi_14", float("nan"))
            if not math.isnan(rsi):
                score += 1.0 if rsi >= 75 else (0.5 if rsi >= 60 else 0.0)
            si = short_interest.get(t)
            if si is not None:
                score += max(0.0, min(2.0, si * 8.0))
            pm = premarket_gap.get(t)
            if pm is not None:
                score += max(-0.5, min(2.0, pm * 25.0))
            return score

        ranked = sorted(snapshot["candidates"], key=combined_score, reverse=True)

        header = (
            f"{'Ticker':<12} {'Market':<12} {'Sector':<7} {'20d Ret':>8} {'Sharpe':>7} "
            f"{'5d Ret':>7} {'60d Ret':>8} {'RSI':>6} {'vs Idx':>8} {'52wH%':>7} "
            f"{'Beta':>6} {'VolR':>6} {'MACD':>7} {'ATR%':>6} "
            f"{'ShrtInt':>8} {'PreMkt':>8} {'IV':>7} {'DivYld':>7} {'Price':>10}"
        )

        lines = [
            f"Market snapshot as of {snapshot['as_of_date']}",
            f"Benchmark (S&P 500) {MOMENTUM_WINDOW}-day return: {snapshot['benchmark_return']:.1%}",
            f"Regime: {regime} | SPX vs 200d SMA: {spx_vs:.1%} | VIX: {vix_str}",
            f"Composite regime score: {rscore}/100 — {score_label}",
            "",
            "Top candidates (sorted by combined score) — ALL signals:",
            "ShrtInt = short % of float (N/A for Baltic/Nordic). PreMkt = premarket gap. IV = implied vol or realized HV fallback.",
            "",
            header,
            "-" * len(header),
        ]

        def fmt(v: float, fmt_str: str = ".1%") -> str:
            return "N/A" if (v is None or (isinstance(v, float) and math.isnan(v))) else format(v, fmt_str)

        def fmt_opt(v: "float | None", fmt_str: str = ".1%") -> str:
            return "N/A" if v is None else format(v, fmt_str)

        for c in ranked:
            t = c["ticker"]
            si = short_interest.get(t)
            pm = premarket_gap.get(t)
            iv = iv_proxy.get(t)
            lines.append(
                f"{t:<12} {c['market']:<12} {c.get('sector', '?'):<7} "
                f"{fmt(c['momentum']):>8} "
                f"{fmt(c['sharpe_20d'], '.2f'):>7} "
                f"{fmt(c['mom_5d']):>7} "
                f"{fmt(c['mom_60d']):>8} "
                f"{fmt(c['rsi_14'], '.1f'):>6} "
                f"{fmt(c['vs_index']):>8} "
                f"{fmt(c['pct_from_52w_high']):>7} "
                f"{fmt(c['beta'], '.2f'):>6} "
                f"{fmt(c['vol_ratio'], '.2f'):>6} "
                f"{fmt(c.get('macd_hist', float('nan'))):>7} "
                f"{fmt(c.get('atr_pct', float('nan'))):>6} "
                f"{fmt_opt(si, '.1%'):>8} "
                f"{fmt_opt(pm, '+.1%'):>8} "
                f"{fmt_opt(iv, '.2f'):>7} "
                f"{fmt(c.get('dividend_yield', float('nan'))):>7} "
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

        if snapshot.get("insider_context"):
            lines += ["", snapshot["insider_context"]]

        if snapshot.get("trends_context"):
            lines += ["", snapshot["trends_context"]]

        lines += ["", "Build your portfolio using all available signals. Return valid JSON only."]
        return "\n".join(lines)

    def _call_openai(
        self,
        user_message: str,
        regime: str = "NEUTRAL",
        learning_context: str = "",
    ) -> PortfolioProposal:
        regime_guidance = _REGIME_GUIDANCE.get(regime, _REGIME_GUIDANCE["NEUTRAL"])
        system_prompt = _SYSTEM_PROMPT.format(
            today=date.today().isoformat(),
            regime_guidance=regime_guidance,
        )
        if learning_context:
            system_prompt += f"\n\n## Live learning — MANDATORY overrides from past runs\n{learning_context}"

        response = self.client.chat.completions.create(
            model=self.MODEL,
            response_format={"type": "json_object"},
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )

        usage = response.usage
        cost = log_usage(
            agent_name="OpenAIFullAnalyst",
            model=self.MODEL,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
        )
        logger.info(
            "FullAnalyst tokens — in: %d, out: %d (cost: $%.4f)",
            usage.prompt_tokens,
            usage.completion_tokens,
            cost,
        )

        data = json.loads(response.choices[0].message.content)
        raw_positions = data.get("positions", [])

        # Auto-fix: if any weight > 1.0 the model output percentages
        if any(float(p["weight"]) > 1.0 for p in raw_positions):
            logger.warning("FullAnalyst returned percentage weights — auto-converting to decimals")
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


# Backwards-compatibility alias (orchestrator imports OpenAIChallenger)
OpenAIChallenger = OpenAIFullAnalyst
