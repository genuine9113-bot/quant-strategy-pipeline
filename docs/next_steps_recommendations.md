# RAAA Strategy - Next Steps & Recommendations

## Executive Summary

The backtesting engine is **fully operational** and has completed initial testing of the RAAA strategy. Results show promising fundamentals (52.94% win rate, no liquidations) but require optimization to meet profitability targets.

**Current Performance**: -3.68% return, 51.85% max drawdown
**Target Performance**: >100% CAGR, <30% max drawdown, >1.8 profit factor

## Immediate Actions Required

### 1. Parameter Optimization (Priority: HIGH)

**Stop Loss Width Optimization**
- Current: 1.5 ATR
- Test range: 1.0, 1.25, 1.5, 1.75, 2.0, 2.5 ATR
- Hypothesis: 1.5 ATR may be too tight, causing premature exits
- Expected impact: Reduce stop-out rate, improve profit factor

**Trailing Stop Optimization**
- Current: 2.0 ATR after 1R profit
- Test range: 1.5, 2.0, 2.5, 3.0 ATR
- Test activation: 0.5R, 1.0R, 1.5R profit thresholds
- Expected impact: Better profit capture in trends

**Partial TP Level Optimization**
- Current: 2R (40%), 3R (30%), 4R+ (trail)
- Test first TP: 1.5R, 2.0R, 2.5R, 3.0R
- Test exit percentages: 30/30/40, 40/30/30, 50/25/25
- Expected impact: Lock in profits earlier, reduce giveback

**Regime Cooldown Reduction**
- Current: 8 hours (2 × 4H bars)
- Test: 4 hours (1 × 4H bar), 6 hours, 8 hours
- Expected impact: Increase trade frequency from 1.5 to 3-5 trades/month

### 2. Walk-Forward Validation (Priority: HIGH)

**Implementation Plan**:
```
Period 1 (IS): 2025-03-06 to 2025-08-31 (6 months)
Period 1 (OOS): 2025-09-01 to 2025-11-30 (3 months)
Period 2 (IS): 2025-03-06 to 2025-11-30 (9 months)
Period 2 (OOS): 2025-12-01 to 2026-02-01 (2 months)
```

**Optimization Methodology**:
1. Grid search on IS period
2. Select top 3 parameter sets by Sharpe ratio
3. Validate on OOS period
4. Accept if OOS Sharpe > 0.5 and Max DD < 30%
5. Test parameter stability (±20% variation)

**Key Metrics to Optimize**:
- Primary: Calmar Ratio (CAGR / Max DD)
- Secondary: Profit Factor, Win Rate, Sharpe Ratio
- Constraint: Max DD < 30%

### 3. Regime-Specific Analysis (Priority: MEDIUM)

**Questions to Answer**:
- Which regimes are profitable? (Trending Bull/Bear vs Chop/Squeeze)
- Should we disable certain regime strategies?
- Are entry conditions too strict for some regimes?
- Do we need different stops for different regimes?

**Analysis Script**:
```python
# Group trades by entry regime
regime_performance = trades_df.groupby('entry_regime').agg({
    'pnl_net': ['sum', 'mean', 'count'],
    'pnl_pct': 'mean'
})

# Calculate regime-specific metrics
for regime in ['TRENDING_BULL', 'TRENDING_BEAR', 'CHOP_HIGH_VOL', 'SQUEEZE_LOW_VOL']:
    regime_trades = trades_df[trades_df['entry_regime'] == regime]
    win_rate = (regime_trades['pnl_net'] > 0).mean()
    profit_factor = regime_trades[regime_trades['pnl_net'] > 0]['pnl_net'].sum() / \
                    abs(regime_trades[regime_trades['pnl_net'] < 0]['pnl_net'].sum())
    print(f"{regime}: WR={win_rate:.1%}, PF={profit_factor:.2f}")
```

### 4. Strategy Enhancement (Priority: MEDIUM)

**Divergence Detection** (Currently TODO in code):
```python
def detect_divergence(prices, rsi, lookback=5):
    """
    Detect bullish/bearish divergence:
    - Bullish: Price makes lower low, RSI makes higher low
    - Bearish: Price makes higher high, RSI makes lower high
    """
    # Implement with rolling window
    pass
```

