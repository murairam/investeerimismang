"""
OpenAIStrategist — GPT-4o-powered alpha generator.
Uses gpt-4o with JSON mode for reliable structured output.

Cost estimate: ~$0.010 per run, ~$0.94 for the full game (94 days).
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
from data.portfolio_store import load_performance_history
from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)

# ── Regime guidance ────────────────────────────────────────────────────────────
_REGIME_GUIDANCE = {
    "BULL": (
        "Market regime: BULL (SPX above 200d SMA by ≥2%). "
        "Concentrate hard — 6–8 positions only. Top 2-3 consensus picks at 20-25% each. "
        "No position below 10%. Cut anything with Sharpe below the median. "
        "High beta, high conviction — this is the regime to make big gains."
    ),
    "BEAR": (
        "Market regime: BEAR (SPX below 200d SMA by ≥2%). "
        "Spread risk across 10–14 positions. Cap individual at 12%. "
        "Favour low-beta quality names (healthcare, staples, utilities). No position below 6%. "
        "Diversification here is real risk management, not dilution."
    ),
    "NEUTRAL": (
        "Market regime: NEUTRAL (SPX near 200d SMA). "
        "Target 8–10 high-conviction positions. No token positions — minimum 8% per pick. "
        "Top 2-3 consensus picks at 18-22%. Mid-tier picks at 10-14%. Tail picks at 8-10%. "
        "Daily rebalancing replaces insurance positions — if a pick is not worth 8%, skip it entirely. "
        "Quality over quantity: 8 strong picks beat 15 mediocre ones."
    ),
}

def _vix_guidance(vix: float) -> str:
    if math.isnan(vix):
        return "VIX data unavailable — use regime signals only."
    if vix > 30:
        return (
            f"VIX is {vix:.1f} — extreme fear. Reduce overall beta. "
            "Cap your highest-conviction positions at 20% and prefer names with strong earnings visibility. "
            "This is not the time for speculative breakouts."
        )
    if vix > 22:
        return (
            f"VIX is {vix:.1f} — elevated uncertainty. "
            "Be selective: only add a position if its Sharpe_20d is clearly above the median. "
            "Slightly prefer quality over pure momentum."
        )
    if vix < 15:
        return (
            f"VIX is {vix:.1f} — market complacency. "
            "Momentum strategy works well here but ensure every position has a genuine Sharpe edge. "
            "Avoid names that are 'up on nothing' — confirm with vs_index > 0."
        )
    return f"VIX is {vix:.1f} — normal range. Standard momentum strategy applies."


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
- Regime-based position count: BULL 6–8, NEUTRAL 8–10, BEAR 10–14. Daily rebalancing replaces diversification — rotate out losers tomorrow rather than holding insurance positions today. Minimum 8% per position (NEUTRAL/BULL). No token 5-6% picks unless BEAR regime.
- Diversify across at least 2 markets to reduce single-market risk.
- Stocks near 52-week highs (pct_from_52w_high close to 0%) are breaking out — favour them.
- vs_index > 0 means the stock beat its own market — pure alpha signal.
- vol_ratio = today's volume / 20d average volume. >1.5 means the move has high-volume confirmation (strong signal). <0.7 means low-volume move (weak signal, be cautious).
- Goal: BEAT other game participants — take conviction bets, not passive exposure.
- **Diversify from the crowd**: if your top 5 picks are all US mega-cap tech, you are running the same portfolio as every other participant. You MUST include at least 2 picks from non-US markets (Nordic, Baltic, or European). This is required for every portfolio.
- **Sector cap (hard rule)**: No single sector (Tech, Fin, Energy, Health, Cons, Ind, Util, Mat, Tel) may exceed 35% of total portfolio weight. Sum the weights in the Sector column before submitting — if any sector exceeds 35%, replace the weakest name in that sector with the best candidate from an underrepresented sector.
- **DivYld column**: The game auto-reinvests dividends — a 4% yield stock earns ~1.5% free return over the 75-day game on top of price gains. Nordic utilities and Baltic stocks often carry 3–6% yields; factor this in when comparing otherwise-similar candidates.

## Baltic market specialist guidance
Baltic stocks behave differently from US/Nordic names — apply specific caution:
- **Most liquid & reliable**: LHV1T.TL (banking, strong fundamentals), TAL1T.TL (tech/growth, highest Baltic liquidity)
- **Thin-volume names** (use only with strong signals): PRF1T.TL, MRK1T.TL, ARC1T.TL — low daily volume means ATR% is misleadingly small; do NOT apply standard ATR-based sizing to these
- **Baltic edge**: local competitors may overlook Baltic stocks; if fundamentals and momentum align, Baltic picks are differentiated alpha
- **Dividend strength**: LHV1T.TL, GRG1L.VS, APG1L.VS often carry 3–6% yields — genuine free return in this game

## Portfolio turnover — MANDATORY HOLD RATE
At least 40% of total portfolio weight must remain in positions held from yesterday. This prevents chasing noise and avoids systematic open-price slippage (you always buy at the next day's open, so excessive turnover means buying yesterday's momentum at a premium).
- A current holding should be KEPT unless the replacement candidate has Sharpe_20d ≥ 20% higher.
- Exception: exit immediately if a holding shows negative vs_index AND RSI > 70 (overbought with weakening alpha).

## Position sizing — MANDATORY RULES
You MUST size by conviction. Equal-weighting is forbidden.
- Tier 1 (best Sharpe + breakout signal): 20–25% each, max 2–3 positions
- Tier 2 (solid momentum): 12–18% each
- Tier 3 (diversifiers, lower conviction): 5–10% each
- Every position must have a different weight that reflects your actual conviction level.
- If any two positions have the same weight, explain why in the rationale.

## Market regime
{regime_guidance}

## VIX volatility filter
{vix_guidance}

## Output format
You must respond with a valid JSON object and nothing else.

{{
  "positions": [
    {{
      "ticker": "TICKER",
      "weight": 0.20,
      "rationale": "One-sentence reason for THIS ticker at THIS specific weight."
    }}
  ],
  "reasoning": "2-3 sentence thesis: which are your top picks and why are they sized that way.",
  "confidence": 0.75
}}

Rules:
- "weight" is a decimal fraction (0.20 = 20%).
- "confidence" is between 0.0 and 1.0.
- Weights must sum to ≤ 1.00.
- Every position weight must be ≥ 0.05 and ≤ 0.25.
- Include between 5 and 20 positions.
- No duplicate tickers.
- Positions MUST have varied weights — equal weighting across all positions is not acceptable.
"""


