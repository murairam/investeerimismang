"""
Abstract base class that all LLM agents must implement.
"""
import logging
from abc import ABC, abstractmethod
from typing import Optional

from data.fetcher import MarketSnapshot
from portfolio.models import PortfolioProposal, Position

logger = logging.getLogger(__name__)


def conviction_to_weight(conviction: int) -> float:
    """Convert a conviction score (1-10) to a preliminary position weight.

    Uses a simple linear scale anchored to game constraints:
      10 → 0.25 (max allowed weight)
       5 → 0.13 (mid-range)
       1 → 0.05 (minimum allowed weight)

    The Risk Manager applies full Kelly sizing after synthesis; this function
    provides a consistent preliminary weight for proposals from sub-agents so
    the Risk Manager can compare proposals on a common scale.

    If the LLM accidentally returns a ``weight`` float instead of ``conviction``
    (e.g. 0.20 rather than 8), the value is detected and converted back to an
    integer conviction score via inverse linear mapping before scaling.
    """
    # Guard: if the model returned a weight (0.0-1.0) instead of conviction (1-10),
    # convert it back to an approximate integer conviction score.
    if isinstance(conviction, float) and 0.0 < conviction <= 1.0:
        conviction = max(1, min(10, round(conviction * 40)))  # 0.25 → 10, 0.05 → 2

    conviction = max(1, min(10, int(conviction)))
    # Linear interpolation: conviction 1 → 0.05, conviction 10 → 0.25
    weight = 0.05 + (conviction - 1) * (0.20 / 9)
    return round(weight, 4)


def validate_conviction_variance(proposal: PortfolioProposal, agent_name: str) -> PortfolioProposal:
    """Ensure positions have differentiated conviction scores.

    If all convictions are identical, spread them linearly by position order
    (first position gets +2, last gets -2, clamped to 1-10) so the Risk Manager
    receives differentiated inputs for weighting decisions.
    Logs a WARNING when triggered so LLM conviction drift can be monitored.
    """
    if not proposal.positions:
        return proposal
    convictions = [p.conviction for p in proposal.positions if p.conviction is not None]
    if len(convictions) < 2:
        return proposal
    if len(set(convictions)) > 1:
        return proposal  # already differentiated — no action needed

    base_conv = convictions[0]
    n = len(proposal.positions)
    logger.warning(
        "%s: all %d positions have identical conviction=%s — spreading linearly",
        agent_name, n, base_conv,
    )
    new_positions = []
    # n >= 2 is guaranteed by the guard at the top of the function, so n-1 >= 1 always.
    spread = min(2, n - 1)
    step = (2.0 * spread) / (n - 1)  # float step avoids integer-division zero for n >= 6
    for i, pos in enumerate(proposal.positions):
        # Spread: top pick gets base+spread, bottom gets base-spread (clamped 1-10)
        adj = max(1, min(10, round(base_conv + spread - i * step)))
        new_weight = conviction_to_weight(adj)
        new_positions.append(
            Position(
                ticker=pos.ticker,
                weight=new_weight,
                rationale=pos.rationale,
                conviction=adj,
            )
        )
    return PortfolioProposal(
        positions=new_positions,
        reasoning=proposal.reasoning,
        confidence=proposal.confidence,
        learning_reflection=proposal.learning_reflection,
    )


class BaseAgent(ABC):
    @abstractmethod
    def propose(
        self,
        snapshot: MarketSnapshot,
        prior_proposal: Optional[PortfolioProposal] = None,
    ) -> PortfolioProposal:
        """
        Generate or revise a PortfolioProposal.

        Args:
            snapshot:       Current market data and momentum signals.
            prior_proposal: Output from the preceding agent (Phase 2 hook).
                            Strategist receives None; Risk Manager receives Strategist's output.
        """
        ...

    def cross_check(
        self,
        snapshot: MarketSnapshot,
        own_proposal: PortfolioProposal,
        peer_proposals: list[PortfolioProposal],
    ) -> dict:
        """
        Optional second-pass debate. Given own proposal and peer proposals, identify
        agreements and disagreements on individual tickers.

        Returns a dict:
          {"agrees": ["TICKER1", ...], "disagrees": [{"ticker": "X", "reason": "..."}]}

        Default: no-op (returns empty dict). Subclasses may override for richer debate.
        """
        return {}
