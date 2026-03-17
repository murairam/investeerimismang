"""
AlphaSharkOrchestrator — wires the full pipeline end-to-end.

Pipeline:
  1. DataFetcher.get_market_snapshot()
  2. Load previous portfolio from portfolio_history.json (if exists)
  3a. OpenAIStrategist (GPT-4o)       ─┐ run IN PARALLEL (ThreadPoolExecutor)
  3b. GeminiChallenger (gemini-flash)  ─┤ (challenger falls back to gpt-4o-mini on quota)
                                        ↓
  4. OpenAIRiskManager (GPT-4o-mini): meta-analyst, synthesises both proposals
  5. PortfolioValidator.validate() → normalize if needed
  6. Save portfolio to portfolio_history.json
  7. Append entry to DAILY_LOG.md
  8. WebhookDispatcher.send(formatted_embed)
  9. Log outcome to stdout (captured by GitHub Actions)
"""
import logging
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from agents.gemini_challenger import GeminiChallenger
from agents.openai_risk_manager import OpenAIRiskManager
from agents.openai_strategist import OpenAIStrategist
from config import CASH_POLICY
from data.cost_tracker import get_total_cost
from data.diary import append_entry as append_daily_log
from data.fetcher import DataFetcher
from data.learning_report import generate_pregame_learning_report
from data.meta_learning import generate_meta_learning_report
from data.mode_guard import enforce_mode_and_freeze, generate_live_handoff_if_due
from data.paper_account import rebalance_to_proposal
from data.portfolio_store import load_last, load_yesterday_prices, save as save_portfolio
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

        # Enforce pre-game/live mode behavior and post-start parameter freeze
        mode_info = enforce_mode_and_freeze(snapshot["as_of_date"], game_start_date="2026-04-06")
        logger.info(
            "Mode: %s (days to live: %d, lock: %s)",
            mode_info["mode"],
            mode_info["days_to_live"],
            mode_info["lock_status"],
        )

        # Step 2: load previous portfolio for continuity
        prior_portfolio = load_last()
        if prior_portfolio:
            logger.info("Prior portfolio loaded (%d positions)", len(prior_portfolio.positions))
        else:
            logger.info("No previous portfolio — cold start")

        # Compute actual P&L for prior portfolio using yesterday's saved prices
        daily_pnl: dict = {}
        portfolio_return_1d = 0.0
        benchmark_1d = snapshot.get("benchmark_return_1d", 0.0)
        alpha_1d = 0.0
        yesterday_prices = load_yesterday_prices()
        if prior_portfolio and yesterday_prices:
            for pos in prior_portfolio.positions:
                r = snapshot["returns_1d"].get(pos.ticker, float("nan"))
                if not math.isnan(r):
                    daily_pnl[pos.ticker] = r
                    portfolio_return_1d += pos.weight * r
            alpha_1d = portfolio_return_1d - benchmark_1d
            logger.info(
                "Yesterday: portfolio %.2f%% vs benchmark %.2f%% (alpha: %+.2f%%)",
                portfolio_return_1d * 100, benchmark_1d * 100, alpha_1d * 100,
            )
            winners = sorted([(t, r) for t, r in daily_pnl.items() if r > 0], key=lambda x: -x[1])
            losers = sorted([(t, r) for t, r in daily_pnl.items() if r < 0], key=lambda x: x[1])
            if winners:
                logger.info("Winners: %s", ", ".join(f"{t} {r:+.1%}" for t, r in winners[:3]))
            if losers:
                logger.info("Losers: %s", ", ".join(f"{t} {r:+.1%}" for t, r in losers[:3]))

        # Steps 3a + 3b: run strategist and challenger IN PARALLEL — they're fully independent
        logger.info("Calling OpenAIStrategist (GPT-4o) + GeminiChallenger in parallel …")
        strategist_proposal = None
        challenger_proposal = None
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_strategist = executor.submit(
                self.strategist.propose, snapshot, prior_portfolio
            )
            future_challenger = executor.submit(
                self.challenger.propose, snapshot, prior_portfolio
            )

            try:
                strategist_proposal = future_strategist.result()
            except Exception as exc:
                logger.exception("Strategist failed: %s", exc)

            try:
                challenger_proposal = future_challenger.result()
            except Exception as exc:
                logger.exception("Challenger failed: %s", exc)

        # Fail-safe routing
        if strategist_proposal is None and challenger_proposal is None:
            logger.error("Both strategist and challenger failed — aborting run")
            sys.exit(1)

        if strategist_proposal is None and challenger_proposal is not None:
            logger.warning("Strategist unavailable — using challenger proposal as base")
            strategist_proposal = challenger_proposal

        if challenger_proposal is None:
            logger.warning("Challenger unavailable — meta-analyst will use strategist only")
            challenger_proposal = type(strategist_proposal)()

        logger.info("Strategist produced %d positions", len(strategist_proposal.positions))
        if challenger_proposal.positions:
            logger.info("Challenger produced %d positions", len(challenger_proposal.positions))
        else:
            logger.info("Challenger unavailable — meta-analyst will use strategist only")

        # Step 4: Meta-analyst synthesises both proposals
        logger.info("Calling OpenAIRiskManager (GPT-4o-mini) — synthesising …")
        final_proposal = self.risk_manager.propose(
            snapshot,
            prior_proposal=strategist_proposal,
            challenger_proposal=challenger_proposal if challenger_proposal.positions else None,
        )

        # Step 5: Validate & normalise
        result = self.validator.validate(final_proposal, regime=snapshot.get("regime"))
        if not result.ok:
            logger.warning("Validation errors — normalising: %s", result.errors)
            final_proposal = self.validator.normalize(final_proposal)

            result = self.validator.validate(final_proposal, regime=snapshot.get("regime"))
            if not result.ok:
                logger.error("Portfolio still invalid after normalisation: %s", result.errors)
                sys.exit(1)

        # Step 5b: decide whether to keep residual cash or deploy to 100%
        total = sum(p.weight for p in final_proposal.positions)
        if total < self.validator.c["max_total_weight"] - 1e-9:
            deploy_cash, reason = self._cash_policy_decision(final_proposal, snapshot)
            residual_cash = self.validator.c["max_total_weight"] - total
            if deploy_cash:
                logger.info("Cash policy: deploying residual cash %.1f%% (%s)", residual_cash * 100, reason)
                final_proposal = self.validator.normalize(final_proposal)
                final_proposal.reasoning = (
                    f"{final_proposal.reasoning} Residual cash was deployed ({reason})."
                ).strip()
            else:
                logger.info("Cash policy: keeping cash buffer %.1f%% (%s)", residual_cash * 100, reason)
                final_proposal.reasoning = (
                    f"{final_proposal.reasoning} A cash buffer was intentionally retained ({reason})."
                ).strip()

        # Enforce game rule: max 25% cash (min 75% invested), regardless of cash policy
        total = sum(p.weight for p in final_proposal.positions)
        min_total = self.validator.c.get("min_total_weight", 0.75)
        if total < min_total - 1e-9:
            logger.info(
                "Portfolio at %.1f%% — deploying to meet 75%% minimum (game rule: max 25%% cash)",
                total * 100,
            )
            final_proposal = self.validator.normalize(final_proposal)

        total = sum(p.weight for p in final_proposal.positions)
        logger.info(
            "Final portfolio: %d positions, total weight %.1f%%, confidence %.0f%%",
            len(final_proposal.positions),
            total * 100,
            final_proposal.confidence * 100,
        )
        for pos in final_proposal.positions:
            logger.info("  %-12s  %5.1f%%  %s", pos.ticker, pos.weight * 100, pos.rationale[:60])

        # Step 6: Persist portfolio for tomorrow's run (include benchmark + P&L data)
        final_tickers = {pos.ticker for pos in final_proposal.positions}
        close_prices_for_positions = {
            t: p for t, p in snapshot.get("price_map", {}).items() if t in final_tickers
        }
        daily_performance: Optional[dict] = None
        if daily_pnl:
            daily_performance = {
                "portfolio_return_1d": portfolio_return_1d,
                "benchmark_return_1d": benchmark_1d,
                "alpha_1d": alpha_1d,
                "position_returns": daily_pnl,
            }
        save_portfolio(
            final_proposal,
            snapshot["as_of_date"],
            benchmark_return=snapshot["benchmark_return"],
            close_prices=close_prices_for_positions,
            daily_performance=daily_performance,
        )

        # Step 6b: paper trading account (virtual €10,000 baseline)
        paper_metrics = rebalance_to_proposal(
            final_proposal,
            as_of_date=snapshot["as_of_date"],
            price_map=snapshot.get("price_map", {}),
        )
        if paper_metrics:
            logger.info(
                "Paper account: equity €%.2f (%+.2f%% since start, %+.2f%% today)",
                paper_metrics["equity"],
                paper_metrics["return_since_start"] * 100,
                paper_metrics["daily_return"] * 100,
            )

        # Step 7: Append to daily log
        append_daily_log(
            final_proposal,
            snapshot,
            prior=prior_portfolio,
            performance=daily_performance,
            paper_metrics=paper_metrics,
        )

        # Step 7b: update pre-game learning report (towards April 6)
        learning_summary = generate_pregame_learning_report(target_date="2026-04-06")
        logger.info(
            "Learning report updated: days left %d, avg alpha %+.2f%%, paper return %+.2f%%",
            learning_summary["days_left"],
            learning_summary["avg_alpha"] * 100,
            learning_summary["paper_return"] * 100,
        )

        # Step 7c: generate meta-learning report (AI critiques its own reasoning quality)
        meta_summary = generate_meta_learning_report(target_date="2026-04-06")
        logger.info(
            "Meta-learning report updated: accuracy %.0f%%, insights %d, biases %d, alpha hit rate %.0f%%",
            meta_summary["accuracy_score"] * 100,
            meta_summary["insights_count"],
            meta_summary["biases_count"],
            meta_summary["alpha_hit_rate"] * 100,
        )

        # On/after live date, emit one-time handoff summary automatically
        handoff_info = generate_live_handoff_if_due(snapshot["as_of_date"], game_start_date="2026-04-06")
        if handoff_info and handoff_info.get("generated"):
            logger.info("Live handoff generated: %s", handoff_info["path"])

        # Step 8: Send to Discord
        embed = self.dispatcher.format_embed(
            final_proposal,
            snapshot,
            prior_proposal=prior_portfolio,
            paper_metrics=paper_metrics,
            mode=mode_info["mode"],
        )
        # Mention user in LIVE mode so they get a notification
        self.dispatcher.send(embed, mention_user=(mode_info["mode"] == "LIVE"))

        # Step 9: Print cost summary
        cost_summary = get_total_cost()
        logger.info(
            "💰 Today's API cost: $%.4f | Total project cost: $%.4f (%d runs)",
            cost_summary["daily_breakdown"].get(snapshot["as_of_date"], 0.0),
            cost_summary["total_cost"],
            cost_summary["run_count"],
        )

        logger.info("── AlphaShark pipeline complete ──")

    def _cash_policy_decision(self, proposal, snapshot) -> tuple[bool, str]:
        total = sum(p.weight for p in proposal.positions)
        cash_pct = self.validator.c["max_total_weight"] - total
        if cash_pct <= CASH_POLICY["min_cash_gap"]:
            return True, "residual below 1%"

        candidate_map = {c["ticker"]: c for c in snapshot["candidates"]}
        selected_vs_index = [
            candidate_map[p.ticker]["vs_index"]
            for p in proposal.positions
            if p.ticker in candidate_map
        ]
        avg_vs_index = sum(selected_vs_index) / len(selected_vs_index) if selected_vs_index else 0.0

        regime = snapshot.get("regime", "NEUTRAL")
        vix = snapshot.get("vix_level", float("nan"))
        benchmark_return = snapshot.get("benchmark_return", 0.0)

        if regime == "BEAR":
            return False, "bear regime"

        if not math.isnan(vix) and vix >= CASH_POLICY["high_vix_threshold"]:
            return False, f"elevated volatility (VIX {vix:.1f})"

        if benchmark_return <= CASH_POLICY["weak_benchmark_threshold"] and avg_vs_index < 0.01:
            return False, "weak benchmark momentum and modest stock alpha"

        if avg_vs_index >= CASH_POLICY["strong_alpha_threshold"]:
            return True, f"strong selected alpha ({avg_vs_index:+.1%})"

        if regime == "BULL":
            return True, "bull regime"

        return False, "neutral regime with mixed edge"
