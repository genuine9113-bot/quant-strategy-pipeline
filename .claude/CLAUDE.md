## Project Context
This is a quantitative trading strategy development project for **Regime-Adaptive Aggressive Alpha (RAAA)** strategy.
We use a modular approach with specialized subagents.

## Project Structure
- research/: Market trend and strategy research
- data/: Data pipeline and preprocessing (OKX API, Funding Rate, On-Chain data)
- strategies/: Strategy implementation (Regime engine, RAAA logic, Risk manager)
- backtest/: Backtesting engine (Multi-asset, Leverage, Liquidation simulation)
- results/: Performance reports
- docs/: Documentation (reviews, walkthroughs)
- tests/: Unit and integration tests
- logs/: Application and module logs
- requirements.txt: Python dependencies (ccxt, pandas, numpy, etc.)

## Coding Standards
- Language: Python 3.10+
- Style: Black formatter, PEP 8
- Dependencies: Listed in `requirements.txt` (ccxt, pandas, numpy, ta-lib, etc.)
- Documentation: Docstrings for all functions
- Testing: pytest with >80% coverage
- Logging: Standardized `logging` (INFO level, file + console output)
- Error Handling: Retry logic for APIs, Graceful degradation for missing data

## Strategy Overview: RAAA (Regime-Adaptive Aggressive Alpha)
- **Exchange**: OKX (Perpetual Futures, USDT-Margined Swap)
- **Assets**: BTC/USDT Perp, ETH/USDT Perp
- **Direction**: Long & Short (양방향)
- **Leverage**: 5× (Isolated Margin)
- **Timeframes**: 15m (Entry), 1H (Signal), 4H (Regime)
- **Frequency**: High (일평균 2-5 trades)
- **Target**: CAGR > 100%, Profit Factor > 1.8, Max DD < 30%

## Execution Flow
1. **Research**: `research_agent` -> `research/strategy_research.md` (RAAA Strategy Definition)
2. **Data**: `data_agent` -> `data/pipeline.py` (OKX API, Multi-Asset, Multi-TF, Funding Rate)
3. **Regime**: `regime_agent` -> `strategies/regime.py` (4-State Regime Classification)
4. **Strategy**: `strategy_agent` -> `strategies/raaa_strategy.py` (Regime-based Entry/Exit)
5. **Risk**: `risk_agent` -> `strategies/risk_manager.py` (Global Risk Controls)
6. **Backtest**: `backtest_agent` -> `results/backtest_report.md` (Multi-asset, Leverage, Funding)
7. **Optimization**: `optimization_agent` -> `results/optimization_report.md` (Walk-Forward)
8. **Review**: `review_agent` -> `docs/final_review.md` (Final Sign-off)

## Logging Standards
- **Format**: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- **Output**:
    - Console: INFO+
    - Module-specific files: `logs/<module_name>.log` (DEBUG+)
    - Examples: `logs/pipeline.log`, `logs/regime.log`, `logs/strategy.log`, `logs/backtest.log`
- **Requirement**: All key actions (Trade signals, Regime changes, API calls, Risk events) must be logged.

## Error Handling Guidelines
- **API Calls**: Implement exponential backoff for network requests (3 retries min).
- **Data Integrity**: Validate schema (columns, types) before processing. Raise `ValueError` on missing critical data.
- **Fail-Safe**: Strategies must handle empty/nan signals without crashing (default to Neutral/No-Action).
- **Liquidation Defense**: Monitor margin ratio and enforce position reduction at 80% threshold.

## Subagents

### research_agent
**Purpose**: Research profitable crypto futures strategies (2025-2026)
**Context**: Multi-Regime trading, Trend Following, Mean Reversion, Volatility Breakout
**Output**: research/strategy_research.md
**Rules**:
- Focus on "Regime-Adaptive Aggressive Alpha" (RAAA) logic
- Research 4-State Regime Classification (Trending Bull/Bear, Chop, Squeeze)
- Analyze impact of leverage, funding rates, and liquidation risk
- Study BTC-ETH correlation patterns and cross-asset signals

