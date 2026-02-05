# Task: Strategy Pivot to BTC Structure/Momentum

- [x] Update Requirements (spec.md) <!-- id: 0 -->
    - [x] Draft new `spec.md` with BTC, MTF, and Structure focus
    - [x] Define dynamic risk management rules
    - [x] Remove rigid performance targets
- [x] Update Agent Configuration (CLAUDE.md) <!-- id: 4 -->
    - [x] Align `research_agent` with BTC structure focus
    - [x] Align `data_agent` with MTF requirements
    - [x] Align `strategy_agent` with new logic
    - [x] Align `backtest_agent` with intraday focus
- [x] Research & Design <!-- id: 1 -->
    - [x] Research recent crypto trends (2025-2026 context)
    - [x] Update `research/momentum_research.md` (or create new)
- [/] Implementation (Planned) <!-- id: 2 -->
    - [x] Update Data Pipeline (BTC fetching, MTF support)
    - [x] Implement new Strategy Logic (Structure analysis)
    - [x] Update Backtest Engine
- [x] Optimization (Current) <!-- id: 3 -->
    - [x] Create Optimization Script (Parameter Grid)
    - [x] Run Batch Backtests (ATR, RSI, Lookback)
    - [x] Analyze Stability and Select Best params
- [x] Refinement (Planned) <!-- id: 4 -->
    - [x] Add Chop Index Filter to BTCStrategy
    - [x] Relax Trailing Stop Logic in BacktestEngine
    - [x] Run Validation Backtest

- [x] Final Review (Current) <!-- id: 5 -->
    - [x] Analyze Code Quality and Logic
    - [x] verify alignment with Market Structure principles
    - [x] Create docs/final_review.md

- [ ] Future Work (Deferred) <!-- id: 6 -->
    - [ ] Shift Entry Timeframe to 1H/4H (to combat fees)
    - [ ] Re-run Optimization for higher timeframes
    - [ ] Implement Live Trading Connector
