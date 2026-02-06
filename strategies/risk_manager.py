"""
Global Risk Manager for RAAA Strategy

Implements:
- Drawdown limits (10%, 15%, 20%) - UPDATED: More conservative
- Daily loss limits (5%)
- Volatility scaling (ATR Percentile) - UPDATED: 80th/90th thresholds
- Correlation risk management
- Funding rate risk controls
- Liquidation defense
- Position limit enforcement
- Consecutive loss protection - NEW
"""

import logging
from datetime import datetime, date
import numpy as np

# Setup module-specific logger
logger = logging.getLogger("RiskManager")
logger.setLevel(logging.DEBUG)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# File handler
try:
    file_handler = logging.FileHandler('logs/risk_manager.log')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(console_formatter)
    logger.addHandler(file_handler)
except Exception:
    pass  # If logs directory doesn't exist, skip file logging

logger.addHandler(console_handler)


class RiskManager:
    """
    Global risk control system for RAAA strategy.

    Spec References:
    - Section 8: Global Risk Controls
    - Section 6.1: Position Sizing
    - Section 7.6: Liquidation Defense
    """

    def __init__(self, initial_equity=100000):
        """
        Initialize risk manager.

        Args:
            initial_equity: Starting capital in USDT
        """
        self.initial_equity = initial_equity
        self.current_equity = initial_equity
        self.max_equity = initial_equity

        # Daily loss tracking
        self.daily_start_equity = initial_equity
        self.current_date = None

        # Drawdown limits (UPDATED: More conservative)
        self.dd_limit_soft = 0.10   # 10% -> Size 50% reduction (was 15%)
        self.dd_limit_firm = 0.15   # 15% -> No new entries (was 20%)
        self.dd_limit_hard = 0.20   # 20% -> Close all, halt strategy (was 30%)

        # Position limits (Spec 6.3: 228-235)
        self.max_concurrent_positions = 2  # BTC 1 + ETH 1
        self.max_margin_per_position = 0.25  # 25% of Equity
        self.max_total_margin = 0.50  # 50% of Equity
        self.leverage = 3  # Fixed 3x (UPDATED: was 5x)

        # Consecutive loss protection (NEW)
        self.consecutive_losses = 0
        self.consecutive_loss_scale_threshold = 3  # 3 losses -> 50% size reduction
        self.consecutive_loss_stop_threshold = 5   # 5 losses -> stop entries for day

        # Correlation risk (Spec 8.4: 303-305)
        self.corr_high_threshold = 0.9  # Reduce total margin to 40%
        self.corr_adjusted_margin_limit = 0.40

        # Funding rate thresholds (Spec 8.5: 307-311)
        self.funding_warning_threshold = 0.001  # ±0.1%
        self.funding_stop_threshold = 0.003     # ±0.3%

        logger.info(f"RiskManager initialized with equity=${initial_equity:,.0f}")

    def update_equity(self, new_equity, current_datetime):
        """
        Update equity and handle daily resets.

        Args:
            new_equity: Current equity value
            current_datetime: datetime object for date tracking
        """
        self.current_equity = new_equity
        self.max_equity = max(self.max_equity, new_equity)

        # Daily reset (Spec 8.2: UTC reset)
        current_date_only = current_datetime.date()
        if self.current_date != current_date_only:
            if self.current_date is not None:
                daily_pnl = new_equity - self.daily_start_equity
                daily_pnl_pct = daily_pnl / self.daily_start_equity * 100
                logger.info(f"Daily P&L for {self.current_date}: ${daily_pnl:,.2f} ({daily_pnl_pct:+.2f}%)")

            self.current_date = current_date_only
            self.daily_start_equity = new_equity
            logger.info(f"Daily reset: Date={self.current_date}, Start Equity=${new_equity:,.2f}")

    def validate_entry(
        self,
        signal_type,
        symbol,
        direction,
        active_positions_count,
        current_margin_usage,
        atr_percentile,
        btc_eth_correlation=None,
        funding_rate=None
    ):
        """
        Check all global risk rules before allowing entry.

        Args:
            signal_type: 'ENTRY_LONG', 'ENTRY_SHORT', 'PYRAMID_LONG', 'PYRAMID_SHORT'
            symbol: 'BTC' or 'ETH'
            direction: 'LONG' or 'SHORT'
            active_positions_count: Number of currently open positions
            current_margin_usage: Total margin currently used (USD)
            atr_percentile: Current ATR percentile (0-100)
            btc_eth_correlation: Current BTC-ETH correlation (optional)
            funding_rate: Current funding rate for direction (optional)

        Returns:
            tuple: (bool allow, float size_multiplier, str reason)
        """
        size_multiplier = 1.0
        reasons = []

        # 1. Hard DD Limit (UPDATED: DD > 20% -> Close all, halt strategy)
        drawdown = self._get_current_drawdown()
        if drawdown > self.dd_limit_hard:
            logger.error(f"HARD DD LIMIT EXCEEDED: {drawdown:.1%} > 20%. STRATEGY HALTED.")
            return False, 0.0, f"Hard DD Limit Exceeded ({drawdown:.1%})"

        # 2. Firm DD Limit (UPDATED: DD > 15% -> No new entries)
        if drawdown > self.dd_limit_firm:
            logger.warning(f"Firm DD limit exceeded: {drawdown:.1%} > 15%. No new entries allowed.")
            return False, 0.0, f"Firm DD Limit Exceeded ({drawdown:.1%})"

        # 3. Daily Loss Limit (Spec 8.2: > 5% daily loss)
        daily_loss_pct = self._get_daily_loss_pct()
        if daily_loss_pct > 0.05:
            logger.warning(f"Daily loss limit exceeded: {daily_loss_pct:.1%} > 5%. No new entries today.")
            return False, 0.0, f"Daily Loss Limit Exceeded ({daily_loss_pct:.1%})"

        # 4. Position Count Limit (Spec 6.3: Max 2 concurrent)
        if active_positions_count >= self.max_concurrent_positions:
            logger.debug(f"Max concurrent positions reached: {active_positions_count}/{self.max_concurrent_positions}")
            return False, 0.0, "Max Concurrent Positions Reached (2)"

        # 5. Total Margin Limit (Spec 8.6: Account margin > 50%)
        effective_margin_limit = self.max_total_margin

        # Adjust for high correlation (Spec 8.4: Corr > 0.9 -> 40% limit)
        if btc_eth_correlation is not None and btc_eth_correlation > self.corr_high_threshold:
            effective_margin_limit = self.corr_adjusted_margin_limit
            logger.warning(f"High correlation detected ({btc_eth_correlation:.3f}). Total margin limit reduced to 40%.")
            reasons.append(f"High Corr ({btc_eth_correlation:.3f})")

        margin_usage_pct = current_margin_usage / self.current_equity
        if margin_usage_pct >= effective_margin_limit:
            logger.warning(f"Total margin limit reached: {margin_usage_pct:.1%} >= {effective_margin_limit:.1%}")
            return False, 0.0, f"Total Margin Limit Reached ({margin_usage_pct:.1%})"

        # 6. Extreme Volatility (UPDATED: ATR Percentile > 90% -> Stop entries)
        if atr_percentile > 90:
            logger.warning(f"Extreme volatility: ATR Percentile {atr_percentile:.1f}th > 90th. No entries.")
            return False, 0.0, f"Extreme Volatility (ATR {atr_percentile:.1f}th > 90th)"

        # 7. High Volatility Scaling (UPDATED: ATR > 80% -> 50% size reduction)
        if atr_percentile > 80:
            size_multiplier *= 0.5
            logger.info(f"High volatility: ATR {atr_percentile:.1f}th > 80th. Size reduced by 50%.")
            reasons.append(f"High Vol ({atr_percentile:.1f}th)")

        # 8. Soft DD Limit (UPDATED: DD > 10% -> 50% size reduction)
        if drawdown > self.dd_limit_soft:
            size_multiplier *= 0.5
            logger.info(f"Soft DD limit: {drawdown:.1%} > 10%. Size reduced by 50%.")
            reasons.append(f"Soft DD ({drawdown:.1%})")

        # 9. Consecutive Loss Protection (NEW)
        if self.consecutive_losses >= self.consecutive_loss_stop_threshold:
            logger.warning(f"Consecutive losses ({self.consecutive_losses}) >= 5. No new entries today.")
            return False, 0.0, f"Consecutive Loss Limit ({self.consecutive_losses} losses)"

        if self.consecutive_losses >= self.consecutive_loss_scale_threshold:
            size_multiplier *= 0.5
            logger.info(f"Consecutive losses ({self.consecutive_losses}) >= 3. Size reduced by 50%.")
            reasons.append(f"Consec Loss ({self.consecutive_losses})")

        # 10. Funding Rate Risk (Spec 8.5: 307-311)
        if funding_rate is not None:
            funding_abs = abs(funding_rate)

            # Stop entries if funding > ±0.3%
            if funding_abs > self.funding_stop_threshold:
                logger.warning(f"Extreme funding rate: {funding_rate:+.4f} > ±0.3%. Stopping {direction} entries.")
                return False, 0.0, f"Extreme Funding Rate ({funding_rate:+.4f})"

            # Confidence -1 if funding > ±0.1% (handled via confidence, but log here)
            if funding_abs > self.funding_warning_threshold:
                logger.info(f"High funding rate: {funding_rate:+.4f} > ±0.1%. Consider confidence reduction.")
                reasons.append(f"High Funding ({funding_rate:+.4f})")

        # All checks passed
        reason_str = "; ".join(reasons) if reasons else "OK"
        if size_multiplier < 1.0:
            logger.info(f"Entry allowed with size_multiplier={size_multiplier:.2f}: {reason_str}")

        return True, size_multiplier, reason_str

    def calculate_position_size(self, price, atr, confidence=1.0, size_multiplier=1.0):
        """
        Calculate position size with risk-based sizing.

        UPDATED:
            Base Risk = 2% of Equity per trade (was 3%)
            Stop Width = 2.0 × ATR (was 1.5 ATR)
            Size (USD) = (Equity × 0.02) / (2.0 × ATR)
            Required Margin = Size (USD) / Leverage(3×)

        Args:
            price: Current asset price
            atr: Current ATR(14) value
            confidence: Confidence multiplier (0.5 ~ 2.0)
            size_multiplier: Risk multiplier from validate_entry (0.5 ~ 1.0)

        Returns:
            tuple: (num_coins, position_size_usd, required_margin)
        """
        # Base risk per trade (UPDATED: 3% -> 2%)
        risk_per_trade = 0.02
        stop_width = 2.0 * atr  # UPDATED: 1.5 ATR -> 2.0 ATR

        if stop_width == 0 or atr == 0:
            logger.warning("ATR is zero. Cannot calculate position size.")
            return 0, 0, 0

        # Calculate base size
        risk_amount = self.current_equity * risk_per_trade
        num_coins = risk_amount / stop_width
        position_size_usd = num_coins * price

        # Apply multipliers (Spec 5.3: Confidence, Spec 8.1/8.3: Size reduction)
        final_size_usd = position_size_usd * confidence * size_multiplier

        # Enforce margin cap (Spec 6.1: Max 25% margin per position)
        max_notional = (self.current_equity * self.max_margin_per_position) * self.leverage

        if final_size_usd > max_notional:
            logger.info(
                f"Position size ${final_size_usd:,.2f} exceeds margin cap. "
                f"Capping to ${max_notional:,.2f} (25% margin × 3× leverage)."
            )
            final_size_usd = max_notional

        # Calculate final values
        final_coins = final_size_usd / price
        required_margin = final_size_usd / self.leverage

        logger.debug(
            f"Position sizing: Price=${price:.2f}, ATR={atr:.2f}, "
            f"Confidence={confidence:.2f}, Multiplier={size_multiplier:.2f} → "
            f"Size=${final_size_usd:,.2f} ({final_coins:.6f} coins), Margin=${required_margin:,.2f}"
        )

        return final_coins, final_size_usd, required_margin

    def get_stop_loss_price(self, entry_price, direction, atr):
        """
        Calculate initial stop loss price.

        UPDATED: 2.0 × ATR(14) stop width (was 1.5 ATR)

        Args:
            entry_price: Entry price
            direction: 'LONG' or 'SHORT'
            atr: Current ATR(14)

        Returns:
            float: Stop loss price
        """
        stop_width = 2.0 * atr  # UPDATED: 1.5 -> 2.0

        if direction == "LONG":
            stop_price = entry_price - stop_width
        else:  # SHORT
            stop_price = entry_price + stop_width

        logger.debug(f"{direction} Stop: Entry=${entry_price:.2f}, ATR={atr:.2f} → Stop=${stop_price:.2f}")
        return stop_price

    def check_liquidation_buffer(self, entry_price, liquidation_price, atr):
        """
        Verify liquidation price buffer is sufficient.

        Spec 7.6 (281-284): Minimum 3 × ATR buffer from entry

        Args:
            entry_price: Position entry price
            liquidation_price: Calculated liquidation price
            atr: Current ATR(14)

        Returns:
            tuple: (bool sufficient, float actual_buffer_atr)
        """
        buffer_distance = abs(entry_price - liquidation_price)
        buffer_atr = buffer_distance / atr if atr > 0 else 0

        min_buffer_atr = 3.0
        sufficient = buffer_atr >= min_buffer_atr

        if not sufficient:
            logger.warning(
                f"Liquidation buffer INSUFFICIENT: {buffer_atr:.2f} ATR < {min_buffer_atr} ATR required. "
                f"Entry=${entry_price:.2f}, Liq=${liquidation_price:.2f}, ATR={atr:.2f}"
            )
        else:
            logger.debug(f"Liquidation buffer OK: {buffer_atr:.2f} ATR >= {min_buffer_atr} ATR")

        return sufficient, buffer_atr

    def check_margin_ratio_risk(self, position_margin_ratio):
        """
        Check if position margin ratio requires defensive action.

        Spec 8.6 (317): Margin ratio > 80% → Reduce position by 50%

        Args:
            position_margin_ratio: Current margin ratio (0-1)

        Returns:
            tuple: (bool reduce_required, str action)
        """
        if position_margin_ratio > 0.80:
            logger.error(
                f"CRITICAL: Position margin ratio {position_margin_ratio:.1%} > 80%. "
                f"IMMEDIATE 50% REDUCTION REQUIRED."
            )
            return True, "REDUCE_50_PCT"

        return False, "OK"

    def _get_current_drawdown(self):
        """Calculate current drawdown from peak equity"""
        if self.max_equity == 0:
            return 0.0
        return (self.max_equity - self.current_equity) / self.max_equity

    def _get_daily_loss_pct(self):
        """Calculate today's loss as percentage of starting equity"""
        if self.daily_start_equity == 0:
            return 0.0
        daily_change = self.current_equity - self.daily_start_equity
        if daily_change >= 0:
            return 0.0  # No loss
        return abs(daily_change) / self.daily_start_equity

    def record_trade_result(self, is_win):
        """
        Record trade result for consecutive loss tracking.

        Args:
            is_win: True if trade was profitable, False if loss
        """
        if is_win:
            if self.consecutive_losses > 0:
                logger.info(f"Winning trade. Resetting consecutive loss counter from {self.consecutive_losses} to 0.")
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            logger.warning(f"Losing trade. Consecutive losses now: {self.consecutive_losses}")

    def reset_consecutive_losses(self):
        """Reset consecutive loss counter (called on daily reset or manual intervention)"""
        if self.consecutive_losses > 0:
            logger.info(f"Resetting consecutive losses from {self.consecutive_losses} to 0.")
            self.consecutive_losses = 0

    def get_risk_summary(self):
        """Get current risk metrics summary for logging"""
        return {
            'current_equity': self.current_equity,
            'max_equity': self.max_equity,
            'drawdown': self._get_current_drawdown(),
            'daily_loss_pct': self._get_daily_loss_pct(),
            'daily_start_equity': self.daily_start_equity,
            'current_date': self.current_date,
            'consecutive_losses': self.consecutive_losses
        }
