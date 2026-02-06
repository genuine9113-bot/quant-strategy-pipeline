
import ccxt
import pandas as pd
import numpy as np
import talib
import os
import time
from datetime import datetime, timedelta
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/pipeline.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("DataPipeline")

# Constants
EXCHANGE_ID = 'okx'
SYMBOLS = ['BTC/USDT:USDT', 'ETH/USDT:USDT']
TIMEFRAMES = ['15m', '1h', '4h']
START_DATE = '2025-02-01 00:00:00'
END_DATE = '2026-02-01 00:00:00'
DATA_DIR = 'data/processed'

def ensure_dir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)

def fetch_ohlcv_history(exchange, symbol, timeframe, start_ts, end_ts):
    """Fetch full history of OHLCV data."""
    logger.info(f"Fetching {symbol} {timeframe} from {datetime.fromtimestamp(start_ts/1000)} to {datetime.fromtimestamp(end_ts/1000)}")
    
    all_ohlcv = []
    since = start_ts
    
    while since < end_ts:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=100)
            if not ohlcv:
                break
            
            all_ohlcv.extend(ohlcv)
            since = ohlcv[-1][0] + 1
            
            # Simple rate limit handling
            time.sleep(exchange.rateLimit / 1000)
            
            if len(all_ohlcv) % 1000 == 0:
                logger.info(f"Fetched {len(all_ohlcv)} candles so far...")
                
        except Exception as e:
            logger.error(f"Error fetching OHLCV: {e}")
            time.sleep(5) # Backoff
            
    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df = df[(df['timestamp'] >= start_ts) & (df['timestamp'] <= end_ts)]
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    
    # Remove duplicates if any
    df = df[~df.index.duplicated(keep='first')]
    
    logger.info(f"Completed fetching {symbol} {timeframe}. Total rows: {len(df)}")
    return df

def fetch_funding_history(exchange, symbol, start_ts, end_ts):
    """Fetch funding rate history."""
    # Note: OKX API for funding history might require specific handling or might not cover full year easily via public API without pagination logic specific to it.
    # ccxt `fetch_funding_rate_history` support varies.
    # implementing a generic loop if supported, otherwise warning.
    
    logger.info(f"Fetching funding history for {symbol}...")
    all_funding = []
    since = start_ts
    
    # Check if exchange supports it
    if not exchange.has['fetchFundingRateHistory']:
        logger.warning("Exchange does not support fetchFundingRateHistory via ccxt directly or correctly.")
        return pd.DataFrame()

    while since < end_ts:
        try:
            funding = exchange.fetch_funding_rate_history(symbol, since=since, limit=100)
            if not funding:
                break
            
            all_funding.extend(funding)
            since = funding[-1]['timestamp'] + 1
            time.sleep(exchange.rateLimit / 1000)
            
        except Exception as e:
            logger.error(f"Error fetching funding history: {e}")
            break
            
    df = pd.DataFrame(all_funding)
    if not df.empty:
        df = df[['timestamp', 'fundingRate', 'symbol']]
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df[(df.index >= pd.to_datetime(start_ts, unit='ms')) & (df.index <= pd.to_datetime(end_ts, unit='ms'))]
    
    return df

def calculate_indicators(df):
    """Calculate technical indicators as per spec.md."""
    # Ensure columns are float
    o = df['open'].values
    h = df['high'].values
    l = df['low'].values
    c = df['close'].values
    v = df['volume'].values
    
    # --- Trend & Momentum ---
    df['EMA_9'] = talib.EMA(c, timeperiod=9)
    df['EMA_20'] = talib.EMA(c, timeperiod=20)
    df['EMA_50'] = talib.EMA(c, timeperiod=50)
    df['EMA_200'] = talib.EMA(c, timeperiod=200)
    
    df['RSI_14'] = talib.RSI(c, timeperiod=14)
    
    df['ADX_14'] = talib.ADX(h, l, c, timeperiod=14)
    df['PLUS_DI_14'] = talib.PLUS_DI(h, l, c, timeperiod=14)
    df['MINUS_DI_14'] = talib.MINUS_DI(h, l, c, timeperiod=14)
    
    df['MOM_12'] = talib.MOM(c, timeperiod=12)
    
    # --- Volatility ---
    df['ATR_14'] = talib.ATR(h, l, c, timeperiod=14)
    # ATR Percentile (rolling rank over 50 bars) -> Need pandas rolling
    # Rank of current ATR relative to last 50 ATRs
    df['ATR_PCT_RANK_50'] = df['ATR_14'].rolling(50).rank(pct=True) * 100
    
    # Bollinger Bands (20, 2.0)
    df['BB_UPPER'], df['BB_MIDDLE'], df['BB_LOWER'] = talib.BBANDS(c, timeperiod=20, nbdevup=2.0, nbdevdn=2.0, matype=0)
    
    # Bollinger Bands (20, 2.5) for Chop Strategy
    df['BB_UPPER_2.5'], _, df['BB_LOWER_2.5'] = talib.BBANDS(c, timeperiod=20, nbdevup=2.5, nbdevdn=2.5, matype=0)
    
    # Keltner Channel (20, 1.5 ATR)
    # KC Middle is EMA 20 usually, or SMA. Spec says Keltner(20, 1.5). Usually uses EMA.
    # Let's use EMA_20 as middle.
    kc_middle = df['EMA_20']
    kc_range = 1.5 * df['ATR_14']
    df['KC_UPPER'] = kc_middle + kc_range
    df['KC_LOWER'] = kc_middle - kc_range
    
    # BB Width Percentile
    # BB Width = (Upper - Lower) / Middle
    df['BB_WIDTH'] = (df['BB_UPPER'] - df['BB_LOWER']) / df['BB_MIDDLE']
    df['BB_WIDTH_PCT_RANK_50'] = df['BB_WIDTH'].rolling(50).rank(pct=True) * 100
    
    # --- Structure ---
    # Donchian Channel (20)
    df['DONCHIAN_UPPER_20'] = df['high'].rolling(20).max()
    df['DONCHIAN_LOWER_20'] = df['low'].rolling(20).min()
    
    # Volume SMA
    df['VOL_SMA_20'] = talib.SMA(v, timeperiod=20)
    
    return df

