# Momentum Strategy Specification (Revised)

## Objective
Develop a Multi-Timeframe (MTF) trading strategy for **Bitcoin (BTC)** that combines **Market Structure** analysis with **Momentum Indicators**.
Focus on the 2025-2026 market cycle (using available data up to present).
The goal is **Positive Expectancy** through robust trend following and risk management, rather than hitting rigid numerical targets.

## Core Philosophy
-   **Trend is King**: Trade in the direction of the Higher Timeframe (HTF) trend.
-   **Structure First**: Price action (Break of Structure, Higher Highs/Lows) takes precedence over lagging indicators.
-   **Dynamic Risk**: Stop-losses are based on market pivots, not arbitrary % values. Profits are secured via trailing stops to catch "fat tails".

## Data Requirements
-   **Asset**: BTC-USD
-   **Period**: 2025 - 2026 (or latest available)
-   **Timeframes**:
    -   **HTF (Trend)**: 4-Hour (4H) or Daily (1D)
    -   **LTF (Entry)**: 15-Minute (15m) or 1-Hour (1H)

## Strategy Logic

### 1. Trend Identification (HTF)
-   **Bullish Bias**: Price > EMA(200) AND Price making Higher Highs / Higher Lows.
-   **Bearish Bias**: Price < EMA(200) AND Price making Lower Lows / Lower Highs.

### 2. Entry Triggers (LTF)
-   **Long Setup**:
    -   HTF is Bullish.
    -   LTF shows a pullback (oversold condition via RSI/Stoch or retest of support).
    -   **Trigger**: LTF Break of Structure (candle close above previous minor high) OR Bullish Divergence on Momentum Indicator.

### 3. Risk Management
-   **Stop Loss (SL)**: Placed below the recent Swing Low (Market Structure).
-   **Take Profit (TP)**: No fixed target.
    -   **Trailing Stop**: Activate after R:R reach 1:1. Trail by ATR or Swing Lows.
    -   **Partial TP**: Optional (e.g., take 50% off at Break of Structure High).

## Performance Targets
-   **Primary**: Net Profit > 0 (Positive Expectancy).
-   **Secondary**: Profit Factor > 1.2.
-   **Risk**: Max Drawdown governed by risk-per-trade (e.g., 1-2% equity per trade).

## Deliverables
1.  **Research**: Logic for Market Structure detection (Pivot points algorithm).
2.  **Data**: Pipeline for fetching 15m/1H/4H BTC data.
3.  **Strategy**: Python implementation of MTF Logic.
4.  **Backtest**: Simulation on recent 2025-2026 data.