**BB-Keltner Squeeze** (Currently simplified):
```python
def detect_squeeze(row):
    """
    Squeeze: BB width < Keltner Channel width
    """
    bb_width = row['BB_UPPER_20'] - row['BB_LOWER_20']
    kc_width = row['KC_UPPER_20'] - row['KC_LOWER_20']
    return bb_width < kc_width
```

**Dynamic Position Sizing**:
- Increase size after 3 consecutive wins
- Decrease size after 3 consecutive losses
- Adjust based on recent win rate (last 10 trades)

### 5. Data Quality Review (Priority: LOW)

**Funding Rate Issue**:
- Current backtest shows $0 funding P&L
- Possible causes:
  1. No positions held during funding times (00:00, 08:00, 16:00 UTC)
  2. Funding rate data quality issue
  3. Logic error in funding calculation

**Action**: Review `BTC_funding.parquet` and `ETH_funding.parquet`:
```python
import pandas as pd
btc_funding = pd.read_parquet('data/processed/BTC_funding.parquet')
print(btc_funding.describe())
print(btc_funding['funding_rate'].plot())  # Check if rates are realistic
```

## Optimization Implementation Guide

### Step 1: Create Optimizer Class

```python
# backtest/optimizer.py
import itertools
import pandas as pd
from backtest.engine import BacktestEngine

class ParameterOptimizer:
    def __init__(self, data_dict, start_date, end_date):
        self.data = data_dict
        self.start_date = start_date
        self.end_date = end_date

    def grid_search(self, param_grid):
        """
        Run grid search over parameter combinations.

        Example param_grid:
        {
            'stop_loss_atr': [1.0, 1.5, 2.0, 2.5],
            'trailing_stop_atr': [1.5, 2.0, 2.5, 3.0],
            'first_tp_r': [1.5, 2.0, 2.5, 3.0]
        }
        """
        results = []

        # Generate all combinations
        keys = param_grid.keys()
        values = param_grid.values()

        for combination in itertools.product(*values):
            params = dict(zip(keys, combination))

            # Run backtest with these parameters
            engine = BacktestEngine(
                initial_capital=100000,
                leverage=5,
                start_date=self.start_date,
                end_date=self.end_date
            )

            # Update strategy parameters
            engine.strategy.stop_loss_multiplier = params['stop_loss_atr']
            engine.strategy.trailing_stop_multiplier = params['trailing_stop_atr']
            # ... etc

            report = engine.run(**self.data)

            # Store results
            results.append({
                **params,
                'cagr': report['summary']['cagr'],
                'max_dd': report['summary']['max_drawdown'],
                'sharpe': report['summary']['sharpe_ratio'],
                'profit_factor': report['trades']['profit_factor'],
                'win_rate': report['trades']['win_rate'],
                'total_trades': report['trades']['total_trades'],
                'calmar': report['summary']['calmar_ratio']
            })

        return pd.DataFrame(results)
```

### Step 2: Run Optimization

```python
# scripts/run_optimization.py
from backtest.optimizer import ParameterOptimizer
import pandas as pd

# Load data
data = {
    'btc_15m': pd.read_parquet('data/processed/BTC_15m.parquet'),
    'btc_1h': pd.read_parquet('data/processed/BTC_1h.parquet'),
    'btc_4h': pd.read_parquet('data/processed/BTC_4h.parquet'),
    'eth_15m': pd.read_parquet('data/processed/ETH_15m.parquet'),
    'eth_1h': pd.read_parquet('data/processed/ETH_1h.parquet'),
    'eth_4h': pd.read_parquet('data/processed/ETH_4h.parquet'),
    'funding_btc': pd.read_parquet('data/processed/BTC_funding.parquet'),
    'funding_eth': pd.read_parquet('data/processed/ETH_funding.parquet')
}

# Define parameter grid (start small!)
param_grid = {
    'stop_loss_atr': [1.0, 1.5, 2.0],
    'trailing_stop_atr': [2.0, 2.5, 3.0],
    'regime_cooldown_hours': [4, 6, 8]
}

# Run optimization (3 × 3 × 3 = 27 backtests)
optimizer = ParameterOptimizer(data, '2025-03-06', '2025-08-31')
results = optimizer.grid_search(param_grid)

# Rank by Calmar ratio
results = results.sort_values('calmar', ascending=False)
print(results.head(10))

# Save results
results.to_csv('results/optimization_results.csv', index=False)
```

