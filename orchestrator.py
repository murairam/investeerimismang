"""
AlphaSharkOrchestrator — wires the full pipeline end-to-end.

Pipeline:
  1. DataFetcher.get_market_snapshot()
  2. Load previous portfolio from portfolio_history.json (if exists)
  3a. OpenAIStrategist (GPT-5.4)        ─┐ run IN PARALLEL (ThreadPoolExecutor 3 workers)
  3b. GeminiChallenger (Gemini 2.5 Flash)─┤ (Catalyst Hunter — FREE, independent)
  3c. OpenAIFullAnalyst (gpt-5.4-nano)   ─┘ (All-signal analyst — independent)
  3d. OpenAIDevil (gpt-5.4-nano): stress-tests top picks from all 3 proposals
  4. OpenAIRiskManager (GPT-5.4): synthesises all 3 proposals + bear cases
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
from agents.openai_challenger import OpenAIFullAnalyst
from agents.openai_devil import OpenAIDevil
from agents.openai_risk_manager import OpenAIRiskManager
from agents.openai_strategist import OpenAIStrategist
from config import CASH_POLICY
from data.cost_tracker import get_total_cost
from data.diary import append_entry as append_daily_log
from data.fetcher import DataFetcher
from data.learning_context import get_learning_context
from data.learning_state import load_learning_state
from data.learning_report import generate_pregame_learning_report
from data.meta_learning import generate_meta_learning_report
from data.mode_guard import enforce_mode_and_freeze, generate_live_handoff_if_due
from data.earnings_fetcher import fetch_upcoming_earnings, format_earnings_warning
from data.news_fetcher import fetch_candidate_news, format_news_for_prompt
from data.insider_fetcher import fetch_insider_trades, format_insider_context
from data.trends_fetcher import fetch_search_interest, format_trends_context
from data.paper_account import rebalance_to_proposal, reset_for_live
from data.portfolio_store import (
    build_signal_snapshot,
    load_last,
    load_yesterday_prices,
    save as save_portfolio,
)
from output.dispatcher import WebhookDispatcher, display_security_name

from portfolio.models import PortfolioProposal
from portfolio.validator import PortfolioValidator

logger = logging.getLogger(__name__)


def _display_name(ticker: str) -> str:
    return display_security_name(ticker)


class AlphaSharkOrchestrator:
    def __init__(self) -> None:
        self.fetcher = DataFetcher()
        self.strategist = OpenAIStrategist()
        self.gemini_challenger = GeminiChallenger()
        self.full_analyst = OpenAIFullAnalyst()
        self.devil = OpenAIDevil()
        self.risk_manager = OpenAIRiskManager()
        self.validator = PortfolioValidator()
        self.dispatcher = WebhookDispatcher()

    def run(self) -> None:
        logger.info("── AlphaShark pipeline starting ──")

        # Step 1: market data
        snapshot = self.fetcher.get_market_snapshot()
        breadth = snapshot.get("breadth_pct", float("nan"))
        term = snapshot.get("vix_term_ratio", float("nan"))
        logger.info(
            "Snapshot: %d candidates, benchmark %.1f%%, regime %s, breadth %.0f%%, VIX term %.2f",
            len(snapshot["candidates"]),
            snapshot["benchmark_return"] * 100,
            snapshot["regime"],
            breadth * 100 if not math.isnan(breadth) else 0,
            term if not math.isnan(term) else 0,
        )

        # Step 1b: inject learning context (what worked / didn't in past runs)
        learning_context = get_learning_context()
        snapshot["learning_context"] = learning_context
        learning_state = load_learning_state()
        if learning_context:
            logger.info("Learning context loaded (%d chars) — injecting into agent prompts", len(learning_context))
            logger.info(
                "Learning state: %d hard rules, %d biases, %d tracked winners, %d tracked losers",
                len(learning_state.get("hard_rules", [])),
                len(learning_state.get("biases_to_avoid", [])),
                len(learning_state.get("validated_winners", [])),
                len(learning_state.get("recurring_losers", [])),
            )
        else:
            logger.info("No learning context yet (first run or files missing)")

        # Steps 1c–1f: fetch news, earnings, insider trades, and trends IN PARALLEL
        top_tickers_50 = [c["ticker"] for c in snapshot["candidates"][:50]]
        us_candidates = [c["ticker"] for c in snapshot["candidates"] if "." not in c["ticker"]]
        all_candidate_tickers = [c["ticker"] for c in snapshot["candidates"]]

        def _fetch_news():
            try:
                items = fetch_candidate_news(top_tickers_50)
                logger.info("Fetched %d news headlines for %d tickers", len(items), len(top_tickers_50))
                return "news_headlines", format_news_for_prompt(items)
            except Exception as exc:
                logger.warning("News fetch failed (non-fatal): %s", exc)
                return "news_headlines", ""

        def _fetch_earnings():
            try:
                earnings = fetch_upcoming_earnings(top_tickers_50)
                if earnings:
                    logger.info("Earnings within 7 days: %s",
                                ", ".join(f"{e['ticker']} {e['earnings_date']}" for e in earnings))
                return "earnings_warning", format_earnings_warning(earnings)
            except Exception as exc:
                logger.warning("Earnings fetch failed (non-fatal): %s", exc)
                return "earnings_warning", ""

        def _fetch_insider():
            try:
                trades = fetch_insider_trades(us_candidates)
                if trades:
                    logger.info("Insider buys: %d found (%s)", len(trades),
                                ", ".join(t["ticker"] for t in trades[:5]))
                else:
                    logger.info("Insider buys: none above $50k threshold")
                return "insider_context", format_insider_context(trades)
            except Exception as exc:
                logger.warning("Insider fetch failed (non-fatal): %s", exc)
                return "insider_context", ""

        def _fetch_trends():
            try:
                trends = fetch_search_interest(all_candidate_tickers)
                if trends:
                    crowded = [t["ticker"] for t in trends if t["signal"] == "crowded"]
                    radar   = [t["ticker"] for t in trends if t["signal"] == "radar"]
                    logger.info("Trends: crowded=%s, under-radar=%s", crowded or "none", radar or "none")
                else:
                    logger.info("Trends: no data (throttled or failed)")
                return "trends_context", format_trends_context(trends)
            except Exception as exc:
                logger.warning("Trends fetch failed (non-fatal): %s", exc)
                return "trends_context", ""

        with ThreadPoolExecutor(max_workers=4) as pool:
            enrichment_futures = [
                pool.submit(_fetch_news),
                pool.submit(_fetch_earnings),
                pool.submit(_fetch_insider),
                pool.submit(_fetch_trends),
            ]
            for future in enrichment_futures:
                key, value = future.result()
                snapshot[key] = value

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
        benchmark_1d = snapshot.get("benchmark_return_1d", float("nan"))
        if math.isnan(benchmark_1d):
            logger.warning("benchmark_return_1d missing from snapshot — alpha will be unreliable; defaulting to 0")
            benchmark_1d = 0.0
        alpha_1d = 0.0
        yesterday_prices = load_yesterday_prices()
        if prior_portfolio and yesterday_prices:
            for pos in prior_portfolio.positions:
                r = snapshot["returns_1d"].get(pos.ticker, float("nan"))
                if not math.isnan(r):
                    daily_pnl[pos.ticker] = r
                    portfolio_return_1d += pos.weight * r
            alpha_1d = portfolio_return_1d - benchmark_1d
            regime = snapshot.get("regime", "NEUTRAL")
            # Regime-aware interpretation: in falling markets, positive alpha matters more than absolute return
            alpha_context = ""
            if regime == "BEAR" and alpha_1d > 0:
                alpha_context = " [BEAR: positive alpha = good defensive positioning]"
            elif regime == "NEUTRAL" and alpha_1d > 0.002:
                alpha_context = " [NEUTRAL: outperforming benchmark]"
            elif alpha_1d < -0.005:
                alpha_context = " [underperforming — review position sizing]"
            logger.info(
                "Yesterday: portfolio %.2f%% vs benchmark %.2f%% (alpha: %+.2f%%)%s",
                portfolio_return_1d * 100, benchmark_1d * 100, alpha_1d * 100, alpha_context,
            )
            winners = sorted([(t, r) for t, r in daily_pnl.items() if r > 0], key=lambda x: -x[1])
            losers = sorted([(t, r) for t, r in daily_pnl.items() if r < 0], key=lambda x: x[1])
            if winners:
                logger.info("Winners: %s", ", ".join(f"{t} {r:+.1%}" for t, r in winners[:3]))
            if losers:
                logger.info("Losers: %s", ", ".join(f"{t} {r:+.1%}" for t, r in losers[:3]))

        # Steps 3a + 3b + 3c: run all 3 analysts IN PARALLEL — fully independent
        logger.info(
            "Calling OpenAIStrategist (GPT-5.4) + GeminiChallenger (Gemini 2.5 Flash) "
            "+ OpenAIFullAnalyst (gpt-5.4-nano) in parallel …"
        )
        strategist_proposal = None
        challenger_proposal = None
        full_analyst_proposal = None
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_strategist = executor.submit(
                self.strategist.propose, snapshot, prior_portfolio
            )
            future_challenger = executor.submit(
                self.gemini_challenger.propose, snapshot, prior_portfolio
            )
            future_full = executor.submit(
                self.full_analyst.propose, snapshot, prior_portfolio
            )

            try:
                strategist_proposal = future_strategist.result()
            except Exception as exc:
                logger.exception("Strategist failed: %s", exc)

            try:
                challenger_proposal = future_challenger.result()
            except Exception as exc:
                logger.exception("GeminiChallenger failed: %s", exc)

            try:
                full_analyst_proposal = future_full.result()
            except Exception as exc:
                logger.exception("FullAnalyst failed: %s", exc)

        # Fail-safe: need at least one proposal
        active_proposals = [p for p in [strategist_proposal, challenger_proposal, full_analyst_proposal] if p is not None]
        if not active_proposals:
            logger.error("All 3 analysts failed — aborting run")
            sys.exit(1)

        if strategist_proposal is None:
            logger.warning("Strategist unavailable — using first available proposal as base")
            strategist_proposal = active_proposals[0]

        if not challenger_proposal or not challenger_proposal.positions:
            logger.warning("GeminiChallenger unavailable — meta-analyst will use 2 proposals only")

        if not full_analyst_proposal or not full_analyst_proposal.positions:
            logger.warning("FullAnalyst unavailable — meta-analyst will use 2 proposals only")

        logger.info("Strategist produced %d positions", len(strategist_proposal.positions))
        if challenger_proposal and challenger_proposal.positions:
            logger.info("GeminiChallenger produced %d positions", len(challenger_proposal.positions))
        if full_analyst_proposal and full_analyst_proposal.positions:
            logger.info("FullAnalyst produced %d positions", len(full_analyst_proposal.positions))

        # Log 3-way overlap — high cross-proposal overlap = strong conviction signal
        all_tickers = {p.ticker for p in strategist_proposal.positions}
        if challenger_proposal and challenger_proposal.positions:
            all_tickers |= {p.ticker for p in challenger_proposal.positions}
        if full_analyst_proposal and full_analyst_proposal.positions:
            all_tickers |= {p.ticker for p in full_analyst_proposal.positions}

        strat_set = {p.ticker for p in strategist_proposal.positions}
        chall_set = {p.ticker for p in challenger_proposal.positions} if challenger_proposal and challenger_proposal.positions else set()
        full_set = {p.ticker for p in full_analyst_proposal.positions} if full_analyst_proposal and full_analyst_proposal.positions else set()
        consensus = {t for t in all_tickers if sum([t in strat_set, t in chall_set, t in full_set]) >= 2}
        triple = {t for t in all_tickers if sum([t in strat_set, t in chall_set, t in full_set]) == 3}

        logger.info(
            "3-way consensus: %d triple picks, %d double picks across %d unique tickers",
            len(triple), len(consensus) - len(triple), len(all_tickers),
        )
        if triple:
            logger.info("Triple consensus (all 3 agents): %s", ", ".join(sorted(triple)))
        if consensus - triple:
            logger.info("Double consensus (2/3 agents): %s", ", ".join(sorted(consensus - triple)))

        # Step 3d: Devil's advocate — stress-tests top picks from all 3 proposals
        logger.info("Calling OpenAIDevil — stress-testing top picks …")
        bear_cases: dict = {}
        # Build a merged "challenger" view for Devil (union of all non-strategist picks)
        devil_challenger = PortfolioProposal(
            positions=(
                (challenger_proposal.positions if challenger_proposal and challenger_proposal.positions else []) +
                (full_analyst_proposal.positions if full_analyst_proposal and full_analyst_proposal.positions else [])
            )
        )
        try:
            bear_cases = self.devil.challenge(
                strategist_proposal,
                devil_challenger,
                snapshot,
            )
        except Exception as exc:
            logger.warning("Devil's advocate failed (non-fatal): %s", exc)

        # Step 4: Meta-analyst synthesises all 3 proposals + bear cases
        logger.info("Calling OpenAIRiskManager (GPT-5.4) — synthesising 3 proposals …")
        final_proposal = self.risk_manager.propose(
            snapshot,
            prior_proposal=strategist_proposal,
            challenger_proposal=challenger_proposal if (challenger_proposal and challenger_proposal.positions) else None,
            bear_cases=bear_cases if bear_cases else None,
            full_analyst_proposal=full_analyst_proposal if (full_analyst_proposal and full_analyst_proposal.positions) else None,
        )

        # Step 5: Validate & normalise
        result = self.validator.validate(final_proposal, regime=snapshot.get("regime"))
        validation_errors_before = list(result.errors)
        normalized = False
        if not result.ok:
            logger.warning("Validation errors — normalising: %s", result.errors)
            final_proposal = self.validator.normalize(final_proposal)
            normalized = True

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

        # Hard floor: game rule requires at least 75% invested (max 25% cash)
        total = sum(p.weight for p in final_proposal.positions)
        min_total = self.validator.c.get("min_total_weight", 0.75)
        if total < min_total - 1e-9:
            logger.info(
                "Portfolio at %.1f%% — deploying to meet %.0f%% game-rule minimum",
                total * 100, min_total * 100,
            )
            final_proposal = self.validator.normalize(final_proposal)

        # Round all weights to whole percentages (game UI has 1% precision)
        final_proposal = self.validator.round_to_whole_pct(final_proposal)

        total = sum(p.weight for p in final_proposal.positions)
        logger.info(
            "Final portfolio: %d positions, total weight %.1f%%, confidence %.0f%%",
            len(final_proposal.positions),
            total * 100,
            final_proposal.confidence * 100,
        )
        for pos in final_proposal.positions:
            logger.info(
                "  %-12s  %-24s %5.1f%%  %s",
                pos.ticker,
                _display_name(pos.ticker)[:24],
                pos.weight * 100,
                pos.rationale[:120],
            )

        # Devil's advocate audit: show how bear-case flags map to final weights
        if bear_cases:
            logger.info("── Devil's advocate impact audit ──")
            flagged_in_portfolio = [
                (pos, bear_cases[pos.ticker])
                for pos in final_proposal.positions
                if pos.ticker in bear_cases
            ]
            not_included = [
                (ticker, info)
                for ticker, info in bear_cases.items()
                if ticker not in {pos.ticker for pos in final_proposal.positions}
            ]
            for pos, info in sorted(flagged_in_portfolio, key=lambda x: x[1]["risk"]):
                risk_icon = "🔴" if info["risk"] == "HIGH" else ("🟡" if info["risk"] == "MEDIUM" else "🟢")
                logger.info(
                    "  %s %-12s %-20s %5.1f%% [%s] %s",
                    risk_icon,
                    pos.ticker,
                    _display_name(pos.ticker)[:20],
                    pos.weight * 100,
                    info["risk"],
                    info["bear_case"][:80],
                )
            if not_included:
                logger.info("  Excluded by Risk Manager (flagged but not in final portfolio):")
                for ticker, info in not_included:
                    risk_icon = "🔴" if info["risk"] == "HIGH" else ("🟡" if info["risk"] == "MEDIUM" else "🟢")
                    logger.info(
                        "    %s %-12s %-20s [%s] %s",
                        risk_icon,
                        ticker,
                        _display_name(ticker)[:20],
                        info["risk"],
                        info["bear_case"][:80],
                    )
            logger.info("──────────────────────────────────")

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

        signal_tickers = {
            pos.ticker for pos in final_proposal.positions
        } | {
            pos.ticker for pos in strategist_proposal.positions
        } | (
            {pos.ticker for pos in challenger_proposal.positions} if challenger_proposal and challenger_proposal.positions else set()
        ) | (
            {pos.ticker for pos in full_analyst_proposal.positions} if full_analyst_proposal and full_analyst_proposal.positions else set()
        )
        selected_now = {pos.ticker for pos in final_proposal.positions}
        candidate_alternatives = [
            {
                "ticker": candidate["ticker"],
                "selection_score": round(float(candidate.get("selection_score", 0.0)), 6),
                "mom_5d": round(float(candidate.get("mom_5d", 0.0)), 6) if candidate.get("mom_5d") is not None else None,
                "vol_ratio": round(float(candidate.get("vol_ratio", 0.0)), 6) if candidate.get("vol_ratio") is not None else None,
            }
            for candidate in snapshot["candidates"]
            if candidate["ticker"] not in selected_now
        ][:5]
        decision_context = {
            "strategist_proposal": strategist_proposal,
            "challenger_proposal": challenger_proposal if (challenger_proposal and challenger_proposal.positions) else None,
            "full_analyst_proposal": full_analyst_proposal if (full_analyst_proposal and full_analyst_proposal.positions) else None,
            "prior_portfolio": prior_portfolio,
            "bear_cases": bear_cases,
            "validation": {
                "normalized": normalized,
                "errors_before_normalization": validation_errors_before,
                "rounded_to_whole_pct": True,
                "post_round_total_weight": round(sum(p.weight for p in final_proposal.positions), 6),
            },
            "candidate_alternatives": candidate_alternatives,
            "signal_snapshot": build_signal_snapshot(
                snapshot["candidates"],
                signal_tickers,
                earnings_warning=snapshot.get("earnings_warning", ""),
            ),
            "returns_1d": snapshot.get("returns_1d", {}),
        }
        save_portfolio(
            final_proposal,
            snapshot["as_of_date"],
            benchmark_return=snapshot["benchmark_return"],
            close_prices=close_prices_for_positions,
            daily_performance=daily_performance,
            decision_context=decision_context,
        )

        # Step 6b: paper trading account (virtual €10,000 baseline)
        # On the first LIVE run the game resets all portfolios to €10,000 — mirror that here
        if mode_info["lock_status"] == "initialized":
            reset_for_live(snapshot["as_of_date"])
            logger.info("Paper account reset to €10,000 for LIVE mode start")

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
            mode=mode_info["mode"],
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
        accuracy_score = meta_summary.get("accuracy_score")
        if accuracy_score is None:
            logger.info(
                "Meta-learning report updated: accuracy N/A (insufficient data), insights %d, biases %d, alpha hit rate %.0f%%",
                meta_summary["insights_count"],
                meta_summary["biases_count"],
                meta_summary["alpha_hit_rate"] * 100,
            )
        else:
            logger.info(
                "Meta-learning report updated: accuracy %.0f%%, insights %d, biases %d, alpha hit rate %.0f%%",
                accuracy_score * 100,
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
        )
        # Mention user in LIVE mode so they get a notification
        self.dispatcher.send(embed, mention_user=True)

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

        return True, "neutral regime — cash earns zero, deploy residual"
