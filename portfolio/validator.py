"""
Validates and normalises a PortfolioProposal against game constraints.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from config import GAME_CONSTRAINTS, POSITION_TARGETS_BY_REGIME
from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]


class PortfolioValidator:
    def __init__(self) -> None:
        self.c = GAME_CONSTRAINTS

    @staticmethod
    def calculate_kelly_fraction(win_rate: float, win_loss_ratio: float) -> float:
        """
        Kelly fraction: f* = W - ((1 - W) / R)
        where W is win probability and R is average win/loss ratio.
        """
        if win_loss_ratio <= 0:
            raise ValueError("win_loss_ratio must be > 0")
        return win_rate - ((1.0 - win_rate) / win_loss_ratio)

    def validate(self, proposal: PortfolioProposal, regime: Optional[str] = None) -> ValidationResult:
        errors: list[str] = []
        min_stocks = self.c["min_stocks"]
        max_stocks = self.c["max_stocks"]

        n = len(proposal.positions)
        if n < min_stocks:
            errors.append(f"Too few stocks: {n} < {min_stocks}")
        if n > max_stocks:
            errors.append(f"Too many stocks: {n} > {max_stocks}")

        # Regime bands are advisory only (do not fail validation)
        if regime and regime in POSITION_TARGETS_BY_REGIME:
            target = POSITION_TARGETS_BY_REGIME[regime]
            if n < target["min_stocks"] or n > target["max_stocks"]:
                logger.info(
                    "Advisory: %d positions outside %s target band %d-%d",
                    n,
                    regime,
                    target["min_stocks"],
                    target["max_stocks"],
                )

        seen_tickers = set()
        dupes = set()  # Using a set for dupes avoids adding the same ticker multiple times
        for p in proposal.positions:
            if p.ticker in seen_tickers:
                dupes.add(p.ticker)
            seen_tickers.add(p.ticker)
        if dupes:
            errors.append(f"Duplicate tickers: {sorted(list(dupes))}")

        for pos in proposal.positions:
            if pos.weight < self.c["min_weight"]:
                errors.append(
                    f"{pos.ticker}: weight {pos.weight:.1%} < {self.c['min_weight']:.0%} minimum"
                )
            if pos.weight > self.c["max_weight"]:
                errors.append(
                    f"{pos.ticker}: weight {pos.weight:.1%} > {self.c['max_weight']:.0%} maximum"
                )

        total = sum(p.weight for p in proposal.positions)
        if total > self.c["max_total_weight"] + 1e-9:
            errors.append(f"Total weight {total:.1%} exceeds 100%")
        if total < self.c["min_total_weight"] - 1e-9:
            errors.append(
                f"Total weight {total:.1%} below {self.c['min_total_weight']:.0%} minimum"
            )

        return ValidationResult(ok=len(errors) == 0, errors=errors)

    def normalize(self, proposal: PortfolioProposal) -> PortfolioProposal:
        """
        Auto-scales weights to conform to game constraints without violating them.
        1. Clips all weights to the allowed [min_weight, max_weight] range.
          2. If total weight > 100%, scales down weights proportionally based on how
              much "headroom" they have above the minimum weight.
          3. If total weight < 100%, scales up weights proportionally based on how
              much room remains below the maximum weight.
        Returns a new PortfolioProposal; the original is not mutated.
        """
        mn, mx = self.c["min_weight"], self.c["max_weight"]

        # 1. Clip individual weights to [min_weight, max_weight]
        for p in proposal.positions:
            if p.weight > mx:
                logger.warning(
                    "Validator clipping %s from %.1f%% to %.0f%% — model ignored weight constraint. "
                    "Renormalization will redistribute the excess across ALL positions.",
                    p.ticker, p.weight * 100, mx * 100,
                )
        positions = [
            Position(
                ticker=p.ticker,
                weight=max(mn, min(mx, p.weight)),
                rationale=p.rationale,
            )
            for p in proposal.positions
        ]

        # 2. Scale down if total weight > 100%
        total_weight = sum(p.weight for p in positions)
        if total_weight > self.c["max_total_weight"]:
            overweight = total_weight - self.c["max_total_weight"]
            total_reducible = sum(p.weight - mn for p in positions)

            if total_reducible > 1e-9:
                positions = [
                    Position(
                        ticker=p.ticker,
                        weight=p.weight - overweight * (p.weight - mn) / total_reducible,
                        rationale=p.rationale,
                    )
                    for p in positions
                ]

        # 3. Scale up if total weight < 100%
        total_weight = sum(p.weight for p in positions)
        if total_weight < self.c["max_total_weight"]:
            underweight = self.c["max_total_weight"] - total_weight
            total_headroom = sum(mx - p.weight for p in positions)

            if total_headroom > 1e-9:
                positions = [
                    Position(
                        ticker=p.ticker,
                        weight=p.weight + underweight * (mx - p.weight) / total_headroom,
                        rationale=p.rationale,
                    )
                    for p in positions
                ]

        final_total = sum(p.weight for p in positions)
        if abs(final_total - self.c["max_total_weight"]) > 1e-6:
            logger.warning(
                "normalize() did not reach exactly 100%% — final total %.4f%%. "
                "Applying proportional correction.",
                final_total * 100,
            )
            if final_total <= 1e-9:
                raise ValueError(
                    f"normalize() produced zero-sum weights ({final_total:.2e}). "
                    "All positions were reduced to zero — this indicates a configuration error."
                )
            positions = [
                Position(ticker=p.ticker, weight=min(self.c["max_weight"], p.weight / final_total), rationale=p.rationale)
                for p in positions
            ]

        return PortfolioProposal(
            positions=positions,
            reasoning=proposal.reasoning,
            confidence=proposal.confidence,
            learning_reflection=proposal.learning_reflection,
        )

    def round_to_whole_pct(self, proposal: PortfolioProposal) -> PortfolioProposal:
        """
        Round all weights to whole percentages preserving the intended total.
        Uses largest-remainder method to distribute rounding errors.
        """
        weights = [p.weight for p in proposal.positions]
        floored = [int(w * 100) for w in weights]
        remainders = [(w * 100 - floored[i], i) for i, w in enumerate(weights)]
        target_total = round(sum(weights) * 100)  # respect the LLM's intended total, not always 100
        deficit = target_total - sum(floored)
        # Distribute remaining percentage points to positions with largest remainders
        for _, i in sorted(remainders, reverse=True)[:deficit]:
            floored[i] += 1
        positions = [
            Position(ticker=p.ticker, weight=floored[i] / 100.0, rationale=p.rationale)
            for i, p in enumerate(proposal.positions)
        ]
        return PortfolioProposal(
            positions=positions,
            reasoning=proposal.reasoning,
            confidence=proposal.confidence,
            learning_reflection=proposal.learning_reflection,
        )

    def apply_kelly_sizing(
        self,
        proposal: PortfolioProposal,
        win_rate: float = 0.55,
        win_loss_ratio: float = 2.0,
        win_rate_by_ticker: dict[str, float] | None = None,
        win_loss_ratio_by_ticker: dict[str, float] | None = None,
    ) -> PortfolioProposal:
        """
        Apply Kelly Criterion sizing based on conviction scores (1-10).
        Formula: K% = W - (1-W)/R
        Scaled by conviction: Weight = K% * (Conviction / 10)
        """
        # Validate default Kelly inputs and log if baseline is non-positive.
        baseline_kelly = self.calculate_kelly_fraction(win_rate, win_loss_ratio)
        if baseline_kelly <= 0:
            logger.warning(
                "Baseline Kelly fraction <= 0 (%.2f%%). Per-ticker fallback floor will be used.",
                baseline_kelly * 100,
            )

        new_positions = []
        win_rate_by_ticker = win_rate_by_ticker or {}
        win_loss_ratio_by_ticker = win_loss_ratio_by_ticker or {}
        for p in proposal.positions:
            ticker_win_rate = float(win_rate_by_ticker.get(p.ticker, win_rate))
            ticker_win_loss = float(win_loss_ratio_by_ticker.get(p.ticker, win_loss_ratio))
            ticker_kelly = self.calculate_kelly_fraction(ticker_win_rate, ticker_win_loss)
            if ticker_kelly <= 0:
                ticker_kelly = 0.10
            # Scale Kelly by conviction (1-10)
            # 10 = Full Kelly, 1 = 0.1 * Kelly
            # Default to 5 if conviction not set (or 0)
            conviction = p.conviction if p.conviction > 0 else 5
            target_weight = ticker_kelly * (conviction / 10.0)
            
            # Clip to game constraints immediately to avoid massive overweights
            target_weight = min(self.c["max_weight"], target_weight)
            target_weight = max(self.c["min_weight"], target_weight)
            
            new_positions.append(Position(
                ticker=p.ticker,
                weight=target_weight,
                rationale=p.rationale,
                conviction=conviction
            ))

        updated_proposal = PortfolioProposal(
            positions=new_positions,
            reasoning=proposal.reasoning,
            confidence=proposal.confidence,
            learning_reflection=proposal.learning_reflection
        )
        
        return self.normalize(updated_proposal)
