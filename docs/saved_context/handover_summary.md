# Handover Summary: BTC Structure Strategy (v1.0)

## System State
We have successfully built a complete **Quantitative Development Pipeline** for Bitcoin.

### 1. Data Pipeline (`data/pipeline.py`)
- **Status**: Stable
- **Capabilities**: Fetches 15m, 1h, 4h, 1d data from Yahoo Finance.
- **Features**: Auto-calculates Technical Indicators (EMA, RSI, ATR).
- **Storage**: Parquet format for fast I/O.

### 2. Strategy Engine (`strategies/btc_strategy.py`)
- **Status**: Functional & Optimized
- **Logic**:
  - **Structure**: Uses Swing High/Low analysis (Lookback=7).
  - **Trend**: 4H Price > EMA 200.
  - **Entry**: Liquidity Sweep of Swing Low + RSI < 45.
  - **Filter**: **Chop Index** (Threshold 50) prevents trading in sideways markets.
- **Config**: Fully parameterizable (ready for optimizer).

### 3. Backtest Engine (`backtest/engine.py` & `optimizer.py`)
- **Status**: Event-Driven, Fee-Aware
- **Features**:
  - **Dynamic Risks**: Trailing Stops (2.5 ATR), Break-even trigger (1.5R).
  - **Metrics**: Calculates Expectancy, Profit Factor, Drawdown.
  - **Automation**: `optimizer.py` can run 100+ batch tests automatically.

---

## Key Findings & Performance
We conducted extensive backtesting and optimization on the **15-minute Timeframe**.

| Metric | Result | Interpretation |
| cr | cr | cr |
| **Gross Profit Factor** | **1.36** | The strategy logic is sound (Positive Edge). |
| **Win Rate** | **37.5%** | Standard for trend/structure following. |
| **Avg Win** | **~$350** | Too small relative to fees. |
| **Net Return** | **-4.7%** | **Unprofitable after Fees.** |

**Conclusion**:
The strategy correctly identifies market turning points, but the **15m Scalping approach is not viable** with standard Spot/Taker fees (~0.04-0.1%). The "Meat" of the move is eaten by costs.

---

## Action Plan for Next Agent
The groundwork is laid. The next steps should focus purely on **Timeframe Expansion** to increase the Average Trade Value.

1.  **Modify `BTCStrategy`**:
    - Change primary entry logic to function on **1H or 4H** bars.
    - Adjust Lookback and ATR Multipliers for these slower timeframes.
2.  **Re-Run Optimization**:
    - Use `backtest/optimizer.py` to find stable parameters for 1H/4H.
    - Target: Avg Win > $1,000 (to make fees negligible).
3.  **Validation**:
    - Verify that Profit Factor remains > 1.3 while Net Return turns Positive.

## Quick Start
To resume work:
```bash
# 1. Activate Venv
source venv/bin/activate

# 2. Run Optimization (if code updated)
python backtest/optimizer.py

# 3. Run Single Backtest
python backtest/engine.py
```
