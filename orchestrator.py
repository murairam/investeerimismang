"""
AlphaSharkOrchestrator — wires the full pipeline end-to-end.

Pipeline:
  1. DataFetcher.get_market_snapshot()
  2. Load previous portfolio from portfolio_history.json (if exists)
    3a. Strategist        ─┐ run IN PARALLEL (ThreadPoolExecutor 3 workers)
    3b. Challenger        ─┤
        3c. Full Analyst    ─┘
    3d. Devil: stress-tests top picks from all 3 proposals
    4. Risk Manager: synthesises all 3 proposals + bear cases
  5. PortfolioValidator.validate() → normalize if needed
  6. Save portfolio to portfolio_history.json
  7. Append entry to DAILY_LOG.md
  8. WebhookDispatcher.send(formatted_embed)
  9. Log outcome to stdout (captured by GitHub Actions)
"""
import logging
import math
import sys
import time
from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
    as_completed,
)
from typing import Optional

from agents.challenger import GeminiChallenger
from agents.full_analyst import OpenAIFullAnalyst
from agents.devil import OpenAIDevil
from agents.risk_manager import OpenAIRiskManager
from agents.strategist import OpenAIStrategist
from config import (
    CASH_POLICY,
    API_TIMEOUT_SECONDS,
    ENABLE_COMPETITOR_INTEL,
    ENABLE_CROSS_CHECK,
    COMPETITOR_INTEL_URLS,
    OPENAI_FALLBACK_MODEL,
    OPENROUTER_ANALYST_MODEL,
    OPENROUTER_CHALLENGER_MODEL,
    OPENROUTER_DEVIL_MODEL,
)
from data.cost_tracker import get_total_cost
from data.diary import append_entry as append_daily_log
from data.fetcher import DataFetcher
from data.learning_context import get_learning_context
from data.leaderboard_fetcher import refresh_competitor_intel_file
from data.learning_state import load_learning_state
from data.learning_report import generate_pregame_learning_report
from data.meta_learning import generate_meta_learning_report, detect_strategy_decay
from data.mode_guard import enforce_mode_and_freeze, generate_live_handoff_if_due
from data.earnings_fetcher import (
    fetch_upcoming_earnings,
    format_earnings_opportunity,
    format_earnings_warning,
    scan_pead_candidates,
    format_pead_signals,
)
from data.news_fetcher import fetch_candidate_news, format_news_for_prompt
from data.insider_fetcher import fetch_insider_trades, format_insider_context
from data.trends_fetcher import fetch_search_interest, format_trends_context
from data.paper_account import rebalance_to_proposal, reset_for_live, load_verified_as_proposal, _load_raw as _load_raw_paper_account
from data.portfolio_store import (
    build_signal_snapshot,
    load_last,
    load_performance_history,
    load_yesterday_prices,
    save as save_portfolio,
)
from output.dispatcher import WebhookDispatcher, display_security_name

from portfolio.models import PortfolioProposal
from portfolio.validator import PortfolioValidator

