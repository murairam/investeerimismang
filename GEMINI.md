# Gemini Codelab Instructions

This document provides a condensed overview of the AlphaShark project, specifically tailored for the Gemini Codelab assistant.

## Project Overview

AlphaShark is an autonomous quantitative trading agent built to compete in the Äripäev/SEB Investment Game. It uses a multi-agent AI system to analyze market data, generate investment strategies, and execute trades in a simulated environment. The project runs daily via GitHub Actions.

## Key Files

- **`main.py`**: The main entry point for the application.
- **`orchestrator.py`**: Coordinates the entire pipeline, from data fetching to portfolio generation and submission.
- **`config.py`**: Contains key configuration parameters, including the universe of stocks, signal parameters, and game constraints.
- **`agents/`**: This directory contains the logic for the different AI agents:
    - `strategist.py`: The primary agent, focused on momentum and breakout strategies.
    - `challenger.py`: A catalyst-hunting agent.
    - `full_analyst.py`: A third agent providing an all-signals view.
    - `devil.py`: A bear-case stress tester.
    - `risk_manager.py`: Synthesizes the proposals from the other agents into a final portfolio.
- **`data/`**: Modules for fetching, storing, and managing financial data.
- **`portfolio/`**: Contains models and validation logic for the investment portfolio.
- **`scripts/`**: A collection of utility scripts for tasks like checking status, verifying portfolios, and running backtests.

## Core Workflow

1.  **Data Fetching**: The system fetches market data, macroeconomic signals, and other enrichment data (news, earnings, etc.).
2.  **Agent Analysis**: The Strategist, Challenger, and Full Analyst agents run in parallel to propose investment portfolios.
3.  **Cross-Agent Debate**: The agents exchange and critique each other's proposals.
4.  **Devil's Advocate**: The Devil's Advocate agent pressure-tests the top picks.
5.  **Risk Management**: The Risk Manager synthesizes all inputs to create a final, validated portfolio.
6.  **Execution**: The final portfolio is posted to Discord and recorded.
7.  **Learning**: The system learns from its performance to improve future decisions.

## Agent Roles

- **Strategist (GPT-5.4)**: Focuses on momentum and breakout signals.
- **Challenger (NVIDIA Nemotron via OpenRouter)**: Hunts for catalysts and event-driven opportunities.
- **Full Analyst (DeepSeek V3.2 via OpenRouter)**: Takes a holistic view of all available signals.
- **Devil's Advocate (Qwen3-235B-A22B via OpenRouter)**: Challenges the top picks with bear cases.
- **Risk Manager (GPT-5.4)**: Synthesizes all proposals, manages risk, and constructs the final portfolio.

## Key Commands

- `python main.py`: Run the full pipeline.
- `python scripts/status.py`: View the project dashboard.
- `python scripts/verify.py`: Interactively confirm or correct the daily portfolio.
- `python scripts/check_models.py`: Test the model routes and API keys.
- `python scripts/historical_shadow_trader.py`: Run a historical backtest.