### data_agent
**Purpose**: Build data pipeline for Multi-Asset, Multi-Timeframe perpetual futures data
**Context**: OKX API (ccxt), OHLCV processing, Funding Rate collection, Indicator calculation
**Output**: data/pipeline.py
**Rules**:
- **Data Source**: OKX API via `ccxt` library
- **Assets**: BTC/USDT-SWAP, ETH/USDT-SWAP (Perpetual Futures)
- **Timeframes**: 15m, 1H, 4H (3-layer hierarchy)
- **Period**: 2025-02-01 to 2026-02-01 (1 year)
- **Indicators**:
  - Trend/Momentum: EMA(9, 20, 50, 200), RSI(14), ADX(14) with ±DI, Momentum(12)
  - Volatility: ATR(14) + Percentile(50), BB(20, 2.0/2.5), Keltner(20, 1.5), BB Width Percentile(50)
  - Structure: Donchian(20), Volume SMA(20)
  - Cross-Asset: BTC-ETH Rolling Correlation(48H), ETH/BTC Ratio BB(20, 2.0)
- **Funding Rate**: Collect 8H funding rate history from OKX (`/api/v5/public/funding-rate-history`)
- **On-Chain (Optional)**: Glassnode/CryptoQuant API (Netflow, MVRV, SOPR, Whale Tx)
- **Data Validation**: Check for missing bars, align timestamps across timeframes
- **Output**: Save processed data in parquet format (`data/processed/`)

### regime_agent
**Purpose**: Implement 4-State Regime Classification Engine
**Context**: Market state detection, Regime transition rules, Cooldown management
**Output**: strategies/regime.py
**Rules**:
- **4H Regime Classification** (re-evaluate every 4H bar close):
  - **State 1: Trending Bull**
    - Condition: EMA(20) > EMA(50) > EMA(200) AND ADX(14) > 25 AND +DI > -DI
    - Allow: Long Only
    - ETH Condition: ETH Long entry allowed only when BTC is also Trending Bull with active BTC position
  - **State 2: Trending Bear**
    - Condition: EMA(20) < EMA(50) < EMA(200) AND ADX(14) > 25 AND -DI > +DI
    - Allow: Short Only
  - **State 3: High Volatility Chop**
    - Condition: ADX(14) < 20 AND ATR Percentile(50) > 70th
    - Allow: Long & Short (Mean Reversion)
  - **State 4: Low Volatility Squeeze**
    - Condition: ADX(14) < 20 AND ATR Percentile(50) < 30th AND BB Width Percentile(50) < 20th
    - Allow: Long & Short (Breakout)
  - **Undefined Regime (No-Trade Zone)**:
    - ADX 20~25 range OR incomplete EMA ordering (e.g., 20 > 200 > 50)
    - Action: Stop new entries, manage existing positions with stop/TP only
- **Regime Transition Rules**:
  - Trending Bull ↔ Trending Bear: Immediately close all positions (Market Order)
  - Other transitions: Keep existing positions, stop/TP manages exit
  - Cooldown: 8 hours (2 × 4H bars) after regime change before applying new regime strategies
- **Logging**: Log all regime changes with timestamp and reason

### strategy_agent
**Purpose**: Implement RAAA strategy with Regime-based entry/exit logic
**Context**: Multi-strategy per regime, Cross-asset signals, Pyramiding in trends
**Output**: strategies/raaa_strategy.py
**Rules**:
- **Entry Strategies by Regime** (detailed in spec.md):
  - **Trending Bull**: Momentum Continuation, Pullback Entry, Breakout Continuation
  - **Trending Bear**: Mirror of Bull strategies (Short)
  - **High Volatility Chop**: BB Mean Reversion, RSI Divergence Reversal
  - **Low Volatility Squeeze**: BB-Keltner Squeeze Breakout, Volume Spike Breakout
- **Cross-Asset Signals**:
  - Monitor BTC-ETH Rolling Correlation(48H)
  - Corr > 0.85: Same direction on both → Confidence +1
  - Corr < 0.5: Divergence opportunity (one Long, one Short)
  - Leader-Follower: BTC breakout → Wait for ETH follow-through
- **Position Sizing**:
  - Base Risk: 3% of Equity per trade
  - Size (USD) = (Equity × 0.03) / (1.5 × ATR(14))
  - Required Margin = Size (USD) / Leverage(5×)
  - Max Single Position Margin: 25% of Equity
  - Max Single Position Notional: 125% of Equity (= 25% × 5×)
