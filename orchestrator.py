"""
AlphaSharkOrchestrator — wires the full pipeline end-to-end.

Pipeline:
  1. DataFetcher.get_market_snapshot()
  2. Load previous portfolio from portfolio_history.json (if exists)
  3a. OpenAIStrategist.propose()    ─┐
  3b. GeminiChallenger.propose()    ─┤ independent proposals
                                     ↓
  4. OpenAIRiskManager (meta-analyst): synthesises both → final portfolio
  5. PortfolioValidator.validate() → normalize if needed
  6. Save portfolio to portfolio_history.json
  7. Append entry to DAILY_LOG.md
  8. WebhookDispatcher.send(formatted_embed)
  9. Log outcome to stdout (captured by GitHub Actions)
"""
import logging
import sys

from agents.gemini_challenger import GeminiChallenger
from agents.openai_risk_manager import OpenAIRiskManager
from agents.openai_strategist import OpenAIStrategist
from data.diary import append_entry as append_daily_log
from data.fetcher import DataFetcher
from data.portfolio_store import load_last, save as save_portfolio
from output.dispatcher import WebhookDispatcher
from portfolio.validator import PortfolioValidator

logger = logging.getLogger(__name__)


class AlphaSharkOrchestrator:
    def __init__(self) -> None:
        self.fetcher = DataFetcher()
        self.strategist = OpenAIStrategist()
        self.challenger = GeminiChallenger()
        self.risk_manager = OpenAIRiskManager()
        self.validator = PortfolioValidator()
        self.dispatcher = WebhookDispatcher()

    def run(self) -> None:
        logger.info("── AlphaShark pipeline starting ──")

        # Step 1: market data
        snapshot = self.fetcher.get_market_snapshot()
        logger.info(
            "Snapshot: %d candidates, benchmark %.1f%%, regime %s",
            len(snapshot["candidates"]),
            snapshot["benchmark_return"] * 100,
            snapshot["regime"],
        )

        # Step 2: load previous portfolio for continuity
        prior_portfolio = load_last()
        if prior_portfolio:
            logger.info("Prior portfolio loaded (%d positions)", len(prior_portfolio.positions))
        else:
            logger.info("No previous portfolio — cold start")

        # Step 3a: GPT-4o Strategist
        logger.info("Calling OpenAIStrategist (GPT-4o) …")
        strategist_proposal = self.strategist.propose(snapshot, prior_proposal=prior_portfolio)

        # Step 3b: Gemini Challenger (independent second opinion, free tier)
        logger.info("Calling GeminiChallenger (gemini-2.0-flash) …")
        challenger_proposal = self.challenger.propose(snapshot, prior_proposal=prior_portfolio)
        if challenger_proposal.positions:
            logger.info("Challenger produced %d positions", len(challenger_proposal.positions))
        else:
            logger.info("Challenger unavailable — meta-analyst will use strategist only")

        # Step 4: Meta-analyst synthesises both proposals
        logger.info("Calling OpenAIRiskManager (GPT-4o-mini) — synthesising proposals …")
        final_proposal = self.risk_manager.propose(
            snapshot,
            prior_proposal=strategist_proposal,
            challenger_proposal=challenger_proposal if challenger_proposal.positions else None,
        )

        # Step 5: Validate & normalise
        result = self.validator.validate(final_proposal)
        if not result.ok:
            logger.warning("Validation errors — normalising: %s", result.errors)
            final_proposal = self.validator.normalize(final_proposal)
            result = self.validator.validate(final_proposal)
            if not result.ok:
                logger.error("Portfolio still invalid after normalisation: %s", result.errors)
                sys.exit(1)

        total = sum(p.weight for p in final_proposal.positions)
        logger.info(
            "Final portfolio: %d positions, total weight %.1f%%, confidence %.0f%%",
            len(final_proposal.positions),
            total * 100,
            final_proposal.confidence * 100,
        )
        for pos in final_proposal.positions:
            logger.info("  %-12s  %5.1f%%  %s", pos.ticker, pos.weight * 100, pos.rationale[:60])

        # Step 6: Persist portfolio for tomorrow's run
        save_portfolio(final_proposal, snapshot["as_of_date"])

        # Step 7: Append to daily log
        append_daily_log(final_proposal, snapshot, prior=prior_portfolio)

        # Step 8: Send to Discord
        embed = self.dispatcher.format_embed(final_proposal, snapshot)
        self.dispatcher.send(embed)

        logger.info("── AlphaShark pipeline complete ──")
