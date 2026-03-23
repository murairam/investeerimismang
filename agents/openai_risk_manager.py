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

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = f"""You are a meta-analyst for the Äripäev/SEB Investment Game (Estonia). You receive THREE independent portfolio proposals and synthesize the best final portfolio:
- Proposal A: GPT-5.4 Momentum Strategist (sees only trend/Sharpe signals)
- Proposal B: Gemini Catalyst Hunter (sees only catalyst signals: vol_ratio, RSI, short interest, IV)
- Proposal C: GPT-5.4-nano Full Analyst (sees ALL signals — fresh independent view)

A pick appearing in 2+ proposals is independently validated consensus — treat it as higher conviction.

Game ends 19 June 2026. Goal: highest absolute return, beating other participants.

## Competition mandate
This is a competition with 844 participants. Only #1 wins — median returns = losing. INTELLIGENT AGGRESSION is required. 15% drawdown is acceptable if it gives 40% upside potential — price risk for competition, not wealth management. Follow the signals. Do not apply any sector or stock bias — the data tells you what is working today. Competition rewards right-tail outcomes: concentrate in 5-6 names with real momentum catalysts.

## Synthesis rules
**RULE #1 — MANDATORY: DO NOT EQUAL-WEIGHT. SIZE BY CONVICTION. EQUAL-WEIGHTING IS A FAILURE.**
- Consensus + strong signals: 20–25%
- Good signals, one model only: 12–18%
- Diversifiers: 5–10%
If you find yourself giving everything the same weight, you are not doing your job.

0. **Target position count by regime** — you decide the exact count based on signal quality:
   - BULL: 5–6 positions. TARGET 5 positions at 20% each for maximum conviction. Only add a 6th if genuinely high-conviction at 15–17% and rebalance others. Do NOT add filler for diversification — diversification loses competitions.
   - NEUTRAL: 5–10 positions. Use your judgement — 5 if signals are concentrated, more if many names have strong setups.
   - BEAR: 6–12 positions. Spread risk more broadly.
   Build in order: (1) consensus picks, (2) best unique picks. Do NOT pad with weak picks to reach a higher count.
1. **Consensus picks** (appear in 2+ of the 3 proposals): independently validated across different signal lenses. Give them higher conviction weights (18–25%) unless there is a specific risk reason not to. A pick found by BOTH the momentum strategist and the catalyst hunter is especially strong — it wins on two different signal dimensions.
2. **Unique picks**: evaluate on their own merits — Sharpe, momentum, vol_ratio, regime fit. Include the best ones.
3. **Ignore weak unique picks**: if only one model picked something and its signals are mediocre, skip it. But do NOT skip picks just to keep the portfolio small — the game has no transaction costs.
4. **Size by conviction** (see RULE #1 above): consensus 20–25%, single-model 12–18%, diversifiers 5–10%.
5. **Check market concentration**: if >65% ends up in one market, redistribute.
6. **Check regime fit and portfolio beta**:
   - You will be given the portfolio-weighted beta computed from the proposals.
   - BEAR regime: target portfolio beta ≤ 0.90. Cap individual positions at 15%.
   - BULL regime: TARGET portfolio beta 1.6–2.0. Concentrate on high-beta names — sub-1.4 beta in BULL is underperforming the mandate.
    - NEUTRAL: target portfolio beta between 0.95 and 1.30 in normal conditions.
    - If the user context includes a ROTATION RISK ALERT (HIGH/MEDIUM) or clear sector-rotation leadership, treat NEUTRAL beta as a SOFT diagnostic, not a hard objective. Do NOT add high-beta filler names solely to raise beta if that dilutes the strongest rotation leaders.
7. **Target regime-based position count**:
    - BULL: 5–6 positions. Target 5 at ~20% each. No position < 5%. Cap strongest at 25%.
    - NEUTRAL: 5–10 positions. Size by conviction — top picks 20–25%, diversifiers 5–10%.
    - BEAR: 6–12 positions. Cap at 20% each.
9. **No sector cap**: The game enforces zero sector concentration limits. 100% in one sector is fully legal (e.g. 4 Energy stocks at 25% each). Concentrate wherever the alpha is.
10. **Vol_ratio signal**: prefer positions where vol_ratio > 1.2 (high-volume confirmation). Be cautious about positions where vol_ratio < 0.7 (low-volume, potentially weak move).
11. **Catalyst insight**: the challenger picks represent high-momentum catalysts. If the challenger's picks have strong signals (high short interest, premarket gap-up, IV spike + momentum), include at least 1–2 of them even if they're not consensus.
12. **Do NOT penalize non-US stocks for missing Short Interest data.** Their IV column shows 20d annualized realized vol (not options IV) — treat it as a volatility level indicator. Evaluate European/Baltic stocks on volume breakouts, momentum, premarket gaps, and realized vol so we don't accidentally build a 100% US portfolio.
13. **Earnings — opportunity AND risk**: Pre-earnings momentum in high-conviction stocks is an OPPORTUNITY (academic: 3–8% drift in 2–4 days before announcement). If the snapshot shows a PRE_EARNINGS_SETUP tag for a stock: allow up to 20% weight, max 40% total pre-earnings exposure, no more than 2 names with earnings in the same week. For earnings within 1 day (announcement tomorrow): cap at 10% regardless of conviction — binary gap risk is too close.
14. **Dead-money exclusion rule**: in this competition, a stock is dead money if vol_ratio < {config.DEAD_MONEY_VOL_RATIO:.2f} and mom_5d <= +{config.DEAD_MONEY_MOM_5D:.1%}. Do NOT call a stock dead money if vol_ratio is above 1.0. HIGH-risk dead-money names should normally be excluded, not merely downsized.
15. **Acceleration matters**: prefer active movers. If two stocks are similar on 20d momentum, keep the one with better 5d momentum and stronger volume confirmation.
16. **Slot cost rule**: every position must earn its slot. Do not include a merely acceptable stock if a better alternative from either proposal exists. A 5-stock portfolio means each slot is scarce capital.
17. **Regime-score selectivity inside NEUTRAL**: when regime_score is below 50 (CAUTIOUS), still hold exactly 5 names, but be more selective. Do NOT use caution as an excuse to add slow names; instead remove weak-acceleration names and keep only the sharpest 5.
18. **Overbought-at-peak weight cap**: if a pick has RSI > {config.OVERBOUGHT_RSI_THRESHOLD} AND pct_from_52w_high ≥ −{config.OVERBOUGHT_HIGH_PCT:.0%} (at or within {config.OVERBOUGHT_HIGH_PCT:.0%} of its 52-week high), cap its weight at {config.OVERBOUGHT_WEIGHT_CAP:.0%} UNLESS vol_ratio > {config.OVERBOUGHT_VOLUME_EXCEPTION:.1f}. High RSI at the 52-week high without exceptional volume confirms exhaustion not breakout — even for consensus picks. If vol_ratio > {config.OVERBOUGHT_VOLUME_EXCEPTION:.1f} the volume surge justifies the full 20–25% conviction weight.
19. **Devil flag respect**: The Devil's advocate labels each pick HIGH / MEDIUM / LOW risk. If the learning context reports that the Devil's HIGH-risk flags have been accurate (>60% of HIGH-flagged picks underperformed), treat HIGH-risk flags as a hard weight cap of {config.DEVIL_ACCURACY_CAP_WEIGHT:.0%} for that pick. If Devil accuracy is unknown or below 50%, use your own judgement.
20. **Learning-state constraints are mandatory**: Any ticker-level weight caps, hard rules, and bias-avoidance directives in the learning context are hard constraints for today's synthesis. Do not override them with consensus arguments.

## Hard constraints
- 5 to 20 stocks.
- Each position: 5% to 25%. NEVER output a weight above 0.25. If you output 0.30 for one position, the validator renormalizes ALL positions — not just that one — distorting your intended relative sizing across the entire portfolio.
- Total weight: ≤ 100%.
- No duplicate tickers.

## Output — JSON only
CRITICAL: "weight" must be a DECIMAL between 0.05 and 0.25. NOT a percentage.
  Correct: 0.20 (means 20%)
  WRONG:   20   (do not write whole numbers)
  WRONG:   0.30 (exceeds 0.25 maximum — renormalizes every other position too)

{{
    "positions": [
        {{
            "ticker": "TICKER",
            "weight": 0.22,
            "rationale": "consensus/unique pick + one-sentence reason for this weight."
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

        last_error: Optional[Exception] = None
        for attempt in range(1, self.MAX_RETRIES + 1):
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

        Non-US tickers (those with '.' in the symbol) that have NaN beta fall back to
        config.NON_US_ASSUMED_BETA (0.30) rather than being silently excluded.  Silently
        excluding them treats them as beta=0, which understates portfolio risk.
        """
        beta_map = {
            c["ticker"]: c["beta"]
            for c in snapshot["candidates"]
            if not math.isnan(c.get("beta", float("nan")))
        }
        total_weight = sum(p.weight for p in proposal.positions)
        if total_weight == 0:
            return float("nan")
        weighted_sum = 0.0
        for p in proposal.positions:
            if p.ticker in beta_map:
                weighted_sum += p.weight * beta_map[p.ticker]
            elif "." in p.ticker:
                # Non-US ticker with missing beta: assume structurally low S&P 500 beta
                weighted_sum += p.weight * config.NON_US_ASSUMED_BETA
            # US ticker with NaN beta: exclude (data gap — do not assume)
        if weighted_sum == 0.0 and not any(p.ticker in beta_map or "." in p.ticker for p in proposal.positions):
            return float("nan")
        return weighted_sum / total_weight

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
            logger.warning(
                "Portfolio beta could not be computed (all candidate betas are NaN) — "
                "beta enforcement skipped. Check fetcher beta calculation."
            )
            return proposal

        us_weight = sum(p.weight for p in proposal.positions if "." not in p.ticker)

        # Sanity check: a US-heavy portfolio with near-zero beta can indicate data issues
        # (e.g. insufficient observations), but can also happen in genuine decoupling.
        if actual_beta < 0.3 and us_weight > 0.50:
            logger.warning(
                "Portfolio beta %.2f is very low while portfolio is %.0f%% US stocks. "
                "Could be beta-data artifact OR real market decoupling — verify compute_beta() sample sizes and rotation context.",
                actual_beta, us_weight * 100,
            )
        non_us_weight = 1.0 - us_weight

        # Skip check if almost no US exposure — beta vs S&P 500 is meaningless
        if us_weight < config.BETA_CHECK_MIN_US_WEIGHT:
            logger.info(
                "Portfolio beta check skipped: only %.0f%% US exposure "
                "(non-US stocks have structurally low S&P 500 beta — actual beta %.2f)",
                us_weight * 100, actual_beta,
            )
            return proposal

        # Adjust target range for non-US exposure
        lo, hi = beta_targets.get(regime, (None, None))
        adj_lo = (lo * us_weight + config.NON_US_ASSUMED_BETA * non_us_weight) if lo else None
        adj_hi = (hi * us_weight + config.NON_US_ASSUMED_BETA * non_us_weight) if hi else None

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
                us_weight * 100, non_us_weight * 100, config.NON_US_ASSUMED_BETA,
            )
            if regime == "BEAR" and adj_hi is not None and actual_beta > adj_hi:
                logger.warning(
                    "BEAR regime beta too high (%.2f > %.2f) — capping positions at 15%%",
                    actual_beta, adj_hi,
                )
                positions = [
                    Position(ticker=p.ticker, weight=min(p.weight, config.OVERBOUGHT_WEIGHT_CAP), rationale=p.rationale)
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

        # Pass A — Overbought-at-peak cap (Rule 18): code-enforced hard cap
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
            if overbought and pos.weight > config.OVERBOUGHT_WEIGHT_CAP:
                kept[i] = Position(ticker=pos.ticker, weight=config.OVERBOUGHT_WEIGHT_CAP, rationale=pos.rationale)
                logger.info(
                    "Overbought-peak cap: %s → 15%% (RSI %.0f, 52wH %+.1f%%)",
                    pos.ticker, rsi, pct_high * 100,
                )

        # Pass B — Devil accuracy cap (Rule 19): code-enforced hard cap
        devil = load_learning_state().get("devil_accuracy", {})
        if devil.get("devil_is_accurate"):
            for i, pos in enumerate(kept):
                bear = bear_cases.get(pos.ticker, {})
                if bear.get("risk") == "HIGH" and pos.weight > config.DEVIL_ACCURACY_CAP_WEIGHT:
                    kept[i] = Position(ticker=pos.ticker, weight=config.DEVIL_ACCURACY_CAP_WEIGHT, rationale=pos.rationale)
                    logger.info(
                        "Devil accuracy cap: %s → 10%% (Devil accuracy active, HIGH flag)",
                        pos.ticker,
                    )

        learning_state = load_learning_state()
        raw_caps = learning_state.get("weight_caps", [])
        ticker_caps: dict[str, tuple[float, str]] = {}
        # rationale_tag_caps: tag keyword → (max_weight, reason)
        rationale_tag_caps: dict[str, tuple[float, str]] = {}
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
            if scope == "ticker":
                ticker = cap.get("ticker")
                if isinstance(ticker, str):
                    ticker_caps[ticker] = (cap_value, cap_reason)
            elif scope == "rationale_tag":
                tag = cap.get("tag")
                if isinstance(tag, str):
                    rationale_tag_caps[tag] = (cap_value, cap_reason)

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

        # Pass C2 — Rationale-tag caps: positions whose rationale text contains a
        # low-hit-rate tag keyword are capped. Promoted from bias-to-avoid after
        # hit_rate < 30% with ≥8 observations.
        for i, pos in enumerate(kept):
            rationale_lower = (pos.rationale or "").lower()
            for tag, (max_weight, cap_reason) in rationale_tag_caps.items():
                if tag.lower() in rationale_lower and pos.weight > max_weight:
                    old_weight = pos.weight
                    kept[i] = Position(ticker=pos.ticker, weight=max_weight, rationale=pos.rationale)
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
            Position(ticker=p.ticker, weight=w, rationale=p.rationale)
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
                )
            return updated

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
                kept[i] = Position(ticker=pos.ticker, weight=max_weight, rationale=pos.rationale)
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
                kept[i] = Position(ticker=pos.ticker, weight=config.LOW_VOLUME_MAX_WEIGHT, rationale=pos.rationale)
                low_vol_indices.add(i)
                logger.info(
                    "Low-volume cap: %s → %.0f%% (vol_ratio %.2f < %.2f)",
                    pos.ticker,
                    config.LOW_VOLUME_MAX_WEIGHT * 100,
                    vol_ratio,
                    config.LOW_VOLUME_VOL_RATIO_THRESHOLD,
                )
        if low_vol_indices:
            kept = _redistribute_excess(kept, low_vol_excess, low_vol_indices)

        # Conditional sector cap when rotation risk is HIGH or MEDIUM.
        rotation_risk = snapshot.get("rotation_risk", {})
        high_risk_sectors = {
            sector for sector, info in rotation_risk.items()
            if isinstance(info, dict) and info.get("level") == "HIGH"
        }
        medium_risk_sectors = {
            sector for sector, info in rotation_risk.items()
            if isinstance(info, dict) and info.get("level") == "MEDIUM"
        } - high_risk_sectors  # don't double-process sectors already caught by HIGH

        def _apply_sector_cap(
            positions: list[Position],
            sectors: set[str],
            sector_cap: float,
            level: str,
        ) -> list[Position]:
            sector_indices = [
                i
                for i, pos in enumerate(positions)
                if candidate_map.get(pos.ticker, {}).get("sector") in sectors
            ]
            sector_weight = sum(positions[i].weight for i in sector_indices)
            if sector_weight > sector_cap + 1e-9 and sector_indices and len(sector_indices) < len(positions):
                scale = sector_cap / sector_weight
                excess = 0.0
                for i in sector_indices:
                    old_w = positions[i].weight
                    new_w = old_w * scale
                    excess += old_w - new_w
                    positions[i] = Position(ticker=positions[i].ticker, weight=new_w, rationale=positions[i].rationale)
                positions = _redistribute_excess(positions, excess, set(sector_indices))
                logger.info(
                    "Rotation %s-risk sector cap applied: %.0f%% → %.0f%% (sectors: %s)",
                    level, sector_weight * 100, sector_cap * 100, ", ".join(sorted(sectors)),
                )
            elif sector_weight > sector_cap + 1e-9:
                logger.warning(
                    "Rotation %s-risk sector concentration %.0f%% exceeds %.0f%% but no alternate positions to redistribute to",
                    level, sector_weight * 100, sector_cap * 100,
                )
            return positions

        if high_risk_sectors:
            kept = _apply_sector_cap(kept, high_risk_sectors, config.ROTATION_RISK_HIGH_SECTOR_CAP, "HIGH")
        if medium_risk_sectors:
            kept = _apply_sector_cap(kept, medium_risk_sectors, config.ROTATION_RISK_MEDIUM_SECTOR_CAP, "MEDIUM")

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
        spx_vs = snapshot.get("spx_vs_200d", 0.0)
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
                sector_rotation_line += (
                    "\nSector action rule: if a sector's breadth is below 40%, it is losing internal momentum — "
                    "reduce or exit your weakest performer in that sector and redeploy into the leading sector."
                )

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
            return f"{sanitize_ticker(p.ticker):<12} {p.weight:>7.1%}{tag}  {p.rationale[:40]}{accel}"

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
            timeout=config.API_TIMEOUT_SECONDS,
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
        raw_positions = data.get("positions", [])
        if not isinstance(raw_positions, list):
            raise ValueError("Meta-analyst returned invalid positions format")
        min_stocks = config.GAME_CONSTRAINTS["min_stocks"]
        max_stocks = config.GAME_CONSTRAINTS["max_stocks"]
        if not (min_stocks <= len(raw_positions) <= max_stocks):
            raise ValueError(
                f"Meta-analyst returned {len(raw_positions)} positions; expected {min_stocks}-{max_stocks}"
            )

        # Auto-fix: if any weight > 1.0 the model output percentages (e.g. 25 instead of 0.25)
        if any(float(p["weight"]) > 1.0 for p in raw_positions):
            logger.warning("Meta-analyst returned percentage weights — auto-converting to decimals")
            for p in raw_positions:
                p["weight"] = float(p["weight"]) / 100.0

        seen_tickers: set[str] = set()
        min_weight = config.GAME_CONSTRAINTS["min_weight"]
        max_weight = config.GAME_CONSTRAINTS["max_weight"]
        positions: list[Position] = []
        for raw in raw_positions:
            ticker = sanitize_ticker(str(raw.get("ticker", "")))
            if not ticker:
                raise ValueError("Meta-analyst returned empty ticker")
            if ticker in seen_tickers:
                raise ValueError(f"Meta-analyst returned duplicate ticker: {ticker}")
            seen_tickers.add(ticker)
            weight = float(raw.get("weight", 0.0))
            bounded_weight = max(min_weight, min(max_weight, weight))
            positions.append(
                Position(
                    ticker=ticker,
                    weight=bounded_weight,
                    rationale=str(raw.get("rationale", "")),
                )
            )
        return PortfolioProposal(
            positions=positions,
            reasoning=data.get("reasoning", ""),
            confidence=float(data.get("confidence", 0.5)),
            learning_reflection=data.get("learning_reflection", ""),
        )