### Step 3: Validate Best Parameters

```python
# Test top 3 parameter sets on OOS period
top_3 = results.head(3)

for idx, params in top_3.iterrows():
    print(f"\nTesting parameters: {params.to_dict()}")

    # Run on OOS period
    optimizer_oos = ParameterOptimizer(data, '2025-09-01', '2025-11-30')
    # ... apply params and run

    print(f"OOS Sharpe: {oos_report['summary']['sharpe_ratio']:.2f}")
    print(f"OOS Max DD: {oos_report['summary']['max_drawdown']:.1%}")
    print(f"OOS CAGR: {oos_report['summary']['cagr']:.1%}")
```

## Expected Timeline

**Week 1**: Parameter optimization grid search
- Days 1-2: Implement optimizer class
- Days 3-5: Run grid search on key parameters
- Days 6-7: Analyze results, select top candidates

**Week 2**: Walk-forward validation
- Days 1-3: OOS testing of top parameters
- Days 4-5: Stability testing (±20% variation)
- Days 6-7: Final parameter selection and documentation

**Week 3**: Strategy enhancement & refinement
- Days 1-3: Implement divergence detection
- Days 4-5: Add BB-Keltner squeeze logic
- Days 6-7: Full backtest with enhanced strategy

**Week 4**: Final validation & deployment prep
- Days 1-3: Full period backtest with optimized parameters
- Days 4-5: Monte Carlo simulation (1000 runs)
- Days 6-7: Live trading preparation (paper trading setup)

## Success Criteria

**Minimum Acceptable Performance** (for live deployment):
- ✅ CAGR > 50% (stretch: >100%)
- ✅ Max Drawdown < 30%
- ✅ Profit Factor > 1.5 (stretch: >1.8)
- ✅ Sharpe Ratio > 1.0
- ✅ Win Rate > 45%
- ✅ Calmar Ratio > 2.0
- ✅ No liquidations in 1-year backtest
- ✅ Consistent performance across all walk-forward periods

**Risk Limits** (hard stops):
- Max single trade loss: 3% of equity
- Max daily loss: 5% of equity
- Max weekly loss: 10% of equity
- Max concurrent positions: 2
- Max leverage: 5×
- Required liquidation buffer: >3 ATR

## Resources Required

**Computational**:
- Grid search: ~30 backtests × 2 min = 1 hour
- Walk-forward: ~10 backtests × 2 min = 20 min
- Total estimated runtime: 2-3 hours for full optimization

**Data**:
- All required data already available
- No additional data sources needed initially
- Consider adding sentiment data later

**Tools**:
- Python 3.10+
- pandas, numpy, matplotlib (already installed)
- Optional: Optuna for Bayesian optimization

## Risk Warnings

⚠️ **Overfitting Risk**:
- With 17 trades in initial backtest, parameter optimization may overfit
- Use walk-forward validation to detect overfitting
- Prefer simple strategies with fewer parameters

⚠️ **Market Regime Change**:
- Strategy optimized on 2025-2026 data may not work in different market conditions
- Monitor live performance closely
- Be prepared to halt strategy if conditions change

⚠️ **Execution Risk**:
- Backtest assumes instant fills at close prices
- Live trading will have slippage, latency, and partial fills
- Start with small position sizes (10-20% of backtest size)

## Conclusion

The backtesting infrastructure is solid and ready for optimization. With focused parameter tuning and strategy enhancements, the RAAA strategy has potential to meet profitability targets.

**Recommended Action**: Proceed immediately to parameter optimization phase, focusing on stop loss width and regime cooldown reduction as primary levers.

**Estimated Time to Live Deployment**: 3-4 weeks with aggressive optimization schedule.
