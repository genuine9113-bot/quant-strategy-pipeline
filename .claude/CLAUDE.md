## Project Context
This is a quantitative trading strategy development project.
We use a modular approach with specialized subagents.

## Project Structure
- research/: Momentum indicator research
- data/: Data pipeline and preprocessing
- strategies/: Strategy implementation
- backtest/: Backtesting engine
- results/: Performance reports
- docs/: Documentation

## Coding Standards
- Language: Python 3.10+
- Style: Black formatter, PEP 8
- Libraries: pandas, numpy, yfinance, backtrader
- Documentation: Docstrings for all functions
- Testing: pytest with >80% coverage

## Workflow
1. Read spec.md for requirements
2. Use subagents for each phase
3. Each subagent outputs to its designated folder
4. Main agent orchestrates and reviews

## Subagents

### research_agent
**Purpose**: Research BTC market structure and trends for 2025-2026
**Context**: Crypto market cycles, Price Action, Multi-Timeframe Analysis
**Output**: research/btc_structure_research.md
**Rules**:
- Focus on Bitcoin (BTC) market structure (Higher Highs/Lows)
- Research Multi-Timeframe (MTF) alignment strategies (4H/Daily trend + 15m/1H entry)
- Define dynamic risk management (Swing lows, ATR trails)
- Cite recent crypto trends and liquidity concepts

### data_agent
**Purpose**: Build data pipeline for fetching Multi-Timeframe BTC data
**Context**: Crypto data APIs, OHLCV processing, MTF data structures
**Output**: data/pipeline.py
**Rules**:
- Fetch BTC-USD data for multiple timeframes (1d, 4h, 1h, 15m)
- Use appropriate sources (yfinance if sufficient, or alternatives)
- Handle timestamps to ensure alignment across timeframes
- Calculate relevant indicators (EMA, RSI, ATR) for each timeframe
- Save processed data in an MTF-friendly format

### strategy_agent
**Purpose**: Implement the BTC Structure & Momentum strategy
**Context**: Price Action logic, Trend Following, Dynamic Risk
**Output**: strategies/btc_strategy.py
**Rules**:
- Implement logic from spec.md:
  - HTF (Trend): EMA(200) + Structure
  - LTF (Entry): Break of Structure or Momentum Divergence
- Implement dynamic Stop Loss (Swing Low) and Trailing Stop
- Focus on "Positive Expectancy" logic rather than rigid targets

### backtest_agent
**Purpose**: Run MTF backtests and analyze trade expectancy
**Context**: Intraday backtesting, Trade logging, Risk metrics
**Output**: backtest/engine.py, results/backtest_report.md
**Rules**:
- Support intraday simulation (event-driven or vector-based)
- Metrics focus: Expectancy, Profit Factor, Risk-Adjusted Return
- Benchmark: Buy-and-Hold BTC
- Generate visual analysis of trade entries vs structure

### review_agent
**Purpose**: Final review of strategy robustness
**Context**: Code quality, Logic verification, Risk/Reward analysis
**Output**: docs/final_review.md
**Rules**:
- Verify "Structure First" logic is correctly implemented
- Check against 2025-2026 market conditions
- Assess risk management dynamics (e.g. slippage handling)
- Suggest improvements for "Positive Expectancy"

### optimization_agent
**Purpose**: Optimize strategy parameters and filters for robustness
**Context**: Parameter sweeps, Stability analysis, Overfitting checks
**Output**: results/optimization_report.md, updated configuration
**Rules**:
- Identify key parameters (ATR multiplier, RSI thresholds, Lookbacks)
- Run batch backtests across different market regimes
- Focus on "Parameter Stability" (plateaus) rather than single highest profit peaks
- Recommend specific parameter sets that maximize Expectancy and Win Rate

## Commands for Main Agent
When orchestrating, use these patterns:
```
# Start a phase
"Use [agent_name] to [specific task]"

# Review results
"Review the output from [agent_name] at [file_path]"

# Integrate results
"Integrate results from [agent_1] and [agent_2]"
```

## Important Notes
- Each subagent works independently
- Main agent reviews each output before proceeding
- If a subagent output is unsatisfactory, re-run with more specific instructions
- Keep main context clean by using subagents for heavy computation
EOF

cat .claude/CLAUDE.md