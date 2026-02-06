"""
RAAA Strategy Backtesting Engine

Event-driven multi-asset, multi-timeframe backtesting with:
- Leverage 3x (Isolated margin) - UPDATED: was 5x
- Funding rate 8H settlement
- Liquidation simulation
- Multi-asset (BTC + ETH) concurrent positions
- Partial exits and pyramiding support
"""

import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import sys
import os

# Add strategies to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.regime import RegimeEngine, MarketRegime
from strategies.risk_manager import RiskManager
from strategies.raaa_strategy import RAAAStrategy, Position

# Setup module-specific logger
logger = logging.getLogger("BacktestEngine")
logger.setLevel(logging.DEBUG)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# File handler
try:
    os.makedirs('logs', exist_ok=True)
    file_handler = logging.FileHandler('logs/backtest.log', mode='w')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(console_formatter)
    logger.addHandler(file_handler)
except Exception as e:
    logger.warning(f"Could not create file handler: {e}")

logger.addHandler(console_handler)


@dataclass
class Trade:
    """Record of a completed trade"""
    trade_id: int
    symbol: str
    direction: str
    entry_time: datetime
    entry_price: float
    entry_size: float  # coins
    entry_margin: float  # USD
    entry_regime: str
    entry_strategy: str
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl_raw: float = 0.0  # Before costs
    pnl_fees: float = 0.0  # Fee costs
    pnl_funding: float = 0.0  # Funding costs/income
    pnl_net: float = 0.0  # Final P&L
    pnl_pct: float = 0.0  # Percentage return
    profit_r: float = 0.0  # Profit in R multiples
    holding_time_hours: float = 0.0
    is_pyramid: bool = False
    pyramid_level: int = 0
    is_liquidation: bool = False


@dataclass
class EquitySnapshot:
    """Equity curve snapshot"""
    timestamp: datetime
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    cash: float
    margin_used: float
    margin_ratio: float
    active_positions: int
    btc_price: float
    eth_price: float


@dataclass
class FundingEvent:
    """Funding rate settlement event"""
    timestamp: datetime
    symbol: str
    funding_rate: float
    position_size_usd: float
    funding_pnl: float  # Negative = paid, Positive = received


