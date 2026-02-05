"""
Optimizer for BTC Strategy
Runs batch backtests across a parameter grid to find robust settings.
"""

import sys
from pathlib import Path
import pandas as pd
import itertools
import logging

# Add project root
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from strategies.btc_strategy import BTCStrategy
from backtest.engine import BacktestEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Optimizer")

def run_optimization():
    # Parameter Grid
    param_grid = {
        "rsi_threshold": [30, 35, 40, 45, 50],
        "structure_lookback": [3, 5, 7, 10],
        "stop_loss_atr": [0.5, 0.8, 1.0, 1.2, 1.5]
    }
    
    keys, values = zip(*param_grid.items())
    combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]
    
    results = []
    total_runs = len(combinations)
    logger.info(f"Starting optimization with {total_runs} combinations...")
    
    for i, params in enumerate(combinations):
        logger.info(f"Running [{i+1}/{total_runs}]: {params}")
        
        # Instantiate Strategy with specific params
        strategy = BTCStrategy(
            rsi_threshold=params["rsi_threshold"],
            structure_lookback=params["structure_lookback"],
            stop_loss_atr=params["stop_loss_atr"]
        )
        
        # Run Backtest (Silent mode preferred, but engine logs to file)
        engine = BacktestEngine(strategy=strategy, initial_capital=100000)
        
        # We need to capture metrics. 
        # Currently engine.run() prints/saves report but doesn't return dict easily.
        # We will modify engine or just read from engine state after run.
        # For efficiency, we'll access engine.trades directly after run.
        
        try:
            engine.run(start_date="2025-12-07")
            
            # Calculate Metrics
            trades = engine.trades
            if not trades:
                res = {**params, "Trades": 0, "WinRate": 0, "ProfitFactor": 0, "TotalReturn": 0, "Expectancy": 0}
            else:
                df_trades = pd.DataFrame([t.pnl for t in trades], columns=["PnL"])
                wins = df_trades[df_trades["PnL"] > 0]
                losses = df_trades[df_trades["PnL"] <= 0]
                
                win_rate = len(wins) / len(trades) * 100
                total_return = ((engine.capital - engine.initial_capital) / engine.initial_capital) * 100
                
                gross_profit = wins["PnL"].sum()
                gross_loss = abs(losses["PnL"].sum())
                profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999
                
                avg_win = wins["PnL"].mean() if not wins.empty else 0
                avg_loss = abs(losses["PnL"].mean()) if not losses.empty else 0
                expectancy = (win_rate/100 * avg_win) - ((1 - win_rate/100) * avg_loss)
                
                res = {
                    **params,
                    "Trades": len(trades),
                    "WinRate": round(win_rate, 2),
                    "ProfitFactor": round(profit_factor, 2),
                    "TotalReturn": round(total_return, 2),
                    "Expectancy": round(expectancy, 2)
                }
            
            results.append(res)
            
        except Exception as e:
            logger.error(f"Failed run {params}: {e}")
            
    # Save Results
    df_results = pd.DataFrame(results)
    output_path = "results/optimization_results.csv"
    df_results.to_csv(output_path, index=False)
    logger.info(f"Optimization complete. Results saved to {output_path}")
    
    # Print Top 5 by Profit Factor
    print("\nTop 5 Configs by Profit Factor:")
    print(df_results.sort_values("ProfitFactor", ascending=False).head(5))

if __name__ == "__main__":
    run_optimization()
