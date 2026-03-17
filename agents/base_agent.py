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
