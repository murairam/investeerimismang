"""
OpenAIRiskManager — GPT-5.4 meta-analyst.

Receives two independent portfolio proposals (GPT-5.4 Strategist + GPT-5.4 Challenger)
and synthesizes a final portfolio:
  - Stocks in BOTH proposals = independently validated = higher conviction weight
  - Unique picks from each = considered on their own merits
  - Applies risk filters: equal-weight check, regime fit, market concentration

Cost depends on current OpenAI GPT-5.4 pricing and prompt size.
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
from data.learning_state import load_learning_state
from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a meta-analyst for the Äripäev/SEB Investment Game (Estonia). You receive THREE independent portfolio proposals and synthesize the best final portfolio:
- Proposal A: GPT-5.4 Momentum Strategist (sees only trend/Sharpe signals)
- Proposal B: Gemini Catalyst Hunter (sees only catalyst signals: vol_ratio, RSI, short interest, IV)
- Proposal C: GPT-5.4-nano Full Analyst (sees ALL signals — fresh independent view)

A pick appearing in 2+ proposals is independently validated consensus — treat it as higher conviction.

Game ends 19 June 2026. Goal: highest absolute return, beating other participants.

## Competition mandate
This is a competition with 844 participants. Only #1 wins — median returns = losing. INTELLIGENT AGGRESSION is required. 15% drawdown is acceptable if it gives 40% upside potential — price risk for competition, not wealth management. Follow the signals. Do not apply any sector or stock bias — the data tells you what is working today. Competition rewards right-tail outcomes: concentrate in 5-6 names with real momentum catalysts.

## Synthesis rules
0. **Target position count by regime** — you decide the exact count based on signal quality:
   - BULL: 5–6 positions. TARGET 5 positions at 20% each for maximum conviction. Only add a 6th if genuinely high-conviction at 15–17% and rebalance others. Do NOT add filler for diversification — diversification loses competitions.
   - NEUTRAL: 5–10 positions. Use your judgement — 5 if signals are concentrated, more if many names have strong setups.
   - BEAR: 6–12 positions. Spread risk more broadly.
   Build in order: (1) consensus picks, (2) best unique picks. Do NOT pad with weak picks to reach a higher count.
1. **Consensus picks** (appear in 2+ of the 3 proposals): independently validated across different signal lenses. Give them higher conviction weights (18–25%) unless there is a specific risk reason not to. A pick found by BOTH the momentum strategist and the catalyst hunter is especially strong — it wins on two different signal dimensions.
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
   - BULL regime: portfolio beta up to 2.0 is acceptable. Concentrate on top names — high beta wins in bull markets.
   - NEUTRAL: target portfolio beta between 0.95 and 1.30.
8. **Target regime-based position count**:
    - BULL: 5–6 positions. Target 5 at ~20% each. No position < 5%. Cap strongest at 25%.
    - NEUTRAL: 5–10 positions. Size by conviction — top picks 20–25%, diversifiers 5–10%.
    - BEAR: 6–12 positions. Cap at 20% each.
9. **No sector cap**: The game enforces zero sector concentration limits. 100% in one sector is fully legal (e.g. 4 Energy stocks at 25% each). Concentrate wherever the alpha is.
10. **Vol_ratio signal**: prefer positions where vol_ratio > 1.2 (high-volume confirmation). Be cautious about positions where vol_ratio < 0.7 (low-volume, potentially weak move).
11. **Catalyst insight**: the challenger picks represent high-momentum catalysts. If the challenger's picks have strong signals (high short interest, premarket gap-up, IV spike + momentum), include at least 1–2 of them even if they're not consensus.
12. **Do NOT penalize non-US stocks for missing Short Interest data.** Their IV column shows 20d annualized realized vol (not options IV) — treat it as a volatility level indicator. Evaluate European/Baltic stocks on volume breakouts, momentum, premarket gaps, and realized vol so we don't accidentally build a 100% US portfolio.
13. **Earnings — opportunity AND risk**: Pre-earnings momentum in high-conviction stocks is an OPPORTUNITY (academic: 3–8% drift in 2–4 days before announcement). If the snapshot shows a PRE_EARNINGS_SETUP tag for a stock: allow up to 20% weight, max 40% total pre-earnings exposure, no more than 2 names with earnings in the same week. For earnings within 1 day (announcement tomorrow): cap at 10% regardless of conviction — binary gap risk is too close.
14. **Dead-money exclusion rule**: in this competition, a stock is dead money if vol_ratio < 0.90 and mom_5d <= +1.0%. Do NOT call a stock dead money if vol_ratio is above 1.0. HIGH-risk dead-money names should normally be excluded, not merely downsized.
15. **Acceleration matters**: prefer active movers. If two stocks are similar on 20d momentum, keep the one with better 5d momentum and stronger volume confirmation.
16. **Slot cost rule**: every position must earn its slot. Do not include a merely acceptable stock if a better alternative from either proposal exists. A 5-stock portfolio means each slot is scarce capital.
17. **Regime-score selectivity inside NEUTRAL**: when regime_score is below 50 (CAUTIOUS), still hold exactly 5 names, but be more selective. Do NOT use caution as an excuse to add slow names; instead remove weak-acceleration names and keep only the sharpest 5.
18. **Overbought-at-peak weight cap**: if a pick has RSI > 82 AND pct_from_52w_high ≥ −2% (at or within 2% of its 52-week high), cap its weight at 15% UNLESS vol_ratio > 1.8. High RSI at the 52-week high without exceptional volume confirms exhaustion not breakout — even for consensus picks. If vol_ratio > 1.8 the volume surge justifies the full 20–25% conviction weight.
19. **Devil flag respect**: The Devil's advocate labels each pick HIGH / MEDIUM / LOW risk. If the learning context reports that the Devil's HIGH-risk flags have been accurate (>60% of HIGH-flagged picks underperformed), treat HIGH-risk flags as a hard weight cap of 10% for that pick. If Devil accuracy is unknown or below 50%, use your own judgement.
20. **Learning-state constraints are mandatory**: Any ticker-level weight caps, hard rules, and bias-avoidance directives in the learning context are hard constraints for today's synthesis. Do not override them with consensus arguments.

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
  "reasoning": "2–3 sentences: what consensus existed, what catalyst picks you included, and portfolio beta vs target.",
  "confidence": 0.80,
  "learning_reflection": "One sentence: how today's synthesis adapts based on recent learning context."
}"""


