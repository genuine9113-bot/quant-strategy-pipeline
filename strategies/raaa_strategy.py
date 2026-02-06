"""
RAAA (Regime-Adaptive Aggressive Alpha) Strategy

Multi-Asset, Multi-Timeframe, Regime-Switching strategy for BTC/ETH perpetual futures.

Core Features:
- 4-state regime classification (Trending Bull/Bear, Chop, Squeeze)
- Regime-specific entry strategies
- Cross-asset signal confirmation
- Pyramiding in trending regimes
- Comprehensive exit management (Stop, Trailing, Partial TP, Time Stop)
- Cooldown management after exits and regime changes

Spec References:
- Section 4: Entry Strategies by Regime
- Section 5: Cross-Asset Signals
- Section 6: Position Management
- Section 7: Exit & Risk Management
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from .regime import MarketRegime, RegimeEngine
from .risk_manager import RiskManager

# Setup module-specific logger
logger = logging.getLogger("RAAA_Strategy")
logger.setLevel(logging.DEBUG)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# File handler
try:
    file_handler = logging.FileHandler('logs/strategy.log')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(console_formatter)
    logger.addHandler(file_handler)
except Exception:
    pass

logger.addHandler(console_handler)


class Position:
    """
    Represents an active trading position.

    Tracks entry, stops, targets, pyramiding state, and exit management.
    """

    def __init__(self, symbol, direction, entry_price, size, entry_time, atr, regime, strategy_type):
        """
        Initialize position.

        Args:
            symbol: 'BTC' or 'ETH'
            direction: 'LONG' or 'SHORT'
            entry_price: Entry price
            size: Position size (coins)
            entry_time: datetime of entry
            atr: ATR(14) at entry
            regime: MarketRegime at entry
            strategy_type: Entry strategy name (e.g., 'Bull Momentum')
        """
        self.symbol = symbol
        self.direction = direction
        self.entry_price = entry_price
        self.size = size
        self.entry_time = entry_time
        self.atr = atr
        self.regime = regime
        self.strategy_type = strategy_type

        # Stop management
        self.stop_loss = None
        self.trailing_stop = None
        self.trailing_active = False

        # Partial TP tracking
        self.partial_tp_done = False  # Blocks further pyramiding
        self.tp_levels = {
            '2R': False,
            '3R': False,
            '4R': False
        }

        # Pyramiding tracking
        self.pyramided = False
        self.pyramid_count = 0
        self.original_size = size
        self.pyramid_entries = [(entry_price, size)]  # List of (price, size)

        # R calculation
        self.initial_r = 1.5 * atr  # 1R = 1.5 ATR initially
        self.current_avg_price = entry_price

        # Highest/Lowest tracking for trailing stop
        self.highest_high = entry_price if direction == 'LONG' else None
        self.lowest_low = entry_price if direction == 'SHORT' else None

        logger.info(
            f"Position opened: {symbol} {direction} @ ${entry_price:.2f}, "
            f"Size={size:.6f}, Regime={regime.value}, Strategy={strategy_type}"
        )

    def add_pyramid(self, pyramid_price, pyramid_size, atr):
        """
        Add pyramid entry to position.

        Spec 6.2 (202-226): Recalculate average price, stop, and R

        Args:
            pyramid_price: Pyramid entry price
            pyramid_size: Additional size (coins)
            atr: Current ATR(14)
        """
        self.pyramid_entries.append((pyramid_price, pyramid_size))
        self.pyramid_count += 1
        self.size += pyramid_size
        self.pyramided = True

        # Recalculate average price (Spec 207-209)
        total_value = sum(price * size for price, size in self.pyramid_entries)
        total_size = sum(size for _, size in self.pyramid_entries)
        self.current_avg_price = total_value / total_size

        # Recalculate stop (Spec 211-214)
        stop_width = 1.5 * atr
        if self.direction == 'LONG':
            self.stop_loss = self.current_avg_price - stop_width
        else:
            self.stop_loss = self.current_avg_price + stop_width

        # Recalculate R (Spec 216-219)
        self.initial_r = stop_width

        logger.info(
            f"Pyramid added to {self.symbol} {self.direction}: "
            f"Pyramid Price=${pyramid_price:.2f}, Size={pyramid_size:.6f}, "
            f"New Avg=${self.current_avg_price:.2f}, New Stop=${self.stop_loss:.2f}, "
            f"Total Size={self.size:.6f}, Pyramid Count={self.pyramid_count}"
        )

    def update_trailing_stop(self, current_high, current_low, atr):
        """
        Update trailing stop if trailing is active.

        Spec 7.2 (250-254): Activates after 1R profit, trails 2 ATR from highest high/lowest low

        Args:
            current_high: Current bar high
            current_low: Current bar low
            atr: Current ATR(14)
        """
        if not self.trailing_active:
            return

        trail_distance = 2.0 * atr

        if self.direction == 'LONG':
            # Update highest high
            if self.highest_high is None or current_high > self.highest_high:
                self.highest_high = current_high

            # Calculate trailing stop
            new_trailing_stop = self.highest_high - trail_distance

            # Only move stop up, never down
            if self.trailing_stop is None or new_trailing_stop > self.trailing_stop:
                old_stop = self.trailing_stop
                self.trailing_stop = new_trailing_stop
                old_stop_str = f"${old_stop:.2f}" if old_stop is not None else "$0.00"
                logger.debug(
                    f"{self.symbol} {self.direction} Trailing Stop updated: "
                    f"{old_stop_str} → ${new_trailing_stop:.2f} "
                    f"(High=${self.highest_high:.2f}, Trail={trail_distance:.2f})"
                )

        else:  # SHORT
            # Update lowest low
            if self.lowest_low is None or current_low < self.lowest_low:
                self.lowest_low = current_low

            # Calculate trailing stop
            new_trailing_stop = self.lowest_low + trail_distance

            # Only move stop down, never up
            if self.trailing_stop is None or new_trailing_stop < self.trailing_stop:
                old_stop = self.trailing_stop
                self.trailing_stop = new_trailing_stop
                old_stop_str = f"${old_stop:.2f}" if old_stop is not None else "$0.00"
                logger.debug(
                    f"{self.symbol} {self.direction} Trailing Stop updated: "
                    f"{old_stop_str} → ${new_trailing_stop:.2f} "
                    f"(Low=${self.lowest_low:.2f}, Trail={trail_distance:.2f})"
                )

    def activate_trailing_stop(self):
        """Activate trailing stop (called when profit > 1R)"""
        if not self.trailing_active:
            self.trailing_active = True
            logger.info(f"{self.symbol} {self.direction} Trailing Stop ACTIVATED (Profit > 1R)")

    def get_profit_r(self, current_price):
        """
        Calculate current profit in R multiples.

        Args:
            current_price: Current asset price

        Returns:
            float: Profit in R (positive = profit, negative = loss)
        """
        if self.direction == 'LONG':
            profit_raw = current_price - self.current_avg_price
        else:
            profit_raw = self.current_avg_price - current_price

        profit_r = profit_raw / self.initial_r if self.initial_r > 0 else 0
        return profit_r


class RAAAStrategy:
    """
    Main RAAA strategy implementation.

    Manages signal generation, position tracking, exit logic, and cooldowns.
    """

    def __init__(self, risk_manager: RiskManager, regime_engine: RegimeEngine):
        """
        Initialize strategy.

        Args:
            risk_manager: RiskManager instance
            regime_engine: RegimeEngine instance (stateful)
        """
        self.risk_manager = risk_manager
        self.regime_engine = regime_engine

        # Position tracking
        self.positions = {}  # {symbol: Position}

        # Cooldown tracking (Spec 6.4: 237-241)
        self.cooldowns = {}  # {symbol: datetime}
        self.cooldown_loss = timedelta(minutes=30)   # 2 × 15m bars
        self.cooldown_profit = timedelta(minutes=15) # 1 × 15m bar

        # Cross-asset state tracking
        self.btc_eth_correlation = None
        self.btc_has_active_long = False

        logger.info("RAAAStrategy initialized")

    def get_signal(
        self,
        row4h,
        row1h,
        row15m,
        symbol,
        current_time,
        btc_eth_correlation=None,
        btc_position_status=None,
        funding_rate=None,
        onchain_signals=None
    ):
        """
        Generate trading signal based on multi-timeframe data.

        Args:
            row4h: 4H bar data (regime classification)
            row1h: 1H bar data (signal generation)
            row15m: 15m bar data (entry timing)
            symbol: 'BTC' or 'ETH'
            current_time: datetime object
            btc_eth_correlation: Current BTC-ETH correlation (optional)
            btc_position_status: dict with BTC position info (optional, for ETH entry)
            funding_rate: Current funding rate (optional)
            onchain_signals: dict with on-chain signals (optional)

        Returns:
            dict: {
                'signal': 'ENTRY_LONG'|'ENTRY_SHORT'|'PYRAMID_LONG'|'PYRAMID_SHORT'|'HOLD',
                'reason': str,
                'regime': MarketRegime,
                'confidence': float (0.5 ~ 2.0)
            }
        """
        # Update regime (detects transitions and cooldowns)
        regime, regime_changed, immediate_close = self.regime_engine.update_regime(row4h, current_time)

        # Store correlation
        self.btc_eth_correlation = btc_eth_correlation

        # Check if in cooldown for this symbol
        if self._is_in_cooldown(symbol, current_time):
            return {
                'signal': 'HOLD',
                'reason': f"In cooldown until {self.cooldowns[symbol]}",
                'regime': regime,
                'confidence': 1.0
            }

        # Check if regime allows new entries
        can_enter, regime_reason = self.regime_engine.can_enter_new_position()
        if not can_enter:
            return {
                'signal': 'HOLD',
                'reason': regime_reason,
                'regime': regime,
                'confidence': 1.0
            }

        # Get active position if exists
        active_position = self.positions.get(symbol)

        # Check pyramiding opportunity first (only in trending regimes)
        if active_position and not active_position.partial_tp_done:
            if regime in [MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR]:
                pyramid_signal = self._check_pyramiding(active_position, row15m['close'], row15m['ATR_14'])
                if pyramid_signal:
                    return {
                        'signal': pyramid_signal,
                        'reason': f"Pyramiding at {active_position.get_profit_r(row15m['close']):.2f}R profit",
                        'regime': regime,
                        'confidence': 1.0
                    }

        # Dispatch to regime-specific entry strategies
        if regime == MarketRegime.TRENDING_BULL:
            signal, reason = self._trending_bull_strategy(row1h, row15m, active_position, symbol, btc_position_status)
        elif regime == MarketRegime.TRENDING_BEAR:
            signal, reason = self._trending_bear_strategy(row1h, row15m, active_position)
        elif regime == MarketRegime.CHOP_HIGH_VOL:
            signal, reason = self._chop_strategy(row1h, row15m, active_position)
        elif regime == MarketRegime.SQUEEZE_LOW_VOL:
            signal, reason = self._squeeze_strategy(row1h, row15m, active_position)
        else:
            signal, reason = "HOLD", "Undefined Regime"

        # Calculate confidence multiplier
        confidence = self._calculate_confidence(
            signal,
            symbol,
            btc_eth_correlation,
            funding_rate,
            onchain_signals
        )

        return {
            'signal': signal,
            'reason': reason,
            'regime': regime,
            'confidence': confidence
        }

    def _trending_bull_strategy(self, row1h, row15m, active_position, symbol, btc_position_status):
        """
        Trending Bull entry strategies.

        Spec 4.1 (88-117):
        - A. Momentum Continuation
        - B. Pullback Entry
        - C. Breakout Continuation

        Args:
            row1h: 1H bar data
            row15m: 15m bar data
            active_position: Position object if exists
            symbol: 'BTC' or 'ETH'
            btc_position_status: dict with BTC position info

        Returns:
            tuple: (signal, reason)
        """
        # Skip if already long
        if active_position and active_position.direction == 'LONG':
            return "HOLD", "Already Long"

        # ETH special condition (Spec 45-46): Only enter ETH Long if BTC is also Trending Bull with active position
        if symbol == 'ETH':
            if btc_position_status is None or not btc_position_status.get('has_long_position'):
                return "HOLD", "ETH Long requires BTC Trending Bull with active Long position"

        # Strategy A: Momentum Continuation (Spec 90-98)
        if self._check_momentum_continuation_1h(row1h):
            if self._check_ema9_pullback_15m(row15m):
                return "ENTRY_LONG", "Bull Momentum Pullback to EMA9"

            # Alternative: Volume surge breakout
            if self._check_volume_surge_15m(row15m, multiplier=2.0):
                return "ENTRY_LONG", "Bull Momentum Volume Surge"

        # Strategy B: Pullback Entry (Spec 100-108)
        if self._check_pullback_conditions_1h(row1h):
            if self._check_bullish_candle_15m(row15m) or self._check_rsi_rebound_15m(row15m):
                return "ENTRY_LONG", "Bull Pullback Entry"

        # Strategy C: Breakout Continuation (Spec 110-117)
        if self._check_breakout_1h(row1h, direction='LONG'):
            # Ideally wait for pullback, but simplified: enter on breakout
            return "ENTRY_LONG", "Bull Breakout Continuation"

        return "HOLD", ""

    def _trending_bear_strategy(self, row1h, row15m, active_position):
        """
        Trending Bear entry strategies (mirror of Bull).

        Spec 4.2 (119-123):
        - Momentum Short
        - Rally Short
        - Breakdown Short

        Returns:
            tuple: (signal, reason)
        """
        # Skip if already short
        if active_position and active_position.direction == 'SHORT':
            return "HOLD", "Already Short"

        # Strategy A: Momentum Short (mirror of Bull A)
        if self._check_momentum_continuation_1h(row1h, direction='SHORT'):
            if self._check_ema9_pullback_15m(row15m):
                return "ENTRY_SHORT", "Bear Momentum Pullback to EMA9"

            if self._check_volume_surge_15m(row15m, multiplier=2.0):
                return "ENTRY_SHORT", "Bear Momentum Volume Surge"

        # Strategy B: Rally Short (Spec 122: RSI 50-60, touches EMA50)
        if self._check_rally_short_conditions_1h(row1h):
            if self._check_bearish_candle_15m(row15m) or self._check_rsi_rebound_15m(row15m, direction='SHORT'):
                return "ENTRY_SHORT", "Bear Rally Short"

        # Strategy C: Breakdown Short
        if self._check_breakout_1h(row1h, direction='SHORT'):
            return "ENTRY_SHORT", "Bear Breakdown"

        return "HOLD", ""

    def _chop_strategy(self, row1h, row15m, active_position):
        """
        High Volatility Chop strategies.

        Spec 4.3 (125-144):
        - A. BB Mean Reversion
        - B. RSI Divergence Reversal

        Returns:
            tuple: (signal, reason)
        """
        # Mean Reversion typically 1 position at a time
        if active_position:
            return "HOLD", "Existing Position in Chop"

        # Strategy A: BB Mean Reversion (Spec 128-135)
        # Long: Price <= Lower BB(2.5), RSI < 25
        if row1h['close'] <= row1h.get('BB_LOWER_2.5', row1h['close']) and row1h['RSI_14'] < 25:
            if self._check_bullish_candle_15m(row15m):
                return "ENTRY_LONG", "Chop Mean Reversion Long"

        # Short: Price >= Upper BB(2.5), RSI > 75
        if row1h['close'] >= row1h.get('BB_UPPER_2.5', row1h['close']) and row1h['RSI_14'] > 75:
            if self._check_bearish_candle_15m(row15m):
                return "ENTRY_SHORT", "Chop Mean Reversion Short"

        # Strategy B: RSI Divergence Reversal (Spec 137-143)
        # Requires historical price/RSI data - simplified for now
        # TODO: Implement divergence detection with rolling window

        return "HOLD", ""

    def _squeeze_strategy(self, row1h, row15m, active_position):
        """
        Low Volatility Squeeze strategies.

        Spec 4.4 (146-163):
        - A. Bollinger-Keltner Squeeze Breakout
        - B. Volume Spike Breakout

        Returns:
            tuple: (signal, reason)
        """
        if active_position:
            return "HOLD", "Existing Position in Squeeze"

        # Strategy A: BB-Keltner Squeeze Breakout (Spec 148-154)
        # Requires BB inside KC detection - simplified for now
        # TODO: Implement squeeze detection (BB width < KC width)

        # Strategy B: Volume Spike Breakout (Spec 156-163)
        if row1h['volume'] > row1h.get('VOL_SMA_20', row1h['volume']) * 3.0:
            # Direction based on candle
            if row1h['close'] > row1h['open']:
                return "ENTRY_LONG", "Squeeze Volume Spike Long"
            else:
                return "ENTRY_SHORT", "Squeeze Volume Spike Short"

        return "HOLD", ""

    def _check_pyramiding(self, position, current_price, atr):
        """
        Check if pyramiding conditions are met.

        Spec 6.2 (202-226):
        - Trending regime only
        - Position profit > 1.5R
        - Partial TP not started
        - Max 1 pyramid

        Args:
            position: Active Position object
            current_price: Current asset price
            atr: Current ATR(14)

        Returns:
            str or None: 'PYRAMID_LONG' or 'PYRAMID_SHORT' if conditions met
        """
        # Check if already pyramided (max 1)
        if position.pyramid_count >= 1:
            return None

        # Check if partial TP already done (blocks pyramiding)
        if position.partial_tp_done:
            return None

        # Check profit > 1.5R
        profit_r = position.get_profit_r(current_price)
        if profit_r < 1.5:
            return None

        logger.info(
            f"Pyramiding conditions met for {position.symbol} {position.direction}: "
            f"Profit={profit_r:.2f}R, Pyramid Count={position.pyramid_count}"
        )

        if position.direction == 'LONG':
            return 'PYRAMID_LONG'
        else:
            return 'PYRAMID_SHORT'

    def _calculate_confidence(self, signal, symbol, btc_eth_correlation, funding_rate, onchain_signals):
        """
        Calculate confidence multiplier for position sizing.

        Spec 5.3 (178-185):
        - Dampened (Negative signals): 0.5×
        - Normal: 1.0×
        - High (Cross-asset confirmation): 1.5×
        - Very High (Cross-asset + On-chain): 2.0×

        Spec 8.5: Funding Rate adjustments

        Args:
            signal: Trading signal
            symbol: Asset symbol
            btc_eth_correlation: BTC-ETH correlation
            funding_rate: Current funding rate
            onchain_signals: dict with on-chain indicators

        Returns:
            float: Confidence multiplier (0.5 ~ 2.0)
        """
        if signal == 'HOLD':
            return 1.0

        confidence = 1.0  # Normal
        direction = 'LONG' if 'LONG' in signal else 'SHORT'

        # Cross-asset confirmation (Spec 5.1: 167-171)
        if btc_eth_correlation is not None:
            if btc_eth_correlation > 0.85:
                # High correlation + same direction = High confidence
                confidence = 1.5
                logger.debug(f"Confidence boost to 1.5× due to high correlation ({btc_eth_correlation:.3f})")

        # On-chain signals (Spec 9: 319-342)
        if onchain_signals:
            onchain_boost = self._evaluate_onchain_signals(onchain_signals, direction)
            if onchain_boost > 0 and confidence > 1.0:
                confidence = 2.0  # Very High
                logger.debug("Confidence boost to 2.0× due to on-chain confirmation")
            elif onchain_boost < 0:
                confidence = 0.5  # Dampened
                logger.debug("Confidence reduced to 0.5× due to negative on-chain signals")

        # Funding rate dampening (Spec 8.5: 307-311)
        if funding_rate is not None:
            # Funding > 0 = Longs pay Shorts
            # Funding < 0 = Shorts pay Longs
            if abs(funding_rate) > 0.001:  # |0.1%|
                if (direction == 'LONG' and funding_rate > 0) or (direction == 'SHORT' and funding_rate < 0):
                    # Paying funding = reduce confidence
                    confidence *= 0.75  # Additional dampening
                    logger.debug(f"Confidence dampened by funding rate ({funding_rate:+.4f})")

        return confidence

    def _evaluate_onchain_signals(self, onchain_signals, direction):
        """
        Evaluate on-chain signals for confidence adjustment.

        Spec 9.1 (323-327): Signal Boosters
        Spec 9.2 (329-333): Signal Dampeners

        Args:
            onchain_signals: dict with on-chain metrics
            direction: 'LONG' or 'SHORT'

        Returns:
            int: +1 (boost), 0 (neutral), -1 (dampen)
        """
        score = 0

        # Example on-chain logic (requires actual data)
        # Boosters for LONG
        if direction == 'LONG':
            if onchain_signals.get('netflow', 0) < 0:  # Outflow
                score += 1
            if onchain_signals.get('mvrv_z', 0) < 0:  # Undervalued
                score += 1

        # Dampeners for LONG
        if direction == 'LONG':
            if onchain_signals.get('netflow', 0) > 0:  # Inflow
                score -= 1
            if onchain_signals.get('mvrv_z', 0) > 3:  # Overheated
                score -= 1

        # TODO: Implement full on-chain logic with real data

        return score

    def check_exits(self, position, row15m, current_time):
        """
        Check all exit conditions for an active position.

        Spec 7 (243-279):
        - Initial Stop Loss (1.5 ATR)
        - Trailing Stop (2 ATR after 1R profit)
        - Partial TP (2R, 3R, 4R+)
        - Time Stop (24H/12H/6H)
        - Regime Change Exit

        Args:
            position: Active Position object
            row15m: Current 15m bar data
            current_time: datetime object

        Returns:
            dict or None: Exit signal dict if exit required
                {
                    'action': 'STOP_LOSS'|'TRAILING_STOP'|'PARTIAL_TP_2R'|'PARTIAL_TP_3R'|'TIME_STOP'|'REGIME_EXIT',
                    'exit_pct': float (0-1, 1.0 = full exit),
                    'reason': str
                }
        """
        current_price = row15m['close']
        current_high = row15m['high']
        current_low = row15m['low']
        atr = row15m['ATR_14']

        # 1. Check Initial Stop Loss
        if position.stop_loss is not None:
            if position.direction == 'LONG' and current_low <= position.stop_loss:
                logger.info(f"{position.symbol} {position.direction} STOP LOSS hit: ${current_low:.2f} <= ${position.stop_loss:.2f}")
                return {'action': 'STOP_LOSS', 'exit_pct': 1.0, 'reason': 'Initial Stop Loss'}

            if position.direction == 'SHORT' and current_high >= position.stop_loss:
                logger.info(f"{position.symbol} {position.direction} STOP LOSS hit: ${current_high:.2f} >= ${position.stop_loss:.2f}")
                return {'action': 'STOP_LOSS', 'exit_pct': 1.0, 'reason': 'Initial Stop Loss'}

        # 2. Update and check Trailing Stop
        profit_r = position.get_profit_r(current_price)

        # Activate trailing if profit > 1R
        if profit_r > 1.0 and not position.trailing_active:
            position.activate_trailing_stop()

        # Update trailing stop
        if position.trailing_active:
            position.update_trailing_stop(current_high, current_low, atr)

            # Check if trailing stop hit
            if position.trailing_stop is not None:
                if position.direction == 'LONG' and current_low <= position.trailing_stop:
                    logger.info(f"{position.symbol} {position.direction} TRAILING STOP hit: ${current_low:.2f} <= ${position.trailing_stop:.2f}")
                    return {'action': 'TRAILING_STOP', 'exit_pct': 1.0, 'reason': f'Trailing Stop (Profit={profit_r:.2f}R)'}

                if position.direction == 'SHORT' and current_high >= position.trailing_stop:
                    logger.info(f"{position.symbol} {position.direction} TRAILING STOP hit: ${current_high:.2f} >= ${position.trailing_stop:.2f}")
                    return {'action': 'TRAILING_STOP', 'exit_pct': 1.0, 'reason': f'Trailing Stop (Profit={profit_r:.2f}R)'}

        # 3. Check Partial TP levels (Spec 7.3: 256-268)
        # Special handling for Mean Reversion (Spec 264-268)
        if position.regime == MarketRegime.CHOP_HIGH_VOL:
            # Mean Reversion TP: BB Middle Band (60%), Opposite BB 1σ (40%)
            # Simplified: Use fixed TP at 1R and 2R
            if profit_r >= 1.0 and not position.tp_levels['2R']:
                position.tp_levels['2R'] = True
                position.partial_tp_done = True
                logger.info(f"{position.symbol} {position.direction} Partial TP 1R (Mean Reversion): 60% exit")
                return {'action': 'PARTIAL_TP_MR_1', 'exit_pct': 0.6, 'reason': 'Mean Reversion TP 1R (60%)'}

            if profit_r >= 2.0 and not position.tp_levels['3R']:
                position.tp_levels['3R'] = True
                logger.info(f"{position.symbol} {position.direction} Partial TP 2R (Mean Reversion): 40% exit")
                return {'action': 'PARTIAL_TP_MR_2', 'exit_pct': 1.0, 'reason': 'Mean Reversion TP 2R (40% = Full Close)'}

        else:
            # Standard Partial TP (Spec 256-262)
            if profit_r >= 2.0 and not position.tp_levels['2R']:
                position.tp_levels['2R'] = True
                position.partial_tp_done = True  # Blocks pyramiding
                logger.info(f"{position.symbol} {position.direction} Partial TP 2R: 40% exit at ${current_price:.2f}")
                return {'action': 'PARTIAL_TP_2R', 'exit_pct': 0.4, 'reason': f'Partial TP 2R (Profit={profit_r:.2f}R)'}

            if profit_r >= 3.0 and not position.tp_levels['3R']:
                position.tp_levels['3R'] = True
                logger.info(f"{position.symbol} {position.direction} Partial TP 3R: 30% exit at ${current_price:.2f}")
                return {'action': 'PARTIAL_TP_3R', 'exit_pct': 0.3, 'reason': f'Partial TP 3R (Profit={profit_r:.2f}R)'}

            # 4R+: Let trailing stop handle

        # 4. Check Time Stop (Spec 7.4: 270-273)
        time_in_position = (current_time - position.entry_time).total_seconds() / 3600  # hours

        if position.regime in [MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR]:
            time_limit = 24  # hours
        elif position.regime == MarketRegime.CHOP_HIGH_VOL:
            time_limit = 12  # hours
        else:  # SQUEEZE_LOW_VOL
            time_limit = 6  # hours

        if time_in_position >= time_limit and profit_r < 1.0:
            logger.warning(
                f"{position.symbol} {position.direction} TIME STOP: {time_in_position:.1f}h >= {time_limit}h, "
                f"Profit={profit_r:.2f}R < 1R"
            )
            return {'action': 'TIME_STOP', 'exit_pct': 1.0, 'reason': f'Time Stop ({time_in_position:.1f}h, <1R profit)'}

        # No exit signal
        return None

    def open_position(self, symbol, direction, entry_price, size, entry_time, atr, regime, strategy_type):
        """
        Open a new position.

        Args:
            symbol: 'BTC' or 'ETH'
            direction: 'LONG' or 'SHORT'
            entry_price: Entry price
            size: Position size (coins)
            entry_time: datetime
            atr: ATR(14) at entry
            regime: MarketRegime at entry
            strategy_type: Entry strategy name

        Returns:
            Position object
        """
        position = Position(symbol, direction, entry_price, size, entry_time, atr, regime, strategy_type)

        # Set initial stop loss
        position.stop_loss = self.risk_manager.get_stop_loss_price(entry_price, direction, atr)

        self.positions[symbol] = position
        return position

    def close_position(self, symbol, exit_price, exit_time, reason, exit_pct=1.0):
        """
        Close a position (full or partial).

        Args:
            symbol: 'BTC' or 'ETH'
            exit_price: Exit price
            exit_time: datetime
            reason: Exit reason
            exit_pct: Percentage to close (0-1)

        Returns:
            tuple: (closed_size, pnl, pnl_pct)
        """
        position = self.positions.get(symbol)
        if not position:
            logger.warning(f"Attempted to close non-existent position: {symbol}")
            return 0, 0, 0

        # Calculate P&L
        if position.direction == 'LONG':
            pnl_per_coin = exit_price - position.current_avg_price
        else:
            pnl_per_coin = position.current_avg_price - exit_price

        closed_size = position.size * exit_pct
        pnl = pnl_per_coin * closed_size
        pnl_pct = (pnl / (position.current_avg_price * closed_size)) * 100 if closed_size > 0 else 0

        logger.info(
            f"Position closed: {symbol} {position.direction}, "
            f"Exit=${exit_price:.2f}, Size={closed_size:.6f} ({exit_pct:.0%}), "
            f"P&L=${pnl:,.2f} ({pnl_pct:+.2f}%), Reason={reason}"
        )

        # Update or remove position
        if exit_pct >= 1.0:
            # Full close
            del self.positions[symbol]

            # Set cooldown (Spec 6.4: 237-241)
            if pnl >= 0:
                cooldown_duration = self.cooldown_profit
            else:
                cooldown_duration = self.cooldown_loss

            self.cooldowns[symbol] = exit_time + cooldown_duration
            logger.info(f"Cooldown set for {symbol} until {self.cooldowns[symbol]}")

        else:
            # Partial close
            position.size -= closed_size
            logger.debug(f"Partial close: {symbol} remaining size={position.size:.6f}")

        return closed_size, pnl, pnl_pct

    def _is_in_cooldown(self, symbol, current_time):
        """Check if symbol is in cooldown period"""
        if symbol not in self.cooldowns:
            return False

        if current_time < self.cooldowns[symbol]:
            return True
        else:
            # Cooldown expired
            del self.cooldowns[symbol]
            logger.info(f"Cooldown expired for {symbol}")
            return False

    # ========== 1H Signal Condition Helpers ==========

    def _check_momentum_continuation_1h(self, row1h, direction='LONG'):
        """
        Check 1H momentum continuation conditions.

        Spec 4.1A / 4.2A (90-93, 113-115):
        - LONG: RSI(14) > 50 & < 80, Close > EMA(20), Vol > SMA(20)*1.3
        - SHORT: RSI(14) < 50 & > 20, Close < EMA(20), Vol > SMA(20)*1.3
        """
        vol_threshold = row1h.get('VOL_SMA_20', row1h['volume']) * 1.3

        if direction == 'LONG':
            return (
                50 < row1h['RSI_14'] < 80 and
                row1h['close'] > row1h['EMA_20'] and
                row1h['volume'] > vol_threshold
            )
        else:  # SHORT
            return (
                20 < row1h['RSI_14'] < 50 and
                row1h['close'] < row1h['EMA_20'] and
                row1h['volume'] > vol_threshold
            )

    def _check_pullback_conditions_1h(self, row1h):
        """
        Check 1H pullback conditions (Spec 4.1B: 100-104).

        - RSI(14) drops to 40-50 range
        - Price touches EMA(50) or BB Middle Band
        - ADX still > 25 (trend intact)
        """
        rsi_ok = 40 <= row1h['RSI_14'] <= 50
        adx_ok = row1h['ADX_14'] > 25

        # Check if price near EMA50 or BB Middle (within 0.5% tolerance)
        price = row1h['close']
        ema50 = row1h.get('EMA_50', price)
        bb_mid = row1h.get('BB_MID_20', price)

        near_ema50 = abs(price - ema50) / ema50 < 0.005
        near_bb_mid = abs(price - bb_mid) / bb_mid < 0.005

        return rsi_ok and adx_ok and (near_ema50 or near_bb_mid)

    def _check_rally_short_conditions_1h(self, row1h):
        """
        Check 1H rally short conditions (Spec 4.2B: 122).

        - RSI rises to 50-60
        - Price touches EMA(50) from below
        - ADX > 25
        """
        rsi_ok = 50 <= row1h['RSI_14'] <= 60
        adx_ok = row1h['ADX_14'] > 25

        price = row1h['close']
        ema50 = row1h.get('EMA_50', price)
        near_ema50 = abs(price - ema50) / ema50 < 0.005

        return rsi_ok and adx_ok and near_ema50

    def _check_breakout_1h(self, row1h, direction='LONG'):
        """
        Check 1H breakout conditions (Spec 4.1C / 4.2C: 110-114, 118-119).

        - LONG: Close > Donchian(20) Upper, Vol > SMA(20) * 2.0
        - SHORT: Close < Donchian(20) Lower, Vol > SMA(20) * 2.0
        """
        vol_threshold = row1h.get('VOL_SMA_20', row1h['volume']) * 2.0
        vol_ok = row1h['volume'] > vol_threshold

        if direction == 'LONG':
            donchian_upper = row1h.get('DONCHIAN_UPPER_20', row1h['close'])
            return row1h['close'] > donchian_upper and vol_ok
        else:  # SHORT
            donchian_lower = row1h.get('DONCHIAN_LOWER_20', row1h['close'])
            return row1h['close'] < donchian_lower and vol_ok

    # ========== 15m Entry Confirmation Helpers ==========

    def _check_ema9_pullback_15m(self, row15m):
        """
        Check if 15m bar touches EMA(9) (Spec 4.1A: 92).

        Low <= EMA(9) <= High
        """
        ema9 = row15m.get('EMA_9', row15m['close'])
        return row15m['low'] <= ema9 <= row15m['high']

    def _check_volume_surge_15m(self, row15m, multiplier=2.0):
        """Check if 15m volume surges above average"""
        vol_sma = row15m.get('VOL_SMA_20', row15m['volume'])
        return row15m['volume'] > vol_sma * multiplier

    def _check_bullish_candle_15m(self, row15m):
        """Check if 15m bar is bullish (close > open)"""
        return row15m['close'] > row15m['open']

    def _check_bearish_candle_15m(self, row15m):
        """Check if 15m bar is bearish (close < open)"""
        return row15m['close'] < row15m['open']

    def _check_rsi_rebound_15m(self, row15m, direction='LONG'):
        """
        Check RSI rebound on 15m (Spec 4.1B: 108).

        - LONG: RSI < 30 (oversold rebound)
        - SHORT: RSI > 70 (overbought rebound)
        """
        if direction == 'LONG':
            return row15m['RSI_14'] < 30
        else:
            return row15m['RSI_14'] > 70

    def get_positions_summary(self):
        """Get summary of all active positions for logging"""
        return {
            symbol: {
                'direction': pos.direction,
                'entry_price': pos.entry_price,
                'current_avg_price': pos.current_avg_price,
                'size': pos.size,
                'stop_loss': pos.stop_loss,
                'trailing_stop': pos.trailing_stop,
                'trailing_active': pos.trailing_active,
                'pyramided': pos.pyramided,
                'pyramid_count': pos.pyramid_count,
                'regime': pos.regime.value,
                'entry_time': pos.entry_time
            }
            for symbol, pos in self.positions.items()
        }
