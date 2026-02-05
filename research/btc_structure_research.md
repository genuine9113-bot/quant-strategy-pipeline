# BTC Market Structure & Multi-Timeframe Research (2025-2026)

## Executive Summary
This document outlines a robust trading framework for Bitcoin (BTC) tailored to the 2025-2026 market cycle. The strategy shifts away from rigid indicator thresholds (like RSI < 30) towards a logic based on **Market Structure (Price Action)** and **Liquidity Dynamics**.

The core premise is **"Positive Expectancy"**: We do not predict the future; we identify setups where the probability of a move in our direction is significantly higher than the risk.

---

## 1. Core Concepts

### 1.1 Market Structure (The "King")
Market structure defines the trend. It takes precedence over all indicators.
- **Bullish Trend**: Series of Higher Highs (HH) and Higher Lows (HL).
- **Bearish Trend**: Series of Lower Lows (LL) and Lower Highs (LH).
- **Break of Structure (BoS)**: When price closes above a previous HH (bullish) or below a previous LL (bearish). This confirms trend continuation.
- **Change of Character (CHoCH)**: The first sign of a reversal (e.g., price breaking a HL in an uptrend).

### 1.2 Liquidity Sweeps (The "Trap")
Institutional algorithms often push price below obvious support (Swing Lows) to trigger retail stop-losses before reversing.
- **Bullish Sweep**: Price dips below a Swing Low but *closes* back above it. This traps sellers.
- **Bearish Sweep**: Price pushes above a Swing High but *closes* back below it. This traps buyers.

### 1.3 Multi-Timeframe (MTF) Alignment
We never trade in isolation. We use two timeframes:
1.  **Higher Timeframe (HTF)**: Determining the *Bias* (4-Hour or Daily).
2.  **Lower Timeframe (LTF)**: Timing the *Entry* (15-Minute or 1-Hour).

**Rule**: Only look for Longs on LTF if HTF is Bullish. Only look for Shorts if HTF is Bearish.

---

## 2. Strategy Logic

### 2.1 Trend Identification (HTF)
We assume a **Bullish Bias** if:
1.  **Price > EMA 200**: The 200-period Exponential Moving Average acts as a dynamic trend baseline.
2.  **Valid Structure**: Price is not in a confirmed downtrend (i.e., most recent major break was to the upside).

### 2.2 Entry Setup (LTF - Long Example)
Once HTF is Bullish, we wait for a pullback on the LTF.
1.  **Zone**: Price retraces to a Discount Zone (e.g., recent Support or EMA 200 on LTF).
2.  **Trigger A (Aggressive - Sweep)**: Price sweeps a previous 15m Low, touches support, and closes back bullish (Hammer candle).
3.  **Trigger B (Conservative - BoS)**: After a pullback, price breaks a minor Lower High (Shift in structure to bullish).
4.  **Momentum Filter**: RSI (14) shows Bullish Divergence (Price Lower Low, RSI Higher Low) OR RSI simply exiting oversold (< 30 -> > 30).

### 2.3 Risk Management (Dynamic)

#### Stop Loss (SL)
-   **Placement**: Below the recent Swing Low that formed the setup.
-   **Buffer**: Add a small buffer (e.g., 0.2% or 1 ATR) to avoid noise wicks.
-   **Never** use a fixed % (e.g., "always 5%"). Volatility in 2026 requires adaptability.

#### Take Profit (TP) & Trailing
-   **Initial Target**: No fixed cap.
-   **Breakeven**: Move SL to Entry Price once price reaches 1R (Reward = Risk).
-   **Trailing**:
    -   Trail SL below each formed Higher Low as price ascends.
    -   Or use Chandelier Exit (ATR-based trail).
-   **Partial TP**: Lock in 50% profit at the next major Resistance Level (Liquidty Pool).

---

## 3. Mathematical Formulas

### 3.1 Pivot Points (For Structure)
Identifying H/L requires a pivot algorithm.
A candle $t$ is a Low Pivot if:
$$ Low_{t-k} > Low_t < Low_{t+k} $$
Where $k$ is the neightborhood parameter (e.g., $k=3$ bars).

### 3.2 True Range & ATR (For Volatility)
Used for Dynamic stops.
$$ TR = \max(High - Low, |High - Close_{prev}|, |Low - Close_{prev}|) $$
$$ ATR_n = \frac{ATR_{n-1} \times (n-1) + TR_t}{n} $$

### 3.3 Expectancy
$$ E = (WinRate \times AvgWin) - (LossRate \times AvgLoss) $$
Goal: $E > 0$ after commissions/slippage.

---

## 4. Implementation Guidance

### 4.1 Data Structures
We need a `MarketData` class that holds data for multiple timeframes synchronized by time.
```python
class MTFData:
    def __init__(self):
        self.htf = pd.DataFrame() # 4H data
        self.ltf = pd.DataFrame() # 15m data
    
    def get_bias(self, timestamp):
        # Look up HTF state at this timestamp
        pass
```

### 4.2 Algorithm Pseudocode
```python
def on_bar(ltf_bar):
    htf_trend = get_htf_trend(ltf_bar.time)
    
    if htf_trend == BULLISH:
        if ltf_bar.close > ema_200 and rsi < 30: # Simple Pullback
             # Check for structure shift
             if check_break_of_structure(ltf_bar):
                 entry_long()
```

---

## 5. References & Trends (2025-2026 Context)
-   **Institutional Liquidity**: 2025 has seen ETF inflows dominating price action. Algorithms hunt liquidity more aggressively than in 2021.
-   **ICT / Smart Money Concepts**: "Fair Value Gaps" (FVG) and "Order Blocks" are statistically significant reaction points in modern BTC markets.
-   **Volatility Regimes**: Post-halving cycles often show reduced volatility. Dynamic ATR-based stops are superior to fixed % stops which get eaten by noise.

---
*Generated by Research Agent for Quant Strategy Pipeline*