class OpenAIRiskManager(BaseAgent):
    MODEL = "gpt-5.4"

    def __init__(self) -> None:
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def propose(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
        challenger_proposal: Optional[PortfolioProposal] = None,
        bear_cases: Optional[dict] = None,
        full_analyst_proposal: Optional[PortfolioProposal] = None,
    ) -> PortfolioProposal:
        if prior_proposal is None:
            raise ValueError("OpenAIRiskManager requires prior_proposal from Strategist.")

        user_message = self._build_message(
            prior_proposal, challenger_proposal, snapshot, bear_cases or {},
            full_analyst=full_analyst_proposal,
        )

        regime = snapshot.get("regime", "NEUTRAL")
        beta_targets = {
            "BULL": (None, 2.0),
            "NEUTRAL": (0.95, 1.30),
            "BEAR": (None, 0.90),
        }

        try:
            result = self._call_openai(user_message)
            result = self._enforce_beta(result, snapshot, regime, beta_targets)
            result = self._enforce_selection_quality(result, snapshot, bear_cases or {})
            logger.info(
                "Meta-analyst: synthesised %d positions from strategist(%d) + gemini(%d) + full(%d) (conf %.0f%%)",
                len(result.positions),
                len(prior_proposal.positions),
                len(challenger_proposal.positions) if challenger_proposal else 0,
                len(full_analyst_proposal.positions) if full_analyst_proposal else 0,
                result.confidence * 100,
            )
            return result
        except Exception as exc:
            logger.warning("Meta-analyst failed (%s) — falling back to merge", exc)
            return self._merge_proposals(prior_proposal, challenger_proposal, full_analyst_proposal)

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

    # Empirical average S&P 500 beta for Nordic/Baltic stocks (structurally low US-market correlation)
    _NON_US_ASSUMED_BETA = 0.30

    def _enforce_beta(
        self,
        proposal: PortfolioProposal,
        snapshot: MarketSnapshot,
        regime: str,
        beta_targets: dict,
    ) -> PortfolioProposal:
        """Check portfolio beta against regime targets, adjusted for non-US exposure.

        Non-US tickers (identified by having '.' in the symbol, e.g. TELIA.ST, DNB.OL)
        naturally have low S&P 500 beta (~0.30). The raw beta targets (0.95-1.15 for NEUTRAL)
        were designed for US-only portfolios. We scale the target down proportionally to
        how much of the portfolio is in non-US stocks.
        """
        actual_beta = self._portfolio_beta(proposal, snapshot)
        if math.isnan(actual_beta):
            return proposal

        us_weight = sum(p.weight for p in proposal.positions if "." not in p.ticker)
        non_us_weight = 1.0 - us_weight

        # Skip check if almost no US exposure — beta vs S&P 500 is meaningless
        if us_weight < 0.25:
            logger.info(
                "Portfolio beta check skipped: only %.0f%% US exposure "
                "(non-US stocks have structurally low S&P 500 beta — actual beta %.2f)",
                us_weight * 100, actual_beta,
            )
            return proposal

        # Adjust target range for non-US exposure
        lo, hi = beta_targets.get(regime, (None, None))
        adj_lo = (lo * us_weight + self._NON_US_ASSUMED_BETA * non_us_weight) if lo else None
        adj_hi = (hi * us_weight + self._NON_US_ASSUMED_BETA * non_us_weight) if hi else None

        in_range = (adj_lo is None or actual_beta >= adj_lo) and (adj_hi is None or actual_beta <= adj_hi)
        raw_str = f"{lo if lo is not None else '?'}–{hi if hi is not None else '?'}"
        adj_str = f"{adj_lo:.2f}–{adj_hi:.2f}" if (adj_lo and adj_hi) else f"≤{adj_hi:.2f}" if adj_hi else "?"

        if in_range:
            logger.info(
                "Portfolio beta %.2f within adjusted target %s "
                "(raw %s scaled for %.0f%% non-US exposure)",
                actual_beta, adj_str, raw_str, non_us_weight * 100,
            )
        else:
            logger.warning(
                "Portfolio beta %.2f outside adjusted target %s "
                "(raw %s, %.0f%% US + %.0f%% non-US at assumed beta %.2f)",
                actual_beta, adj_str, raw_str,
                us_weight * 100, non_us_weight * 100, self._NON_US_ASSUMED_BETA,
            )
            if regime == "BEAR" and adj_hi is not None and actual_beta > adj_hi:
                logger.warning(
                    "BEAR regime beta too high (%.2f > %.2f) — capping positions at 15%%",
                    actual_beta, adj_hi,
                )
                positions = [
                    Position(ticker=p.ticker, weight=min(p.weight, 0.15), rationale=p.rationale)
                    for p in proposal.positions
                ]
                total = sum(p.weight for p in positions)
                if total > 0:
                    positions = [
                        Position(ticker=p.ticker, weight=p.weight / total, rationale=p.rationale)
                        for p in positions
                    ]
                proposal = PortfolioProposal(
                    positions=positions,
                    reasoning=proposal.reasoning,
                    confidence=proposal.confidence,
                    learning_reflection=proposal.learning_reflection,
                )
        return proposal

    def _enforce_selection_quality(
        self,
        proposal: PortfolioProposal,
        snapshot: MarketSnapshot,
        bear_cases: dict[str, dict],
    ) -> PortfolioProposal:
        candidate_map = {c["ticker"]: c for c in snapshot["candidates"]}
        regime_score = snapshot.get("regime_score", 50)
        minimum_positions = 5

        def is_dead_money(ticker: str) -> bool:
            c = candidate_map.get(ticker, {})
            vol_ratio = c.get("vol_ratio", float("nan"))
            mom_5d = c.get("mom_5d", float("nan"))
            if math.isnan(vol_ratio) or math.isnan(mom_5d):
                return False
            return vol_ratio < 0.90 and mom_5d <= 0.01

        def candidate_score(ticker: str) -> float:
            c = candidate_map.get(ticker, {})
            score = 0.0
            sharpe = c.get("sharpe_20d", float("nan"))
            if not math.isnan(sharpe):
                score += max(-1.0, min(2.0, sharpe))
            mom_5d = c.get("mom_5d", float("nan"))
            if not math.isnan(mom_5d):
                score += max(-1.5, min(2.5, mom_5d * 18.0))
            vol_ratio = c.get("vol_ratio", float("nan"))
            if not math.isnan(vol_ratio):
                score += max(-1.0, min(2.0, (vol_ratio - 1.0) * 2.0))
            vs_index = c.get("vs_index", float("nan"))
            if not math.isnan(vs_index):
                score += max(-1.0, min(2.0, vs_index * 12.0))
            if is_dead_money(ticker):
                score -= 2.0
            bear = bear_cases.get(ticker)
            if bear and bear.get("risk") == "HIGH":
                score -= 2.5
            elif bear and bear.get("risk") == "MEDIUM":
                score -= 0.8
            return score

        kept: list[Position] = []
        removed: list[str] = []
        for pos in proposal.positions:
            ticker = pos.ticker
            bear = bear_cases.get(ticker, {})
            if bear.get("risk") == "HIGH" and is_dead_money(ticker):
                removed.append(ticker)
                continue
            if regime_score < 50:
                c = candidate_map.get(ticker, {})
                mom_5d = c.get("mom_5d", float("nan"))
                vol_ratio = c.get("vol_ratio", float("nan"))
                if ((not math.isnan(mom_5d) and mom_5d < 0.0) or
                        (not math.isnan(vol_ratio) and vol_ratio < 0.80 and not math.isnan(mom_5d) and mom_5d < 0.02)):
                    removed.append(ticker)
                    continue
            kept.append(pos)

        if len(kept) < minimum_positions:
            existing = {p.ticker for p in kept}
            ranked_candidates = sorted(
                [c["ticker"] for c in snapshot["candidates"] if c["ticker"] not in existing],
                key=candidate_score,
                reverse=True,
            )
            for ticker in ranked_candidates:
                if len(kept) >= minimum_positions:
                    break
                if candidate_score(ticker) < 0.15:
                    continue
                c = candidate_map[ticker]
                kept.append(
                    Position(
                        ticker=ticker,
                        weight=0.05,
                        rationale=(
                            "Replacement selected by slot-cost filter: stronger short-term acceleration "
                            "or cleaner momentum than removed alternatives."
                        ),
                    )
                )

        if removed:
            logger.info("Selection-quality filter removed: %s", ", ".join(sorted(removed)))

        if not kept:
            return proposal

        # Pass A — Overbought-at-peak cap (Rule 18): code-enforced hard cap
        for i, pos in enumerate(kept):
            c = candidate_map.get(pos.ticker, {})
            rsi = c.get("rsi_14", float("nan"))
            pct_high = c.get("pct_from_52w_high", float("nan"))
            vol_ratio = c.get("vol_ratio", float("nan"))
            overbought = (
                not math.isnan(rsi) and rsi > 82
                and not math.isnan(pct_high) and pct_high >= -0.02
                and (math.isnan(vol_ratio) or vol_ratio <= 1.8)
            )
            if overbought and pos.weight > 0.15:
                kept[i] = Position(ticker=pos.ticker, weight=0.15, rationale=pos.rationale)
                logger.info(
                    "Overbought-peak cap: %s → 15%% (RSI %.0f, 52wH %+.1f%%)",
                    pos.ticker, rsi, pct_high * 100,
                )

        # Pass B — Devil accuracy cap (Rule 19): code-enforced hard cap
        devil = load_learning_state().get("devil_accuracy", {})
        if devil.get("devil_is_accurate"):
            for i, pos in enumerate(kept):
                bear = bear_cases.get(pos.ticker, {})
                if bear.get("risk") == "HIGH" and pos.weight > 0.10:
                    kept[i] = Position(ticker=pos.ticker, weight=0.10, rationale=pos.rationale)
                    logger.info(
                        "Devil accuracy cap: %s → 10%% (Devil accuracy active, HIGH flag)",
                        pos.ticker,
                    )

        learning_state = load_learning_state()
        raw_caps = learning_state.get("weight_caps", [])
        ticker_caps: dict[str, tuple[float, str]] = {}
        for cap in raw_caps:
            if not isinstance(cap, dict):
                continue
            if cap.get("scope") != "ticker":
                continue
            ticker = cap.get("ticker")
            max_weight = cap.get("max_weight")
            if not isinstance(ticker, str):
                continue
            try:
                cap_value = float(max_weight)
            except (TypeError, ValueError):
                continue
            if cap_value <= 0:
                continue
            cap_reason = str(cap.get("reason", "learning_state_cap"))
            ticker_caps[ticker] = (cap_value, cap_reason)

        for i, pos in enumerate(kept):
            cap_info = ticker_caps.get(pos.ticker)
            if not cap_info:
                continue
            max_weight, cap_reason = cap_info
            if pos.weight > max_weight:
                old_weight = pos.weight
                kept[i] = Position(ticker=pos.ticker, weight=max_weight, rationale=pos.rationale)
                logger.info(
                    "Learning cap: %s %.0f%% → %.0f%% (%s)",
                    pos.ticker,
                    old_weight * 100,
                    max_weight * 100,
                    cap_reason,
                )

        total_weight = sum(p.weight for p in kept)
        if total_weight <= 0:
            return proposal

        weights = [p.weight / total_weight for p in kept]
        kept = [
            Position(ticker=p.ticker, weight=w, rationale=p.rationale)
            for p, w in zip(kept, weights)
        ]

        return PortfolioProposal(
            positions=kept,
            reasoning=proposal.reasoning,
            confidence=proposal.confidence,
            learning_reflection=proposal.learning_reflection,
        )

    @staticmethod
    def _merge_proposals(
        strategist: PortfolioProposal,
        challenger: Optional[PortfolioProposal],
        full_analyst: Optional[PortfolioProposal] = None,
    ) -> PortfolioProposal:
        """Equal-weight merge fallback when meta-analyst fails entirely."""
        proposals = [strategist]
        weights_per_proposal = [0.50]
        if challenger and challenger.positions:
            proposals.append(challenger)
            weights_per_proposal = [0.40, 0.35]
        if full_analyst and full_analyst.positions:
            proposals.append(full_analyst)
            # Normalize weights to sum to 1
            total_w = sum(weights_per_proposal) + 0.25
            weights_per_proposal = [w / total_w for w in weights_per_proposal] + [0.25 / total_w]

        merged: dict[str, list] = {}
        for proposal, prop_weight in zip(proposals, weights_per_proposal):
            for p in proposal.positions:
                w = p.weight * prop_weight
                if p.ticker in merged:
                    old_w, old_r = merged[p.ticker][0]
                    merged[p.ticker] = [(old_w + w, old_r)]
                else:
                    merged[p.ticker] = [(w, p.rationale)]

        positions = [
            Position(ticker=t, weight=min(0.25, max(0.05, w)), rationale=r)
            for t, [(w, r)] in merged.items()
        ]
        total = sum(p.weight for p in positions)
        if total > 0:
            positions = [
                Position(ticker=p.ticker, weight=p.weight / total, rationale=p.rationale)
                for p in positions
            ]
        return PortfolioProposal(
            positions=positions,
            reasoning="Weighted merge fallback (meta-analyst unavailable)",
            confidence=0.5,
        )

    def _build_message(
        self,
        strategist: PortfolioProposal,
        challenger: Optional[PortfolioProposal],
        snapshot: MarketSnapshot,
        bear_cases: Optional[dict] = None,
        full_analyst: Optional[PortfolioProposal] = None,
    ) -> str:
        regime = snapshot.get("regime", "NEUTRAL")
        spx_vs = snapshot.get("spx_vs_200d", 0.0)
        vix = snapshot.get("vix_level", float("nan"))
        vix_str = f"{vix:.1f}" if not math.isnan(vix) else "N/A"

        # Compute portfolio betas for context
        strat_beta = self._portfolio_beta(strategist, snapshot)
        strat_beta_str = f"{strat_beta:.2f}" if not math.isnan(strat_beta) else "N/A"
        beta_targets = {"BULL": "target ≤2.0", "BEAR": "target ≤0.90", "NEUTRAL": "target 0.95–1.30"}
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

        comm = snapshot.get("commodity_context", {})
        comm_line = ""
        brent = comm.get("brent_price", float("nan"))
        if not math.isnan(brent):
            brent_20d = comm.get("brent_20d", float("nan"))
            wti = comm.get("wti_price", float("nan"))
            wti_20d = comm.get("wti_20d", float("nan"))
            natgas = comm.get("natgas_price", float("nan"))
            natgas_20d = comm.get("natgas_20d", float("nan"))
            comm_line = (
                f"Commodities: Brent ${brent:.1f} ({brent_20d:+.1%} 20d) | "
                f"WTI ${wti:.1f} ({wti_20d:+.1%} 20d) | "
                f"NatGas ${natgas:.2f} ({natgas_20d:+.1%} 20d)"
                if not math.isnan(wti) and not math.isnan(natgas) else
                f"Commodities: Brent ${brent:.1f} ({brent_20d:+.1%} 20d)"
            )

        # Sector rotation context
        sector_mom = snapshot.get("sector_momentum", {})
        sector_rotation_line = ""
        if sector_mom:
            _valid = sorted(
                [(s, d) for s, d in sector_mom.items()
                 if not math.isnan(d.get("avg_mom_20d", float("nan"))) and d.get("count", 0) >= 2],
                key=lambda x: x[1]["avg_mom_20d"], reverse=True,
            )
            if _valid:
                _parts = []
                for s, d in _valid[:5]:
                    br = d.get("breadth", float("nan"))
                    br_s = f" ({br:.0%})" if not math.isnan(br) else ""
                    _parts.append(f"{s} {d['avg_mom_20d']:+.1%}{br_s}")
                _lag = [s for s, d in _valid if d["avg_mom_20d"] < 0]
                sector_rotation_line = f"Sector rotation (20d, breadth): {' | '.join(_parts[:5])}"
                if _lag:
                    sector_rotation_line += f"  |  Laggards: {', '.join(_lag[:4])}"

        game_equity = snapshot.get("game_equity", 10000.0)
        game_ret = snapshot.get("game_return_pct", 0.0)
        lines = [
            f"## Synthesis task — {date.today().isoformat()}",
            f"Game account: €{game_equity:,.0f} ({game_ret:+.2%} since start) — competition mindset required.",
            f"Regime: {regime} | SPX vs 200d: {spx_vs:+.1%} | VIX: {vix_str} | S&P 500 20d: {snapshot['benchmark_return']:+.1%}",
            f"Breadth: {breadth_str} above 50d SMA | VIX term: {term_str} | Credit spreads 20d: {credit_str}",
            f"Composite regime score: {rscore}/100 — {score_label}",
            f"Strategist proposal portfolio beta: {strat_beta_str} ({beta_target_str} for {regime} regime)",
        ]
        if comm_line:
            lines.append(comm_line)
        if sector_rotation_line:
            lines.append(sector_rotation_line)
        rotation_risk = snapshot.get("rotation_risk", {})
        if rotation_risk:
            high = [(s, i) for s, i in rotation_risk.items() if i["level"] == "HIGH"]
            med = [(s, i) for s, i in rotation_risk.items() if i["level"] == "MEDIUM"]
            alert_lines = ["ROTATION RISK ALERT:"]
            for s, i in sorted(high + med, key=lambda x: x[1]["level"]):
                alert_lines.append(f"  {i['level']}: {s} — {i['reason']}")
            if high:
                alert_lines.append(f"  Action: Reduce or exit {', '.join(s for s, _ in high)} before rotation completes.")
            lines += [""] + alert_lines
        lines += [
            "Analyst consensus note: AnaRtg 1=StrongBuy→5=StrongSell; AnaUp% = (target−price)/price. Use as cross-check on weight decisions — high momentum + analyst upside = conviction; high momentum + negative analyst upside = stretched/crowded, consider capping.",
            "",
        ]

        if snapshot.get("learning_context"):
            lines += [
                "### LEARNING CONSTRAINTS — APPLY BEFORE SYNTHESIS",
                snapshot["learning_context"],
                "",
            ]

        candidate_map = {c["ticker"]: c for c in snapshot["candidates"]}

        # Find consensus tickers (appear in 2+ of the 3 proposals)
        strat_tickers = {p.ticker for p in strategist.positions}
        chall_tickers = {p.ticker for p in challenger.positions} if challenger and challenger.positions else set()
        full_tickers = {p.ticker for p in full_analyst.positions} if full_analyst and full_analyst.positions else set()

        # Count appearances across proposals
        all_tickers = strat_tickers | chall_tickers | full_tickers
        consensus = {t for t in all_tickers if sum([t in strat_tickers, t in chall_tickers, t in full_tickers]) >= 2}
        triple = {t for t in all_tickers if sum([t in strat_tickers, t in chall_tickers, t in full_tickers]) == 3}

        if triple:
            lines.append(f"🌟 TRIPLE CONSENSUS (all 3 proposals — maximum conviction): {', '.join(sorted(triple))}")
            lines.append("")
        if consensus - triple:
            lines.append(f"⭐ DOUBLE CONSENSUS (2/3 proposals — high conviction): {', '.join(sorted(consensus - triple))}")
            lines.append("")

        def _fmt_row(p, consensus_set: set, candidate_map: dict) -> str:
            tag = " 🌟" if p.ticker in triple else (" ⭐" if p.ticker in consensus_set else "")
            c = candidate_map.get(p.ticker, {})
            mom_5d = c.get("mom_5d", float("nan"))
            vol_ratio = c.get("vol_ratio", float("nan"))
            accel = (
                f" | 5d {mom_5d:+.1%} | vol {vol_ratio:.2f}"
                if not math.isnan(mom_5d) and not math.isnan(vol_ratio)
                else ""
            )
            return f"{p.ticker:<12} {p.weight:>7.1%}{tag}  {p.rationale[:40]}{accel}"

        # Strategist proposal
        strat_total = sum(p.weight for p in strategist.positions)
        lines += [
            f"### Proposal A — GPT-5.4 Momentum Strategist ({len(strategist.positions)} positions, {strat_total:.0%} total)",
            f"Thesis: {strategist.reasoning}",
            "",
            f"{'Ticker':<12} {'Weight':>8}  Rationale",
            "-" * 65,
        ]
        for p in strategist.positions:
            lines.append(_fmt_row(p, consensus, candidate_map))

        lines.append("")

        # Gemini Challenger proposal
        if challenger and challenger.positions:
            chall_total = sum(p.weight for p in challenger.positions)
            lines += [
                f"### Proposal B — Gemini Catalyst Hunter ({len(challenger.positions)} positions, {chall_total:.0%} total)",
                f"Thesis: {challenger.reasoning}",
                "",
                f"{'Ticker':<12} {'Weight':>8}  Rationale",
                "-" * 65,
            ]
            for p in challenger.positions:
                lines.append(_fmt_row(p, consensus, candidate_map))
        else:
            lines += [
                "### Proposal B — Gemini Catalyst Hunter",
                "Not available — weight Proposal A and C more heavily.",
            ]

        lines.append("")

        # Full Analyst proposal
        if full_analyst and full_analyst.positions:
            full_total = sum(p.weight for p in full_analyst.positions)
            lines += [
                f"### Proposal C — GPT-5.4-nano Full Analyst ({len(full_analyst.positions)} positions, {full_total:.0%} total)",
                f"Thesis: {full_analyst.reasoning}",
                "",
                f"{'Ticker':<12} {'Weight':>8}  Rationale",
                "-" * 65,
            ]
            for p in full_analyst.positions:
                lines.append(_fmt_row(p, consensus, candidate_map))
        else:
            lines += [
                "### Proposal C — GPT-5.4-nano Full Analyst",
                "Not available — use Proposals A and B.",
            ]

        # Sector concentration summary across all proposals
        all_proposals = [
            ("Strategist", strategist),
            ("Gemini", challenger),
            ("FullAnalyst", full_analyst),
        ]
        sector_weights: dict[str, float] = {}
        total_weight_all = 0.0
        for _, proposal in all_proposals:
            if proposal and proposal.positions:
                for p in proposal.positions:
                    sec = candidate_map.get(p.ticker, {}).get("sector", "?")
                    sector_weights[sec] = sector_weights.get(sec, 0.0) + p.weight
                    total_weight_all += p.weight
        if sector_weights and total_weight_all > 0:
            top_sectors = sorted(sector_weights.items(), key=lambda x: -x[1])
            sector_lines = [f"{s}: {w / total_weight_all:.0%}" for s, w in top_sectors[:5]]
            dominant = top_sectors[0]
            concentration_note = ""
            if dominant[1] / total_weight_all > 0.60:
                concentration_note = (
                    f" ⚠️ {dominant[0]} dominates at {dominant[1]/total_weight_all:.0%} of combined proposals. "
                    "If signals genuinely justify concentration, that is fine — but explicitly state your reasoning. "
                    "Consider whether 1 non-correlated pick would improve risk-adjusted return without sacrificing conviction."
                )
            lines += [
                "",
                f"### Sector concentration across all proposals: {' | '.join(sector_lines)}{concentration_note}",
            ]

        # High-overlap consensus warning (must appear prominently before other context)
        if snapshot.get("consensus_warning"):
            lines += [
                "",
                "### ⚠️ CONSENSUS WARNING — DAILY TRADING MANDATE",
                snapshot["consensus_warning"],
            ]

        if snapshot.get("earnings_warning"):
            lines += ["", snapshot["earnings_warning"]]

        debate_summary = snapshot.get("debate_summary", "")
        if debate_summary:
            lines += ["", "### Cross-Agent Debate Summary", debate_summary]

        decay = snapshot.get("strategy_decay", {})
        if decay.get("decay_detected"):
            lines += [
                "",
                f"### STRATEGY DECAY ALERT",
                f"Recent alpha has dropped to {decay['recent_avg_alpha']:+.2%}/day "
                f"(was {decay['prior_avg_alpha']:+.2%}/day over prior {decay['prior_days']} days, "
                f"decay magnitude: {decay['decay_magnitude']:+.4f}).",
                "Consider: (a) rotating into a different sector, (b) reducing highest-beta positions, "
                "(c) checking if our top picks have become consensus crowded trades.",
            ]

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
            "### Slot-Cost and Selectivity Rules",
            "Every slot must beat the next-best alternative. In a 5-stock competition portfolio, do not keep a merely acceptable name if another proposal offered a cleaner, faster mover.",
            "CAUTIOUS regime-score handling: remain concentrated, but cut slow or dead-money names rather than padding with soft holdings.",
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
            temperature=0.15,
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
            learning_reflection=data.get("learning_reflection", ""),
        )