def calculate_cross_asset(btc_df, eth_df, timeframe_suffix):
    """Calculate cross-asset correlations and ratios."""
    # Merge on index
    merged = pd.merge(btc_df['close'], eth_df['close'], left_index=True, right_index=True, suffixes=('_BTC', '_ETH'))
    
    # Rolling Correlation 48 bars (Spec says 48H, but for 4H bars it's 12 bars? 
    # Spec 362: "BTC-ETH Rolling Correlation: 48 bars (4H 기준)" -> implies 48 * 4H = 8 days? 
    # Or "48H" means 48 hours?
    # Spec 168: "Rolling Correlation(48H)" -> 48 Hours.
    # At 4H timeframe, 48 hours = 12 bars.
    # At 1H timeframe, 48 hours = 48 bars.
    # At 15m timeframe, 48 hours = 192 bars.
    # Let's use 48 hours equivalent window.
    
    # But Spec line 362 says "48 bars (4H 기준)". This might mean "48 bars window calculated on 4H candles".
    # Since we are processing each TF, let's just stick to a fixed window or try to interpret.
    # I will assume 48 bars for now as per line 362 text, or maybe 12 bars if it meant 48H time.
    # Line 362: "BTC-ETH Rolling Correlation: 48 bars (4H 기준)" -> implies window size is 48 on 4H chart.
    
    window = 48
    corr = merged['close_BTC'].rolling(window).corr(merged['close_ETH'])
    
    # ETH/BTC Ratio
    ratio = merged['close_ETH'] / merged['close_BTC']
    
    # Ratio BB(20, 2.0)
    ratio_upper, ratio_middle, ratio_lower = talib.BBANDS(ratio.values, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
    
    return corr, ratio, ratio_upper, ratio_lower

def main():
    ensure_dir(DATA_DIR)
    ensure_dir('logs')
    
    exchange = ccxt.okx()
    
    start_ts = int(pd.Timestamp(START_DATE).timestamp() * 1000)
    end_ts = int(pd.Timestamp(END_DATE).timestamp() * 1000)
    
    # Store DFs to calculate cross-asset later
    data_store = {} # { 'BTC_1H': df, ... }
    
    for symbol in SYMBOLS:
        symbol_slug = symbol.split('/')[0] # BTC or ETH
        
        # Funding Rate (One per symbol, valid for all TFs)
        funding_df = fetch_funding_history(exchange, symbol, start_ts, end_ts)
        if not funding_df.empty:
            funding_path = os.path.join(DATA_DIR, f"{symbol_slug}_funding.parquet")
            funding_df.to_parquet(funding_path)
            logger.info(f"Saved funding rates to {funding_path}")
            
        for tf in TIMEFRAMES:
            logger.info(f"Processing {symbol} {tf}...")
            df = fetch_ohlcv_history(exchange, symbol, tf, start_ts, end_ts)
            
            if df.empty:
                logger.warning(f"No data for {symbol} {tf}")
                continue
                
            df = calculate_indicators(df)
            
            key = f"{symbol_slug}_{tf}"
            data_store[key] = df
            
            # Save individual processed data
            path = os.path.join(DATA_DIR, f"{symbol_slug}_{tf}.parquet")
            df.to_parquet(path)
            logger.info(f"Saved {path}")
            
    # Calculate Cross correlations if we have both BTC and ETH for same TFs
    for tf in TIMEFRAMES:
        btc_key = f"BTC_{tf}"
        eth_key = f"ETH_{tf}"
        
        if btc_key in data_store and eth_key in data_store:
            btc_df = data_store[btc_key]
            eth_df = data_store[eth_key]
            
            logger.info(f"Calculating cross-asset metrics for {tf}...")
            corr, ratio, r_up, r_low = calculate_cross_asset(btc_df, eth_df, tf)
            
            # We need to save these. We can append to the individual files or save separate cross file.
            # Easier to append to each file or just ETH file (since ratio is ETH/BTC).
            # Spec implies these are available globally.
            # Let's add CORR and RATIO to both DF or just use them in strategy.
            # For pipeline, let's add to valid dataframes and re-save.
            
            # Add to BTC
            btc_df['CORR_BTC_ETH'] = corr
            # BTC doesn't really have a ratio in its own context usually, but Correlation is useful.
            
            # Add to ETH
            eth_df['CORR_BTC_ETH'] = corr
            eth_df['ETH_BTC_RATIO'] = ratio
            eth_df['ETH_BTC_RATIO_UPPER'] = r_up
            eth_df['ETH_BTC_RATIO_LOWER'] = r_low
            
            # Re-save
            btc_path = os.path.join(DATA_DIR, f"BTC_{tf}.parquet")
            eth_path = os.path.join(DATA_DIR, f"ETH_{tf}.parquet")
            
            btc_df.to_parquet(btc_path)
            eth_df.to_parquet(eth_path)
            logger.info(f"Updated {tf} parquets with cross-asset data.")

if __name__ == "__main__":
    main()