class BacktestEngine:
    """
    Event-driven backtesting engine for RAAA strategy.

    Simulates multi-asset perpetual futures trading with:
    - Multi-timeframe synchronization (15m, 1H, 4H)
    - Regime-based strategy execution
    - Leverage 3x with isolated margin (UPDATED: was 5x)
    - 8-hour funding rate settlement
    - Liquidation simulation
    - Partial exits and pyramiding
    """

    def __init__(
        self,
        initial_capital=100000,
        leverage=3,
        fee_rate=0.0005,
        slippage_rate=0.0002,
        start_date="2025-03-06",
        end_date="2026-02-01"
    ):
        """
        Initialize backtest engine.

        Args:
            initial_capital: Starting USDT capital
            leverage: Leverage multiplier (3x, UPDATED: was 5x)
            fee_rate: Trading fee per trade (0.05% = OKX Taker)
            slippage_rate: Slippage per trade (0.02%)
            start_date: Backtest start date (YYYY-MM-DD)
            end_date: Backtest end date (YYYY-MM-DD)
        """
        # Capital management
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.equity = initial_capital
        self.leverage = leverage

        # Cost structure
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.total_cost_rate = fee_rate + slippage_rate  # 0.07%

        # Date range
        self.start_date = pd.to_datetime(start_date)
        self.end_date = pd.to_datetime(end_date)

        # Initialize strategy components
        self.risk_manager = RiskManager(initial_equity=initial_capital)
        self.regime_engine = RegimeEngine()
        self.strategy = RAAAStrategy(self.risk_manager, self.regime_engine)

        # Trade tracking
        self.trades = []
        self.trade_id_counter = 1
        self.equity_curve = []
        self.funding_events = []

        # Liquidation tracking
        self.liquidation_prices = {}  # {symbol: liquidation_price}
        self.mmr = 0.005  # OKX Maintenance Margin Ratio (0.5%)

        # Performance tracking
        self.total_fees_paid = 0.0
        self.total_funding_paid = 0.0
        self.total_funding_received = 0.0

        logger.info(
            f"BacktestEngine initialized: Capital=${initial_capital:,}, "
            f"Leverage={leverage}x, Fees={fee_rate:.4f}, Slippage={slippage_rate:.4f}, "
            f"Period={start_date} to {end_date}"
        )

    def run(
        self,
        btc_15m: pd.DataFrame,
        btc_1h: pd.DataFrame,
        btc_4h: pd.DataFrame,
        eth_15m: pd.DataFrame,
        eth_1h: pd.DataFrame,
        eth_4h: pd.DataFrame,
        funding_btc: pd.DataFrame,
        funding_eth: pd.DataFrame
    ) -> Dict:
        """
        Execute full backtest simulation.

        Args:
            btc_15m, btc_1h, btc_4h: BTC data at different timeframes
            eth_15m, eth_1h, eth_4h: ETH data at different timeframes
            funding_btc, funding_eth: Funding rate data

        Returns:
            dict: Comprehensive backtest results
        """
        logger.info("=" * 80)
        logger.info("STARTING BACKTEST SIMULATION")
        logger.info("=" * 80)

        # Filter data by date range
        btc_15m = btc_15m[self.start_date:self.end_date].copy()
        btc_1h = btc_1h[self.start_date:self.end_date].copy()
        btc_4h = btc_4h[self.start_date:self.end_date].copy()
        eth_15m = eth_15m[self.start_date:self.end_date].copy()
        eth_1h = eth_1h[self.start_date:self.end_date].copy()
        eth_4h = eth_4h[self.start_date:self.end_date].copy()

        # Convert funding to dict for fast lookup
        funding_btc_dict = funding_btc.to_dict('index') if not funding_btc.empty else {}
        funding_eth_dict = funding_eth.to_dict('index') if not funding_eth.empty else {}

        logger.info(f"BTC 15m bars: {len(btc_15m)}, ETH 15m bars: {len(eth_15m)}")
        logger.info(f"BTC Funding events: {len(funding_btc_dict)}, ETH Funding events: {len(funding_eth_dict)}")

        # Multi-timeframe index tracking
        idx_btc_1h = 0
        idx_btc_4h = 0
        idx_eth_1h = 0
        idx_eth_4h = 0

        total_bars = len(btc_15m)
        progress_interval = 1000

        # Main event loop: iterate through 15m bars
        for bar_count, (current_time, row15m_btc) in enumerate(btc_15m.iterrows(), 1):

            # Progress logging
            if bar_count % progress_interval == 0:
                logger.info(
                    f"Progress: {bar_count}/{total_bars} bars ({bar_count/total_bars*100:.1f}%), "
                    f"Equity=${self.equity:,.2f}, Active Positions={len(self.strategy.positions)}"
                )

            # Get corresponding ETH 15m bar
            if current_time not in eth_15m.index:
                logger.debug(f"Skipping {current_time}: No ETH 15m data")
                continue
            row15m_eth = eth_15m.loc[current_time]

            # 1. MULTI-TIMEFRAME SYNCHRONIZATION
            row1h_btc, idx_btc_1h = self._sync_timeframe(current_time, btc_1h, idx_btc_1h)
            row4h_btc, idx_btc_4h = self._sync_timeframe(current_time, btc_4h, idx_btc_4h)
            row1h_eth, idx_eth_1h = self._sync_timeframe(current_time, eth_1h, idx_eth_1h)
            row4h_eth, idx_eth_4h = self._sync_timeframe(current_time, eth_4h, idx_eth_4h)

            if row1h_btc is None or row4h_btc is None or row1h_eth is None or row4h_eth is None:
                continue

            # 2. REGIME UPDATE (only on 4H bar close)
            if self._is_4h_close(current_time):
                regime, regime_changed, immediate_close = self.regime_engine.update_regime(row4h_btc, current_time)

                if immediate_close:
                    logger.warning(f"OPPOSITE REGIME TRANSITION at {current_time}. Closing all positions immediately.")
                    self._close_all_positions(current_time, row15m_btc['close'], row15m_eth['close'], "Opposite Regime Transition")
            else:
                # Keep current regime for non-4H bars
                regime = self.regime_engine.current_regime

            # 3. FUNDING SETTLEMENT (00:00, 08:00, 16:00 UTC)
            if self._should_apply_funding(current_time):
                self._check_and_apply_funding(
                    current_time,
                    row15m_btc['close'],
                    row15m_eth['close'],
                    funding_btc_dict,
                    funding_eth_dict
                )

            # 3.5. DAILY RESET (00:00 UTC) - Reset consecutive loss counter
            if current_time.hour == 0 and current_time.minute == 0:
                self.risk_manager.reset_consecutive_losses()

            # 4. LIQUIDATION CHECK (every 15m bar)
            self._check_liquidations(current_time, row15m_btc, row15m_eth)

            # 5. EXIT SIGNAL CHECK (active positions)
            self._check_exits(current_time, row15m_btc, row15m_eth)

            # 6. ENTRY SIGNAL CHECK (new or pyramiding)
            self._check_entry_signals(
                current_time,
                row15m_btc, row1h_btc, row4h_btc,
                row15m_eth, row1h_eth, row4h_eth,
                funding_btc_dict, funding_eth_dict
            )

            # 7. UPDATE EQUITY CURVE
            self._update_equity_curve(current_time, row15m_btc['close'], row15m_eth['close'])

        # Generate final report
        logger.info("=" * 80)
        logger.info("BACKTEST SIMULATION COMPLETED")
        logger.info("=" * 80)

        return self.generate_report()

    def _sync_timeframe(self, current_time: datetime, data_tf: pd.DataFrame, current_idx: int) -> Tuple[Optional[pd.Series], int]:
        """
        Synchronize higher timeframe data to current 15m bar.

        Returns the most recent closed bar from higher TF.

        Args:
            current_time: Current 15m bar timestamp
            data_tf: Higher timeframe DataFrame
            current_idx: Current index in data_tf

        Returns:
            tuple: (row, new_index)
        """
        # Advance index while next bar is still in the past
        while current_idx < len(data_tf) - 1 and data_tf.index[current_idx + 1] <= current_time:
            current_idx += 1

        # Return current row (most recent closed bar)
        if current_idx < len(data_tf) and data_tf.index[current_idx] <= current_time:
            return data_tf.iloc[current_idx], current_idx

        return None, current_idx

    def _is_4h_close(self, current_time: datetime) -> bool:
        """Check if current time is a 4H bar close (00:00, 04:00, 08:00, etc.)"""
        return current_time.hour % 4 == 0 and current_time.minute == 0

    def _should_apply_funding(self, current_time: datetime) -> bool:
        """Check if funding settlement time (00:00, 08:00, 16:00 UTC)"""
        return current_time.hour in [0, 8, 16] and current_time.minute == 0

    def _get_signal_without_regime_update(
        self,
        row1h, row15m, symbol, current_time,
        regime, btc_eth_correlation, btc_position_status, funding_rate
    ):
        """
        Get trading signal without triggering regime update.
        This is used during backtesting to avoid re-classifying regime on every bar.
        """
        # Check if in cooldown
        if self.strategy._is_in_cooldown(symbol, current_time):
            return {
                'signal': 'HOLD',
                'reason': f"In cooldown until {self.strategy.cooldowns[symbol]}",
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

        # Get active position
        active_position = self.strategy.positions.get(symbol)

        # Check pyramiding opportunity
        if active_position and not active_position.partial_tp_done:
            from strategies.regime import MarketRegime
            if regime in [MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR]:
                pyramid_signal = self.strategy._check_pyramiding(active_position, row15m['close'], row15m['ATR_14'])
                if pyramid_signal:
                    return {
                        'signal': pyramid_signal,
                        'reason': f"Pyramiding at {active_position.get_profit_r(row15m['close']):.2f}R profit",
                        'regime': regime,
                        'confidence': 1.0
                    }

        # Dispatch to regime-specific strategies
        from strategies.regime import MarketRegime
        if regime == MarketRegime.TRENDING_BULL:
            signal, reason = self.strategy._trending_bull_strategy(row1h, row15m, active_position, symbol, btc_position_status)
        elif regime == MarketRegime.TRENDING_BEAR:
            signal, reason = self.strategy._trending_bear_strategy(row1h, row15m, active_position)
        elif regime == MarketRegime.CHOP_HIGH_VOL:
            signal, reason = self.strategy._chop_strategy(row1h, row15m, active_position)
        elif regime == MarketRegime.SQUEEZE_LOW_VOL:
            signal, reason = self.strategy._squeeze_strategy(row1h, row15m, active_position)
        else:
            signal, reason = "HOLD", "Undefined Regime"

        # Calculate confidence
        confidence = self.strategy._calculate_confidence(
            signal, symbol, btc_eth_correlation, funding_rate, None
        )

        return {
            'signal': signal,
            'reason': reason,
            'regime': regime,
            'confidence': confidence
        }

    def _check_entry_signals(
        self,
        current_time: datetime,
        row15m_btc, row1h_btc, row4h_btc,
        row15m_eth, row1h_eth, row4h_eth,
        funding_btc_dict, funding_eth_dict
    ):
        """
        Check entry signals for both BTC and ETH.
        """
        # Get BTC-ETH correlation from 4H data
        btc_eth_correlation = row4h_btc.get('BTC_ETH_CORR_48H')

        # BTC position status for ETH entry check
        btc_position = self.strategy.positions.get('BTC')
        btc_position_status = {
            'has_long_position': btc_position is not None and btc_position.direction == 'LONG'
        } if btc_position else None

        # Get current funding rates
        funding_btc = self._get_current_funding(current_time, funding_btc_dict)
        funding_eth = self._get_current_funding(current_time, funding_eth_dict)

        # Get current regime (without triggering update)
        current_regime = self.regime_engine.current_regime

        # Check BTC signals (pass regime directly to avoid re-updating)
        signal_btc = self._get_signal_without_regime_update(
            row1h_btc, row15m_btc, 'BTC', current_time,
            current_regime, btc_eth_correlation, None, funding_btc
        )

        if signal_btc['signal'] != 'HOLD':
            self._execute_entry('BTC', signal_btc, row15m_btc, current_time, btc_eth_correlation, funding_btc)

        # Check ETH signals
        signal_eth = self._get_signal_without_regime_update(
            row1h_eth, row15m_eth, 'ETH', current_time,
            current_regime, btc_eth_correlation, btc_position_status, funding_eth
        )

        if signal_eth['signal'] != 'HOLD':
            self._execute_entry('ETH', signal_eth, row15m_eth, current_time, btc_eth_correlation, funding_eth)

    def _execute_entry(
        self,
        symbol: str,
        signal_dict: Dict,
        row15m: pd.Series,
        current_time: datetime,
        btc_eth_correlation: Optional[float],
        funding_rate: Optional[float]
    ):
        """
        Execute entry (new position or pyramiding).
        """
        signal = signal_dict['signal']
        direction = 'LONG' if 'LONG' in signal else 'SHORT'
        is_pyramid = 'PYRAMID' in signal

        entry_price = row15m['close']
        atr = row15m['ATR_14']
        atr_percentile = row15m.get('ATR_PCT_RANK_50', 50)

        # Get active position if exists
        active_position = self.strategy.positions.get(symbol)

        # PYRAMIDING EXECUTION
        if is_pyramid and active_position:
            # Calculate pyramid size (50% of original)
            pyramid_size = active_position.original_size * 0.5
            pyramid_size_usd = pyramid_size * entry_price
            pyramid_margin = pyramid_size_usd / self.leverage

            # Check if we have enough cash
            if self.cash < pyramid_margin:
                logger.warning(f"Insufficient cash for {symbol} pyramid: Need ${pyramid_margin:,.2f}, Have ${self.cash:,.2f}")
                return

            # Apply costs
            entry_cost = self._apply_costs(pyramid_size_usd)

            # Calculate liquidation price
            total_margin = active_position.entry_margin + pyramid_margin  # Approximation
            total_size_usd = (active_position.size + pyramid_size) * entry_price
            liquidation_price = self._calculate_liquidation_price(
                active_position.current_avg_price,  # Use current avg
                direction,
                total_margin,
                total_size_usd
            )

            # Check liquidation buffer
            buffer_ok, buffer_atr = self.risk_manager.check_liquidation_buffer(
                entry_price, liquidation_price, atr
            )

            if not buffer_ok:
                logger.warning(f"Pyramid rejected for {symbol}: Insufficient liquidation buffer ({buffer_atr:.2f} ATR)")
                return

            # Execute pyramid
            active_position.add_pyramid(entry_price, pyramid_size, atr)
            self.liquidation_prices[symbol] = liquidation_price

            # Deduct cash
            self.cash -= (pyramid_margin + entry_cost)
            self.total_fees_paid += entry_cost

            # Create trade record (partial, will be completed on exit)
            trade = Trade(
                trade_id=self.trade_id_counter,
                symbol=symbol,
                direction=direction,
                entry_time=current_time,
                entry_price=entry_price,
                entry_size=pyramid_size,
                entry_margin=pyramid_margin,
                entry_regime=signal_dict['regime'].value,
                entry_strategy=signal_dict['reason'],
                is_pyramid=True,
                pyramid_level=active_position.pyramid_count
            )
            self.trades.append(trade)
            self.trade_id_counter += 1

            logger.info(
                f"PYRAMID EXECUTED: {symbol} {direction} @ ${entry_price:.2f}, "
                f"Size={pyramid_size:.6f} ({pyramid_size_usd:,.2f} USD), Margin=${pyramid_margin:,.2f}, "
                f"Liq=${liquidation_price:.2f}"
            )
            return

        # NEW POSITION ENTRY
        # Validate entry with risk manager
        current_margin_used = sum(
            pos.size * entry_price / self.leverage
            for pos in self.strategy.positions.values()
        )

        allow, size_multiplier, risk_reason = self.risk_manager.validate_entry(
            signal_type=signal,
            symbol=symbol,
            direction=direction,
            active_positions_count=len(self.strategy.positions),
            current_margin_usage=current_margin_used,
            atr_percentile=atr_percentile,
            btc_eth_correlation=btc_eth_correlation,
            funding_rate=funding_rate
        )

        if not allow:
            logger.debug(f"{symbol} entry rejected: {risk_reason}")
            return

        # Calculate position size
        confidence = signal_dict['confidence']
        num_coins, position_size_usd, required_margin = self.risk_manager.calculate_position_size(
            price=entry_price,
            atr=atr,
            confidence=confidence,
            size_multiplier=size_multiplier
        )

        if num_coins == 0 or position_size_usd == 0:
            logger.warning(f"{symbol} entry rejected: Position size is zero")
            return

        # Check if we have enough cash
        if self.cash < required_margin:
            logger.warning(f"Insufficient cash for {symbol} entry: Need ${required_margin:,.2f}, Have ${self.cash:,.2f}")
            return

        # Apply entry costs
        entry_cost = self._apply_costs(position_size_usd)

        # Calculate liquidation price
        liquidation_price = self._calculate_liquidation_price(
            entry_price, direction, required_margin, position_size_usd
        )

        # Check liquidation buffer
        buffer_ok, buffer_atr = self.risk_manager.check_liquidation_buffer(
            entry_price, liquidation_price, atr
        )

        if not buffer_ok:
            logger.warning(f"Entry rejected for {symbol}: Insufficient liquidation buffer ({buffer_atr:.2f} ATR)")
            return

        # Open position in strategy
        position = self.strategy.open_position(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            size=num_coins,
            entry_time=current_time,
            atr=atr,
            regime=signal_dict['regime'],
            strategy_type=signal_dict['reason']
        )

        # Store entry margin in position (for tracking)
        position.entry_margin = required_margin

        # Store liquidation price
        self.liquidation_prices[symbol] = liquidation_price

        # Deduct cash
        self.cash -= (required_margin + entry_cost)
        self.total_fees_paid += entry_cost

        # Update risk manager
        self.risk_manager.update_equity(self.equity, current_time)

        # Create trade record
        trade = Trade(
            trade_id=self.trade_id_counter,
            symbol=symbol,
            direction=direction,
            entry_time=current_time,
            entry_price=entry_price,
            entry_size=num_coins,
            entry_margin=required_margin,
            entry_regime=signal_dict['regime'].value,
            entry_strategy=signal_dict['reason']
        )
        self.trades.append(trade)
        self.trade_id_counter += 1

        logger.info(
            f"ENTRY EXECUTED: {symbol} {direction} @ ${entry_price:.2f}, "
            f"Size={num_coins:.6f} ({position_size_usd:,.2f} USD), Margin=${required_margin:,.2f}, "
            f"Stop=${position.stop_loss:.2f}, Liq=${liquidation_price:.2f}, "
            f"Confidence={confidence:.2f}, Multiplier={size_multiplier:.2f}"
        )

    def _check_exits(self, current_time: datetime, row15m_btc: pd.Series, row15m_eth: pd.Series):
        """
        Check exit conditions for all active positions.
        """
        positions_to_check = list(self.strategy.positions.items())

        for symbol, position in positions_to_check:
            # Get current row
            row15m = row15m_btc if symbol == 'BTC' else row15m_eth

            # Check exit signals
            exit_signal = self.strategy.check_exits(position, row15m, current_time)

            if exit_signal:
                exit_price = row15m['close']
                self._execute_exit(symbol, position, exit_signal, exit_price, current_time)

    def _execute_exit(
        self,
        symbol: str,
        position: Position,
        exit_dict: Dict,
        exit_price: float,
        exit_time: datetime
    ):
        """
        Execute exit (full or partial).
        """
        exit_pct = exit_dict['exit_pct']
        reason = exit_dict['reason']

        # Close position in strategy
        closed_size, pnl_raw, pnl_pct = self.strategy.close_position(
            symbol=symbol,
            exit_price=exit_price,
            exit_time=exit_time,
            reason=reason,
            exit_pct=exit_pct
        )

        if closed_size == 0:
            return

        # Calculate costs
        closed_size_usd = closed_size * exit_price
        exit_cost = self._apply_costs(closed_size_usd)
        self.total_fees_paid += exit_cost

        # Calculate net P&L
        pnl_net = pnl_raw - exit_cost

        # Return margin to cash
        margin_returned = (closed_size_usd / self.leverage) * exit_pct
        self.cash += margin_returned + pnl_net

        # Update equity
        self.equity = self.cash + self._calculate_unrealized_pnl()

        # Update risk manager
        self.risk_manager.update_equity(self.equity, exit_time)

        # Track consecutive losses (NEW: only for full exits)
        if exit_pct >= 1.0:
            is_win = pnl_net > 0
            self.risk_manager.record_trade_result(is_win)

        # Find matching trade(s) and update
        matching_trades = [
            t for t in self.trades
            if t.symbol == symbol and t.exit_time is None
            and t.direction == position.direction
        ]

        if matching_trades:
            for trade in matching_trades[:int(1/exit_pct) or 1]:  # Update proportional trades
                trade.exit_time = exit_time
                trade.exit_price = exit_price
                trade.exit_reason = reason
                trade.pnl_raw = pnl_raw / len(matching_trades)
                trade.pnl_fees = exit_cost / len(matching_trades)
                trade.pnl_net = pnl_net / len(matching_trades)
                trade.pnl_pct = pnl_pct
                trade.profit_r = position.get_profit_r(exit_price) if position else 0
                trade.holding_time_hours = (exit_time - trade.entry_time).total_seconds() / 3600

        # Remove liquidation price if full close
        if exit_pct >= 1.0 and symbol in self.liquidation_prices:
            del self.liquidation_prices[symbol]

        logger.info(
            f"EXIT EXECUTED: {symbol} {position.direction}, "
            f"Exit=${exit_price:.2f}, Size={closed_size:.6f} ({exit_pct:.0%}), "
            f"P&L=${pnl_net:,.2f} ({pnl_pct:+.2f}%), Reason={reason}"
        )

    def _close_all_positions(
        self,
        current_time: datetime,
        btc_price: float,
        eth_price: float,
        reason: str
    ):
        """
        Immediately close all positions (for regime transitions).
        """
        positions_to_close = list(self.strategy.positions.items())

        for symbol, position in positions_to_close:
            exit_price = btc_price if symbol == 'BTC' else eth_price
            exit_dict = {'exit_pct': 1.0, 'reason': reason, 'action': 'REGIME_EXIT'}
            self._execute_exit(symbol, position, exit_dict, exit_price, current_time)

    def _check_liquidations(self, current_time: datetime, row15m_btc: pd.Series, row15m_eth: pd.Series):
        """
        Check if any positions should be liquidated.
        """
        positions_to_check = list(self.strategy.positions.items())

        for symbol, position in positions_to_check:
            if symbol not in self.liquidation_prices:
                continue

            liquidation_price = self.liquidation_prices[symbol]
            row15m = row15m_btc if symbol == 'BTC' else row15m_eth

            # Check if liquidation price was touched
            liquidated = False
            if position.direction == 'LONG':
                if row15m['low'] <= liquidation_price:
                    liquidated = True
            else:  # SHORT
                if row15m['high'] >= liquidation_price:
                    liquidated = True

            if liquidated:
                logger.error(
                    f"LIQUIDATION: {symbol} {position.direction} @ ${liquidation_price:.2f}, "
                    f"Entry=${position.entry_price:.2f}, Size={position.size:.6f}"
                )

                # Liquidation = 100% margin loss
                margin_lost = position.entry_margin
                self.equity -= margin_lost
                self.cash = max(0, self.cash)  # Ensure non-negative

                # Update trade records
                matching_trades = [
                    t for t in self.trades
                    if t.symbol == symbol and t.exit_time is None
                    and t.direction == position.direction
                ]

                for trade in matching_trades:
                    trade.exit_time = current_time
                    trade.exit_price = liquidation_price
                    trade.exit_reason = "LIQUIDATION"
                    trade.pnl_net = -trade.entry_margin
                    trade.pnl_pct = -100.0
                    trade.is_liquidation = True
                    trade.holding_time_hours = (current_time - trade.entry_time).total_seconds() / 3600

                # Remove position
                del self.strategy.positions[symbol]
                del self.liquidation_prices[symbol]

                # Update risk manager
                self.risk_manager.update_equity(self.equity, current_time)

                # Track consecutive losses (NEW: liquidation is always a loss)
                self.risk_manager.record_trade_result(is_win=False)

    def _check_and_apply_funding(
        self,
        current_time: datetime,
        btc_price: float,
        eth_price: float,
        funding_btc_dict: Dict,
        funding_eth_dict: Dict
    ):
        """
        Apply 8-hour funding rate settlement to open positions.
        """
        for symbol, position in self.strategy.positions.items():
            # Get funding rate
            if symbol == 'BTC':
                funding_rate = self._get_current_funding(current_time, funding_btc_dict)
                current_price = btc_price
            else:
                funding_rate = self._get_current_funding(current_time, funding_eth_dict)
                current_price = eth_price

            if funding_rate is None:
                logger.debug(f"No funding rate data for {symbol} at {current_time}")
                continue

            # Calculate funding P&L
            position_size_usd = position.size * current_price

            if position.direction == 'LONG':
                # Long pays funding if funding > 0
                funding_pnl = -position_size_usd * funding_rate
            else:  # SHORT
                # Short receives funding if funding > 0
                funding_pnl = position_size_usd * funding_rate

            # Apply to equity
            self.cash += funding_pnl
            self.equity += funding_pnl

            # Track funding
            if funding_pnl < 0:
                self.total_funding_paid += abs(funding_pnl)
            else:
                self.total_funding_received += funding_pnl

            # Record funding event
            funding_event = FundingEvent(
                timestamp=current_time,
                symbol=symbol,
                funding_rate=funding_rate,
                position_size_usd=position_size_usd,
                funding_pnl=funding_pnl
            )
            self.funding_events.append(funding_event)

            # Update trade records
            matching_trades = [
                t for t in self.trades
                if t.symbol == symbol and t.exit_time is None
                and t.direction == position.direction
            ]
            for trade in matching_trades:
                trade.pnl_funding += funding_pnl / len(matching_trades)

            logger.debug(
                f"Funding applied: {symbol} {position.direction}, Rate={funding_rate:+.4f}, "
                f"Size=${position_size_usd:,.2f}, P&L=${funding_pnl:+,.2f}"
            )

    def _get_current_funding(self, current_time: datetime, funding_dict: Dict) -> Optional[float]:
        """
        Get funding rate for current time (or most recent past).
        """
        if not funding_dict:
            return None

        # Try exact match
        if current_time in funding_dict:
            return funding_dict[current_time].get('funding_rate', 0)

        # Find most recent past funding
        past_times = [t for t in funding_dict.keys() if t <= current_time]
        if past_times:
            most_recent = max(past_times)
            return funding_dict[most_recent].get('funding_rate', 0)

        return None

    def _calculate_liquidation_price(
        self,
        entry_price: float,
        direction: str,
        margin: float,
        size_usd: float
    ) -> float:
        """
        Calculate liquidation price for isolated margin position.

        Formula:
            max_loss = margin - (size_usd × MMR)
            liquidation_price = entry_price ± (max_loss / num_coins)
        """
        if size_usd == 0:
            return 0

        num_coins = size_usd / entry_price
        max_loss = margin - (size_usd * self.mmr)

        if direction == 'LONG':
            liquidation_price = entry_price - (max_loss / num_coins)
        else:  # SHORT
            liquidation_price = entry_price + (max_loss / num_coins)

        return max(0, liquidation_price)  # Ensure non-negative

    def _apply_costs(self, size_usd: float) -> float:
        """
        Calculate trading costs (fees + slippage).

        Returns:
            float: Total cost in USD
        """
        return size_usd * self.total_cost_rate

    def _calculate_unrealized_pnl(self) -> float:
        """
        Calculate total unrealized P&L from open positions.
        """
        # This is a placeholder - in reality we'd use current prices
        # For simplicity, we'll track this in equity updates
        return 0

    def _update_equity_curve(self, current_time: datetime, btc_price: float, eth_price: float):
        """
        Record equity curve snapshot.
        """
        # Calculate unrealized P&L
        unrealized_pnl = 0
        margin_used = 0

        for symbol, position in self.strategy.positions.items():
            current_price = btc_price if symbol == 'BTC' else eth_price

            if position.direction == 'LONG':
                pnl_per_coin = current_price - position.current_avg_price
            else:
                pnl_per_coin = position.current_avg_price - current_price

            unrealized_pnl += pnl_per_coin * position.size
            margin_used += (position.size * current_price) / self.leverage

        # Update equity
        realized_pnl = self.equity - self.initial_capital - unrealized_pnl
        self.equity = self.cash + unrealized_pnl

        # Calculate margin ratio
        margin_ratio = margin_used / self.equity if self.equity > 0 else 0

        # Record snapshot
        snapshot = EquitySnapshot(
            timestamp=current_time,
            equity=self.equity,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            cash=self.cash,
            margin_used=margin_used,
            margin_ratio=margin_ratio,
            active_positions=len(self.strategy.positions),
            btc_price=btc_price,
            eth_price=eth_price
        )
        self.equity_curve.append(snapshot)

    def generate_report(self) -> Dict:
        """
        Generate comprehensive backtest report.
        """
        logger.info("Generating backtest report...")

        # Convert to DataFrames
        trades_df = pd.DataFrame([vars(t) for t in self.trades if t.exit_time is not None])
        equity_df = pd.DataFrame([vars(s) for s in self.equity_curve])
        funding_df = pd.DataFrame([vars(f) for f in self.funding_events])

        # Save to CSV
        os.makedirs('results', exist_ok=True)
        trades_df.to_csv('results/trade_log.csv', index=False)
        equity_df.to_csv('results/equity_curve.csv', index=False)

        # Calculate metrics
        report = {
            'summary': self._calculate_summary_metrics(trades_df, equity_df),
            'trades': self._calculate_trade_metrics(trades_df),
            'funding': self._calculate_funding_metrics(funding_df),
            'regime': self._calculate_regime_metrics(trades_df),
            'assets': self._calculate_asset_metrics(trades_df)
        }

        # Generate markdown report
        self._save_markdown_report(report)

        logger.info("Report generated successfully")
        return report

    def _calculate_summary_metrics(self, trades_df: pd.DataFrame, equity_df: pd.DataFrame) -> Dict:
        """Calculate summary metrics"""
        if equity_df.empty:
            return {}

        final_equity = equity_df['equity'].iloc[-1]
        total_return = (final_equity - self.initial_capital) / self.initial_capital

        # Calculate CAGR
        days = (self.end_date - self.start_date).days
        years = days / 365.25
        cagr = (final_equity / self.initial_capital) ** (1 / years) - 1 if years > 0 else 0

        # Max Drawdown
        equity_series = equity_df['equity']
        running_max = equity_series.expanding().max()
        drawdown = (equity_series - running_max) / running_max
        max_drawdown = drawdown.min()

        # Sharpe Ratio (daily returns)
        daily_returns = equity_series.pct_change().dropna()
        if len(daily_returns) > 0 and daily_returns.std() > 0:
            sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
        else:
            sharpe_ratio = 0

        return {
            'initial_capital': self.initial_capital,
            'final_equity': final_equity,
            'total_return': total_return,
            'total_return_pct': total_return * 100,
            'cagr': cagr,
            'cagr_pct': cagr * 100,
            'max_drawdown': max_drawdown,
            'max_drawdown_pct': max_drawdown * 100,
            'sharpe_ratio': sharpe_ratio,
            'calmar_ratio': cagr / abs(max_drawdown) if max_drawdown != 0 else 0,
            'total_fees_paid': self.total_fees_paid,
            'total_funding_paid': self.total_funding_paid,
            'total_funding_received': self.total_funding_received,
            'net_funding': self.total_funding_received - self.total_funding_paid
        }

    def _calculate_trade_metrics(self, trades_df: pd.DataFrame) -> Dict:
        """Calculate trade statistics"""
        if trades_df.empty:
            return {'total_trades': 0}

        winning_trades = trades_df[trades_df['pnl_net'] > 0]
        losing_trades = trades_df[trades_df['pnl_net'] < 0]

        profit_factor = (
            winning_trades['pnl_net'].sum() / abs(losing_trades['pnl_net'].sum())
            if len(losing_trades) > 0 and losing_trades['pnl_net'].sum() != 0
            else 0
        )

        return {
            'total_trades': len(trades_df),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / len(trades_df) if len(trades_df) > 0 else 0,
            'profit_factor': profit_factor,
            'avg_win': winning_trades['pnl_net'].mean() if len(winning_trades) > 0 else 0,
            'avg_loss': losing_trades['pnl_net'].mean() if len(losing_trades) > 0 else 0,
            'avg_holding_time_hours': trades_df['holding_time_hours'].mean(),
            'liquidations': len(trades_df[trades_df['is_liquidation'] == True]),
            'pyramids': len(trades_df[trades_df['is_pyramid'] == True])
        }

    def _calculate_funding_metrics(self, funding_df: pd.DataFrame) -> Dict:
        """Calculate funding statistics"""
        if funding_df.empty:
            return {'total_funding_events': 0}

        return {
            'total_funding_events': len(funding_df),
            'total_funding_paid': self.total_funding_paid,
            'total_funding_received': self.total_funding_received,
            'net_funding_pnl': self.total_funding_received - self.total_funding_paid
        }

    def _calculate_regime_metrics(self, trades_df: pd.DataFrame) -> Dict:
        """Calculate regime-specific metrics"""
        if trades_df.empty:
            return {}

        regime_stats = trades_df.groupby('entry_regime').agg({
            'trade_id': 'count',
            'pnl_net': ['sum', 'mean'],
        }).to_dict()

        return regime_stats

    def _calculate_asset_metrics(self, trades_df: pd.DataFrame) -> Dict:
        """Calculate asset-specific metrics"""
        if trades_df.empty:
            return {}

        asset_stats = {}
        for symbol in ['BTC', 'ETH']:
            symbol_trades = trades_df[trades_df['symbol'] == symbol]
            if len(symbol_trades) > 0:
                winning = symbol_trades[symbol_trades['pnl_net'] > 0]
                asset_stats[symbol] = {
                    'total_trades': len(symbol_trades),
                    'win_rate': len(winning) / len(symbol_trades),
                    'total_pnl': symbol_trades['pnl_net'].sum(),
                    'avg_pnl': symbol_trades['pnl_net'].mean()
                }

        return asset_stats

    def _save_markdown_report(self, report: Dict):
        """Save comprehensive markdown report"""
        with open('results/backtest_report.md', 'w') as f:
            f.write("# RAAA Strategy Backtest Report\n\n")
            f.write(f"**Backtest Period**: {self.start_date.date()} to {self.end_date.date()}\n\n")
            f.write(f"**Initial Capital**: ${report['summary']['initial_capital']:,.2f}\n")
            f.write(f"**Final Equity**: ${report['summary']['final_equity']:,.2f}\n\n")

            f.write("## Summary\n\n")
            f.write(f"- **Total Return**: {report['summary']['total_return_pct']:.2f}%\n")
            f.write(f"- **CAGR**: {report['summary']['cagr_pct']:.2f}%\n")
            f.write(f"- **Max Drawdown**: {report['summary']['max_drawdown_pct']:.2f}%\n")
            f.write(f"- **Sharpe Ratio**: {report['summary']['sharpe_ratio']:.2f}\n")
            f.write(f"- **Calmar Ratio**: {report['summary']['calmar_ratio']:.2f}\n\n")

            f.write("## Performance vs Targets\n\n")
            f.write("| Metric | Target | Achieved | Status |\n")
            f.write("|--------|--------|----------|--------|\n")

            cagr_ok = "✅" if report['summary']['cagr'] > 1.0 else "❌"
            dd_ok = "✅" if report['summary']['max_drawdown'] > -0.30 else "❌"
            pf_ok = "✅" if report['trades'].get('profit_factor', 0) > 1.8 else "❌"
            wr_ok = "✅" if report['trades'].get('win_rate', 0) > 0.45 else "❌"

            f.write(f"| CAGR | > 100% | {report['summary']['cagr_pct']:.2f}% | {cagr_ok} |\n")
            f.write(f"| Max DD | < 30% | {abs(report['summary']['max_drawdown_pct']):.2f}% | {dd_ok} |\n")
            f.write(f"| Profit Factor | > 1.8 | {report['trades'].get('profit_factor', 0):.2f} | {pf_ok} |\n")
            f.write(f"| Win Rate | > 45% | {report['trades'].get('win_rate', 0)*100:.2f}% | {wr_ok} |\n\n")

            f.write("## Trade Statistics\n\n")
            f.write(f"- **Total Trades**: {report['trades']['total_trades']}\n")
            f.write(f"- **Winning Trades**: {report['trades']['winning_trades']}\n")
            f.write(f"- **Losing Trades**: {report['trades']['losing_trades']}\n")
            f.write(f"- **Win Rate**: {report['trades']['win_rate']*100:.2f}%\n")
            f.write(f"- **Profit Factor**: {report['trades'].get('profit_factor', 0):.2f}\n")
            f.write(f"- **Avg Win**: ${report['trades'].get('avg_win', 0):,.2f}\n")
            f.write(f"- **Avg Loss**: ${report['trades'].get('avg_loss', 0):,.2f}\n")
            f.write(f"- **Avg Holding Time**: {report['trades'].get('avg_holding_time_hours', 0):.1f} hours\n")
            f.write(f"- **Liquidations**: {report['trades'].get('liquidations', 0)}\n")
            f.write(f"- **Pyramids**: {report['trades'].get('pyramids', 0)}\n\n")

            f.write("## Funding Impact\n\n")
            f.write(f"- **Total Funding Paid**: ${report['summary']['total_funding_paid']:,.2f}\n")
            f.write(f"- **Total Funding Received**: ${report['summary']['total_funding_received']:,.2f}\n")
            f.write(f"- **Net Funding P&L**: ${report['summary']['net_funding']:,.2f}\n\n")

            f.write("## Conclusion\n\n")
            if cagr_ok == "✅" and dd_ok == "✅" and pf_ok == "✅":
                f.write("✅ **Strategy PASSED**: All key targets achieved.\n")
            else:
                f.write("❌ **Strategy FAILED**: Some targets not met. Further optimization required.\n")

        logger.info("Markdown report saved to results/backtest_report.md")
