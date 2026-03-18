"""
OpenAIRiskManager — GPT-4o-mini meta-analyst.

Receives two independent portfolio proposals (GPT-4o Strategist + Gemini Challenger)
and synthesizes a final portfolio:
  - Stocks in BOTH proposals = independently validated = higher conviction weight
  - Unique picks from each = considered on their own merits
  - Applies risk filters: equal-weight check, regime fit, market concentration

Cost: ~$0.0006/run, ~$0.06 for the full game.
"""
import json
import logging
import math
import os
from datetime import date
from typing import Optional

from openai import OpenAI

from agents.base_agent import BaseAgent
from data.cost_tracker import log_usage
from data.fetcher import MarketSnapshot
from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a meta-analyst for the Äripäev/SEB Investment Game (Estonia). You receive two independent portfolio proposals — one from GPT-4o Strategist (momentum-focused) and one from a Contrarian Challenger — and synthesize the best final portfolio.

Game ends 19 June 2026. Goal: highest absolute return, beating other participants.

## Synthesis rules
0. **Target position count by regime** (HARD requirement):
   - BULL: 6–8 positions. Concentrate. No position below 10%.
   - NEUTRAL: 8–10 positions. No position below 8%. Daily rebalancing is your risk management — skip any pick you wouldn't hold at 8%+.
   - BEAR: 10–14 positions. Cap each at 12%. Spread risk for single-name protection.
   Build the portfolio in order: (1) all consensus picks, (2) best unique picks by signal quality. Stop when you hit the regime ceiling. Do NOT pad with weak picks to reach a higher count.
1. **Consensus picks** (appear in BOTH proposals): independently validated. Give them higher conviction weights (18–25%) unless there is a specific risk reason not to.
2. **Unique picks**: evaluate on their own merits — Sharpe, momentum, vol_ratio, regime fit. Include the best ones.
3. **Ignore weak unique picks**: if only one model picked something and its signals are mediocre, skip it. But do NOT skip picks just to keep the portfolio small — the game has no transaction costs.
4. **DO NOT equal-weight**. Size by conviction:
   - Consensus + strong signals: 20–25%
   - Good signals, one model only: 12–18%
   - Diversifiers: 5–10%
5. **Equal-weighting is a failure**. If you find yourself giving everything the same weight, you are not doing your job.
6. **Check market concentration**: if >65% ends up in one market, redistribute.
7. **Check regime fit and portfolio beta**:
   - You will be given the portfolio-weighted beta computed from the proposals.
   - BEAR regime: target portfolio beta ≤ 0.90. Cap individual positions at 15%.
   - BULL regime: portfolio beta up to 1.30 is acceptable. Concentrate on top names.
   - NEUTRAL: target portfolio beta between 0.95 and 1.15.
8. **Target regime-based position count** across at least 2 markets:
    - BULL: 6–8 positions (concentrate, no position < 10%)
    - NEUTRAL: 8–10 positions (no position < 8%, quality beats quantity)
    - BEAR: 10–14 positions (spread risk, cap at 12% each)
9. **Sector cap (hard rule)**: No single sector (Tech, Fin, Energy, Health, Cons, Ind, Util, Mat, Tel) may exceed 35% of total weight. Sum the sector weights in both proposals before synthesising — if consensus picks push one sector above 35%, replace the weakest name in that sector with the best candidate from an underrepresented sector.
10. **Vol_ratio signal**: prefer positions where vol_ratio > 1.2 (high-volume confirmation). Be cautious about positions where vol_ratio < 0.7 (low-volume, potentially weak move).
11. **Contrarian insight**: the challenger picks represent what the momentum crowd is ignoring. If the challenger's picks have strong signals (recovering RSI, accelerating 5d momentum, positive vs_index), include at least 1–2 of them even if they're not consensus.

## Hard constraints
- 5 to 20 stocks.
- Each position: 5% to 25%.
- Total weight: ≤ 100%.
- No duplicate tickers.

