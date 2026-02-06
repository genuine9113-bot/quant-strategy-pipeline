"""
Regime Classification Engine for RAAA Strategy

Classifies market into 4 states based on 4H data:
- Trending Bull
- Trending Bear
- High Volatility Chop
- Low Volatility Squeeze
- Undefined (No-Trade Zone)

Handles regime transitions with cooldown management.
"""

from enum import Enum
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import logging

# Setup module-specific logger
logger = logging.getLogger("RegimeEngine")
logger.setLevel(logging.DEBUG)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# File handler
try:
    file_handler = logging.FileHandler('logs/regime.log')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(console_formatter)
    logger.addHandler(file_handler)
except Exception:
    pass  # If logs directory doesn't exist, skip file logging

logger.addHandler(console_handler)


class MarketRegime(Enum):
    """Market regime states"""
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    CHOP_HIGH_VOL = "CHOP_HIGH_VOL"
    SQUEEZE_LOW_VOL = "SQUEEZE_LOW_VOL"
    UNDEFINED = "UNDEFINED"


class RegimeEngine:
    """
    Stateful regime classification engine with transition detection and cooldown management.

    Spec References:
    - Section 3: Regime Classification
    - Section 3 (lines 76-84): Regime Transition Rules
    - CLAUDE.md (lines 111-115): Cooldown 8 hours after regime change
    """

    def __init__(self):
        """Initialize regime engine with state tracking"""
        self.current_regime = MarketRegime.UNDEFINED
        self.previous_regime = MarketRegime.UNDEFINED
        self.regime_changed_at = None
        self.cooldown_hours = 8  # 2 × 4H bars
        self.in_cooldown = False

        logger.info("RegimeEngine initialized")

    def classify_row(self, row):
        """
        Classify a single row of 4H data into a MarketRegime.

        Args:
            row: DataFrame row or dict with required indicators

        Expected columns:
            - EMA_20, EMA_50, EMA_200
            - ADX_14, PLUS_DI_14, MINUS_DI_14
            - ATR_PCT_RANK_50: ATR percentile (0-100)
            - BB_WIDTH_PCT_RANK_50: BB Width percentile (0-100)

        Returns:
            MarketRegime enum
        """
        try:
            # Extract required indicators
            ema20 = row['EMA_20']
            ema50 = row['EMA_50']
            ema200 = row['EMA_200']
            adx = row['ADX_14']
            plus_di = row['PLUS_DI_14']
            minus_di = row['MINUS_DI_14']
            atr_pct = row['ATR_PCT_RANK_50']
            bb_width_pct = row['BB_WIDTH_PCT_RANK_50']

            # Validate: if any are NaN, return UNDEFINED
            if pd.isna([ema20, ema50, ema200, adx, plus_di, minus_di, atr_pct, bb_width_pct]).any():
                logger.debug("Regime classification returned UNDEFINED due to NaN values")
                return MarketRegime.UNDEFINED

            # State 1: Trending Bull
            # Spec 40-47: EMA(20) > EMA(50) > EMA(200) AND ADX(14) > 25 AND +DI > -DI
            if (ema20 > ema50 > ema200) and (adx > 25) and (plus_di > minus_di):
                return MarketRegime.TRENDING_BULL

            # State 2: Trending Bear
            # Spec 49-56: EMA(20) < EMA(50) < EMA(200) AND ADX(14) > 25 AND -DI > +DI
            if (ema20 < ema50 < ema200) and (adx > 25) and (minus_di > plus_di):
                return MarketRegime.TRENDING_BEAR

            # State 3: High Volatility Chop
            # Spec 58-64: ADX(14) < 20 AND ATR Percentile(50) > 70th
            if (adx < 20) and (atr_pct > 70):
                return MarketRegime.CHOP_HIGH_VOL

            # State 4: Low Volatility Squeeze
            # Spec 66-73: ADX(14) < 20 AND ATR Percentile(50) < 30th AND BB Width Percentile(50) < 20th
            if (adx < 20) and (atr_pct < 30) and (bb_width_pct < 20):
                return MarketRegime.SQUEEZE_LOW_VOL

            # Undefined Regime (No-Trade Zone)
            # Spec 80-84: ADX 20~25 range OR incomplete EMA ordering
            logger.debug(f"Regime UNDEFINED: ADX={adx:.2f}, EMAs=({ema20:.2f}, {ema50:.2f}, {ema200:.2f})")
            return MarketRegime.UNDEFINED

        except KeyError as e:
            logger.warning(f"Missing required column for regime classification: {e}")
            return MarketRegime.UNDEFINED
        except Exception as e:
            logger.error(f"Unexpected error in regime classification: {e}")
            return MarketRegime.UNDEFINED

    def update_regime(self, row, current_time):
        """
        Update current regime and detect transitions.

        Args:
            row: Current 4H bar data
            current_time: datetime object for cooldown tracking

        Returns:
            tuple: (regime, regime_changed, immediate_close_required)
                - regime: Current MarketRegime
                - regime_changed: bool indicating if regime changed
                - immediate_close_required: bool for Bull↔Bear transition
        """
        new_regime = self.classify_row(row)
        regime_changed = False
        immediate_close_required = False

        # Detect regime change
        if new_regime != self.current_regime:
            self.previous_regime = self.current_regime
            self.current_regime = new_regime
            regime_changed = True

            # Spec 77: Trending Bull ↔ Trending Bear requires immediate close
            if self._is_opposite_trending_transition(self.previous_regime, new_regime):
                immediate_close_required = True
                self.regime_changed_at = current_time
                logger.warning(
                    f"CRITICAL REGIME TRANSITION: {self.previous_regime.value} → {new_regime.value} "
                    f"at {current_time}. IMMEDIATE CLOSE ALL POSITIONS REQUIRED."
                )
                # Activate cooldown only for opposite trending transitions
                self.in_cooldown = True
                logger.info(f"Cooldown activated for {self.cooldown_hours} hours until {current_time + timedelta(hours=self.cooldown_hours)}")
            elif new_regime == MarketRegime.UNDEFINED or self.previous_regime == MarketRegime.UNDEFINED:
                # UNDEFINED transitions don't trigger cooldown - it's just a no-trade zone
                logger.debug(
                    f"Regime transition to/from UNDEFINED: {self.previous_regime.value} → {new_regime.value} at {current_time}. "
                    f"No cooldown activated."
                )
            else:
                # Normal regime change between tradeable regimes
                self.regime_changed_at = current_time
                logger.info(
                    f"Regime transition: {self.previous_regime.value} → {new_regime.value} at {current_time}. "
                    f"Existing positions maintained (Stop/TP manages exit)."
                )
                # Activate cooldown for regime changes between tradeable regimes
                self.in_cooldown = True
                logger.info(f"Cooldown activated for {self.cooldown_hours} hours until {current_time + timedelta(hours=self.cooldown_hours)}")

        # Check if cooldown expired
        if self.in_cooldown and self.regime_changed_at:
            time_since_change = (current_time - self.regime_changed_at).total_seconds() / 3600  # hours
            if time_since_change >= self.cooldown_hours:
                self.in_cooldown = False
                logger.info(f"Cooldown expired at {current_time}. New regime strategies now active.")

        return new_regime, regime_changed, immediate_close_required

    def _is_opposite_trending_transition(self, prev_regime, new_regime):
        """
        Check if transition is between opposite trending regimes.

        Spec 77: Trending Bull → Trending Bear or vice versa
        """
        return (
            (prev_regime == MarketRegime.TRENDING_BULL and new_regime == MarketRegime.TRENDING_BEAR) or
            (prev_regime == MarketRegime.TRENDING_BEAR and new_regime == MarketRegime.TRENDING_BULL)
        )

    def can_enter_new_position(self):
        """
        Check if new entries are allowed based on cooldown status.

        Returns:
            tuple: (bool allowed, str reason)
        """
        if self.in_cooldown:
            return False, f"In cooldown period after regime change (expires in {self._get_remaining_cooldown_hours():.1f}h)"

        if self.current_regime == MarketRegime.UNDEFINED:
            return False, "Undefined regime (No-Trade Zone)"

        return True, "OK"

    def _get_remaining_cooldown_hours(self):
        """Calculate remaining cooldown hours"""
        if not self.regime_changed_at:
            return 0

        from datetime import datetime
        elapsed = (datetime.now() - self.regime_changed_at).total_seconds() / 3600
        return max(0, self.cooldown_hours - elapsed)

    def process_dataframe(self, df):
        """
        Apply classification to entire dataframe (for backtesting initialization).

        Args:
            df: DataFrame with 4H data

        Returns:
            Series of MarketRegime enums
        """
        logger.info(f"Processing {len(df)} rows for regime classification")
        regimes = df.apply(self.classify_row, axis=1)

        # Log regime distribution
        regime_counts = regimes.value_counts()
        logger.info(f"Regime distribution:\n{regime_counts}")

        return regimes

    def add_regime_column(self, df):
        """
        Add 'REGIME' column to dataframe.

        Args:
            df: DataFrame with 4H data

        Returns:
            DataFrame with added REGIME column
        """
        df['REGIME'] = self.process_dataframe(df)
        return df

    def get_state_summary(self):
        """Get current regime state summary for logging"""
        return {
            'current_regime': self.current_regime.value,
            'previous_regime': self.previous_regime.value,
            'in_cooldown': self.in_cooldown,
            'regime_changed_at': self.regime_changed_at,
            'remaining_cooldown_hours': self._get_remaining_cooldown_hours() if self.in_cooldown else 0
        }
