"""
Abstract base class that all LLM agents must implement.
"""
from abc import ABC, abstractmethod
from typing import Optional

from data.fetcher import MarketSnapshot
from portfolio.models import PortfolioProposal


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
