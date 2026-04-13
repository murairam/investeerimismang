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
import config
from data.cost_tracker import log_usage
from data.fetcher import MarketSnapshot, sanitize_ticker
from data.learning_state import load_learning_state
from portfolio.models import PortfolioProposal, Position
from portfolio.validator import PortfolioValidator

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a meta-analyst for the Äripäev/SEB Investment Game (Estonia). You receive THREE independent portfolio proposals and synthesize the best final portfolio:
- Proposal A: GPT-5.4 Momentum Strategist (sees only trend/Sharpe signals)
- Proposal B: Gemini Catalyst Hunter (sees only catalyst signals: vol_ratio, RSI, short interest, IV)
- Proposal C: GPT-5.4-nano Full Analyst (sees ALL signals — fresh independent view)

A pick appearing in 2+ proposals is independently validated consensus — treat it as higher conviction.

Game ends 19 June 2026. Goal: highest absolute return, beating other participants.

## Competition mandate
This is a competition with {n_participants} participants. Only #1 wins — median returns = losing. INTELLIGENT AGGRESSION is required. 15% drawdown is acceptable if it gives 40% upside potential — price risk for competition, not wealth management. Follow the signals. Do not apply any sector or stock bias — the data tells you what is working today. Competition rewards right-tail outcomes: concentrate in 5-6 names with real momentum catalysts.

## Synthesis rules
**RULE #1 — MANDATORY: ASSIGN CONVICTION SCORES (1-10). DO NOT OUTPUT WEIGHTS.**
- 10 = max conviction (multi-source consensus + strongest evidence)
- 8-9 = high conviction
- 5-7 = medium conviction
- 1-4 = low conviction
Position sizing is computed downstream by Kelly math.

0. **Target position count by regime** — you decide the exact count based on signal quality:
   - BULL: 5–6 positions. TARGET 5 positions with conviction 8–10. Only add a 6th if genuinely high-conviction (>=7).
   - NEUTRAL: 5–8 positions. Keep concentration high; no filler names.
   - BEAR: 6–12 positions. Spread risk more broadly.
   Build in order: (1) consensus picks, (2) best unique picks.
