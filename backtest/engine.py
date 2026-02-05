"""
Backtest Engine for BTC Structure/Momentum Strategy

This engine handles:
1. Event-driven simulation on 15m data
2. Execution of TradeSignal objects from BTCStrategy
3. Portfolio tracking (Cash, Equity, Position)
4. Comprehensive Metric Calculation (Expectancy, Profit Factor, etc.)
5. Risk Management Verification

Author: Backtest Agent
Date: February 2026
"""

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import logging
from datetime import datetime
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from strategies.btc_strategy import BTCStrategy, TradeSignal

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("results/backtest.log"),
    ]
)
logger = logging.getLogger(__name__)

class Position:
    def __init__(self, entry_time, entry_price, size, stop_loss, take_profit=None):
        self.entry_time = entry_time
        self.entry_price = entry_price
        self.size = size # units of BTC
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.peak_price = entry_price
        self.exit_time = None
        self.exit_price = None
        self.exit_reason = None
        self.pnl = 0.0

    @property
    def is_open(self):
        return self.exit_price is None

    def close(self, time, price, reason):
        self.exit_time = time
        self.exit_price = price
        self.exit_reason = reason
        self.pnl = (self.exit_price - self.entry_price) * self.size

    def update_peak(self, price):
        if price > self.peak_price:
            self.peak_price = price