## Output — JSON only
CRITICAL: "weight" must be a DECIMAL between 0.05 and 0.25. NOT a percentage.
  Correct: 0.20 (means 20%)
  WRONG:   20   (do not write whole numbers)

{
  "positions": [
    {
      "ticker": "TICKER",
      "weight": 0.22,
      "rationale": "consensus/unique pick + one-sentence reason for this weight."
    }
  ],
  "reasoning": "2–3 sentences: what consensus existed, what contrarian picks you included, and portfolio beta vs target.",
  "confidence": 0.80
}"""


class OpenAIRiskManager(BaseAgent):
    MODEL = "gpt-4o-mini"

    def __init__(self) -> None:
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def propose(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
        challenger_proposal: Optional[PortfolioProposal] = None,
        bear_cases: Optional[dict] = None,
    ) -> PortfolioProposal:
        if prior_proposal is None:
            raise ValueError("OpenAIRiskManager requires prior_proposal from Strategist.")

        user_message = self._build_message(prior_proposal, challenger_proposal, snapshot, bear_cases or {})

        try:
            result = self._call_openai(user_message)
            logger.info(
                "Meta-analyst: synthesised %d positions from strategist(%d) + challenger(%d) (conf %.0f%%)",
                len(result.positions),
                len(prior_proposal.positions),
                len(challenger_proposal.positions) if challenger_proposal else 0,
                result.confidence * 100,
            )
            return result
        except Exception as exc:
            logger.warning("Meta-analyst failed (%s) — falling back to strategist proposal", exc)
            return prior_proposal

    @staticmethod
    def _portfolio_beta(proposal: PortfolioProposal, snapshot: MarketSnapshot) -> float:
        """Compute weighted-average beta of a proposal using the candidate beta values."""
        beta_map = {
            c["ticker"]: c["beta"]
            for c in snapshot["candidates"]
            if not math.isnan(c.get("beta", float("nan")))
        }
        covered = [(p.weight, beta_map[p.ticker]) for p in proposal.positions if p.ticker in beta_map]
        if not covered:
            return float("nan")
        covered_weight = sum(w for w, _ in covered)
        if covered_weight == 0:
            return float("nan")
        return sum(w * b for w, b in covered) / covered_weight

    def _build_message(
        self,
        strategist: PortfolioProposal,
        challenger: Optional[PortfolioProposal],
        snapshot: MarketSnapshot,
        bear_cases: Optional[dict] = None,
    ) -> str:
        regime = snapshot.get("regime", "NEUTRAL")
        spx_vs = snapshot.get("spx_vs_200d", 0.0)
        vix = snapshot.get("vix_level", float("nan"))
        vix_str = f"{vix:.1f}" if not math.isnan(vix) else "N/A"

        # Compute portfolio betas for context
        strat_beta = self._portfolio_beta(strategist, snapshot)
        strat_beta_str = f"{strat_beta:.2f}" if not math.isnan(strat_beta) else "N/A"
        beta_targets = {"BULL": "target ≤1.30", "BEAR": "target ≤0.90", "NEUTRAL": "target 0.95–1.15"}
        beta_target_str = beta_targets.get(regime, "target 0.95–1.15")

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

        lines = [
            f"## Synthesis task — {date.today().isoformat()}",
            f"Regime: {regime} | SPX vs 200d: {spx_vs:+.1%} | VIX: {vix_str} | S&P 500 20d: {snapshot['benchmark_return']:+.1%}",
            f"Breadth: {breadth_str} above 50d SMA | VIX term: {term_str} | Credit spreads 20d: {credit_str}",
            f"Composite regime score: {rscore}/100 — {score_label}",
            f"Strategist proposal portfolio beta: {strat_beta_str} ({beta_target_str} for {regime} regime)",
            "",
        ]

        # Find consensus tickers
        strat_tickers = {p.ticker for p in strategist.positions}
        chall_tickers = {p.ticker for p in challenger.positions} if challenger and challenger.positions else set()
        consensus = strat_tickers & chall_tickers

        if consensus:
            lines.append(f"⭐ CONSENSUS picks (in BOTH proposals — higher conviction): {', '.join(sorted(consensus))}")
            lines.append("")

        # Strategist proposal
        strat_total = sum(p.weight for p in strategist.positions)
        lines += [
            f"### Proposal A — GPT-4o Strategist ({len(strategist.positions)} positions, {strat_total:.0%} total)",
            f"Thesis: {strategist.reasoning}",
            "",
            f"{'Ticker':<12} {'Weight':>8}  Rationale",
            "-" * 65,
        ]
        for p in strategist.positions:
            tag = " ⭐" if p.ticker in consensus else ""
            lines.append(f"{p.ticker:<12} {p.weight:>7.1%}{tag}  {p.rationale[:50]}")

        lines.append("")

        # Challenger proposal (if available)
        if challenger and challenger.positions:
            chall_total = sum(p.weight for p in challenger.positions)
            lines += [
                f"### Proposal B — Gemini Challenger ({len(challenger.positions)} positions, {chall_total:.0%} total)",
                f"Thesis: {challenger.reasoning}",
                "",
                f"{'Ticker':<12} {'Weight':>8}  Rationale",
                "-" * 65,
            ]
            for p in challenger.positions:
                tag = " ⭐" if p.ticker in consensus else ""
                lines.append(f"{p.ticker:<12} {p.weight:>7.1%}{tag}  {p.rationale[:50]}")
        else:
            lines += [
                "### Proposal B — Gemini Challenger",
                "Not available (fallback — use Proposal A as base, apply risk rules).",
            ]

        if snapshot.get("earnings_warning"):
            lines += ["", snapshot["earnings_warning"]]

        if snapshot.get("learning_context"):
            lines += ["", snapshot["learning_context"]]

        if snapshot.get("insider_context"):
            lines += ["", snapshot["insider_context"]]

        if snapshot.get("trends_context"):
            lines += ["", snapshot["trends_context"]]

        if bear_cases:
            high_risk = [(t, v) for t, v in bear_cases.items() if v["risk"] == "HIGH"]
            other_risk = [(t, v) for t, v in bear_cases.items() if v["risk"] != "HIGH"]
            lines += ["", "### ⚠️ Devil's Advocate — Bear Cases"]
            lines.append(
                "These are the strongest arguments AGAINST each pick. "
                "Factor them into your weight decisions — HIGH risk picks should be sized down or cut."
            )
            if high_risk:
                lines.append("")
                lines.append("**HIGH RISK (reduce weight or exclude):**")
                for ticker, v in high_risk:
                    lines.append(f"  {ticker}: {v['bear_case']}")
            if other_risk:
                lines.append("")
                lines.append("**MEDIUM / LOW RISK (acknowledge but can hold):**")
                for ticker, v in other_risk:
                    lines.append(f"  {ticker} [{v['risk']}]: {v['bear_case']}")

        lines += [
            "",
            "Synthesise the final portfolio. Weight consensus picks higher. "
            "For HIGH-RISK picks flagged above: reduce weight by at least 30% vs what you'd otherwise give, or exclude. "
            "Apply regime and concentration rules. Respond ONLY with the JSON object.",
        ]
        return "\n".join(lines)

    def _call_openai(self, user_message: str) -> PortfolioProposal:
        response = self.client.chat.completions.create(
            model=self.MODEL,
            response_format={"type": "json_object"},
            temperature=0.3,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )

        usage = response.usage
        cost = log_usage(
            agent_name="OpenAIRiskManager",
            model=self.MODEL,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
        )
        logger.info(
            "Meta-analyst tokens — in: %d, out: %d (cost: $%.5f)",
            usage.prompt_tokens,
            usage.completion_tokens,
            cost,
        )

        data = json.loads(response.choices[0].message.content)
        raw_positions = data["positions"]

        # Auto-fix: if any weight > 1.0 the model output percentages (e.g. 25 instead of 0.25)
        if any(float(p["weight"]) > 1.0 for p in raw_positions):
            logger.warning("Meta-analyst returned percentage weights — auto-converting to decimals")
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
