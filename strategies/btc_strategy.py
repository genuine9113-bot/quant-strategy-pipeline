"""
BTC Structure & Momentum Strategy (MTF)

This module implements the core trading logic based on:
1. HTF Trend (4H/Daily): EMA 200 & Market Structure
2. LTF Entry (15m): Liquidity Sweeps & Break of Structure (BoS)
3. Dynamic Risk: ATR-based Stops & Trailing Profit

Author: Strategy Agent
Date: February 2026
"""

import logging
import pandas as pd
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List
from enum import Enum

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("strategies/btc_strategy.log"),
    ],
)
logger = logging.getLogger(__name__)

class Trend(Enum):
    BULLISH = 1
    BEARISH = -1
    NEUTRAL = 0

@dataclass
class TradeSignal:
    timestamp: pd.Timestamp
    action: str  # "BUY" or "SELL"
    price: float
    stop_loss: float
    take_profit: Optional[float]
    reason: str

class MarketStructure:
    """
    Analyzes Price Action for Market Structure (HH, HL, LH, LL).
    """
    def __init__(self, lookback: int = 5):
        self.lookback = lookback

    def is_pivot_low(self, df: pd.DataFrame, idx: int) -> bool:
        """Check if index is a Swing Low."""
        if idx < self.lookback or idx >= len(df) - self.lookback:
            return False
        
        low = df["Low"].iloc[idx]
        # Check neighbors
        left = df["Low"].iloc[idx - self.lookback : idx].min()
        right = df["Low"].iloc[idx + 1 : idx + self.lookback + 1].min()
        
        return low < left and low < right

    def is_pivot_high(self, df: pd.DataFrame, idx: int) -> bool:
        """Check if index is a Swing High."""
        if idx < self.lookback or idx >= len(df) - self.lookback:
            return False
            
        high = df["High"].iloc[idx]
        left = df["High"].iloc[idx - self.lookback : idx].max()
        right = df["High"].iloc[idx + 1 : idx + self.lookback + 1].max()
        
        return high > left and high > right

    def get_recent_structure(self, df: pd.DataFrame, current_idx: int) -> Dict[str, float]:
        """Find most recent major Swing High and Swing Low."""
        # Scan backwards from current_idx
        swing_high = None
        swing_low = None
        
        for i in range(current_idx - 1, max(0, current_idx - 100), -1):
            if swing_high is None and self.is_pivot_high(df, i):
                swing_high = df["High"].iloc[i]
            if swing_low is None and self.is_pivot_low(df, i):
                swing_low = df["Low"].iloc[i]
            
            if swing_high is not None and swing_low is not None:
                break
                
        return {"swing_high": swing_high, "swing_low": swing_low}

