# BTC Strategy Walkthrough

## 1. Strategy Pivot Overview
We have transitioned from a US Equity strategy to a **Bitcoin (BTC) Multi-Timeframe Structure Strategy**.
- **Asset**: BTC-USD
- **Timeframes**: 15m (Entry), 1h/4h (Structure), 1d (Trend)
- **Core Logic**: Market Structure (Liquidity Sweeps) + Momentum (RSI/EMA)
- **Risk Management**: Dynamic ATR-based Stops, Trailing to Break-even

## 2. Implementation Components
### Data Pipeline (`data/pipeline.py`)
- **Action**: Rewritten to fetch MTF data.
- **Verification**: Confirmed data fetching for 15m (60d), 1h/4h (90d), 1d (1y).

### Strategy Logic (`strategies/btc_strategy.py`)
- **Features**:
  - `get_htf_trend`: Checks 4H Price vs EMA 200.
  - `check_entry_signal`: Liquidity Sweeps + RSI < 45 on 15m.
  - **[NEW] Chop Index**: Filters out signals when volatility is high/directionless (Index > 50).
- **Optimization**:
  - Best Param Set: RSI 45, Lookback 7, ATR 1.0.

### Backtest Engine (`backtest/engine.py`)
- **Execution**: Event-Driven Intraday Simulation.
- **Risk Management**:
  - Move to Break-even at **1.5R** (Increased from 1.0R).
  - Trail Stop by **2.5 ATR** (Increased from 2.0 ATR).

## 3. Verification Backtest Results
**Period**: Jan 4, 2026 - Jan 17, 2026
**Metrics**:
- **Total Trades**: 8 (Significantly reduced from initial 14+ due to filters)
- **Win Rate**: 37.5%
- **Profit Factor (Gross)**: 1.36 (Positive Edge)
- **Expectancy (Gross)**: $34.84 per trade

**Critical Finding: Fee Impact**
- While the strategy generates profit *before fees* ($280 Gross PnL), the transaction costs (approx $120/trade) turn the Net Result negative.
- **Net Return**: -4.69%.
- **Conclusion**: The 15m scalp targets (~$350 avg win) are too small relative to Spot/Taker fees.

## 4. Next Steps
To achieve **Net Profitability**, we must increase the Average Win Size significantly to cover fees.
- **Recommendation**: Shift Entry timeframe to **1H** or **4H** to capture larger swings ($1000+ moves).
