#!/usr/bin/env python3
"""
Migrate portfolio_history.json to a PostgreSQL database.
Automatically creates the schema and inserts all historical data.

Usage:
    python scripts/migrate_to_postgres.py
"""
import json
import os
import sys
import psycopg2
from psycopg2.extras import Json
from dotenv import load_dotenv

def main():
    load_dotenv()
    db_url = os.environ.get("SUPABASE_CONNECTION_STRING")
    if not db_url:
        print("❌ ERROR: SUPABASE_CONNECTION_STRING not found in environment. Please add it to your .env file.")
        sys.exit(1)

    history_path = os.path.join(os.path.dirname(__file__), "..", "portfolio_history.json")
    if not os.path.exists(history_path):
        print(f"❌ ERROR: Could not find {history_path}")
        sys.exit(1)

    with open(history_path, "r") as f:
        data = json.load(f)
    
    history = data.get("history", [])
    if not history:
        print("No historical records found in JSON.")
        sys.exit(1)

    print(f"Connecting to database...")
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)
        
    cur = conn.cursor()

    print("Creating tables...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_runs (
            date DATE PRIMARY KEY,
            source VARCHAR(50),
            regime VARCHAR(20),
            benchmark_return_1d DOUBLE PRECISION,
            portfolio_return_1d DOUBLE PRECISION,
            alpha_1d DOUBLE PRECISION,
            signal_snapshot JSONB,
            decision_metrics JSONB,
            bear_cases JSONB,
            price_map JSONB
        );

        CREATE TABLE IF NOT EXISTS portfolio_positions (
            id SERIAL PRIMARY KEY,
            date DATE REFERENCES daily_runs(date),
            ticker VARCHAR(20),
            weight DOUBLE PRECISION,
            rationale TEXT,
            tags JSONB,
            return_1d DOUBLE PRECISION
        );

        CREATE TABLE IF NOT EXISTS agent_proposals (
            id SERIAL PRIMARY KEY,
            date DATE REFERENCES daily_runs(date),
            agent VARCHAR(50),
            ticker VARCHAR(20),
            weight DOUBLE PRECISION,
            rationale TEXT,
            tags JSONB
        );

        CREATE TABLE IF NOT EXISTS competition_standings (
            date DATE PRIMARY KEY,
            rank INT,
            total_participants INT
        );
    """)
    conn.commit()

    print(f"Migrating {len(history)} daily records...")
    for record in history:
        date = record.get("date")
        if not date:
            continue

        source = record.get("provenance", "ai_proposed")
        regime = record.get("regime", "NEUTRAL")
        
        outcomes = record.get("outcomes", {}).get("1d", {})
        p_ret = outcomes.get("portfolio_return")
        b_ret = outcomes.get("benchmark_return")
        alpha = outcomes.get("alpha")
        pos_returns = outcomes.get("position_returns", {})

        cur.execute("""
            INSERT INTO daily_runs (date, source, regime, benchmark_return_1d, portfolio_return_1d, alpha_1d, signal_snapshot, decision_metrics, bear_cases)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (date) DO UPDATE SET
                source = EXCLUDED.source,
                regime = EXCLUDED.regime,
                benchmark_return_1d = EXCLUDED.benchmark_return_1d,
                portfolio_return_1d = EXCLUDED.portfolio_return_1d,
                alpha_1d = EXCLUDED.alpha_1d,
                signal_snapshot = EXCLUDED.signal_snapshot,
                decision_metrics = EXCLUDED.decision_metrics,
                bear_cases = EXCLUDED.bear_cases
        """, (date, source, regime, b_ret, p_ret, alpha, Json(record.get("signal_snapshot", {})), Json(record.get("decision_metrics", {})), Json(record.get("bear_cases", {}))))

        cur.execute("DELETE FROM agent_proposals WHERE date = %s", (date,))
        cur.execute("DELETE FROM portfolio_positions WHERE date = %s", (date,))
        cur.execute("DELETE FROM competition_standings WHERE date = %s", (date,))

        final_port = record.get("final_portfolio", {})
        for pos in final_port.get("positions", []):
            ret_1d = pos_returns.get(pos["ticker"])
            cur.execute("INSERT INTO portfolio_positions (date, ticker, weight, rationale, tags, return_1d) VALUES (%s, %s, %s, %s, %s, %s)",
                        (date, pos["ticker"], pos["weight"], pos["rationale"], Json(pos.get("tags", [])), ret_1d))

        for agent_key, agent_name in [("strategist_proposal", "strategist"), ("challenger_proposal", "challenger"), ("full_analyst_proposal", "full_analyst")]:
            prop = record.get(agent_key)
            if prop:
                for pos in prop.get("positions", []):
                    cur.execute("INSERT INTO agent_proposals (date, agent, ticker, weight, rationale, tags) VALUES (%s, %s, %s, %s, %s, %s)",
                                (date, agent_name, pos["ticker"], pos["weight"], pos["rationale"], Json(pos.get("tags", []))))

        standing = record.get("competition_standing")
        if isinstance(standing, dict) and standing.get("rank") and standing.get("total"):
            standing_date = standing.get("date", date)
            cur.execute("""
                INSERT INTO competition_standings (date, rank, total_participants)
                VALUES (%s, %s, %s)
            """, (standing_date, standing.get("rank"), standing.get("total")))

    if "close_prices" in data:
        latest_date = history[-1]["date"] if history else None
        if latest_date:
            cur.execute("UPDATE daily_runs SET price_map = %s WHERE date = %s", (Json(data["close_prices"]), latest_date))

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Migration complete! Your database is now online and populated.")

if __name__ == "__main__":
    main()