1. **Consensus picks** (appear in 2+ of the 3 proposals): independently validated across different signal lenses. Give them higher conviction scores (8–10) unless there is a specific risk reason not to.
2. **Unique picks**: evaluate on their own merits — Sharpe, momentum, vol_ratio, regime fit. Include the best ones.
3. **Ignore weak unique picks**: if only one model picked something and its signals are mediocre, skip it.
4. **Consensus conviction floor (MANDATORY)**: ticker in exactly 2 of 3 proposals → minimum conviction 8 (unless Devil flags HIGH risk). Ticker in all 3 proposals → minimum conviction 9 (unless Devil flags HIGH risk). Do not assign below these floors — ensemble agreement IS the signal.
5. **Score by conviction** (see RULE #1 above): consensus 8–10, strong single-model 6–8, diversifiers 3–6.
   Conviction → weight mapping (Python-computed): 10→~25% | 9→~22% | 8→~20% | 7→~18% | 6→~16% | 5→~13% | 4→~11% | 3→~9% | 2→~7% | 1→~5%
6. **Check market concentration**: if >65% ends up in one market, redistribute unless signal concentration is clearly superior.
7. **Check regime fit and portfolio beta**:
   - You will be given the portfolio-weighted beta computed from the proposals.
   - BEAR regime: target portfolio beta ≤ 0.90. Cap individual positions at 15%.
   - BULL regime: TARGET portfolio beta 1.6–2.0. Concentrate on high-beta names — sub-1.4 beta in BULL is underperforming the mandate.
    - NEUTRAL: soft target portfolio beta between 0.95 and 1.30 in normal conditions.
    - If the user context includes a ROTATION RISK ALERT (HIGH/MEDIUM) or clear sector-rotation leadership, treat NEUTRAL beta as a SOFT diagnostic, not a hard objective. Do NOT add high-beta filler names solely to raise beta if that dilutes the strongest rotation leaders.
8. **Acceleration matters**: prefer active movers. If two stocks are similar on 20d momentum, keep the one with better 5d momentum and stronger volume confirmation.
9. **Slot cost rule**: every position must earn its slot. Do not include a merely acceptable stock if a better alternative from either proposal exists.
10. **Earnings timing rule**: pre-earnings setups can be high conviction; earnings in <=1 day should be low conviction due to binary gap risk.
11. **Risk overlays**: respect Devil HIGH/MEDIUM risk assessments and learning-state constraints.

## Guardrail ownership
Hard game constraints and final weight bounds are enforced by Python validator logic. Focus this synthesis on ranking and conviction quality, not on re-deriving hard bounds.

## Hard constraints
- 5 to 20 stocks.
- No duplicate tickers.
- Every position must include a conviction integer from 1 to 10.

## Output — JSON only
CRITICAL: output `conviction` (1-10), not `weight`.

{{
    "positions": [
        {{
            "ticker": "TICKER",
            "conviction": 9,
            "rationale": "consensus/unique pick + one-sentence reason for this conviction score."
        }}
    ],
    "reasoning": "2–3 sentences: what consensus existed, what catalyst picks you included, and portfolio beta vs target.",
    "confidence": 0.80,
    "learning_reflection": "One sentence: how today's synthesis adapts based on recent learning context."
}}"""


class OpenAIRiskManager(BaseAgent):
    MODEL = "gpt-5.4"
    MAX_RETRIES = 3

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

        n_participants = snapshot.get("n_participants", 844)
        last_error: Optional[Exception] = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                result = self._call_openai(user_message, n_participants)
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
                last_error = exc
                logger.warning("Meta-analyst attempt %d/%d failed: %s", attempt, self.MAX_RETRIES, exc)

        logger.error(
            "Risk Manager failed after %d retries — using deterministic ranked-candidates fallback (%s)",
            self.MAX_RETRIES,
            last_error,
        )
        return self._fallback_top_ranked(snapshot)

    @staticmethod
    def _portfolio_beta(proposal: PortfolioProposal, snapshot: MarketSnapshot) -> float:
        """Compute weighted-average beta of a proposal using the candidate beta values.

        Uses only observed beta values from snapshot candidates. Missing betas are excluded
        rather than replaced with fixed assumptions.
        """
        beta_map = {
            c["ticker"]: c["beta"]
            for c in snapshot["candidates"]
            if not math.isnan(c.get("beta", float("nan")))
        }
        weighted_sum = 0.0
        covered_weight = 0.0
        for p in proposal.positions:
            if p.ticker in beta_map:
                weighted_sum += p.weight * beta_map[p.ticker]
                covered_weight += p.weight
            # Missing beta ticker: exclude from both numerator and denominator
        if covered_weight == 0.0:
            return float("nan")
        return weighted_sum / covered_weight

    def _enforce_sector_rotation_cap(
        self,
        proposal: PortfolioProposal,
        snapshot: MarketSnapshot,
    ) -> PortfolioProposal:
        """
        Hard-cap sector concentration when rotation_risk signals exhaustion.
        Uses sector tags from candidate records (same source as fetcher signals).

        Trimmed weight is redistributed to positions OUTSIDE the capped sector(s)
        proportionally by headroom (max_weight - current_weight), so the capped
        sector is never scaled back above its cap by renormalization.
        """
        rotation_risk: dict = snapshot.get("rotation_risk", {})
        candidate_map = {c["ticker"]: c for c in snapshot["candidates"]}
        min_w = config.GAME_CONSTRAINTS["min_weight"]
        max_w = config.GAME_CONSTRAINTS["max_weight"]

        def _sector_of(ticker: str) -> str:
            c = candidate_map.get(ticker, {})
            return c.get("sector") or config.SECTOR_MAP.get(ticker, "?")

        # Build sector → effective cap (lowest applicable cap wins)
        sector_caps: dict[str, float] = {}
        for sector, info in rotation_risk.items():
            level = info.get("level", "")
            if level == "HIGH":
                sector_caps[sector] = config.SECTOR_ROTATION_CAP_HIGH
            elif level == "MEDIUM":
                sector_caps[sector] = config.SECTOR_ROTATION_CAP_MEDIUM

        # Compute current sector weights
        sector_weights: dict[str, float] = {}
        for pos in proposal.positions:
            s = _sector_of(pos.ticker)
            sector_weights[s] = sector_weights.get(s, 0.0) + pos.weight

        # Determine which sectors need trimming and by how much
        effective_caps: dict[str, float] = {}
        for sector, weight in sector_weights.items():
            cap = config.SECTOR_CAP_UNCONDITIONAL
            if sector in sector_caps:
                cap = min(cap, sector_caps[sector])
            if weight > cap + 1e-9:
                effective_caps[sector] = cap

        if not effective_caps:
            return proposal

        positions = list(proposal.positions)
        total_freed: float = 0.0
        capped_sectors = set(effective_caps.keys())

        for sector, cap in effective_caps.items():
            current = sum(p.weight for p in positions if _sector_of(p.ticker) == sector)
            if current <= cap + 1e-9:
                continue
            excess = current - cap
            logger.warning(
                "Sector rotation cap: %s at %.0f%% exceeds %s cap of %.0f%% — trimming %.0f%%",
                sector, current * 100,
                "rotation-risk" if sector in sector_caps else "unconditional",
                cap * 100, excess * 100,
            )
            # Trim from heaviest positions in this sector first
            sector_indices = sorted(
                [i for i, p in enumerate(positions) if _sector_of(p.ticker) == sector],
                key=lambda i: positions[i].weight,
                reverse=True,
            )
            remaining = excess
            for idx in sector_indices:
                if remaining <= 1e-9:
                    break
                pos = positions[idx]
                trim = min(remaining, pos.weight - min_w)
                if trim > 1e-9:
                    positions[idx] = Position(
                        ticker=pos.ticker,
                        weight=pos.weight - trim,
                        rationale=pos.rationale,
                        conviction=pos.conviction,
                    )
                    remaining -= trim
            total_freed += excess - remaining  # actual amount trimmed (may be < excess if all at min_w)

        # Redistribute freed weight to positions OUTSIDE all capped sectors,
        # proportionally by headroom, so capped sectors are never scaled back up.
        if total_freed > 1e-9:
            uncapped = [i for i, p in enumerate(positions) if _sector_of(p.ticker) not in capped_sectors]
            headroom = [max(0.0, max_w - positions[i].weight) for i in uncapped]
            total_headroom = sum(headroom)
            if total_headroom > 1e-9:
                for list_idx, port_idx in enumerate(uncapped):
                    share = headroom[list_idx] / total_headroom
                    pos = positions[port_idx]
                    positions[port_idx] = Position(
                        ticker=pos.ticker,
                        weight=min(max_w, pos.weight + total_freed * share),
                        rationale=pos.rationale,
                        conviction=pos.conviction,
                    )
            else:
                # All uncapped positions are already at max_weight — leave as residual cash
                logger.warning(
                    "Sector cap freed %.0f%% but all non-capped positions are at max_weight — "
                    "leaving as cash (%.0f%% total)",
                    total_freed * 100,
                    sum(p.weight for p in positions) * 100,
                )

        return PortfolioProposal(
            positions=positions,
            reasoning=proposal.reasoning,
            confidence=proposal.confidence,
            learning_reflection=proposal.learning_reflection,
        )

    def _enforce_vix_stress_cap(
        self,
        proposal: PortfolioProposal,
        snapshot: MarketSnapshot,
    ) -> PortfolioProposal:
        """
        Hard-cap individual positions with beta > STRESS_INDIVIDUAL_BETA_CAP at
        OVERBOUGHT_WEIGHT_CAP when VIX >= VIX_STRESS_THRESHOLD in NEUTRAL regime.

        Called AFTER all normalization and rounding in the orchestrator so that
        normalize() / round_to_whole_pct() cannot re-inflate the capped weights.
        Any freed weight that cannot be redistributed (because uncapped positions
        are already at max_weight) remains as implicit cash — the game rule only
        requires ≥75% invested, so this is always safe.
        """
        regime = snapshot.get("regime", "")
        vix = snapshot.get("vix_level", 0) or 0
        if regime != "NEUTRAL" or vix < config.VIX_STRESS_THRESHOLD:
            return proposal

        cap = config.OVERBOUGHT_WEIGHT_CAP
        max_w = config.GAME_CONSTRAINTS["max_weight"]
        beta_map = {
            c["ticker"]: c["beta"]
            for c in snapshot["candidates"]
            if not math.isnan(c.get("beta", float("nan")))
        }

        positions = list(proposal.positions)
        capped_indices: set[int] = set()
        freed_weight = 0.0
        for i, p in enumerate(positions):
            stock_beta = beta_map.get(p.ticker, float("nan"))
            if not math.isnan(stock_beta) and stock_beta > config.STRESS_INDIVIDUAL_BETA_CAP and p.weight > cap:
                freed_weight += p.weight - cap
                positions[i] = Position(ticker=p.ticker, weight=cap, rationale=p.rationale, conviction=p.conviction)
                capped_indices.add(i)
                logger.warning(
                    "VIX stress cap (final): %s beta %.2f → weight %.0f%% capped to %.0f%% (VIX %.1f)",
                    p.ticker, stock_beta, p.weight * 100, cap * 100, vix,
                )

        if not capped_indices:
            return proposal

        # Redistribute freed weight only to uncapped positions, bounded by max_weight.
        remaining = freed_weight
        for _ in range(len(positions)):
            headroom = {
                i: max_w - p.weight
                for i, p in enumerate(positions)
                if i not in capped_indices and max_w - p.weight > 1e-9
            }
            if not headroom or remaining < 1e-9:
                break
            total_headroom = sum(headroom.values())
            new_positions = list(positions)
            actually_added = 0.0
            for i, avail in headroom.items():
                add = min(avail, remaining * (avail / total_headroom))
                new_positions[i] = Position(
                    ticker=positions[i].ticker,
                    weight=positions[i].weight + add,
                    rationale=positions[i].rationale,
                    conviction=positions[i].conviction,
                )
                actually_added += add
            positions = new_positions
            remaining -= actually_added
            if remaining < 1e-9:
                break

        if remaining > 1e-9:
            logger.info(
                "VIX stress cap: %.1f%% freed weight could not be redistributed "
                "(uncapped positions at max_weight) — retained as cash buffer",
                remaining * 100,
            )

        # Re-apply cap as final guarantee after redistribution
        positions = [
            Position(
                ticker=p.ticker,
                weight=min(p.weight, cap) if i in capped_indices else p.weight,
                rationale=p.rationale,
                conviction=p.conviction,
            )
            for i, p in enumerate(positions)
        ]
        return PortfolioProposal(
            positions=positions,
            reasoning=proposal.reasoning,
            confidence=proposal.confidence,
            learning_reflection=proposal.learning_reflection,
        )

    def _enforce_beta(
        self,
        proposal: PortfolioProposal,
        snapshot: MarketSnapshot,
        regime: str,
        beta_targets: dict,
    ) -> PortfolioProposal:
        """Check portfolio beta against regime targets using observed beta coverage only."""
        actual_beta = self._portfolio_beta(proposal, snapshot)
        if math.isnan(actual_beta):
            logger.warning(
                "Portfolio beta could not be computed (all candidate betas are NaN) — "
                "beta enforcement skipped. Check fetcher beta calculation."
            )
            return proposal

        beta_map = {
            c["ticker"]: c["beta"]
            for c in snapshot["candidates"]
            if not math.isnan(c.get("beta", float("nan")))
        }
        covered_weight = sum(p.weight for p in proposal.positions if p.ticker in beta_map)
        if covered_weight < config.BETA_CHECK_MIN_US_WEIGHT:
            logger.info(
                "Portfolio beta check skipped: only %.0f%% of weight has observed beta coverage",
                covered_weight * 100,
            )
            return proposal

        lo, hi = beta_targets.get(regime, (None, None))
        in_range = (lo is None or actual_beta >= lo) and (hi is None or actual_beta <= hi)
        target_str = f"{lo:.2f}–{hi:.2f}" if (lo is not None and hi is not None) else f"≤{hi:.2f}" if hi is not None else "?"

        if in_range:
            logger.info(
                "Portfolio beta %.2f within target %s (coverage %.0f%%)",
                actual_beta, target_str, covered_weight * 100,
            )
        else:
            logger.warning(
                "Portfolio beta %.2f outside target %s (coverage %.0f%%)",
                actual_beta, target_str, covered_weight * 100,
            )
            if regime == "BEAR" and hi is not None and actual_beta > hi:
                logger.warning(
                    "BEAR regime beta too high (%.2f > %.2f) — capping positions at 15%%",
                    actual_beta, hi,
                )
                positions = [
                    Position(ticker=p.ticker, weight=min(p.weight, config.OVERBOUGHT_WEIGHT_CAP), rationale=p.rationale, conviction=p.conviction)
                    for p in proposal.positions
                ]
                total = sum(p.weight for p in positions)
                if total > 0:
                    positions = [
                        Position(ticker=p.ticker, weight=p.weight / total, rationale=p.rationale, conviction=p.conviction)
                        for p in positions
                    ]
                proposal = PortfolioProposal(
                    positions=positions,
                    reasoning=proposal.reasoning,
                    confidence=proposal.confidence,
                    learning_reflection=proposal.learning_reflection,
                )

        # VIX stress override: unconditional — fires regardless of whether portfolio beta
        # is in-range. In NEUTRAL with elevated VIX, cap any individual stock with
        # beta > STRESS_INDIVIDUAL_BETA_CAP at OVERBOUGHT_WEIGHT_CAP, then redistribute
        # freed weight only across uncapped positions to keep capped names at/below the cap.
        vix = snapshot.get("vix_level", 0) or 0
        if regime == "NEUTRAL" and vix >= config.VIX_STRESS_THRESHOLD:
            cap = config.OVERBOUGHT_WEIGHT_CAP
            positions = list(proposal.positions)
            capped_indices: set[int] = set()
            freed_weight = 0.0
            for i, p in enumerate(positions):
                stock_beta = beta_map.get(p.ticker, float("nan"))
                if not math.isnan(stock_beta) and stock_beta > config.STRESS_INDIVIDUAL_BETA_CAP and p.weight > cap:
                    freed_weight += p.weight - cap
                    positions[i] = Position(ticker=p.ticker, weight=cap, rationale=p.rationale, conviction=p.conviction)
                    capped_indices.add(i)
                    logger.warning(
                        "VIX stress cap: %s beta %.2f → weight %.0f%% capped to %.0f%% (VIX %.1f)",
                        p.ticker, stock_beta, p.weight * 100, cap * 100, vix,
                    )
            if capped_indices:
                # Redistribute freed weight only among uncapped positions, bounded by max_weight
                # so no uncapped position exceeds the game constraint (which would trigger
                # validator.normalize() and risk re-inflating the stress-capped names).
                max_w = config.GAME_CONSTRAINTS["max_weight"]
                remaining = freed_weight
                for _ in range(len(positions)):  # iterate until freed weight is fully absorbed
                    headroom = {i: max_w - p.weight for i, p in enumerate(positions) if i not in capped_indices and max_w - p.weight > 1e-9}
                    if not headroom or remaining < 1e-9:
                        break
                    total_headroom = sum(headroom.values())
                    new_positions = list(positions)
                    actually_added = 0.0
                    for i, avail in headroom.items():
                        add = min(avail, remaining * (avail / total_headroom))
                        new_positions[i] = Position(ticker=positions[i].ticker, weight=positions[i].weight + add, rationale=positions[i].rationale, conviction=positions[i].conviction)
                        actually_added += add
                    positions = new_positions
                    remaining -= actually_added
                    if remaining < 1e-9:
                        break
                # Re-apply VIX cap after redistribution to guarantee hard ceiling
                positions = [
                    Position(ticker=p.ticker, weight=min(p.weight, cap) if i in capped_indices else p.weight, rationale=p.rationale, conviction=p.conviction)
                    for i, p in enumerate(positions)
                ]
                proposal = PortfolioProposal(positions=positions, reasoning=proposal.reasoning, confidence=proposal.confidence, learning_reflection=proposal.learning_reflection)
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
            return vol_ratio < config.DEAD_MONEY_VOL_RATIO and mom_5d <= config.DEAD_MONEY_MOM_5D

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
                if candidate_score(ticker) < config.MIN_CANDIDATE_SCORE_FOR_SLOT:
                    continue
                c = candidate_map[ticker]
                kept.append(
                    Position(
                        ticker=ticker,
                        weight=config.FALLBACK_REPLACEMENT_WEIGHT,
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

        kept = self._rebalance_for_competition_edge(kept, candidate_map, bear_cases, regime_score)

        # Pass A — Overbought-at-peak cap (Rule 18): code-enforced hard cap
        # When a stock is overbought AND its sector has HIGH rotation risk, apply a tighter
        # per-position cap so that multiple overbought stocks in the same exhausted sector
        # cannot aggregate past the sector rotation cap.
        overbought_capped_indices: set[int] = set()
        ob_cap_by_index: dict[int, float] = {}  # track per-position effective cap for re-enforcement
        rotation_risk = snapshot.get("rotation_risk", {})
        for i, pos in enumerate(kept):
            c = candidate_map.get(pos.ticker, {})
            rsi = c.get("rsi_14", float("nan"))
            pct_high = c.get("pct_from_52w_high", float("nan"))
            vol_ratio = c.get("vol_ratio", float("nan"))
            overbought = (
                not math.isnan(rsi) and rsi > config.OVERBOUGHT_RSI_THRESHOLD
                and not math.isnan(pct_high) and pct_high >= -config.OVERBOUGHT_HIGH_PCT
                and (math.isnan(vol_ratio) or vol_ratio <= config.OVERBOUGHT_VOLUME_EXCEPTION)
            )
            if overbought:
                # Check sector rotation risk to determine effective cap
                sector = c.get("sector") or config.SECTOR_MAP.get(pos.ticker, "")
                sector_rot_level = (rotation_risk.get(sector) or {}).get("level", "")
                if sector_rot_level == "HIGH":
                    # Tighter cap: HIGH rotation + overbought → cap at 1/3 of sector rotation cap
                    effective_ob_cap = min(config.OVERBOUGHT_WEIGHT_CAP,
                                          config.SECTOR_ROTATION_CAP_HIGH / 3)
                elif sector_rot_level == "MEDIUM":
                    effective_ob_cap = min(config.OVERBOUGHT_WEIGHT_CAP,
                                          config.SECTOR_ROTATION_CAP_MEDIUM / 3)
                else:
                    effective_ob_cap = config.OVERBOUGHT_WEIGHT_CAP
                if pos.weight > effective_ob_cap:
                    kept[i] = Position(ticker=pos.ticker, weight=effective_ob_cap, rationale=pos.rationale, conviction=pos.conviction)
                    overbought_capped_indices.add(i)
                    ob_cap_by_index[i] = effective_ob_cap
                    logger.info(
                        "Overbought-peak cap: %s → %.0f%% (RSI %.0f, 52wH %+.1f%%, sector=%s rot=%s)",
                        pos.ticker, effective_ob_cap * 100, rsi, pct_high * 100,
                        sector or "?", sector_rot_level or "none",
                    )

        # Pass B — Devil accuracy cap (Rule 19): code-enforced tiered cap
        devil_capped_indices: set[int] = set()
        devil_cap_by_index: dict[int, float] = {}  # track per-position cap for re-enforcement
        learning_state = load_learning_state()
        devil = learning_state.get("devil_accuracy", {})
        if devil.get("devil_is_accurate"):
            for i, pos in enumerate(kept):
                bear = bear_cases.get(pos.ticker, {})
                risk_level = bear.get("risk", "")
                if risk_level == "HIGH" and pos.weight > config.DEVIL_CAP_HIGH:
                    kept[i] = Position(ticker=pos.ticker, weight=config.DEVIL_CAP_HIGH, rationale=pos.rationale, conviction=pos.conviction)
                    devil_capped_indices.add(i)
                    devil_cap_by_index[i] = config.DEVIL_CAP_HIGH
                    logger.info(
                        "Devil accuracy cap: %s → %.0f%% (Devil accuracy active, HIGH flag)",
                        pos.ticker, config.DEVIL_CAP_HIGH * 100,
                    )
                elif risk_level == "MEDIUM" and pos.weight > config.DEVIL_CAP_MEDIUM:
                    kept[i] = Position(ticker=pos.ticker, weight=config.DEVIL_CAP_MEDIUM, rationale=pos.rationale, conviction=pos.conviction)
                    devil_capped_indices.add(i)
                    devil_cap_by_index[i] = config.DEVIL_CAP_MEDIUM
                    logger.info(
                        "Devil accuracy cap: %s → %.0f%% (Devil accuracy active, MEDIUM flag)",
                        pos.ticker, config.DEVIL_CAP_MEDIUM * 100,
                    )
        raw_caps = learning_state.get("weight_caps", [])
        ticker_caps: dict[str, tuple[float, str]] = {}
        # rationale_tag_caps: tag keyword → (max_weight, reason)
        rationale_tag_caps: dict[str, tuple[float, str]] = {}
        global_cap: Optional[tuple[float, str]] = None
        for cap in raw_caps:
            if not isinstance(cap, dict):
                continue
            scope = cap.get("scope")
            max_weight = cap.get("max_weight")
            try:
                cap_value = float(max_weight)
            except (TypeError, ValueError):
                continue
            if cap_value <= 0:
                continue
            cap_reason = str(cap.get("reason", "learning_state_cap"))
            if scope == "global":
                if global_cap is None or cap_value < global_cap[0]:
                    global_cap = (cap_value, cap_reason)
            elif scope == "ticker":
                ticker = cap.get("ticker")
                if isinstance(ticker, str):
                    ticker_caps[ticker] = (cap_value, cap_reason)
            elif scope == "rationale_tag":
                tag = cap.get("tag")
                if isinstance(tag, str):
                    rationale_tag_caps[tag] = (cap_value, cap_reason)

        # Apply global cap to all positions
        if global_cap is not None:
            gc_value, gc_reason = global_cap
            for i, pos in enumerate(kept):
                if pos.weight > gc_value:
                    logger.info(
                        "Global cap: %s %.0f%% → %.0f%% (%s)",
                        pos.ticker, pos.weight * 100, gc_value * 100, gc_reason,
                    )
                    kept[i] = Position(ticker=pos.ticker, weight=gc_value, rationale=pos.rationale, conviction=pos.conviction)

        for i, pos in enumerate(kept):
            cap_info = ticker_caps.get(pos.ticker)
            if not cap_info:
                continue
            max_weight, cap_reason = cap_info
            if pos.weight > max_weight:
                old_weight = pos.weight
                kept[i] = Position(ticker=pos.ticker, weight=max_weight, rationale=pos.rationale, conviction=pos.conviction)
                logger.info(
                    "Learning cap: %s %.0f%% → %.0f%% (%s)",
                    pos.ticker,
                    old_weight * 100,
                    max_weight * 100,
                    cap_reason,
                )

        # Pass C2 — Rationale-tag caps: positions whose rationale text contains a
        # low-hit-rate tag keyword are capped. Promoted from bias-to-avoid after
        # hit_rate < 30% with ≥8 observations.
        for i, pos in enumerate(kept):
            rationale_lower = (pos.rationale or "").lower()
            for tag, (max_weight, cap_reason) in rationale_tag_caps.items():
                if tag.lower() in rationale_lower and pos.weight > max_weight:
                    old_weight = pos.weight
                    kept[i] = Position(ticker=pos.ticker, weight=max_weight, rationale=pos.rationale, conviction=pos.conviction)
                    logger.info(
                        "Rationale-tag cap: %s %.0f%% → %.0f%% (tag '%s' %s)",
                        pos.ticker,
                        old_weight * 100,
                        max_weight * 100,
                        tag,
                        cap_reason,
                    )
                    break  # apply the most restrictive matching tag only

        total_weight = sum(p.weight for p in kept)
        if total_weight <= 0:
            return proposal

        weights = [p.weight / total_weight for p in kept]
        kept = [
            Position(ticker=p.ticker, weight=w, rationale=p.rationale, conviction=p.conviction)
            for p, w in zip(kept, weights)
        ]

        def _redistribute_excess(
            positions: list[Position],
            excess: float,
            blocked_indices: set[int],
        ) -> list[Position]:
            if excess <= 1e-9:
                return positions
            max_weight = config.GAME_CONSTRAINTS["max_weight"]
            eligible = [i for i, p in enumerate(positions) if i not in blocked_indices and p.weight < max_weight]
            if not eligible:
                return positions
            headrooms = {i: max_weight - positions[i].weight for i in eligible}
            total_headroom = sum(headrooms.values())
            if total_headroom <= 1e-9:
                return positions
            updated = positions[:]
            for i in eligible:
                delta = excess * (headrooms[i] / total_headroom)
                updated[i] = Position(
                    ticker=updated[i].ticker,
                    weight=updated[i].weight + delta,
                    rationale=updated[i].rationale,
                    conviction=updated[i].conviction,
                )
            return updated

        # Re-enforce overbought cap after normalization — normalization inflates capped weights.
        # Use per-position effective cap (which may be tighter than OVERBOUGHT_WEIGHT_CAP
        # when sector rotation risk is HIGH or MEDIUM).
        ob_excess = 0.0
        for i, pos in enumerate(kept):
            if i in overbought_capped_indices:
                cap_val = ob_cap_by_index.get(i, config.OVERBOUGHT_WEIGHT_CAP)
                if pos.weight > cap_val:
                    ob_excess += pos.weight - cap_val
                    kept[i] = Position(ticker=pos.ticker, weight=cap_val, rationale=pos.rationale, conviction=pos.conviction)
        if ob_excess > 1e-9:
            kept = _redistribute_excess(kept, ob_excess, overbought_capped_indices)

        # Re-enforce devil accuracy caps after normalization — use per-index cap value.
        devil_excess = 0.0
        for i, pos in enumerate(kept):
            if i in devil_capped_indices:
                cap_val = devil_cap_by_index.get(i, config.DEVIL_CAP_HIGH)
                if pos.weight > cap_val:
                    devil_excess += pos.weight - cap_val
                    kept[i] = Position(ticker=pos.ticker, weight=cap_val, rationale=pos.rationale, conviction=pos.conviction)
        if devil_excess > 1e-9:
            kept = _redistribute_excess(kept, devil_excess, devil_capped_indices | overbought_capped_indices)

        # Re-enforce ticker caps after normalization to avoid cap drift.
        capped_excess = 0.0
        capped_indices: set[int] = set()
        for i, pos in enumerate(kept):
            cap_info = ticker_caps.get(pos.ticker)
            if not cap_info:
                continue
            max_weight, _ = cap_info
            if pos.weight > max_weight:
                capped_excess += pos.weight - max_weight
                kept[i] = Position(ticker=pos.ticker, weight=max_weight, rationale=pos.rationale, conviction=pos.conviction)
                capped_indices.add(i)
        kept = _redistribute_excess(kept, capped_excess, capped_indices)

        # Pass D — Low-volume concentration cap (applied POST-normalization so it survives
        # renormalization).  Positions with vol_ratio below the threshold are oversized relative
        # to their confirmation level; cap them and redistribute the freed weight.
        low_vol_excess = 0.0
        low_vol_indices: set[int] = set()
        for i, pos in enumerate(kept):
            vol_ratio = candidate_map.get(pos.ticker, {}).get("vol_ratio", float("nan"))
            if (
                not math.isnan(vol_ratio)
                and vol_ratio < config.LOW_VOLUME_VOL_RATIO_THRESHOLD
                and pos.weight > config.LOW_VOLUME_MAX_WEIGHT
            ):
                low_vol_excess += pos.weight - config.LOW_VOLUME_MAX_WEIGHT
                kept[i] = Position(ticker=pos.ticker, weight=config.LOW_VOLUME_MAX_WEIGHT, rationale=pos.rationale, conviction=pos.conviction)
                low_vol_indices.add(i)
                logger.info(
                    "Low-volume cap: %s → %.0f%% (vol_ratio %.2f < %.2f)",
                    pos.ticker,
                    config.LOW_VOLUME_MAX_WEIGHT * 100,
                    vol_ratio,
                    config.LOW_VOLUME_VOL_RATIO_THRESHOLD,
                )
        if low_vol_indices:
            # Overbought-capped positions must not receive excess — their cap would be violated again
            kept = _redistribute_excess(kept, low_vol_excess, low_vol_indices | overbought_capped_indices)

        # Pass E — Tier-1 RSI gate (high momentum, unconfirmed by volume).
        # Positions with RSI in the "hot but not yet overbought" band (HIGH_MOMENTUM_RSI_GATE to
        # OVERBOUGHT_RSI_THRESHOLD) that lack genuine breakout volume (vol_ratio < OVERBOUGHT_VOLUME_EXCEPTION)
        # are capped at HIGH_MOMENTUM_CAP_WITHOUT_VOLUME (18%).  This addresses the observed pattern of
        # max-sizing exhausted momentum names that then underperform — volume confirmation is required
        # before a position earns full Tier-1 (20–25%) weight.
        hot_rsi_excess = 0.0
        hot_rsi_indices: set[int] = set()
        for i, pos in enumerate(kept):
            # Skip positions already capped by earlier passes
            if i in overbought_capped_indices or i in low_vol_indices:
                continue
            c = candidate_map.get(pos.ticker, {})
            rsi = c.get("rsi_14", float("nan"))
            vol_ratio = c.get("vol_ratio", float("nan"))
            cap = config.HIGH_MOMENTUM_CAP_WITHOUT_VOLUME
            if (
                not math.isnan(rsi)
                and config.HIGH_MOMENTUM_RSI_GATE < rsi < config.OVERBOUGHT_RSI_THRESHOLD
                and (math.isnan(vol_ratio) or vol_ratio < config.OVERBOUGHT_VOLUME_EXCEPTION)
                and pos.weight > cap
            ):
                hot_rsi_excess += pos.weight - cap
                kept[i] = Position(ticker=pos.ticker, weight=cap, rationale=pos.rationale, conviction=pos.conviction)
                hot_rsi_indices.add(i)
                logger.info(
                    "Hot-RSI gate (Pass E): %s → %.0f%% (RSI %.1f in gate band, vol_ratio %.2f < %.1f)",
                    pos.ticker, cap * 100, rsi,
                    vol_ratio if not math.isnan(vol_ratio) else 0.0,
                    config.OVERBOUGHT_VOLUME_EXCEPTION,
                )
        if hot_rsi_indices:
            kept = _redistribute_excess(kept, hot_rsi_excess, hot_rsi_indices | overbought_capped_indices | low_vol_indices)

        # No sector caps are applied. Rotation risk remains an informational input for sizing quality,
        # but legal concentration is preserved if the strongest alpha clusters in one sector.

        weighted_vol_sum = 0.0
        vol_weight_covered = 0.0
        for pos in kept:
            vol_ratio = candidate_map.get(pos.ticker, {}).get("vol_ratio", float("nan"))
            if math.isnan(vol_ratio):
                continue
            weighted_vol_sum += pos.weight * vol_ratio
            vol_weight_covered += pos.weight
        if vol_weight_covered > 0:
            portfolio_avg_vol = weighted_vol_sum / vol_weight_covered
            if portfolio_avg_vol < config.PORTFOLIO_MIN_AVG_VOL_RATIO:
                logger.warning(
                    "Portfolio avg vol_ratio %.2f below floor %.2f",
                    portfolio_avg_vol,
                    config.PORTFOLIO_MIN_AVG_VOL_RATIO,
                )

        for pos in kept:
            c = candidate_map.get(pos.ticker, {})
            mom_5d = c.get("mom_5d", float("nan"))
            rationale = (pos.rationale or "").lower()
            mentions_breakout = "breakout" in rationale or "volume" in rationale
            if mentions_breakout and not math.isnan(mom_5d) and mom_5d <= 0.002:
                logger.warning(
                    "Rationale/data mismatch: %s described as breakout but mom_5d is %.2f%%",
                    pos.ticker,
                    mom_5d * 100,
                )

        kept = self._enforce_hard_weight_bounds(kept)

        return PortfolioProposal(
            positions=kept,
            reasoning=proposal.reasoning,
            confidence=proposal.confidence,
            learning_reflection=proposal.learning_reflection,
        )

    @staticmethod
    def _rebalance_for_competition_edge(
        positions: list[Position],
        candidate_map: dict[str, dict],
        bear_cases: dict[str, dict],
        regime_score: int,
    ) -> list[Position]:
        if not positions:
            return positions

        original_total = sum(position.weight for position in positions)
        if original_total <= 1e-12:
            return positions

        weighted: list[Position] = []
        cautious_market = regime_score < 50
        for position in positions:
            candidate = candidate_map.get(position.ticker, {})
            vol_ratio = candidate.get("vol_ratio", float("nan"))
            momentum_5d = candidate.get("mom_5d", float("nan"))
            rsi = candidate.get("rsi_14", float("nan"))
            pct_from_high = candidate.get("pct_from_52w_high", float("nan"))
            devil_risk = (bear_cases.get(position.ticker, {}) or {}).get("risk", "")

            multiplier = 1.0
            if not math.isnan(momentum_5d) and momentum_5d >= config.QUALITY_REBALANCE_STRONG_MOM_5D:
                multiplier *= config.QUALITY_REBALANCE_MOMENTUM_BONUS

            if not math.isnan(vol_ratio) and vol_ratio >= config.QUALITY_REBALANCE_STRONG_VOLUME:
                multiplier *= config.QUALITY_REBALANCE_CONFIRMATION_BONUS

            if not math.isnan(vol_ratio) and vol_ratio < config.DEAD_MONEY_VOL_RATIO:
                multiplier *= config.QUALITY_REBALANCE_LOW_VOLUME_PENALTY
                if cautious_market and vol_ratio < config.LOW_VOLUME_VOL_RATIO_THRESHOLD:
                    multiplier *= config.QUALITY_REBALANCE_WEAK_VOLUME_PENALTY

            if (
                not math.isnan(rsi)
                and rsi > config.OVERBOUGHT_RSI_THRESHOLD
                and not math.isnan(pct_from_high)
                and pct_from_high >= -config.OVERBOUGHT_HIGH_PCT
                and (math.isnan(vol_ratio) or vol_ratio <= config.OVERBOUGHT_VOLUME_EXCEPTION)
            ):
                multiplier *= config.QUALITY_REBALANCE_OVERBOUGHT_PENALTY

            if devil_risk == "HIGH":
                multiplier *= config.QUALITY_REBALANCE_HIGH_RISK_PENALTY
            elif devil_risk == "MEDIUM":
                multiplier *= config.QUALITY_REBALANCE_MEDIUM_RISK_PENALTY

            if (
                not math.isnan(vol_ratio)
                and not math.isnan(momentum_5d)
                and vol_ratio < config.DEAD_MONEY_VOL_RATIO
                and momentum_5d <= config.DEAD_MONEY_MOM_5D
            ):
                multiplier *= config.QUALITY_REBALANCE_DEAD_MONEY_PENALTY

            # Clamp multiplier to prevent extreme compounding
            multiplier = max(config.QUALITY_REBALANCE_MULTIPLIER_MIN,
                             min(config.QUALITY_REBALANCE_MULTIPLIER_MAX, multiplier))

            weighted.append(
                Position(
                    ticker=position.ticker,
                    weight=max(1e-6, position.weight * multiplier),
                    rationale=position.rationale,
                    conviction=position.conviction,
                )
            )

        adjusted_total = sum(position.weight for position in weighted)
        if adjusted_total <= 1e-12:
            return positions

        return [
            Position(
                ticker=position.ticker,
                weight=(position.weight / adjusted_total) * original_total,
                rationale=position.rationale,
                conviction=position.conviction,
            )
            for position in weighted
        ]

    @staticmethod
    def _enforce_hard_weight_bounds(positions: list[Position]) -> list[Position]:
        """Ensure final weights satisfy min/max bounds and sum to 100%.

        This is a final guardrail after quality passes (caps, sector/volume redistributions).
        Those passes can unintentionally re-inflate uncapped names above max weight.
        """
        if not positions:
            return positions

        minimum_weight = config.GAME_CONSTRAINTS["min_weight"]
        maximum_weight = config.GAME_CONSTRAINTS["max_weight"]
        target_total = config.GAME_CONSTRAINTS["max_total_weight"]

        normalized_total = sum(position.weight for position in positions)
        if normalized_total <= 1e-12:
            return positions

        bounded_positions = [
            Position(
                ticker=position.ticker,
                weight=max(minimum_weight, min(maximum_weight, position.weight / normalized_total)),
                rationale=position.rationale,
                conviction=position.conviction,
            )
            for position in positions
        ]

        for _ in range(10):
            current_total = sum(position.weight for position in bounded_positions)
            delta = target_total - current_total
            if abs(delta) <= 1e-8:
                break

            if delta > 0:
                candidate_indices = [
                    index for index, position in enumerate(bounded_positions)
                    if position.weight < maximum_weight - 1e-9
                ]
                if not candidate_indices:
                    break
                total_headroom = sum(maximum_weight - bounded_positions[index].weight for index in candidate_indices)
                if total_headroom <= 1e-12:
                    break
                updated_positions = bounded_positions[:]
                for index in candidate_indices:
                    increment = delta * ((maximum_weight - bounded_positions[index].weight) / total_headroom)
                    updated_positions[index] = Position(
                        ticker=bounded_positions[index].ticker,
                        weight=min(maximum_weight, bounded_positions[index].weight + increment),
                        rationale=bounded_positions[index].rationale,
                        conviction=bounded_positions[index].conviction,
                    )
                bounded_positions = updated_positions
            else:
                reduction = -delta
                candidate_indices = [
                    index for index, position in enumerate(bounded_positions)
                    if position.weight > minimum_weight + 1e-9
                ]
                if not candidate_indices:
                    break
                total_reducible = sum(bounded_positions[index].weight - minimum_weight for index in candidate_indices)
                if total_reducible <= 1e-12:
                    break
                updated_positions = bounded_positions[:]
                for index in candidate_indices:
                    decrement = reduction * ((bounded_positions[index].weight - minimum_weight) / total_reducible)
                    updated_positions[index] = Position(
                        ticker=bounded_positions[index].ticker,
                        weight=max(minimum_weight, bounded_positions[index].weight - decrement),
                        rationale=bounded_positions[index].rationale,
                        conviction=bounded_positions[index].conviction,
                    )
                bounded_positions = updated_positions

        final_total = sum(position.weight for position in bounded_positions)
        if final_total > 1e-12 and abs(final_total - target_total) > 1e-6:
            rescaled_positions = [
                Position(
                    ticker=position.ticker,
                    weight=position.weight / final_total,
                    rationale=position.rationale,
                    conviction=position.conviction,
                )
                for position in bounded_positions
            ]
            bounded_positions = [
                Position(
                    ticker=position.ticker,
                    weight=max(minimum_weight, min(maximum_weight, position.weight)),
                    rationale=position.rationale,
                    conviction=position.conviction,
                )
                for position in rescaled_positions
            ]

        return bounded_positions

    @staticmethod
    def _merge_proposals(
        strategist: PortfolioProposal,
        challenger: Optional[PortfolioProposal],
        full_analyst: Optional[PortfolioProposal] = None,
    ) -> PortfolioProposal:
        """Equal-weight merge fallback when meta-analyst fails entirely."""
        proposals = [strategist]
        weights_per_proposal = [1.0]
        if challenger and challenger.positions:
            proposals.append(challenger)
            weights_per_proposal = [0.55, 0.45]
        if full_analyst and full_analyst.positions:
            proposals.append(full_analyst)
            weights_per_proposal = [0.40, 0.35, 0.25]
        # Normalize weights to sum to 1.0 for all cases
        total_w = sum(weights_per_proposal)
        if total_w > 0:
            weights_per_proposal = [w / total_w for w in weights_per_proposal]

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

    @staticmethod
    def _fallback_top_ranked(snapshot: MarketSnapshot) -> PortfolioProposal:
        ranked = snapshot.get("ranked_candidates", [])
        fallback_tickers: list[str] = []

        for item in ranked:
            if not isinstance(item, dict):
                continue
            ticker = item.get("ticker")
            if isinstance(ticker, str) and ticker not in fallback_tickers:
                fallback_tickers.append(ticker)
            if len(fallback_tickers) >= 5:
                break

        if len(fallback_tickers) < 5:
            for candidate in snapshot.get("candidates", []):
                ticker = candidate.get("ticker") if isinstance(candidate, dict) else None
                if isinstance(ticker, str) and ticker not in fallback_tickers:
                    fallback_tickers.append(ticker)
                if len(fallback_tickers) >= 5:
                    break

        fallback_tickers = fallback_tickers[:5]
        positions = [
            Position(
                ticker=ticker,
                weight=0.20,
                rationale="FALLBACK: Risk Manager API failure — equal-weight top-5 by competition score",
            )
            for ticker in fallback_tickers
        ]
        logger.error(
            "Risk Manager fallback activated: %s",
            ", ".join(sanitize_ticker(t) for t in fallback_tickers),
        )
        return PortfolioProposal(
            positions=positions,
            reasoning="FALLBACK: Risk Manager API failure — equal-weight top-5 by competition score",
            confidence=0.2,
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
        spx_vs = snapshot.get("spx_vs_sma", 0.0)
        vix = snapshot.get("vix_level", float("nan"))
        vix_str = f"{vix:.1f}" if not math.isnan(vix) else "N/A"

        # Compute portfolio betas for context
        strat_beta = self._portfolio_beta(strategist, snapshot)
        strat_beta_str = f"{strat_beta:.2f}" if not math.isnan(strat_beta) else "N/A"
        rotation_risk = snapshot.get("rotation_risk", {})
        rotation_alert_active = any(
            isinstance(info, dict) and info.get("level") in {"HIGH", "MEDIUM"}
            for info in rotation_risk.values()
        )
        beta_targets = {
            "BULL": "target 1.6–2.0",
            "BEAR": "target ≤0.90",
            "NEUTRAL": (
                "soft target 0.95–1.30 (rotation-active: do not add beta filler)"
                if rotation_alert_active
                else "target 0.95–1.30"
            ),
        }
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
            parts = [f"Brent ${brent:.1f}"]
            if not math.isnan(brent_20d):
                parts[0] += f" ({brent_20d:+.1%} 20d)"
            if not math.isnan(wti):
                wti_part = f"WTI ${wti:.1f}"
                if not math.isnan(wti_20d):
                    wti_part += f" ({wti_20d:+.1%} 20d)"
                parts.append(wti_part)
            if not math.isnan(natgas):
                ng_part = f"NatGas ${natgas:.2f}"
                if not math.isnan(natgas_20d):
                    ng_part += f" ({natgas_20d:+.1%} 20d)"
                parts.append(ng_part)
            comm_line = "Commodities: " + " | ".join(parts)

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
                sector_rotation_line += (
                    "\nSector action rule: if a sector's breadth is below 40%, it is losing internal momentum — "
                    "reduce or exit your weakest performer in that sector and redeploy into the leading sector."
                )

        game_equity = snapshot.get("game_equity", 10000.0)
        game_ret = snapshot.get("game_return_pct", 0.0)
        lines = [
            f"## Synthesis task — {date.today().isoformat()}",
            f"Game account: €{game_equity:,.0f} ({game_ret:+.2%} since start) — competition mindset required.",
            f"Regime: {regime} | SPX vs 50d: {spx_vs:+.1%} | VIX: {vix_str} | S&P 500 20d: {snapshot['benchmark_return']:+.1%}",
            f"Breadth: {breadth_str} above 50d SMA | VIX term: {term_str} | Credit spreads 20d: {credit_str}",
            f"Composite regime score: {rscore}/100 — {score_label}",
            f"Strategist proposal portfolio beta: {strat_beta_str} ({beta_target_str} for {regime} regime)",
        ]
        portfolio_state_context = snapshot.get("portfolio_state_context", "")
        if portfolio_state_context:
            lines += ["", portfolio_state_context]
        if comm_line:
            lines.append(comm_line)
        if sector_rotation_line:
            lines.append(sector_rotation_line)
        if rotation_risk:
            high = [(s, i) for s, i in rotation_risk.items() if i["level"] == "HIGH"]
            med = [(s, i) for s, i in rotation_risk.items() if i["level"] == "MEDIUM"]
            alert_lines = ["ROTATION RISK ALERT:"]
            for s, i in sorted(high + med, key=lambda x: x[1]["level"]):
                alert_lines.append(f"  {i['level']}: {s} — {i['reason']}")
            if high:
                alert_lines.append(f"  Action: Reduce or exit {', '.join(s for s, _ in high)} before rotation completes.")
            if regime == "NEUTRAL":
                alert_lines.append(
                    "  Beta guidance override: treat NEUTRAL beta as secondary under active rotation risk; "
                    "do not add high-beta names only to push beta upward."
                )
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
            lines.append(
                "🌟 TRIPLE CONSENSUS (all 3 proposals — maximum conviction): "
                + ", ".join(sanitize_ticker(t) for t in sorted(triple))
            )
            lines.append("")
        if consensus - triple:
            lines.append(
                "⭐ DOUBLE CONSENSUS (2/3 proposals — high conviction): "
                + ", ".join(sanitize_ticker(t) for t in sorted(consensus - triple))
            )
            lines.append("")

        def _fmt_row(p, consensus_set: set) -> str:
            tag = " 🌟" if p.ticker in triple else (" ⭐" if p.ticker in consensus_set else "")
            safe_rationale = p.rationale[:40].replace('|', '').strip()
            return f"{sanitize_ticker(p.ticker)}|{p.weight:.1%}{tag}|{safe_rationale}"

        # Strategist proposal
        strat_total = sum(p.weight for p in strategist.positions)
        lines += [
            f"### Proposal A — Strategist ({len(strategist.positions)} positions, {strat_total:.0%} total)",
            f"Thesis: {strategist.reasoning}",
            "",
            "Ticker|Weight|Rationale"
        ]
        for p in strategist.positions:
            lines.append(_fmt_row(p, consensus))

        lines.append("")

        # Gemini Challenger proposal
        if challenger and challenger.positions:
            chall_total = sum(p.weight for p in challenger.positions)
            lines += [
                f"### Proposal B — Challenger ({len(challenger.positions)} positions, {chall_total:.0%} total)",
                f"Thesis: {challenger.reasoning}",
                "",
                "Ticker|Weight|Rationale"
            ]
            for p in challenger.positions:
                lines.append(_fmt_row(p, consensus))
        else:
            lines += [
                "### Proposal B — Challenger",
                "Not available — weight Proposal A and C more heavily.",
            ]

        lines.append("")

        # Full Analyst proposal
        if full_analyst and full_analyst.positions:
            full_total = sum(p.weight for p in full_analyst.positions)
            lines += [
                f"### Proposal C — Full Analyst ({len(full_analyst.positions)} positions, {full_total:.0%} total)",
                f"Thesis: {full_analyst.reasoning}",
                "",
                "Ticker|Weight|Rationale"
            ]
            for p in full_analyst.positions:
                lines.append(_fmt_row(p, consensus))
        else:
            lines += [
                "### Proposal C — Full Analyst",
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
            # Build signal lookup for fact-checking devil's narrative claims
            _signal_lookup = {c["ticker"]: c for c in snapshot.get("candidates", [])}
            lines += ["", "### ⚠️ Devil's Advocate — Bear Cases"]
            lines.append(
                "These are the strongest arguments AGAINST each pick. "
                "Factor them into your weight decisions — HIGH risk picks should be sized down or cut. "
                "ACTUAL SIGNALS are appended for fact-checking — if the devil's narrative contradicts the signals, trust the signals."
            )
            if high_risk:
                lines.append("")
                lines.append("**HIGH RISK (reduce weight or exclude):**")
                for ticker, v in high_risk:
                    sigs = _signal_lookup.get(ticker, {})
                    vr = sigs.get("vol_ratio", float("nan"))
                    m5 = sigs.get("mom_5d", float("nan"))
                    rsi = sigs.get("rsi_14", float("nan"))
                    vr_str = f"{vr:.2f}" if not math.isnan(vr) else "n/a"
                    m5_str = f"{m5 * 100:+.1f}%" if not math.isnan(m5) else "n/a"
                    rsi_str = f"{rsi:.0f}" if not math.isnan(rsi) else "n/a"
                    lines.append(f"  {sanitize_ticker(ticker)}: {v['bear_case']}")
                    lines.append(f"    [ACTUAL SIGNALS: vol_ratio={vr_str}, mom_5d={m5_str}, rsi={rsi_str}]")
            if other_risk:
                lines.append("")
                lines.append("**MEDIUM / LOW RISK (acknowledge but can hold):**")
                for ticker, v in other_risk:
                    sigs = _signal_lookup.get(ticker, {})
                    vr = sigs.get("vol_ratio", float("nan"))
                    m5 = sigs.get("mom_5d", float("nan"))
                    rsi = sigs.get("rsi_14", float("nan"))
                    vr_str = f"{vr:.2f}" if not math.isnan(vr) else "n/a"
                    m5_str = f"{m5 * 100:+.1f}%" if not math.isnan(m5) else "n/a"
                    rsi_str = f"{rsi:.0f}" if not math.isnan(rsi) else "n/a"
                    lines.append(f"  {sanitize_ticker(ticker)} [{v['risk']}]: {v['bear_case']}")
                    lines.append(f"    [ACTUAL SIGNALS: vol_ratio={vr_str}, mom_5d={m5_str}, rsi={rsi_str}]")

        # Late-game mode and groupthink alerts for Risk Manager
        late_game_mode = snapshot.get("late_game_mode", "NORMAL")
        if late_game_mode == "RECOUP":
            lines += ["", "LATE-GAME MODE: RECOUP — portfolio underperforming with <3 weeks left. Weight toward higher-beta/catalyst names. Accept slightly more risk for upside."]
        elif late_game_mode == "LOCK_IN":
            lines += ["", "LATE-GAME MODE: LOCK_IN — portfolio outperforming with <3 weeks left. Prefer beta 1.0-1.4 with confirmed momentum over high-beta concentration. Protect gains."]
        if snapshot.get("groupthink_risk"):
            lines += ["", "⚠ GROUPTHINK ALERT: >60% of proposals share the same consensus picks. Evaluate whether any non-consensus pick from the candidate table offers asymmetric alpha not yet in the obvious names."]

        lines += [
            "",
            "### Slot-Cost and Selectivity Rules",
            "Every slot must beat the next-best alternative. In a 5-stock competition portfolio, do not keep a merely acceptable name if another proposal offered a cleaner, faster mover.",
            "CAUTIOUS regime-score handling: remain concentrated, but cut slow or dead-money names rather than padding with soft holdings.",
            "",
            "Synthesise the final portfolio. Score consensus picks higher (conviction), not weights. "
            "For HIGH-RISK picks flagged above: reduce conviction by at least 3 points or exclude. "
            "Apply regime and concentration rules. Respond ONLY with the JSON object.",
        ]
        return "\n".join(lines)

    def _call_openai(self, user_message: str, n_participants: int = 844) -> PortfolioProposal:
        system_prompt = _SYSTEM_PROMPT.format(n_participants=n_participants)
        response = self.client.chat.completions.create(
            model=self.MODEL,
            response_format={"type": "json_object"},
            temperature=0.15,
            timeout=config.API_TIMEOUT_SECONDS,
            messages=[
                {"role": "system", "content": system_prompt},
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
        raw_positions = data.get("positions", [])
        if not isinstance(raw_positions, list):
            raise ValueError("Meta-analyst returned invalid positions format")

        min_stocks = config.GAME_CONSTRAINTS["min_stocks"]
        max_stocks = config.GAME_CONSTRAINTS["max_stocks"]
        if not (min_stocks <= len(raw_positions) <= max_stocks):
            raise ValueError(
                f"Meta-analyst returned {len(raw_positions)} positions; expected {min_stocks}-{max_stocks}"
            )

        seen_tickers: set[str] = set()
        positions: list[Position] = []

        for raw in raw_positions:
            ticker = sanitize_ticker(str(raw.get("ticker", "")))
            if not ticker:
                raise ValueError("Meta-analyst returned empty ticker")
            if ticker in seen_tickers:
                raise ValueError(f"Meta-analyst returned duplicate ticker: {ticker}")
            seen_tickers.add(ticker)

            conviction_raw = raw.get("conviction")
            if conviction_raw is None:
                raise ValueError(f"Meta-analyst missing conviction for {ticker}")
            conviction = int(conviction_raw)
            conviction = max(1, min(10, conviction))

            positions.append(
                Position(
                    ticker=ticker,
                    weight=0.0,  # Kelly sizing fills this
                    rationale=str(raw.get("rationale", "")),
                    conviction=conviction,
                )
            )

        proposal = PortfolioProposal(
            positions=positions,
            reasoning=data.get("reasoning", ""),
            confidence=float(data.get("confidence", 0.5)),
            learning_reflection=data.get("learning_reflection", ""),
        )

        learning_state = load_learning_state()
        winners = learning_state.get("validated_winners", [])
        win_rate_by_ticker: dict[str, float] = {}
        for item in winners:
            if not isinstance(item, dict):
                continue
            ticker = sanitize_ticker(str(item.get("ticker", "")))
            hit_rate = item.get("hit_rate")
            if ticker and isinstance(hit_rate, (float, int)):
                win_rate_by_ticker[ticker] = float(hit_rate)

        rationale_stats = learning_state.get("rationale_stats", {})
        avg_pos = []
        avg_neg = []
        for stats in rationale_stats.values():
            if not isinstance(stats, dict):
                continue
            avg = stats.get("avg_return_1d")
            if isinstance(avg, (float, int)):
                if avg > 0:
                    avg_pos.append(float(avg))
                elif avg < 0:
                    avg_neg.append(abs(float(avg)))
        avg_win = sum(avg_pos) / len(avg_pos) if avg_pos else 0.01
        avg_loss = sum(avg_neg) / len(avg_neg) if avg_neg else 0.01
        win_loss_ratio = avg_win / max(avg_loss, 1e-6)
        clamped_ratio = max(0.5, min(5.0, win_loss_ratio))
        # If the learning-derived ratio would make Kelly negative (f* = W - (1-W)/R ≤ 0),
        # the data is too noisy to trust — fall back to a neutral 2.0 ratio.
        _DEFAULT_WIN_LOSS = 2.0
        if 0.55 - (0.45 / clamped_ratio) <= 0:
            logger.warning(
                "Learning-state win/loss ratio %.2f produces negative Kelly — using default %.1f",
                clamped_ratio, _DEFAULT_WIN_LOSS,
            )
            clamped_ratio = _DEFAULT_WIN_LOSS

        validator = PortfolioValidator()
        proposal = validator.apply_kelly_sizing(
            proposal,
            win_rate=0.55,
            win_loss_ratio=clamped_ratio,
            win_rate_by_ticker=win_rate_by_ticker,
        )
        logger.info("Applied Kelly sizing from conviction scores")

        return proposal