- **Max Concurrent Positions**: **2 Total (BTC 1개 + ETH 1개)**
  - **BTC**: 최대 1 포지션 (피라미딩 포함 시 최대 2단계)
  - **ETH**: 최대 1 포지션 (피라미딩 포함 시 최대 2단계)
  - **전체 최대 마진 사용**: Equity의 50% (2 positions × 25% each)
  - **전체 최대 명목가치**: Equity의 250% (= 50% × 5×)
- **Pyramiding (Trending Regime Only)**:
  - **조건**:
    - 현재 Regime이 Trending Bull 또는 Trending Bear일 때만
    - 기존 포지션이 **1.5R 이상 수익** 중일 때
    - Partial TP 시작 전이어야 함 (포지션 축소 후에는 피라미딩 금지)
  - **추가 사이즈**: 초기 사이즈의 **50%**
  - **최대 추가**: 1회만 (총 2단계: 100% + 50% = 150%)
  - **평균 단가 재계산**:
    - 새 평균가 = (Entry1 × Size1 + Entry2 × Size2) / (Size1 + Size2)
  - **손절 재계산**:
    - 새 Stop = 평균 단가 - 1.5 × ATR(14) (Long)
    - 새 Stop = 평균 단가 + 1.5 × ATR(14) (Short)
  - **R 기준 재계산**:
    - 피라미딩 후 1R = 재계산된 Stop 거리 (평균가 기준 1.5 ATR)
    - Partial TP의 2R/3R/4R은 새 평균가 + 새 R 기준으로 계산
  - **Trailing Stop**: 전체 포지션 기준 최고점/최저점에서 2 ATR 추적
  - **제한**: Mean Reversion 및 Squeeze Breakout 전략에서는 피라미딩 금지
- **Cooldown**:
  - 손실 청산 후: 30분 (2 × 15m bars)
  - 수익 청산 후: 15분 (1 × 15m bar)
  - Regime 전환 후: 8시간 (2 × 4H bars)
  - 적용 시점: 포지션 전량 청산 시에만 (Partial TP에는 미적용)
- **Exit Rules**:
  - Initial Stop: 1.5 × ATR(14) from entry (피라미딩 후 평균가 기준으로 재계산)
  - Trailing Stop: 2 × ATR from highest high/lowest low (activates after 1R profit)
  - Partial TP: 2R (40%), 3R (30%), 4R+ (Trail)
  - Time Stop: Trending (24H), Mean Reversion (12H), Squeeze (6H)
  - Regime Change: Opposite trending → Immediate close
- **Confidence Multiplier**:
  - Dampened (Negative signals): 0.5×
  - Normal: 1.0×
  - High (Cross-asset confirmation): 1.5×
  - Very High (Cross-asset + On-chain): 2.0×
  - **Important**: After applying Confidence Multiplier, single position margin must not exceed 25% cap

### risk_agent
**Purpose**: Implement global risk controls and position limits
**Context**: Drawdown management, Volatility scaling, Liquidation defense, Funding risk
**Output**: strategies/risk_manager.py
**Rules**:
- **Drawdown Limits**:
  - DD > 15%: Position size 50% reduction
  - DD > 20%: Stop new entries, manage existing only
  - DD > 30%: Close all positions, halt strategy
- **Daily Loss Limit**: 5% of Equity per day (UTC reset)
- **Volatility Scaling**:
  - ATR Percentile > 90th: Position size 50% reduction
  - ATR Percentile > 95th: Stop new entries
- **Correlation Risk**:
  - BTC-ETH Corr > 0.9: Total margin limit 40% (기본 50% → 40% 축소)
- **Funding Rate Risk**:
  - Funding > ±0.1%: Confidence -1 for that direction
  - Funding > ±0.3%: Stop new entries in that direction
  - Track and log 8H funding costs/income in P&L
- **Liquidation Defense**:
  - Ensure liquidation price buffer: ≥ 3 × ATR from entry
  - Margin ratio > 80%: Reduce position by 50%
  - Account margin usage > 50%: Stop new entries (전체 마진 한도)