class OpenAIStrategist(BaseAgent):
    MAX_RETRIES = 3
    MODEL = "gpt-4o"

    def __init__(self) -> None:
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def propose(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
    ) -> PortfolioProposal:
        user_message = self._build_user_message(snapshot, prior_proposal)
        regime = snapshot.get("regime", "NEUTRAL")
        vix = snapshot.get("vix_level", float("nan"))
        learning_context = snapshot.get("learning_context", "")

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                proposal = self._call_openai(user_message, regime, vix, learning_context)
                logger.info(
                    "Strategist produced %d positions (confidence %.0f%%)",
                    len(proposal.positions),
                    proposal.confidence * 100,
                )
                return proposal
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                logger.warning("Attempt %d/%d failed: %s", attempt, self.MAX_RETRIES, exc)
                if attempt == self.MAX_RETRIES:
                    raise RuntimeError("OpenAIStrategist: exhausted retries") from exc

        raise RuntimeError("OpenAIStrategist: unreachable")

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

        breadth = snapshot.get("breadth_pct", float("nan"))
        term = snapshot.get("vix_term_ratio", float("nan"))
        credit = snapshot.get("credit_change", float("nan"))
        rscore = snapshot.get("regime_score", 50)
        breadth_str = f"{breadth:.0%}" if not math.isnan(breadth) else "N/A"
        term_str = f"{term:.2f}" if not math.isnan(term) else "N/A"
        credit_str = f"{credit:+.2%}" if not math.isnan(credit) else "N/A"
        score_label = (
            "DEFENSIVE" if rscore < 30 else
            "CAUTIOUS"  if rscore < 50 else
            "NEUTRAL"   if rscore < 70 else
            "BULLISH"
        )

        header = (
            f"{'Ticker':<12} {'Market':<12} {'Sector':<7} {'20d Ret':>8} {'Sharpe':>7} "
            f"{'5d Ret':>7} {'60d Ret':>8} {'RSI':>6} {'vs Idx':>8} "
            f"{'52wH%':>7} {'Beta':>6} {'VolRatio':>9} {'MACD':>7} {'ATR%':>6} {'DivYld':>7} {'Price':>10}"
        )
        lines = [
            f"Market snapshot as of {snapshot['as_of_date']}",
            f"Benchmark (S&P 500) {MOMENTUM_WINDOW}-day return: {snapshot['benchmark_return']:.1%}",
            f"Regime: {regime} | SPX vs 200d SMA: {spx_vs:.1%} | VIX: {vix_str}",
            f"Breadth: {breadth_str} above 50d SMA | VIX term: {term_str} (>1=calm, <0.9=fear) | Credit spreads 20d: {credit_str} (positive=risk-on)",
            f"Composite regime score: {rscore}/100 — {score_label} (0–30=defensive, 31–49=cautious, 50–69=neutral, 70+=bullish)",
            "",
            "Top candidates (sorted by Sharpe_20d, RSI>75 filtered out):",
            "ATR% = daily expected move as % of price — size smaller when ATR% is high.",
            "",
            header,
            "-" * len(header),
        ]

        def fmt(v: float, fmt_str: str = ".1%") -> str:
            return "N/A" if math.isnan(v) else format(v, fmt_str)

        for c in snapshot["candidates"]:
            lines.append(
                f"{c['ticker']:<12} {c['market']:<12} {c.get('sector', '?'):<7} "
                f"{fmt(c['momentum']):>8} "
                f"{fmt(c['sharpe_20d'], '.2f'):>7} "
                f"{fmt(c['mom_5d']):>7} "
                f"{fmt(c['mom_60d']):>8} "
                f"{fmt(c['rsi_14'], '.1f'):>6} "
                f"{fmt(c['vs_index']):>8} "
                f"{fmt(c['pct_from_52w_high']):>7} "
                f"{fmt(c['beta'], '.2f'):>6} "
                f"{fmt(c['vol_ratio'], '.2f'):>9} "
                f"{fmt(c.get('macd_hist', float('nan'))):>7} "
                f"{fmt(c.get('atr_pct', float('nan'))):>6} "
                f"{fmt(c.get('dividend_yield', float('nan'))):>7} "
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
                "Turnover rule: to EXIT a current holding, the replacement must have a Sharpe_20d "
                "at least 20% higher than the stock being replaced. "
                "Do not swap positions for marginal gains — each trade executes at next-day open price.",
            ]

        # Performance context — full daily P&L review
        perf_history = load_performance_history(max_days=5)
        daily_entries = [e for e in perf_history if "portfolio_return_1d" in e]
        if daily_entries:
            lines += ["", "## Performance review (last %d days)" % len(daily_entries)]
            col_header = f"{'Date':<12} {'Portfolio':>10} {'Benchmark':>10} {'Alpha':>8}    Key movers"
            lines.append(col_header)
            lines.append("-" * len(col_header))
            for entry in daily_entries:
                p_ret = entry.get("portfolio_return_1d", float("nan"))
                b_ret = entry.get("benchmark_return_1d", float("nan"))
                a_ret = entry.get("alpha_1d", float("nan"))
                pos_rets = entry.get("position_returns", {})

                p_str = f"{p_ret:+.1%}" if not math.isnan(p_ret) else "N/A"
                b_str = f"{b_ret:+.1%}" if not math.isnan(b_ret) else "N/A"
                a_str = f"{a_ret:+.1%}" if not math.isnan(a_ret) else "N/A"

                movers = []
                if pos_rets:
                    top_w = sorted(pos_rets.items(), key=lambda x: -x[1])[:2]
                    top_l = sorted(pos_rets.items(), key=lambda x: x[1])[:1]
                    for t, r in top_w:
                        if r > 0:
                            movers.append(f"{t} {r:+.1%} ▲")
                    for t, r in top_l:
                        if r < 0:
                            movers.append(f"{t} {r:+.1%} ▼")
                movers_str = "  ".join(movers) if movers else ""
                lines.append(
                    f"{entry['date']:<12} {p_str:>10} {b_str:>10} {a_str:>8}    {movers_str}"
                )

            # Cumulative stats
            cum_port = sum(
                e.get("portfolio_return_1d", 0.0) for e in daily_entries
                if not math.isnan(e.get("portfolio_return_1d", float("nan")))
            )
            cum_bench = sum(
                e.get("benchmark_return_1d", 0.0) for e in daily_entries
                if not math.isnan(e.get("benchmark_return_1d", float("nan")))
            )
            cum_alpha = cum_port - cum_bench
            lines.append(
                f"\nCumulative since tracking: portfolio {cum_port:+.1%}, "
                f"benchmark {cum_bench:+.1%}, alpha {cum_alpha:+.1%}"
            )

            # Consistent winners/losers across days
            ticker_returns: dict = {}
            for entry in daily_entries:
                for t, r in entry.get("position_returns", {}).items():
                    ticker_returns.setdefault(t, []).append(r)
            consistent_winners = [
                t for t, rets in ticker_returns.items()
                if len(rets) >= 2 and all(r > 0 for r in rets)
            ]
            consistent_losers = [
                t for t, rets in ticker_returns.items()
                if len(rets) >= 2 and all(r < 0 for r in rets)
            ]
            if consistent_winners:
                lines.append(f"Consistent winners this week: {', '.join(consistent_winners)}")
            if consistent_losers:
                lines.append(f"Consistent underperformers: {', '.join(consistent_losers)}")

            # Strategy adaptation signal
            if len(daily_entries) >= 2:
                recent_alpha = [
                    e.get("alpha_1d", float("nan")) for e in daily_entries[-3:]
                    if not math.isnan(e.get("alpha_1d", float("nan")))
                ]
                if recent_alpha:
                    avg_alpha = sum(recent_alpha) / len(recent_alpha)
                    if avg_alpha > 0.003:
                        lines.append(
                            "Strategy adaptation signal: recent alpha is positive — "
                            "current momentum picks are working. Maintain conviction."
                        )
                    elif avg_alpha < -0.003:
                        lines.append(
                            "Strategy adaptation signal: recent alpha is negative — "
                            "consider reviewing position sizing and reviewing losers for exit."
                        )
                    else:
                        lines.append(
                            "Strategy adaptation signal: alpha is near zero — "
                            "monitor for regime change signals before making large shifts."
                        )
        elif len(perf_history) >= 2:
            # Fallback: show old-style benchmark trend if no P&L data yet
            lines += ["", "## Recent benchmark trend (S&P 500 20d return over last runs)"]
            for entry in perf_history:
                bret = entry.get("benchmark_return_20d", float("nan"))
                bret_str = f"{bret:+.1%}" if not math.isnan(bret) else "N/A"
                lines.append(f"  {entry['date']}: S&P 500 20d = {bret_str}")
            first_bret = perf_history[0].get("benchmark_return_20d", float("nan"))
            last_bret = perf_history[-1].get("benchmark_return_20d", float("nan"))
            if not (math.isnan(first_bret) or math.isnan(last_bret)):
                delta = last_bret - first_bret
                trend = "improving" if delta > 0.005 else ("deteriorating" if delta < -0.005 else "flat")
                lines.append(f"  Trend: benchmark momentum is {trend} ({delta:+.1%} over {len(perf_history)} days).")

        if snapshot.get("earnings_warning"):
            lines += ["", snapshot["earnings_warning"]]

        if snapshot.get("news_headlines"):
            lines += ["", snapshot["news_headlines"]]

        if snapshot.get("insider_context"):
            lines += ["", snapshot["insider_context"]]

        if snapshot.get("trends_context"):
            lines += ["", snapshot["trends_context"]]

        lines += [
            "",
            "Generate a portfolio from the candidates above following the game rules and "
            "strategy mandate in your system prompt. Respond ONLY with the JSON object.",
        ]
        return "\n".join(lines)

    def _call_openai(
        self,
        user_message: str,
        regime: str = "NEUTRAL",
        vix: float = float("nan"),
        learning_context: str = "",
    ) -> PortfolioProposal:
        regime_guidance = _REGIME_GUIDANCE.get(regime, _REGIME_GUIDANCE["NEUTRAL"])
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            today=date.today().isoformat(),
            regime_guidance=regime_guidance,
            vix_guidance=_vix_guidance(vix),
        )
        # Inject learning context into the system prompt so it has mandatory-instruction weight.
        # Placed after the strategy rules so it acts as a live override, not a soft suggestion.
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
            agent_name="OpenAIStrategist",
            model=self.MODEL,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
        )
        logger.info(
            "Strategist tokens — in: %d, out: %d (cost: $%.4f)",
            usage.prompt_tokens,
            usage.completion_tokens,
            cost,
        )

        data = json.loads(response.choices[0].message.content)

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