logger = logging.getLogger(__name__)
_FULL_ANALYST_RESULT_TIMEOUT = 600  # keep generous but avoid >10 minute hangs
_ENRICHMENT_TOTAL_TIMEOUT = API_TIMEOUT_SECONDS * 3


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
        if not snapshot.get("candidates"):
            logger.error("Empty candidates list from fetcher — aborting")
            sys.exit(1)
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

        # Step 1a: commodity prices (Brent, WTI, NatGas) — energy thesis validation
        snapshot["commodity_context"] = self.fetcher.fetch_commodity_context()
        comm = snapshot["commodity_context"]
        if not math.isnan(comm.get("brent_price", float("nan"))):
            logger.info(
                "Commodities: Brent $%.1f (%+.1f%% 20d) | WTI $%.1f | NatGas $%.2f",
                comm["brent_price"],
                comm.get("brent_20d", float("nan")) * 100 if not math.isnan(comm.get("brent_20d", float("nan"))) else 0,
                comm.get("wti_price", float("nan")) if not math.isnan(comm.get("wti_price", float("nan"))) else 0,
                comm.get("natgas_price", float("nan")) if not math.isnan(comm.get("natgas_price", float("nan"))) else 0,
            )

        # Step 1a-ii: EUR/USD FX context — adjust US equity signals for EUR base currency
        # The game is EUR-denominated; US equity returns in USD overstate gains if EUR strengthens.
        fx_ctx = self.fetcher.fetch_fx_context()
        snapshot["fx_context"] = fx_ctx
        eurusd_20d = fx_ctx.get("eurusd_20d", float("nan"))
        eurusd_5d = fx_ctx.get("eurusd_5d", float("nan"))
        eurusd_1d = fx_ctx.get("eurusd_1d", float("nan"))
        if not math.isnan(eurusd_20d):
            n_adjusted = 0
            for c in snapshot["candidates"]:
                if "." not in c["ticker"]:  # US equity (no dot = not European/Baltic)
                    c["momentum"] -= eurusd_20d
                    if not math.isnan(c.get("mom_5d", float("nan"))) and not math.isnan(eurusd_5d):
                        c["mom_5d"] -= eurusd_5d
                    vol = c.get("vol_20d", float("nan"))
                    c["sharpe_20d"] = c["momentum"] / vol if (not math.isnan(vol) and vol > 0) else 0.0
                    c["vs_index"] = c["momentum"] - snapshot["benchmark_return"]
                    n_adjusted += 1
            if not math.isnan(eurusd_1d):
                for ticker in list(snapshot["returns_1d"].keys()):
                    if "." not in ticker:
                        snapshot["returns_1d"][ticker] -= eurusd_1d
            logger.info(
                "FX: EUR/USD 20d %+.2f%% — applied drag to %d US equity signals and returns_1d",
                eurusd_20d * 100, n_adjusted,
            )
        else:
            logger.warning("FX context unavailable — US returns not EUR-adjusted")

        # Step 1b: inject verified game equity into snapshot so agents see real performance
        _pa = _load_raw_paper_account()
        if _pa:
            snapshot["game_equity"] = float(_pa.get("last_equity", 10000.0))
            snapshot["game_return_pct"] = (snapshot["game_equity"] / float(_pa.get("initial_capital", 10000.0)) - 1)
        else:
            snapshot["game_equity"] = 10000.0
            snapshot["game_return_pct"] = 0.0

        # Step 1b-i: refresh competitor intelligence from manual watchlist (rate-limited)
        if ENABLE_COMPETITOR_INTEL and COMPETITOR_INTEL_URLS:
            try:
                refreshed = refresh_competitor_intel_file(
                    profile_urls=COMPETITOR_INTEL_URLS,
                    output_path="docs/competitor_intel.md",
                    min_refresh_hours=12.0,
                    force=False,
                )
                if refreshed:
                    logger.info("Competitor intelligence refreshed from manual watchlist")
                else:
                    logger.info("Competitor intelligence is fresh — reusing existing snapshot")
            except Exception as exc:
                logger.warning("Competitor intelligence refresh failed (non-fatal): %s", exc)

        # Step 1b: inject learning context (what worked / didn't in past runs)
        learning_context = get_learning_context(current_regime=snapshot.get("regime", "NEUTRAL"))
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

        # Signal importance: log which signals are most predictive this run (Change 1)
        _sig_imp_raw = learning_state.get("signal_importance", {})
        _sig_imp = _sig_imp_raw.get("global", _sig_imp_raw) if isinstance(_sig_imp_raw, dict) else {}
        if _sig_imp:
            top_signals = sorted(_sig_imp.items(), key=lambda x: -x[1])
            logger.info(
                "Signal importance (directional accuracy): %s",
                ", ".join(f"{s} {v:.0%}" for s, v in top_signals),
            )
            # Inject as context string so agents know which signals to trust most today
            sig_lines = ["Most predictive signals today (directional accuracy vs next-day return):"]
            sig_lines += [f"  {s}: {v:.0%} accuracy" for s, v in top_signals if v != 0.5]
            snapshot["signal_importance_context"] = "\n".join(sig_lines)
            # Append to learning context so all agents see it
            if sig_lines and len(_sig_imp) >= 3:
                existing_lc = snapshot.get("learning_context", "")
                sig_section = "\n=== SIGNAL IMPORTANCE (from recent performance) ===\n" + "\n".join(sig_lines)
                snapshot["learning_context"] = (existing_lc + sig_section) if existing_lc else sig_section

        # Strategy decay detection: compare recent alpha to prior alpha (Change 5)
        from data.portfolio_store import load_decision_history as _load_decision_hist
        _hist_for_decay = _load_decision_hist(max_days=20)
        decay_info = detect_strategy_decay(_hist_for_decay)
        snapshot["strategy_decay"] = decay_info
        if decay_info.get("decay_detected"):
            logger.warning(
                "Strategy decay detected: recent %d-day alpha %+.2f%% vs prior %d-day alpha %+.2f%% (delta %+.2f%%)",
                decay_info["recent_days"],
                decay_info["recent_avg_alpha"] * 100,
                decay_info["prior_days"],
                decay_info["prior_avg_alpha"] * 100,
                -decay_info["decay_magnitude"] * 100,
            )
        else:
            logger.info("Strategy decay check: %s", decay_info.get("status", "insufficient_data"))

        # Steps 1c–1f: fetch news, earnings, insider trades, and trends IN PARALLEL
        top_tickers_50 = [c["ticker"] for c in snapshot["candidates"][:50]]
        us_top_candidates = [c["ticker"] for c in snapshot["candidates"][:120] if "." not in c["ticker"]]
        all_candidate_tickers = [c["ticker"] for c in snapshot["candidates"]]

        def _fetch_news():
            try:
                items = fetch_candidate_news(top_tickers_50)
                logger.info("Fetched %d news headlines for %d tickers", len(items), len(all_candidate_tickers))
                return "news_headlines", format_news_for_prompt(items)
            except Exception as exc:
                logger.warning("News fetch failed (non-fatal): %s", exc)
                return "news_headlines", ""

        def _fetch_earnings():
            try:
                # 1. Upcoming earnings
                earnings = fetch_upcoming_earnings(top_tickers_50)
                snapshot["earnings"] = earnings # Store raw data
                
                if earnings:
                    logger.info("Earnings within 7 days: %s",
                                ", ".join(f"{e['ticker']} {e['earnings_date']}" for e in earnings))
                
                candidates = snapshot["candidates"]
                opportunity_text = format_earnings_opportunity(candidates, earnings)
                warning_text = format_earnings_warning(earnings, candidates)
                
                if opportunity_text:
                    logger.info("Pre-earnings opportunities identified: %s",
                                ", ".join(e["ticker"] for e in earnings))

                # 2. PEAD (Post-Earnings Announcement Drift)
                pead_signals = scan_pead_candidates(top_tickers_50)
                snapshot["pead_signals"] = pead_signals # Store raw data
                pead_text = format_pead_signals(pead_signals)
                if pead_text:
                    logger.info("PEAD opportunities identified: %s", 
                                ", ".join(s['ticker'] for s in pead_signals))

                combined = "\n".join(part for part in [pead_text, opportunity_text, warning_text] if part)
                return "earnings_warning", combined
            except Exception as exc:
                logger.warning("Earnings fetch failed (non-fatal): %s", exc)
                snapshot["earnings"] = []
                snapshot["pead_signals"] = []
                return "earnings_warning", ""

        def _fetch_insider():
            try:
                trades = fetch_insider_trades(us_top_candidates)
                if trades:
                    from collections import Counter
                    _tc = Counter(t["ticker"] for t in trades)
                    _summary = ", ".join(
                        f"{tk}×{n}" if n > 1 else tk
                        for tk, n in _tc.most_common(5)
                    )
                    logger.info("Insider buys: %d transactions, %d tickers (%s)", len(trades), len(_tc), _summary)
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

        enrichment_defaults = {
            "news_headlines": "",
            "earnings_warning": "",
            "insider_context": "",
            "trends_context": "",
        }
        enrichment_executor = ThreadPoolExecutor(max_workers=4)
        future_to_name: dict = {}
        try:
            future_to_name = {
                enrichment_executor.submit(_fetch_news): "news",
                enrichment_executor.submit(_fetch_earnings): "earnings",
                enrichment_executor.submit(_fetch_insider): "insider",
                enrichment_executor.submit(_fetch_trends): "trends",
            }
            start_times = {future: time.perf_counter() for future in future_to_name}

            for future in as_completed(future_to_name, timeout=_ENRICHMENT_TOTAL_TIMEOUT):
                name = future_to_name[future]
                key, value = future.result()
                enrichment_defaults[key] = value
                logger.info(
                    "Enrichment '%s' completed in %.1fs",
                    name,
                    time.perf_counter() - start_times[future],
                )
        except FuturesTimeoutError:
            logger.error(
                "Enrichment stage exceeded %.1fs; continuing with available context only",
                _ENRICHMENT_TOTAL_TIMEOUT,
            )
        finally:
            for future, name in future_to_name.items():
                if not future.done():
                    future.cancel()
                    logger.error("Enrichment '%s' did not finish and was cancelled", name)
            enrichment_executor.shutdown(wait=False, cancel_futures=True)

        snapshot.update(enrichment_defaults)

        # Enforce pre-game/live mode behavior and post-start parameter freeze
        mode_info = enforce_mode_and_freeze(snapshot["as_of_date"], game_start_date="2026-04-06")
        logger.info(
            "Mode: %s (days to live: %d, lock: %s)",
            mode_info["mode"],
            mode_info["days_to_live"],
            mode_info["lock_status"],
        )

        # Step 2: load previous portfolio for continuity
        # Prefer the verified game portfolio (from verify.py) so agents reason about
        # actual holdings, not the AI's prior proposal which may differ from the game.
        # --- DEBUG: Log the absolute path and contents of paper_account.json ---
        # import os
        # from data.paper_account import _PAPER_STORE_PATH
        # logger.info("[DEBUG] paper_account.json absolute path: %s", os.path.abspath(_PAPER_STORE_PATH))
        # try:
        #     with open(os.path.abspath(_PAPER_STORE_PATH), "r") as f:
        #         paper_data = f.read()
        #     logger.info("[DEBUG] paper_account.json contents: %s", paper_data)
        # except Exception as exc:
        #     logger.warning("[DEBUG] Could not read paper_account.json: %s", exc)

        verified_portfolio = load_verified_as_proposal()
        prior_portfolio = verified_portfolio or load_last()
        if prior_portfolio:
            source = "verified game" if verified_portfolio else "AI proposal"
            logger.info("Prior portfolio loaded (%d positions, source: %s)", len(prior_portfolio.positions), source)
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

        snapshot["portfolio_state_context"] = self._build_portfolio_state_context(
            prior_portfolio=prior_portfolio,
            portfolio_return_1d=portfolio_return_1d if daily_pnl else None,
            benchmark_return_1d=benchmark_1d if daily_pnl else None,
            alpha_1d=alpha_1d if daily_pnl else None,
        )
        if snapshot["portfolio_state_context"]:
            logger.info("Portfolio state context prepared (%d chars) for all agents", len(snapshot["portfolio_state_context"]))

        # Steps 3a + 3b + 3c: run all 3 analysts IN PARALLEL — fully independent
        logger.info(
            "Calling Strategist + Challenger + FullAnalyst in parallel … models: strategist=gpt-5.4, challenger=%s→gemini-2.5-flash→%s, full_analyst=%s→%s",
            OPENROUTER_CHALLENGER_MODEL,
            OPENAI_FALLBACK_MODEL,
            OPENROUTER_ANALYST_MODEL,
            OPENAI_FALLBACK_MODEL,
        )
        strategist_proposal = None
        challenger_proposal = None
        full_analyst_proposal = None
        n_agents = sum(1 for f in [self.strategist, self.gemini_challenger, self.full_analyst] if f is not None)
        executor = ThreadPoolExecutor(max_workers=n_agents)
        _parallel_start = time.perf_counter()
        try:
            future_start_times: dict = {}
            future_strategist = executor.submit(
                self.strategist.propose, snapshot, prior_portfolio
            )
            future_start_times[future_strategist] = ("Strategist", time.perf_counter())
            future_challenger = executor.submit(
                self.gemini_challenger.propose, snapshot, prior_portfolio
            )
            future_start_times[future_challenger] = (
                "Challenger",
                time.perf_counter(),
            )
            future_full = executor.submit(
                self.full_analyst.propose, snapshot, prior_portfolio
            )
            future_start_times[future_full] = (
                "FullAnalyst",
                time.perf_counter(),
            )

            _agent_timeout = API_TIMEOUT_SECONDS * 3
            _challenger_timeout = max(API_TIMEOUT_SECONDS * 3, 400)  # give Challenger even more headroom (user prefers longer)

            try:
                strategist_proposal = future_strategist.result(timeout=_agent_timeout)
                label, started = future_start_times[future_strategist]
                logger.info("[%s] completed in %.1fs", label, time.perf_counter() - started)
            except FuturesTimeoutError:
                future_strategist.cancel()
                label, started = future_start_times[future_strategist]
                logger.error("[%s] timed out after %.1fs — continuing without Strategist", label, time.perf_counter() - started)
            except Exception as exc:
                logger.exception("Strategist failed: %s", exc)
                label, started = future_start_times[future_strategist]
                logger.info("[%s] failed in %.1fs", label, time.perf_counter() - started)

            # Deadline-based timeout: 320s from when all futures were submitted.
            # Nemotron observed at ~276s total; this gives headroom regardless of Strategist elapsed time.
            _challenger_deadline = max(1.0, 320 - (time.perf_counter() - _parallel_start))
            try:
                _challenger_wait = min(_challenger_timeout, _challenger_deadline)
                challenger_proposal = future_challenger.result(timeout=_challenger_wait)
                label, started = future_start_times[future_challenger]
                logger.info("[%s] completed in %.1fs (timeout %.1fs)", label, time.perf_counter() - started, _challenger_wait)
            except FuturesTimeoutError:
                future_challenger.cancel()
                label, started = future_start_times[future_challenger]
                logger.error(
                    "[%s] timed out after %.1fs (timeout %.1fs) — continuing without Challenger",
                    label,
                    time.perf_counter() - started,
                    min(_challenger_timeout, _challenger_deadline),
                )
            except Exception as exc:
                logger.exception("Challenger failed: %s", exc)
                label, started = future_start_times[future_challenger]
                logger.info("[%s] failed in %.1fs", label, time.perf_counter() - started)

            try:
                full_analyst_proposal = future_full.result(timeout=_FULL_ANALYST_RESULT_TIMEOUT)
                label, started = future_start_times[future_full]
                logger.info("[%s] completed in %.1fs", label, time.perf_counter() - started)
            except FuturesTimeoutError:
                future_full.cancel()
                label, started = future_start_times[future_full]
                logger.error(
                    "[%s] timed out after %.1fs (timeout %.1fs) — continuing without FullAnalyst",
                    label,
                    time.perf_counter() - started,
                    _FULL_ANALYST_RESULT_TIMEOUT,
                )
            except Exception as exc:
                logger.exception("FullAnalyst failed: %s", exc)
                future_full.cancel()
                label, started = future_start_times[future_full]
                logger.info("[%s] failed in %.1fs", label, time.perf_counter() - started)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        # Fail-safe: need at least one proposal
        active_proposals = [p for p in [strategist_proposal, challenger_proposal, full_analyst_proposal] if p is not None]
        if not active_proposals:
            logger.error("All 3 analysts failed — aborting run")
            sys.exit(1)

        # base_proposal is passed to Devil and Risk Manager as the "Proposal A" anchor.
        # Do NOT reassign strategist_proposal — that causes phantom debate duplicates where
        # strategist_proposal and challenger_proposal point to the same object, inflating consensus.
        strategist_failed = strategist_proposal is None
        base_proposal = strategist_proposal if not strategist_failed else active_proposals[0]
        if strategist_failed:
            logger.warning("Strategist unavailable — using first available proposal as base for Risk Manager")

        if not challenger_proposal or not challenger_proposal.positions:
            logger.warning("Challenger unavailable — meta-analyst will use 2 proposals only")

        if not full_analyst_proposal or not full_analyst_proposal.positions:
            logger.warning("FullAnalyst unavailable — meta-analyst will use 2 proposals only")

        if strategist_proposal and strategist_proposal.positions:
            logger.info("Strategist produced %d positions (model: gpt-5.4)", len(strategist_proposal.positions))
        if challenger_proposal and challenger_proposal.positions:
            logger.info(
                "Challenger produced %d positions (route: %s→gemini-2.5-flash→%s)",
                len(challenger_proposal.positions),
                OPENROUTER_CHALLENGER_MODEL,
                OPENAI_FALLBACK_MODEL,
            )
        if full_analyst_proposal and full_analyst_proposal.positions:
            logger.info(
                "FullAnalyst produced %d positions (route: %s→%s)",
                len(full_analyst_proposal.positions),
                OPENROUTER_ANALYST_MODEL,
                OPENAI_FALLBACK_MODEL,
            )

        # Log 3-way overlap — high cross-proposal overlap = strong conviction signal
        all_tickers: set[str] = set()
        if strategist_proposal and strategist_proposal.positions:
            all_tickers |= {p.ticker for p in strategist_proposal.positions}
        if challenger_proposal and challenger_proposal.positions:
            all_tickers |= {p.ticker for p in challenger_proposal.positions}
        if full_analyst_proposal and full_analyst_proposal.positions:
            all_tickers |= {p.ticker for p in full_analyst_proposal.positions}

        strat_set = {p.ticker for p in strategist_proposal.positions} if strategist_proposal and strategist_proposal.positions else set()
        chall_set = {p.ticker for p in challenger_proposal.positions} if challenger_proposal and challenger_proposal.positions else set()
        full_set = {p.ticker for p in full_analyst_proposal.positions} if full_analyst_proposal and full_analyst_proposal.positions else set()
        consensus = {t for t in all_tickers if sum([t in strat_set, t in chall_set, t in full_set]) >= 2}
        triple = {t for t in all_tickers if sum([t in strat_set, t in chall_set, t in full_set]) == 3}

        _n_active = sum(1 for s in [strat_set, chall_set, full_set] if s)
        logger.info(
            "%d-way consensus: %d triple picks, %d double picks across %d unique tickers",
            _n_active, len(triple), len(consensus) - len(triple), len(all_tickers),
        )
        if triple:
            logger.info("Triple consensus (all 3 agents): %s", ", ".join(sorted(triple)))
        if consensus - triple:
            logger.info("Double consensus (2/3 agents): %s", ", ".join(sorted(consensus - triple)))

        # Step 3d: Optional cross-agent debate (deprecated; keep behind flag for shadow comparison)
        if ENABLE_CROSS_CHECK:
            # Only include proposals that genuinely exist — no duplicates from fallback copies.
            debate_flags: dict[str, dict] = {}
            live_proposals = []
            if strategist_proposal and strategist_proposal.positions:
                live_proposals.append(("strategist", self.strategist, strategist_proposal))
            if challenger_proposal and challenger_proposal.positions:
                live_proposals.append(("challenger", self.gemini_challenger, challenger_proposal))
            if full_analyst_proposal and full_analyst_proposal.positions:
                live_proposals.append(("full_analyst", self.full_analyst, full_analyst_proposal))
            if len(live_proposals) >= 2:
                with ThreadPoolExecutor(max_workers=3) as dex:
                    debate_futures = {
                        name: dex.submit(
                            agent.cross_check,
                            snapshot,
                            own,
                            [p for n, a, p in live_proposals if p is not own],
                        )
                        for name, agent, own in live_proposals
                    }
                    for name, fut in debate_futures.items():
                        try:
                            debate_flags[name] = fut.result(timeout=45)
                        except Exception as exc:
                            logger.warning("Cross-check for %s failed (non-fatal): %s", name, exc)

                # Compile debate flags into a summary string for the Risk Manager
                debate_lines = []
                all_disagrees: dict[str, list[str]] = {}
                all_agrees: list[str] = []
                for agent_name, result in debate_flags.items():
                    agrees = result.get("agrees", [])
                    disagrees = result.get("disagrees", [])
                    if agrees:
                        all_agrees.extend(agrees)
                    for item in disagrees:
                        ticker = item.get("ticker", "?")
                        reason = item.get("reason", "")
                        all_disagrees.setdefault(ticker, []).append(f"{agent_name}: {reason}")

                if all_agrees:
                    from collections import Counter
                    agree_counts = Counter(all_agrees)
                    strong = [t for t, n in agree_counts.items() if n >= 2]
                    if strong:
                        debate_lines.append(f"Cross-agent agreements (2+ agents agree): {', '.join(sorted(set(strong)))}")
                if all_disagrees:
                    debate_lines.append("Cross-agent disagreements (one agent excluded while peers included at >=15%):")
                    for ticker, reasons in all_disagrees.items():
                        debate_lines.append(f"  {ticker}: " + " | ".join(reasons[:2]))

                if debate_lines:
                    snapshot["debate_summary"] = "\n".join(debate_lines)
                    logger.info("Cross-agent debate: %d agreements, %d disagreements surfaced",
                                len(all_agrees), len(all_disagrees))
                else:
                    logger.info("Cross-agent debate: no significant disagreements")
        else:
            logger.info("Cross-agent debate disabled by config flag (ENABLE_CROSS_CHECK=false)")

        # Step 3e: Devil's advocate — stress-tests top picks from all 3 proposals
        logger.info("Calling Devil — stress-testing top picks (route: %s→%s) …", OPENROUTER_DEVIL_MODEL, OPENAI_FALLBACK_MODEL)
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
                base_proposal,
                devil_challenger,
                snapshot,
            )
        except Exception as exc:
            logger.warning("Devil's advocate failed (non-fatal): %s", exc)

        # Step 4: Meta-analyst synthesises all available proposals + bear cases
        _available = sum(1 for p in [strategist_proposal, challenger_proposal, full_analyst_proposal] if p and p.positions)
        logger.info("Calling Risk Manager — synthesising %d proposal(s) (model: gpt-5.4) …", _available)
        final_proposal = self.risk_manager.propose(
            snapshot,
            prior_proposal=base_proposal,
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

        # Step 5c: enforce sector rotation cap AFTER all normalization/rounding
        # so that normalize() and round_to_whole_pct() cannot re-inflate a capped sector.
        final_proposal = self.risk_manager._enforce_sector_rotation_cap(final_proposal, snapshot)

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
                pos.rationale,
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
                    info["bear_case"],
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
                        info["bear_case"],
                    )
            logger.info("──────────────────────────────────")

        # Step 6: Persist portfolio for tomorrow's run (include benchmark + P&L data)
        final_tickers = {pos.ticker for pos in final_proposal.positions}
        close_prices_for_positions = {
            t: p for t, p in snapshot.get("price_map", {}).items() if t in final_tickers
        }
        missing_prices = final_tickers - set(snapshot.get("price_map", {}).keys())
        if missing_prices:
            logger.warning(
                "No close price for tickers (paper account may drift): %s",
                ", ".join(sorted(missing_prices)),
            )
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
        } | (
            {pos.ticker for pos in strategist_proposal.positions} if strategist_proposal and strategist_proposal.positions else set()
        ) | (
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
            "regime": snapshot.get("regime", "NEUTRAL"),
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
            skip_label = " [already processed today]" if paper_metrics.get("skipped_duplicate") else ""
            logger.info(
                "Paper account: equity €%.2f (%+.2f%% since start, %+.2f%% today)%s",
                paper_metrics["equity"],
                paper_metrics["return_since_start"] * 100,
                paper_metrics["daily_return"] * 100,
                skip_label,
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
        try:
            handoff_info = generate_live_handoff_if_due(snapshot["as_of_date"], game_start_date="2026-04-06")
            if handoff_info and handoff_info.get("generated"):
                logger.info("Live handoff generated: %s", handoff_info["path"])
        except Exception as exc:
            logger.warning("Live handoff generation failed (non-fatal): %s", exc, exc_info=True)

        # Step 8: Send to Discord
        # Use the verified game portfolio as the diff baseline so "Changes from Yesterday"
        # reflects actual game holdings, not the AI's previous proposal.
        verified_prior = load_verified_as_proposal()
        embed = self.dispatcher.format_embed(
            final_proposal,
            snapshot,
            prior_proposal=verified_prior or prior_portfolio,
            paper_metrics=paper_metrics,
        )
        # Mention user only in LIVE mode so they get a phone notification; skip pings during PREGAME
        is_live = mode_info.get("mode") == "LIVE"
        self.dispatcher.send(embed, mention_user=is_live)

        # Step 9: Print cost summary
        cost_summary = get_total_cost()
        logger.info(
            "💰 Today's API cost: $%.4f | Total project cost: $%.4f (%d runs)",
            cost_summary["daily_breakdown"].get(snapshot["as_of_date"], 0.0),
            cost_summary["total_cost"],
            cost_summary["run_count"],
        )

        logger.info("── AlphaShark pipeline complete ──")

    @staticmethod
    def _build_portfolio_state_context(
        prior_portfolio: Optional[PortfolioProposal],
        portfolio_return_1d: Optional[float],
        benchmark_return_1d: Optional[float],
        alpha_1d: Optional[float],
    ) -> str:
        lines: list[str] = ["### Portfolio State & History (must use in reasoning)"]

        if prior_portfolio and prior_portfolio.positions:
            lines.append("Current holdings from verified/game state:")
            for pos in prior_portfolio.positions:
                lines.append(f"  - {pos.ticker}: {pos.weight:.1%}")
        else:
            lines.append("Current holdings: cold start (no prior portfolio found).")

        if (
            portfolio_return_1d is not None
            and benchmark_return_1d is not None
            and alpha_1d is not None
        ):
            lines += [
                "Yesterday performance (from actual prior holdings):",
                (
                    f"  - Portfolio {portfolio_return_1d:+.2%} vs benchmark {benchmark_return_1d:+.2%} "
                    f"(alpha {alpha_1d:+.2%})"
                ),
            ]

        perf_history = load_performance_history(max_days=5)
        daily_entries = [entry for entry in perf_history if "portfolio_return_1d" in entry]
        if daily_entries:
            lines.append("Recent performance history (last 5 days):")
            for entry in daily_entries:
                date_label = entry.get("date", "?")
                p_ret = entry.get("portfolio_return_1d")
                b_ret = entry.get("benchmark_return_1d")
                a_ret = entry.get("alpha_1d")
                if any(v is None for v in (p_ret, b_ret, a_ret)):
                    continue
                lines.append(
                    f"  - {date_label}: portfolio {p_ret:+.2%}, benchmark {b_ret:+.2%}, alpha {a_ret:+.2%}"
                )

        lines += [
            "Use this context explicitly: keep strong winners, cut persistent laggards, and justify turnover/size changes against this state.",
        ]
        return "\n".join(lines)

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
