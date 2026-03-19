"""
Portfolio data models.
"""
from dataclasses import dataclass, field


@dataclass
class Position:
    ticker: str
    weight: float       # fraction, e.g. 0.15 = 15%
    rationale: str


@dataclass
class PortfolioProposal:
    positions: list[Position] = field(default_factory=list)
    reasoning: str = ""
    confidence: float = 0.0     # 0.0 – 1.0
    learning_reflection: str = ""  # one-sentence adaptation note from learning context
