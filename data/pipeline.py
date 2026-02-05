"""
Data Pipeline for BTC MTF Strategy

This module fetches OHLCV data for Bitcoin (BTC-USD) across multiple timeframes
(15m, 1h, 4h, 1d) and calculates relevant indicators. The processed data is
saved to the data/processed/ directory for use by the MTF strategy.

Author: Data Agent
Date: February 2026
"""

import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import yfinance as yf

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("data/pipeline.log"),
    ],
)
logger = logging.getLogger(__name__)


class DataPipeline:
    """
    Data pipeline for fetching and processing Multi-Timeframe (MTF) Bitcoin data.

    Features:
    - Fetches BTC-USD data for 15m, 1h, 4h, 1d timeframes
    - Calculates EMA (200), RSI (14), ATR (14) for each timeframe
    - Aligns timestamps to UTC
    - Saves individual timeframe files and a combined config
    """

    TIMEFRAMES = {
        "15m": {"period": "60d", "interval": "15m"},   # Max allowable by yfinance for 15m
        "1h":  {"period": "90d", "interval": "1h"},    # User requested 90 days
        "4h":  {"period": "90d", "interval": "1h"},    # User requested 90 days (resampled from 1h)
        "1d":  {"period": "1y",  "interval": "1d"},    # Need >200 data points for EMA(200)
    }

    def __init__(self, output_dir: str = "data/processed"):
        """
        Initialize the data pipeline.

        Args:
            output_dir: Directory path for saving processed data files.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"DataPipeline initialized with output directory: {self.output_dir}")

    def fetch_data(
        self,
        symbol: str,
        interval: str,
        period: str,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV data for a symbol from yfinance.

        Args:
            symbol: Stock ticker symbol (e.g., "BTC-USD").
            interval: Data interval (e.g., "15m", "1h", "1d").
            period: Data period (e.g., "60d", "730d", "max").
            max_retries: Maximum number of retry attempts on failure.
            retry_delay: Delay in seconds between retries.

        Returns:
            DataFrame with OHLCV data or None if fetch fails.
        """
        for attempt in range(max_retries):
            try:
                logger.info(f"Fetching {symbol} [{interval}] (attempt {attempt + 1}/{max_retries})")

                ticker = yf.Ticker(symbol)
                # Note: yfinance 'period' argument is used for intraday limits
                df = ticker.history(period=period, interval=interval, auto_adjust=True)

                if df.empty:
                    logger.warning(f"No data returned for {symbol} [{interval}]")
                    return None

                # Standardize column names
                df = df.reset_index()
                # yfinance timestamps are timezone-aware, convert to UTC and remove tz info for parquet compat
                if "Date" in df.columns:
                    col_name = "Date"
                else:
                    col_name = "Datetime" # Intraday usually comes as Datetime
                    df = df.rename(columns={"Datetime": "Date"})

                df["Date"] = pd.to_datetime(df["Date"]).dt.tz_convert("UTC").dt.tz_localize(None)

                # Keep required columns
                required_cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
                # Filter strictly
                available_cols = [c for c in required_cols if c in df.columns]
                df = df[available_cols]

                if len(available_cols) < 5: # Missing OHLVC
                     logger.error(f"Missing columns in {symbol} data")
                     return None

                logger.info(f"Successfully fetched {len(df)} rows for {symbol} [{interval}]")
                return df

            except Exception as e:
                logger.error(f"Error fetching {symbol} (attempt {attempt + 1}): {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)

        logger.error(f"Failed to fetch data for {symbol} after {max_retries} attempts")
        return None

    def resample_data(self, df: pd.DataFrame, target_interval: str) -> pd.DataFrame:
        """
        Resample data to a higher timeframe (e.g., 1h -> 4h).
        
        Args:
            df: Lower timeframe DataFrame (must have Date index or column).
            target_interval: Target offset string (e.g., '4h').
        
        Returns:
            Resampled DataFrame.
        """
        logger.info(f"Resampling data to {target_interval}...")
        
        df_copy = df.copy()
        df_copy = df_copy.set_index("Date")
        
        # Resample logic
        resampled = df_copy.resample(target_interval).agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum"
        }).dropna()
        
        resampled = resampled.reset_index()
        logger.info(f"Resampled to {len(resampled)} rows")
        return resampled

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate technical indicators used in the strategy.
        
        Indicators:
        - EMA 200 (Trend Baseline)
        - RSI 14 (Momentum)
        - ATR 14 (Volatility)
        
        Args:
            df: DataFrame with OHLCV data.
        
        Returns:
            DataFrame with added indicator columns.
        """
        prices = df["Close"]
        
        # 1. EMA 200
        df["EMA_200"] = prices.ewm(span=200, adjust=False).mean()
        
        # 2. RSI 14
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        
        # Note: Standard RSI uses Wilder's Smoothing, but Rolling Mean is often sufficient proxy.
        # For precision matching Research, let's implement Wilder's if possible, or stick to simple for speed.
        # Let's use EWM for Wilder's approximation which is standard in pandas/TA-Lib
        # Wilder's Smoothing is equivalent to EMA with alpha=1/n
        gain = delta.where(delta > 0, 0.0).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/14, adjust=False).mean()
        
        rs = gain / loss
        df["RSI"] = 100 - (100 / (1 + rs))
        df["RSI"] = df["RSI"].fillna(50)
        
        # 3. ATR 14
        high = df["High"]
        low = df["Low"]
        close_prev = df["Close"].shift(1)
        
        tr1 = high - low
        tr2 = abs(high - close_prev)
        tr3 = abs(low - close_prev)
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        df["ATR"] = tr.ewm(alpha=1/14, adjust=False).mean()
        
        return df

    def process_timeframe(self, symbol: str, tf_name: str, config: Dict) -> Optional[pd.DataFrame]:
        """
        Pipeline step for a single timeframe.
        """
        # Special case for 4h: Fetch 1h and resample
        if tf_name == "4h":
            # Fetch 1h data first
            df = self.fetch_data(symbol, "1h", config["period"])
            if df is not None:
                df = self.resample_data(df, "4h")
        else:
            df = self.fetch_data(symbol, config["interval"], config["period"])
            
        if df is None:
            return None
            
        # Calculate Indicators
        df = self.calculate_indicators(df)
        
        # Save
        filename = f"{symbol}_{tf_name}.parquet"
        filepath = self.output_dir / filename
        df.to_parquet(filepath, index=False)
        logger.info(f"Saved {tf_name} data to {filepath}")
        
        return df

    def run(self, symbol: str = "BTC-USD") -> Dict[str, str]:
        """
        Run the pipeline for all timeframes.
        
        Args:
            symbol: Ticker symbol (default: BTC-USD).
            
        Returns:
            Dictionary mapping timeframe names to file paths.
        """
        logger.info(f"Starting Multi-Timeframe Pipeline for {symbol}")
        
        results = {}
        
        for tf_name, config in self.TIMEFRAMES.items():
            try:
                df = self.process_timeframe(symbol, tf_name, config)
                if df is not None:
                    results[tf_name] = str(self.output_dir / f"{symbol}_{tf_name}.parquet")
                else:
                    results[tf_name] = None
            except Exception as e:
                logger.error(f"Failed to process {tf_name}: {e}")
                results[tf_name] = None
                
        # Summary
        success_count = sum(1 for v in results.values() if v is not None)
        logger.info("=" * 50)
        logger.info(f"Pipeline Completed. Success: {success_count}/{len(self.TIMEFRAMES)}")
        logger.info("=" * 50)
        
        return results


def main():
    """Main entry point."""
    pipeline = DataPipeline()
    pipeline.run(symbol="BTC-USD")


if __name__ == "__main__":
    main()