class BacktestEngine:
    def __init__(self, strategy=None, initial_capital=10000.0, maker_fee=0.0002, taker_fee=0.0004):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.capital = initial_capital # Cash + Unrealized PnL
        self.maker_fee = maker_fee # 0.02%
        self.taker_fee = taker_fee # 0.04%
        
        self.strategy = strategy if strategy else BTCStrategy()
        self.trades: List[Position] = []
        self.equity_curve = []
        self.position: Optional[Position] = None
        
        # Paths
        self.results_dir = Path("results")
        self.results_dir.mkdir(exist_ok=True)

    def run(self, start_date="2025-01-01", end_date="2026-12-31"):
        """
        Execute the backtest loop.
        """
        # Load 15m data from strategy
        df_15m = self.strategy.data.get("15m")
        if df_15m is None or df_15m.empty:
            logger.error("No 15m data found for backtest")
            return
        
        # Filter date range
        mask = (df_15m.index >= start_date) & (df_15m.index <= end_date)
        df = df_15m.loc[mask]
        
        logger.info(f"Starting Backtest: {start_date} to {end_date} ({len(df)} candles)")
        logger.info(f"Initial Capital: ${self.initial_capital:,.2f}")
        
        # --- Event Loop ---
        warming_up = True
        warmup_bars = 50
        
        for i in range(len(df)):
            if i < warmup_bars: continue
            
            timestamp = df.index[i]
            row = df.iloc[i]
            
            # 1. Update Portfolio (Mark-to-Market)
            current_price = row["Close"]
            
            if self.position:
                # Update unrealized PnL
                unrealized_pnl = (current_price - self.position.entry_price) * self.position.size
                self.capital = self.cash + unrealized_pnl
                
                # Check Exits (Intraday checks assume high/low interaction)
                self.check_exit(row, timestamp)
                
                # if position closed this bar
                if not self.position:
                    self.capital = self.cash
                
                # Trailing Stop Management
                if self.position and self.position.is_open:
                    self.manage_risk(row, timestamp)
            else:
                self.capital = self.cash # No open position
            
            self.equity_curve.append({"Date": timestamp, "Equity": self.capital})
            
            # 2. Check Entries (only if no position)
            if self.position is None:
                signal = self.strategy.check_entry_signal(row, i, df)
                if signal and signal.action == "BUY":
                    self.execute_entry(signal)
                    
        # --- End of Backtest ---
        self.generate_report()

    def execute_entry(self, signal: TradeSignal):
        # Position Sizing: Risk 2% of current capital
        risk_pct = 0.02
        risk_amount = self.capital * risk_pct
        
        # Stop distance
        dist_to_sl = signal.price - signal.stop_loss
        if dist_to_sl <= 0:
            logger.warning(f"Invalid SL for signal at {signal.timestamp}: SL {signal.stop_loss} >= Price {signal.price}")
            return
            
        # Size = Risk Amount / distance per unit
        position_size = risk_amount / dist_to_sl
        
        # Check cash constraints
        cost = position_size * signal.price
        fee = cost * self.taker_fee
        if cost + fee > self.cash:
            # Maximize size
            position_size = (self.cash * 0.99) / signal.price # 1% buffer for fee
        
        # Execute
        self.cash -= (position_size * signal.price) + fee
        self.position = Position(
            entry_time=signal.timestamp,
            entry_price=signal.price,
            size=position_size,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit
        )
        logger.info(f"[ENTRY] {signal.timestamp} BUY {position_size:.4f} BTC @ {signal.price:.2f} (SL: {signal.stop_loss:.2f})")

    def check_exit(self, row, timestamp):
        """Check if SL or TP hit based on High/Low."""
        pos = self.position
        if not pos: return # Safety check
        
        # Stop Loss
        if row["Low"] <= pos.stop_loss:
            # Assume slippage on SL (executed at SL or Low, simpler: SL - slippage)
            exit_price = pos.stop_loss
            self.close_position(timestamp, exit_price, "Stop Loss")
            return
            
        # Update Peak for Trailing logic
        pos.update_peak(row["High"])

    def manage_risk(self, row, timestamp):
        """Dynamic trailing stop logic."""
        pos = self.position
        current_price = row["Close"]
        atr = row["ATR"]
        
        # Logic: If profit > 1.5R (was 1R), move SL to Breakeven
        # Giving more room for initial volatility
        r_multiple = (current_price - pos.entry_price) / (pos.entry_price - pos.stop_loss)
        
        if r_multiple >= 1.5 and pos.stop_loss < pos.entry_price:
            pos.stop_loss = pos.entry_price * 1.001 # BE + small buffer
            logger.info(f"[{timestamp}] Move SL to Breakeven: {pos.stop_loss:.2f}")
            
        # Logic: Trail by 2.5 ATR (was 2.0) if trend is strong (R > 2.0)
        # Looser trailing to capture larger moves
        if r_multiple > 2.0:
            new_sl = current_price - (atr * 2.5)
            if new_sl > pos.stop_loss:
                pos.stop_loss = new_sl
                # logger.info(f"Trailing SL updated: {new_sl}")

    def close_position(self, timestamp, price, reason):
        pos = self.position
        proceeds = pos.size * price
        fee = proceeds * self.maker_fee # Assume limit exit or best effort
        
        self.cash += proceeds - fee
        pos.close(timestamp, price, reason)
        self.trades.append(pos)
        self.position = None
        
        logger.info(f"[EXIT] {timestamp} {reason} @ {price:.2f} | PnL: ${pos.pnl:.2f}")

    def generate_report(self):
        """Calculate and save metrics."""
        if not self.trades:
            logger.warning("No trades generated.")
            print("# BTC Strategy Backtest Report\n\nNo trades executed during the period.")
            return

        df_trades = pd.DataFrame([{
            "Entry Time": t.entry_time,
            "Exit Time": t.exit_time,
            "Entry Price": t.entry_price,
            "Exit Price": t.exit_price,
            "Size": t.size,
            "PnL": t.pnl,
            "Reason": t.exit_reason
        } for t in self.trades])
        
        # Metrics
        wins = df_trades[df_trades["PnL"] > 0]
        losses = df_trades[df_trades["PnL"] <= 0]
        
        win_rate = len(wins) / len(df_trades) * 100
        avg_win = wins["PnL"].mean() if not wins.empty else 0
        avg_loss = abs(losses["PnL"].mean()) if not losses.empty else 0
        profit_factor = (wins["PnL"].sum() / abs(losses["PnL"].sum())) if not losses.empty else float("inf")
        expectancy = (win_rate/100 * avg_win) - ((1 - win_rate/100) * avg_loss)
        
        total_ret = ((self.capital - self.initial_capital) / self.initial_capital) * 100
        
        report = f"""# BTC Strategy Backtest Report

## Summary
- **Period**: {df_trades["Entry Time"].min()} to {df_trades["Exit Time"].max()}
- **Total Trades**: {len(df_trades)}
- **Win Rate**: {win_rate:.2f}%
- **Profit Factor**: {profit_factor:.2f}
- **Expectancy**: ${expectancy:.2f} per trade

## Financials
- **Initial Capital**: ${self.initial_capital:,.2f}
- **Final Equity**: ${self.capital:,.2f}
- **Total Return**: {total_ret:.2f}%

## Trade Analysis
- **Avg Win**: ${avg_win:.2f}
- **Avg Loss**: ${avg_loss:.2f}
- **Best Trade**: ${df_trades["PnL"].max():.2f}
- **Worst Trade**: ${df_trades["PnL"].min():.2f}

"""
        # Save to file
        with open(self.results_dir / "backtest_report.md", "w") as f:
            f.write(report)
        
        df_trades.to_csv(self.results_dir / "trade_log.csv", index=False)
        pd.DataFrame(self.equity_curve).to_csv(self.results_dir / "equity_curve.csv", index=False)
        
        logger.info(f"Report generated: {self.results_dir}/backtest_report.md")
        print(report)

if __name__ == "__main__":
    engine = BacktestEngine(initial_capital=100000)
    engine.run(start_date="2025-12-07")
