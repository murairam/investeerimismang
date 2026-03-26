"""
Abstract base class that all LLM agents must implement.
"""
from abc import ABC, abstractmethod
from typing import Optional

from data.fetcher import MarketSnapshot
from portfolio.models import PortfolioProposal


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
