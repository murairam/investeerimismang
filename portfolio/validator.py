"""
Validates and normalises a PortfolioProposal against game constraints.
"""
import logging
from dataclasses import dataclass

from config import GAME_CONSTRAINTS
from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]


class PortfolioValidator:
    def __init__(self) -> None:
        self.c = GAME_CONSTRAINTS

    def validate(self, proposal: PortfolioProposal) -> ValidationResult:
        errors: list[str] = []

        n = len(proposal.positions)
        if n < self.c["min_stocks"]:
            errors.append(f"Too few stocks: {n} < {self.c['min_stocks']}")
        if n > self.c["max_stocks"]:
            errors.append(f"Too many stocks: {n} > {self.c['max_stocks']}")

        tickers = [p.ticker for p in proposal.positions]
        dupes = [t for t in set(tickers) if tickers.count(t) > 1]
        if dupes:
            errors.append(f"Duplicate tickers: {dupes}")

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

        return ValidationResult(ok=len(errors) == 0, errors=errors)

    def normalize(self, proposal: PortfolioProposal) -> PortfolioProposal:
        """
        Auto-scales weights to conform to game constraints without violating them.
        1. Clips all weights to the allowed [min_weight, max_weight] range.
        2. If total weight > 100%, scales down weights proportionally based on how
           much "headroom" they have above the minimum weight. This prevents any
           weight from being scaled down below the minimum.
        Returns a new PortfolioProposal; the original is not mutated.
        """
        mn, mx = self.c["min_weight"], self.c["max_weight"]

        # 1. Clip individual weights to [min_weight, max_weight]
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
            # Sum of weight amounts that can be reduced (i.e., the part above min_weight)
            total_reducible = sum(p.weight - mn for p in positions)

            if total_reducible > 1e-9:  # Avoid division by zero
                positions = [
                    Position(
                        ticker=p.ticker,
                        # Reduce weight proportionally to its "reducible" part
                        weight=p.weight - overweight * (p.weight - mn) / total_reducible,
                        rationale=p.rationale,
                    )
                    for p in positions
                ]

        return PortfolioProposal(
            positions=positions,
            reasoning=proposal.reasoning,
            confidence=proposal.confidence,
        )