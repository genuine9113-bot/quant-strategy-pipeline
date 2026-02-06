"""
BTC Volatility Breakout Strategy - Strategy Logic
진입/청산 로직 및 리스크 관리
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime, timedelta
import pandas as pd
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class Direction(Enum):
    LONG = "long"
    SHORT = "short"


class ExitReason(Enum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TIME_STOP = "time_stop"


class RiskAction(Enum):
    NORMAL = "normal"
    REDUCED_RISK = "reduced_risk"  # DD 1단계: 리스크 50% 축소
    NO_NEW_ENTRY = "no_new_entry"  # DD 2단계: 신규 진입 중지
    HALT = "halt"  # DD 3단계: 전략 정지


@dataclass
class Position:
    """포지션 정보"""
    direction: Direction
    entry_price: float
    entry_time: datetime
    size_usd: float
    sl_price: float
    tp_price: float
    atr_at_entry: float


@dataclass
class Signal:
    """진입 신호"""
    direction: Direction
    trigger_price: float
    entry_price: float
    sl_price: float
    tp_price: float
    size_usd: float
    atr: float


@dataclass
class TradingState:
    """거래 상태 관리"""
    position: Optional[Position] = None
    peak_nav: float = 10000.0
    current_nav: float = 10000.0
    daily_pnl: float = 0.0
    daily_trades: int = 0
    daily_losses: int = 0
    consecutive_losses: int = 0
    consecutive_loss_time: Optional[datetime] = None  # 4연속 손절 발생 시점
    last_exit_time: Optional[datetime] = None
    last_exit_reason: Optional[ExitReason] = None
    today_long_traded: bool = False
    today_short_traded: bool = False
    current_date: Optional[str] = None
    halted: bool = False


class VBStrategy:
    """Volatility Breakout 전략"""

    def __init__(
        self,
        k: float = 0.5,
        sl_atr_mult: float = 1.5,
        tp_atr_mult: float = 2.5,
        time_stop_hours: int = 24,
        ema_period: int = 50,
        range_pct_threshold: float = 20.0,
        funding_threshold: float = 0.30,
        risk_per_trade: float = 0.015,
        max_margin_pct: float = 0.25,
        leverage: float = 3.0,
        initial_capital: float = 10000.0,
        dd_stage1: float = 0.08,
        dd_stage2: float = 0.13,
        dd_stage3: float = 0.18,
        daily_loss_limit: float = 0.025,
        cooldown_sl_hours: int = 2,
        cooldown_time_hours: int = 1,
    ):
        # 핵심 파라미터
        self.k = k
        self.sl_atr_mult = sl_atr_mult
        self.tp_atr_mult = tp_atr_mult
        self.time_stop_hours = time_stop_hours

        # 필터
        self.ema_period = ema_period
        self.range_pct_threshold = range_pct_threshold
        self.funding_threshold = funding_threshold / 100  # 0.30% -> 0.003

        # 포지션 사이징
        self.risk_per_trade = risk_per_trade
        self.max_margin_pct = max_margin_pct
        self.leverage = leverage
        self.initial_capital = initial_capital

        # 리스크 관리
        self.dd_stage1 = dd_stage1
        self.dd_stage2 = dd_stage2
        self.dd_stage3 = dd_stage3
        self.daily_loss_limit = daily_loss_limit
        self.cooldown_sl_hours = cooldown_sl_hours
        self.cooldown_time_hours = cooldown_time_hours

    def check_risk_limits(self, state: TradingState, current_time: datetime = None) -> RiskAction:
        """리스크 한도 체크"""
        if state.halted:
            return RiskAction.HALT

        # Drawdown 계산
        dd = (state.peak_nav - state.current_nav) / state.peak_nav if state.peak_nav > 0 else 0

        if dd >= self.dd_stage3:
            state.halted = True
            logger.warning(f"DD Stage 3 triggered: {dd:.2%} - Strategy HALTED")
            return RiskAction.HALT

        if dd >= self.dd_stage2:
            return RiskAction.NO_NEW_ENTRY

        if dd >= self.dd_stage1:
            return RiskAction.REDUCED_RISK

        # 일간 손실 한도
        daily_loss_pct = -state.daily_pnl / state.current_nav if state.current_nav > 0 else 0
        if daily_loss_pct >= self.daily_loss_limit:
            return RiskAction.NO_NEW_ENTRY

        # 당일 2거래 손절
        if state.daily_losses >= 2:
            return RiskAction.NO_NEW_ENTRY

        # 4연속 손절 - 24시간 후 리셋
        if state.consecutive_losses >= 4:
            if state.consecutive_loss_time is not None and current_time is not None:
                hours_since = (current_time - state.consecutive_loss_time).total_seconds() / 3600
                if hours_since >= 24:
                    state.consecutive_losses = 0
                    state.consecutive_loss_time = None
                else:
                    return RiskAction.NO_NEW_ENTRY
            else:
                return RiskAction.NO_NEW_ENTRY

        return RiskAction.NORMAL

    def check_cooldown(self, state: TradingState, current_time: datetime) -> bool:
        """쿨다운 체크 - True면 대기 필요"""
        if state.last_exit_time is None:
            return False

        if state.last_exit_reason == ExitReason.TAKE_PROFIT:
            return False  # 익절 후 쿨다운 없음

        if state.last_exit_reason == ExitReason.STOP_LOSS:
            cooldown_hours = self.cooldown_sl_hours
        else:  # TIME_STOP
            cooldown_hours = self.cooldown_time_hours

        elapsed = (current_time - state.last_exit_time).total_seconds() / 3600
        return elapsed < cooldown_hours

    def check_direction_filter(self, close: float, ema_50: float, direction: Direction) -> bool:
        """방향 필터 체크 - True면 진입 허용"""
        if pd.isna(ema_50):
            return False

        if direction == Direction.LONG:
            return close > ema_50
        else:
            return close < ema_50

    def check_noise_filter(self, range_pct: float) -> bool:
        """노이즈 필터 체크 - True면 진입 허용"""
        if pd.isna(range_pct):
            return True  # 데이터 없으면 일단 허용
        return range_pct >= self.range_pct_threshold

    def check_funding_filter(self, funding_rate: float, direction: Direction) -> bool:
        """펀딩 필터 체크 - True면 진입 허용"""
        if pd.isna(funding_rate):
            return True

        if direction == Direction.LONG:
            return funding_rate <= self.funding_threshold
        else:
            return funding_rate >= -self.funding_threshold

    def calculate_position_size(
        self, nav: float, atr: float, entry_price: float, risk_action: RiskAction
    ) -> float:
        """포지션 사이즈 계산"""
        # 리스크 금액
        risk_amount = self.risk_per_trade * nav

        # DD 1단계시 50% 축소
        if risk_action == RiskAction.REDUCED_RISK:
            risk_amount *= 0.5

        # SL 거리
        sl_distance = self.sl_atr_mult * atr
        sl_pct = sl_distance / entry_price

        # 포지션 사이즈
        position_size_usd = risk_amount / sl_pct if sl_pct > 0 else 0

        # 마진 한도 적용
        max_position = self.max_margin_pct * nav * self.leverage
        position_size_usd = min(position_size_usd, max_position)

        return position_size_usd

    def check_entry(self, bar: pd.Series, state: TradingState) -> Optional[Signal]:
        """진입 신호 체크"""
        current_time = bar["timestamp"]
        current_date = str(current_time.date())

        # 날짜 변경시 일간 상태 리셋
        if state.current_date != current_date:
            state.current_date = current_date
            state.daily_pnl = 0.0
            state.daily_trades = 0
            state.daily_losses = 0
            state.today_long_traded = False
            state.today_short_traded = False

        # 기존 포지션 있으면 스킵
        if state.position is not None:
            return None

        # 리스크 체크
        risk_action = self.check_risk_limits(state, current_time)
        if risk_action in [RiskAction.NO_NEW_ENTRY, RiskAction.HALT]:
            return None

        # 쿨다운 체크
        if self.check_cooldown(state, current_time):
            return None

        close = bar["close"]
        long_trigger = bar["long_trigger"]
        short_trigger = bar["short_trigger"]
        ema_50 = bar["ema_50_1h"]
        atr = bar["atr_14_1h"]
        range_pct = bar["range_pct_20"]
        funding_rate = bar.get("funding_rate", 0)

        # 필수 데이터 체크
        if pd.isna(long_trigger) or pd.isna(short_trigger) or pd.isna(atr):
            return None

        # Long 신호 체크
        if close >= long_trigger and not state.today_long_traded:
            direction = Direction.LONG
            if (
                self.check_direction_filter(close, ema_50, direction)
                and self.check_noise_filter(range_pct)
                and self.check_funding_filter(funding_rate, direction)
            ):
                entry_price = close
                sl_price = entry_price - self.sl_atr_mult * atr
                tp_price = entry_price + self.tp_atr_mult * atr
                size_usd = self.calculate_position_size(
                    state.current_nav, atr, entry_price, risk_action
                )

                if size_usd > 0:
                    return Signal(
                        direction=direction,
                        trigger_price=long_trigger,
                        entry_price=entry_price,
                        sl_price=sl_price,
                        tp_price=tp_price,
                        size_usd=size_usd,
                        atr=atr,
                    )

        # Short 신호 체크
        if close <= short_trigger and not state.today_short_traded:
            direction = Direction.SHORT
            if (
                self.check_direction_filter(close, ema_50, direction)
                and self.check_noise_filter(range_pct)
                and self.check_funding_filter(funding_rate, direction)
            ):
                entry_price = close
                sl_price = entry_price + self.sl_atr_mult * atr
                tp_price = entry_price - self.tp_atr_mult * atr
                size_usd = self.calculate_position_size(
                    state.current_nav, atr, entry_price, risk_action
                )

                if size_usd > 0:
                    return Signal(
                        direction=direction,
                        trigger_price=short_trigger,
                        entry_price=entry_price,
                        sl_price=sl_price,
                        tp_price=tp_price,
                        size_usd=size_usd,
                        atr=atr,
                    )

        return None

    def check_exit(self, position: Position, bar: pd.Series) -> Optional[ExitReason]:
        """청산 조건 체크"""
        current_time = bar["timestamp"]
        high = bar["high"]
        low = bar["low"]

        # Time Stop
        hours_held = (current_time - position.entry_time).total_seconds() / 3600
        if hours_held >= self.time_stop_hours:
            return ExitReason.TIME_STOP

        if position.direction == Direction.LONG:
            # SL 먼저 체크 (보수적)
            if low <= position.sl_price:
                return ExitReason.STOP_LOSS
            if high >= position.tp_price:
                return ExitReason.TAKE_PROFIT
        else:  # SHORT
            if high >= position.sl_price:
                return ExitReason.STOP_LOSS
            if low <= position.tp_price:
                return ExitReason.TAKE_PROFIT

        return None

    def get_exit_price(
        self, position: Position, exit_reason: ExitReason, bar: pd.Series
    ) -> float:
        """청산 가격 결정"""
        if exit_reason == ExitReason.STOP_LOSS:
            return position.sl_price
        elif exit_reason == ExitReason.TAKE_PROFIT:
            return position.tp_price
        else:  # TIME_STOP
            return bar["close"]