class BTCStrategy:
    """
    Main Strategy Class orchestrating MTF interpretation and Trade Execution.
    """
    def __init__(
        self, 
        data_dir: str = "data/processed",
        rsi_threshold: int = 45,
        structure_lookback: int = 7, # Optimized
        stop_loss_atr: float = 1.0,  # Optimized
        chop_threshold: float = 50.0 # New filter: < 50 implies Trending
    ):
        self.data_dir = Path(data_dir)
        self.structure_analyzer = MarketStructure(lookback=structure_lookback)
        self.rsi_threshold = rsi_threshold
        self.stop_loss_atr = stop_loss_atr
        self.chop_threshold = chop_threshold
        self.data = {}
        self.load_data()

    def load_data(self):
        """Load processed parquet files for relevant timeframes."""
        try:
            self.data["15m"] = pd.read_parquet(self.data_dir / "BTC-USD_15m.parquet")
            self.data["1h"] = pd.read_parquet(self.data_dir / "BTC-USD_1h.parquet")
            self.data["4h"] = pd.read_parquet(self.data_dir / "BTC-USD_4h.parquet")
            
            # Set index to Date for easier lookup, but keep column for backtest
            for tf in self.data:
                if "Date" in self.data[tf].columns:
                    self.data[tf]["Datetime"] = self.data[tf]["Date"]
                    self.data[tf] = self.data[tf].set_index("Datetime").sort_index()
            
            # Pre-calculate Chop Index for 15m
            self.calculate_chop_index(self.data["15m"])
                    
            logger.info("Loaded MTF data successfully.")
        except Exception as e:
            logger.error(f"Failed to load data: {e}")
            raise

    def calculate_chop_index(self, df: pd.DataFrame, period: int = 14):
        """
        Calculate Chop Index: 100 * LOG10( SUM(ATR(1), n) / ( Max(Hi, n) - Min(Lo, n) ) ) / LOG10(n)
        Low values (<38.2) = Trend, High (>61.8) = Chop.
        We use a threshold (e.g. 50) to filter out chop.
        """
        try:
            high = df["High"]
            low = df["Low"]
            close = df["Close"]
            
            # TR1 = High - Low
            tr1 = high - low
            # TR2 = abs(High - PrevClose)
            tr2 = (high - close.shift(1)).abs()
            # TR3 = abs(Low - PrevClose)
            tr3 = (low - close.shift(1)).abs()
            
            # True Range = max(tr1, tr2, tr3)
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            
            # Sum of TR over period
            sum_tr = tr.rolling(window=period).sum()
            
            # Max High - Min Low over period
            max_hi = high.rolling(window=period).max()
            min_lo = low.rolling(window=period).min()
            range_diff = max_hi - min_lo
            
            # Handle division by zero
            range_diff = range_diff.replace(0, np.nan)
            
            # CI Calculation
            ci = 100 * np.log10(sum_tr / range_diff) / np.log10(period)
            
            df["ChopIndex"] = ci.fillna(50) # Default to neutral if nan
            
        except Exception as e:
            logger.error(f"Failed to calculate Chop Index: {e}")
            df["ChopIndex"] = 50.0

    def get_htf_trend(self, timestamp: pd.Timestamp) -> Trend:
        """
        Determine Trend on 4H: Price > EMA200
        """
        # Find the 4H bar effective at this timestamp
        # Using 'asof' to find the last known 4H close
        if timestamp not in self.data["4h"].index:
             # Find closest preceding timestamp
             idx = self.data["4h"].index.searchsorted(timestamp)
             if idx == 0: return Trend.NEUTRAL
             htf_row = self.data["4h"].iloc[idx - 1]
        else:
             htf_row = self.data["4h"].loc[timestamp]

        # Simple Trend Logic: Price > EMA 200
        if htf_row["Close"] > htf_row["EMA_200"]:
            return Trend.BULLISH
        elif htf_row["Close"] < htf_row["EMA_200"]:
            return Trend.BEARISH
        
        return Trend.NEUTRAL

    def check_entry_signal(self, current_row: pd.Series, idx: int, df_15m: pd.DataFrame) -> Optional[TradeSignal]:
        """
        Check for 15m Entry Signal:
        1. Bullish: Sweep previous low + Close > EMA200 (Mean Reversion/Trend Join)
           OR Structure Break (Close > Swing High)
        """
        timestamp = current_row.name
        htf_trend = self.get_htf_trend(timestamp)
        
        if htf_trend != Trend.BULLISH:
            # logger.debug(f"{timestamp}: HTF Not Bullish") 
            return None 
            
        # Chop Filter
        if current_row.get("ChopIndex", 100) > self.chop_threshold:
            # Too choppy, skip
            return None
        
        # --- Long Setup ---
        
        # 1. Structure Analysis
        recent_structure = self.structure_analyzer.get_recent_structure(df_15m, idx)
        pivot_low_level = recent_structure["swing_low"]
        
        if pivot_low_level is None: return None

        latest_close = current_row["Close"]
        atr = current_row["ATR"]
        
        # Logic: Liquidity Sweep
        # Did we dip below swing low recently but close above?
        is_sweep = False
        sweep_low_price = pivot_low_level # Default to level, but search for actual wick
        
        scan_window = 3
        for i in range(max(0, idx - scan_window), idx + 1):
             bar = df_15m.iloc[i]
             # Check if this bar dipped below the pivot level
             if bar["Low"] < pivot_low_level and bar["Close"] > pivot_low_level:
                 is_sweep = True
                 sweep_low_price = min(sweep_low_price, bar["Low"]) # Track the lowest point of the sweep
                 # Note: We continue loop to find the 'deepest' point if multiple candles swept
        
        # Logic: RSI Oversold or Bullish Divergence (Simulated by RSI rising from <30)
        # Relaxed slightly: RSI < threshold to catch more trend pullbacks
        rsi_bullish = current_row["RSI"] < self.rsi_threshold and current_row["RSI"] > df_15m["RSI"].iloc[idx-1]
        
        if is_sweep and rsi_bullish:
             reason = "Liquidity Sweep + RSI Turn"
             # SL anchored to the actual Wick Low of the sweep, minus buffer
             stop_loss = sweep_low_price - (atr * self.stop_loss_atr) 
             
             # Sanity check: SL must be below Entry
             if stop_loss >= latest_close:
                 stop_loss = latest_close - (atr * 1.0) # Fallback
             
             return TradeSignal(
                 timestamp=timestamp,
                 action="BUY",
                 price=latest_close,
                 stop_loss=stop_loss,
                 take_profit=None, # Dynamic trailing
                 reason=reason
             )
             
        return None

    def run_backtest(self, start_date: str = "2025-01-01"):
        """
        Simple Iterate-and-Check simulation.
        For real backtesting, we'd use the engine, but this verifying logic.
        """
        df_15m = self.data["15m"]
        df_15m = df_15m[df_15m.index >= pd.Timestamp(start_date)]
        
        signals = []
        
        logger.info(f"Running strategy check on {len(df_15m)} bars starting {start_date}")
        
        for i in range(50, len(df_15m)): # Warmup
            row = df_15m.iloc[i]
            signal = self.check_entry_signal(row, i, df_15m)
            if signal:
                signals.append(signal)
                
        logger.info(f"Generated {len(signals)} signals")
        return signals

if __name__ == "__main__":
    strategy = BTCStrategy()
    signals = strategy.run_backtest(start_date="2025-12-07") # 60 days Start
    
    # Print sample signals
    for sig in signals[:5]:
        print(f"[{sig.timestamp}] {sig.action} @ {sig.price:.2f} | SL: {sig.stop_loss:.2f} | {sig.reason}")