- **Position Limits Enforcement**:
  - Max 2 concurrent positions (BTC 1 + ETH 1)
  - Max margin per position: 25% of Equity
  - Total margin usage: ≤ 50% of Equity
  - Confidence Multiplier 적용 후에도 25% 마진 캡 유지

### backtest_agent
**Purpose**: Run backtests with multi-asset, leverage, funding, and liquidation simulation
**Context**: High-frequency intraday backtesting, Trade logging, Risk metrics
**Output**: backtest/engine.py, results/backtest_report.md
**Rules**:
- **Simulation Capabilities**:
  - Multi-asset: BTC/USDT-SWAP + ETH/USDT-SWAP simultaneous
  - Multi-timeframe: 15m entry, 1H signal, 4H regime
  - Leverage: 5× with isolated margin per position
  - Initial Capital: $100,000 (USDT)
  - Partial exits: Support 40%/30%/30% splits
  - Pyramiding: Support 2-stage entries with average price and R recalculation
- **Cost Model**:
  - Fees: 0.05% per trade (OKX Taker)
  - Slippage: 0.02% per trade
  - Funding Rate: 8H settlement (00:00, 08:00, 16:00 UTC), apply to open positions
- **Liquidation Simulation**:
  - Calculate liquidation price for each position (Isolated mode)
  - Force liquidate if price touches liquidation level
  - Log liquidation events with margin loss
- **Metrics**:
  - Focus: CAGR, Profit Factor, Win Rate, Max DD, Expectancy
  - Targets: CAGR > 100%, PF > 1.8, Win Rate > 45%, Max DD < 30%
  - Track: Funding costs/income, Liquidation count, Margin usage
- **Period**: 2025-02-01 to 2026-02-01 (1 year)
- **Output**: Generate trade log, equity curve, regime distribution, visual analysis

### review_agent
**Purpose**: Final review of RAAA strategy robustness
**Context**: Code quality, Logic verification, Risk/Reward analysis, Leverage safety
**Output**: docs/final_review.md
**Rules**:
- Verify RAAA logic implementation against spec.md
- Check regime classification accuracy (including Undefined/No-Trade zone handling)
- Validate pyramiding logic (average price, stop recalculation, R recalculation)
- Confirm Partial TP blocks further pyramiding
- Assess liquidation risk under extreme volatility
- Review funding rate impact on performance
- Confirm position limits enforcement (2 concurrent max)
- Verify Confidence Multiplier margin cap (25%) enforcement
- Check ETH entry condition (BTC Trending Bull + active BTC position)
- Check against 2025-2026 crypto market assumptions
- Verify cross-asset signal integration

### optimization_agent
**Purpose**: Optimize RAAA parameters via Walk-Forward validation
**Context**: Parameter sweeps, Stability analysis, Leverage efficiency
**Output**: results/optimization_report.md
**Rules**:
- **Method**: Anchored Walk-Forward (70% IS / 30% OOS)
- **Objective**: Maximize CAGR while maintaining DD < 30%
- **Parameters to Optimize**:
  - RSI thresholds (Pullback, Breakout, Mean Reversion)
  - ATR multipliers (Stop, Trailing)
  - Regime thresholds (ADX, ATR Percentile, BB Width)
  - Pyramiding profit threshold (1R ~ 2R range)
  - Confidence multipliers (0.5× ~ 2.0× range)
- **Stability Check**:
  - OOS Profit Factor > 1.5
  - OOS Win Rate > 45%
  - OOS Max DD < 30%
  - Parameter sensitivity: ±20% variation tolerance
- **Output**: Recommend robust parameter sets for 15m/1H/4H strategy

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
- Each subagent works independently with clear outputs
- Main agent reviews each output before proceeding to next phase
- If a subagent output is unsatisfactory, re-run with more specific instructions
- Keep main context clean by delegating heavy computation to subagents
- Follow the Execution Flow sequence (Research → Data → Regime → Strategy → Risk → Backtest → Optimization → Review)
- **Position Limits**: Strictly enforce 2 concurrent positions (BTC 1 + ETH 1) to manage correlation risk
- **Pyramiding**: Only in trending regimes, max 1 additional entry at 1.5R profit, recalculate average price and stops
- **Leverage Safety**: Monitor margin ratio and liquidation distance at all times