"""
Validates and normalises a PortfolioProposal against game constraints.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from config import GAME_CONSTRAINTS, POSITION_TARGETS_BY_REGIME, SECTOR_MAP
from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]


class PortfolioValidator:
    def __init__(self) -> None:
        self.c = GAME_CONSTRAINTS

    def _position_limits(self, regime: Optional[str]) -> tuple[int, int]:
        if regime and regime in POSITION_TARGETS_BY_REGIME:
            target = POSITION_TARGETS_BY_REGIME[regime]
            min_stocks = max(self.c["min_stocks"], target["min_stocks"])
            max_stocks = min(self.c["max_stocks"], target["max_stocks"])
            return min_stocks, max_stocks
        return self.c["min_stocks"], self.c["max_stocks"]

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

        # Sector concentration — advisory only (normalize() cannot fix this)
        max_sector_w = self.c.get("max_sector_weight", 1.0)
        if max_sector_w < 1.0:
            sector_weights: dict[str, float] = {}
            for pos in proposal.positions:
                sector = SECTOR_MAP.get(pos.ticker, "?")
                sector_weights[sector] = sector_weights.get(sector, 0.0) + pos.weight
            for sector, sw in sector_weights.items():
                if sw > max_sector_w + 1e-9:
                    logger.warning(
                        "Advisory: sector '%s' weight %.1f%% exceeds %.0f%% max — consider redistributing",
                        sector, sw * 100, max_sector_w * 100,
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

        return PortfolioProposal(
            positions=positions,
            reasoning=proposal.reasoning,
            confidence=proposal.confidence,
        )

    def round_to_whole_pct(self, proposal: PortfolioProposal) -> PortfolioProposal:
        """
        Round all weights to whole percentages that sum to exactly 100%.
        Uses largest-remainder method to distribute rounding errors.
        """
        weights = [p.weight for p in proposal.positions]
        floored = [int(w * 100) for w in weights]
        remainders = [(w * 100 - floored[i], i) for i, w in enumerate(weights)]
        deficit = 100 - sum(floored)
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
        )

    def enforce_sector_cap(
        self, proposal: PortfolioProposal, candidates: list[dict]
    ) -> PortfolioProposal:
        """
        If any sector exceeds max_sector_weight (35%), replace the weakest
        position in that sector with the best available candidate from an
        underrepresented sector.

        'Weakest' = lowest sharpe_20d for that sector among current positions.
        'Best available' = highest sharpe_20d candidate not already in portfolio
                          and not in the over-weighted sector.

        Runs up to 5 iterations to converge.
        """
        max_sw = self.c.get("max_sector_weight", 1.0)
        if max_sw >= 1.0:
            return proposal

        sharpe_map = {c["ticker"]: c.get("sharpe_20d", 0.0) for c in candidates}

        positions = list(proposal.positions)

        for _ in range(5):
            # Compute current sector weights
            sector_weights: dict[str, float] = {}
            for p in positions:
                s = SECTOR_MAP.get(p.ticker, "?")
                sector_weights[s] = sector_weights.get(s, 0.0) + p.weight

            over = {s: w for s, w in sector_weights.items() if w > max_sw + 1e-9}
            if not over:
                break  # All sectors within cap

            current_tickers = {p.ticker for p in positions}

            # Pick the most over-weight sector
            bad_sector = max(over, key=lambda s: over[s])

            # Find weakest position in that sector
            sector_positions = [p for p in positions if SECTOR_MAP.get(p.ticker, "?") == bad_sector]
            if not sector_positions:
                break
            weakest = min(sector_positions, key=lambda p: sharpe_map.get(p.ticker, 0.0))

            # Find best available replacement: not in portfolio, not in bad_sector
            replacements = [
                c for c in candidates
                if c["ticker"] not in current_tickers
                and SECTOR_MAP.get(c["ticker"], "?") != bad_sector
            ]
            if not replacements:
                logger.warning("Sector cap: no replacement candidates for %s sector — cannot fix", bad_sector)
                break

            best_replacement = max(replacements, key=lambda c: c.get("sharpe_20d", 0.0))

            logger.info(
                "Sector cap enforcement: replacing %s (%s sector, sharpe %.2f) "
                "with %s (%s sector, sharpe %.2f) — %s sector was %.0f%% > %.0f%% cap",
                weakest.ticker, bad_sector, sharpe_map.get(weakest.ticker, 0.0),
                best_replacement["ticker"], SECTOR_MAP.get(best_replacement["ticker"], "?"),
                best_replacement.get("sharpe_20d", 0.0),
                bad_sector, sector_weights[bad_sector] * 100, max_sw * 100,
            )

            positions = [
                Position(
                    ticker=best_replacement["ticker"],
                    weight=weakest.weight,
                    rationale=f"Sector cap replacement for {weakest.ticker} ({bad_sector} sector >{max_sw:.0%})",
                )
                if p.ticker == weakest.ticker else p
                for p in positions
            ]

        return PortfolioProposal(
            positions=positions,
            reasoning=proposal.reasoning,
            confidence=proposal.confidence,
        )