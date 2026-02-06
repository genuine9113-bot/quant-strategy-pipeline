"""
BTC Volatility Breakout Strategy - Backtest Engine
백테스트 실행 및 성과 계산
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.vb_strategy import (
    VBStrategy,
    TradingState,
    Position,
    Signal,
    Direction,
    ExitReason,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """거래 기록"""
    entry_time: datetime
    exit_time: datetime
    direction: str
    entry_price: float
    exit_price: float
    size_usd: float
    pnl: float
    pnl_pct: float
    exit_reason: str
    fees: float
    funding_paid: float


@dataclass
class BacktestResult:
    """백테스트 결과"""
    trades: List[Trade]
    equity_curve: pd.DataFrame
    initial_capital: float
    final_capital: float
    total_return: float
    cagr: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    total_trades: int
    avg_trade_pnl: float
    avg_win: float
    avg_loss: float
    sharpe_ratio: float


class BacktestEngine:
    """백테스트 엔진"""

    def __init__(
        self,
        strategy: VBStrategy,
        initial_capital: float = 10000.0,
        taker_fee: float = 0.0005,  # 0.05%
        slippage: float = 0.0003,   # 0.03%
    ):
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.taker_fee = taker_fee
        self.slippage = slippage

    def calculate_fees(self, size_usd: float) -> float:
        """수수료 계산 (진입 + 청산)"""
        return size_usd * (self.taker_fee + self.slippage) * 2

    def calculate_funding(
        self,
        position: Position,
        current_time: datetime,
        last_funding_time: Optional[datetime],
        funding_rate: float,
    ) -> tuple[float, datetime]:
        """펀딩비 계산"""
        if last_funding_time is None:
            last_funding_time = position.entry_time

        # 8시간마다 펀딩 정산 (00:00, 08:00, 16:00 UTC)
        funding_paid = 0.0
        current_hour = current_time.hour
        last_hour = last_funding_time.hour

        # 간단히 8시간 경과마다 펀딩 적용
        hours_since_entry = (current_time - position.entry_time).total_seconds() / 3600
        funding_periods = int(hours_since_entry / 8)
        
        if funding_periods > 0:
            # Long pays funding, Short receives (when positive funding)
            if position.direction == Direction.LONG:
                funding_paid = position.size_usd * funding_rate * funding_periods
            else:
                funding_paid = -position.size_usd * funding_rate * funding_periods

        return funding_paid, current_time

    def run(self, df: pd.DataFrame) -> BacktestResult:
        """백테스트 실행"""
        logger.info(f"Running backtest on {len(df)} bars")

        state = TradingState(
            peak_nav=self.initial_capital,
            current_nav=self.initial_capital,
        )

        trades: List[Trade] = []
        equity_curve = []
        last_funding_time = None
        total_funding_paid = 0.0

        for idx, bar in df.iterrows():
            current_time = bar["timestamp"]
            funding_rate = bar.get("funding_rate", 0)

            # 포지션 청산 체크
            if state.position is not None:
                exit_reason = self.strategy.check_exit(state.position, bar)

                if exit_reason is not None:
                    # 청산 가격 결정
                    exit_price = self.strategy.get_exit_price(
                        state.position, exit_reason, bar
                    )

                    # 슬리피지 적용
                    if state.position.direction == Direction.LONG:
                        exit_price *= (1 - self.slippage)
                    else:
                        exit_price *= (1 + self.slippage)

                    # P&L 계산
                    if state.position.direction == Direction.LONG:
                        pnl_pct = (exit_price - state.position.entry_price) / state.position.entry_price
                    else:
                        pnl_pct = (state.position.entry_price - exit_price) / state.position.entry_price

                    # 레버리지 적용
                    position_pnl = state.position.size_usd * pnl_pct

                    # 수수료 계산
                    fees = self.calculate_fees(state.position.size_usd)

                    # 펀딩비 계산
                    funding_paid, _ = self.calculate_funding(
                        state.position, current_time, last_funding_time, funding_rate
                    )

                    # 순 P&L
                    net_pnl = position_pnl - fees - funding_paid

                    # 거래 기록
                    trade = Trade(
                        entry_time=state.position.entry_time,
                        exit_time=current_time,
                        direction=state.position.direction.value,
                        entry_price=state.position.entry_price,
                        exit_price=exit_price,
                        size_usd=state.position.size_usd,
                        pnl=net_pnl,
                        pnl_pct=net_pnl / state.current_nav if state.current_nav > 0 else 0,
                        exit_reason=exit_reason.value,
                        fees=fees,
                        funding_paid=funding_paid,
                    )
                    trades.append(trade)

                    # 상태 업데이트
                    state.current_nav += net_pnl
                    state.daily_pnl += net_pnl
                    state.daily_trades += 1

                    if net_pnl < 0:
                        state.daily_losses += 1
                        state.consecutive_losses += 1
                        # 4연속 손절 시 시간 기록
                        if state.consecutive_losses == 4:
                            state.consecutive_loss_time = current_time
                    else:
                        state.consecutive_losses = 0
                        state.consecutive_loss_time = None

                    state.peak_nav = max(state.peak_nav, state.current_nav)
                    state.last_exit_time = current_time
                    state.last_exit_reason = exit_reason

                    # 방향별 거래 기록
                    if state.position.direction == Direction.LONG:
                        state.today_long_traded = True
                    else:
                        state.today_short_traded = True

                    state.position = None
                    last_funding_time = None

                    logger.debug(
                        f"Exit: {trade.direction} @ {exit_price:.2f}, "
                        f"PnL: ${net_pnl:.2f} ({exit_reason.value})"
                    )

            # 진입 신호 체크
            if state.position is None:
                signal = self.strategy.check_entry(bar, state)

                if signal is not None:
                    # 슬리피지 적용
                    if signal.direction == Direction.LONG:
                        entry_price = signal.entry_price * (1 + self.slippage)
                    else:
                        entry_price = signal.entry_price * (1 - self.slippage)

                    # 포지션 생성
                    state.position = Position(
                        direction=signal.direction,
                        entry_price=entry_price,
                        entry_time=current_time,
                        size_usd=signal.size_usd,
                        sl_price=signal.sl_price,
                        tp_price=signal.tp_price,
                        atr_at_entry=signal.atr,
                    )
                    last_funding_time = current_time

                    logger.debug(
                        f"Entry: {signal.direction.value} @ {entry_price:.2f}, "
                        f"Size: ${signal.size_usd:.2f}"
                    )

            # 에쿼티 커브 기록
            unrealized_pnl = 0.0
            if state.position is not None:
                if state.position.direction == Direction.LONG:
                    unrealized_pnl = state.position.size_usd * (
                        bar["close"] - state.position.entry_price
                    ) / state.position.entry_price
                else:
                    unrealized_pnl = state.position.size_usd * (
                        state.position.entry_price - bar["close"]
                    ) / state.position.entry_price

            equity_curve.append({
                "timestamp": current_time,
                "nav": state.current_nav + unrealized_pnl,
                "drawdown": self._calculate_drawdown(
                    state.current_nav + unrealized_pnl, state.peak_nav
                ),
            })

        # 미청산 포지션 처리
        if state.position is not None:
            logger.warning("Position still open at end of backtest, closing at last price")
            last_bar = df.iloc[-1]
            exit_price = last_bar["close"]

            if state.position.direction == Direction.LONG:
                pnl_pct = (exit_price - state.position.entry_price) / state.position.entry_price
            else:
                pnl_pct = (state.position.entry_price - exit_price) / state.position.entry_price

            position_pnl = state.position.size_usd * pnl_pct
            fees = self.calculate_fees(state.position.size_usd)
            net_pnl = position_pnl - fees

            state.current_nav += net_pnl

        # 결과 계산
        equity_df = pd.DataFrame(equity_curve)
        result = self._calculate_metrics(trades, equity_df, state.current_nav)

        return result

    def _calculate_drawdown(self, nav: float, peak: float) -> float:
        """드로다운 계산"""
        if peak <= 0:
            return 0.0
        return (peak - nav) / peak

    def _calculate_metrics(
        self,
        trades: List[Trade],
        equity_df: pd.DataFrame,
        final_capital: float,
    ) -> BacktestResult:
        """성과 지표 계산"""
        total_trades = len(trades)

        if total_trades == 0:
            return BacktestResult(
                trades=trades,
                equity_curve=equity_df,
                initial_capital=self.initial_capital,
                final_capital=final_capital,
                total_return=0.0,
                cagr=0.0,
                max_drawdown=0.0,
                win_rate=0.0,
                profit_factor=0.0,
                total_trades=0,
                avg_trade_pnl=0.0,
                avg_win=0.0,
                avg_loss=0.0,
                sharpe_ratio=0.0,
            )

        # 기본 통계
        total_return = (final_capital - self.initial_capital) / self.initial_capital

        # CAGR 계산
        if len(equity_df) > 0:
            days = (equity_df["timestamp"].iloc[-1] - equity_df["timestamp"].iloc[0]).days
            years = days / 365 if days > 0 else 1
            cagr = (final_capital / self.initial_capital) ** (1 / years) - 1 if years > 0 else 0
        else:
            cagr = 0.0

        # Max Drawdown
        max_drawdown = equity_df["drawdown"].max() if len(equity_df) > 0 else 0.0

        # Win Rate
        winning_trades = [t for t in trades if t.pnl > 0]
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0.0

        # Profit Factor
        gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Average trades
        avg_trade_pnl = sum(t.pnl for t in trades) / total_trades if total_trades > 0 else 0.0
        avg_win = gross_profit / len(winning_trades) if winning_trades else 0.0
        losing_trades = [t for t in trades if t.pnl < 0]
        avg_loss = gross_loss / len(losing_trades) if losing_trades else 0.0

        # Sharpe Ratio (일간 수익률 기준)
        if len(equity_df) > 1:
            equity_df["daily_return"] = equity_df["nav"].pct_change()
            daily_returns = equity_df["daily_return"].dropna()
            if len(daily_returns) > 0 and daily_returns.std() > 0:
                sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
            else:
                sharpe_ratio = 0.0
        else:
            sharpe_ratio = 0.0

        return BacktestResult(
            trades=trades,
            equity_curve=equity_df,
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            cagr=cagr,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=total_trades,
            avg_trade_pnl=avg_trade_pnl,
            avg_win=avg_win,
            avg_loss=avg_loss,
            sharpe_ratio=sharpe_ratio,
        )

    def print_report(self, result: BacktestResult):
        """백테스트 결과 출력"""
        print("\n" + "=" * 60)
        print("BACKTEST REPORT - BTC Volatility Breakout Strategy")
        print("=" * 60)

        print(f"\n{'Initial Capital:':<25} ${result.initial_capital:,.2f}")
        print(f"{'Final Capital:':<25} ${result.final_capital:,.2f}")
        print(f"{'Total Return:':<25} {result.total_return:.2%}")
        print(f"{'CAGR:':<25} {result.cagr:.2%}")

        print(f"\n{'--- Risk Metrics ---'}")
        print(f"{'Max Drawdown:':<25} {result.max_drawdown:.2%}")
        print(f"{'Sharpe Ratio:':<25} {result.sharpe_ratio:.2f}")

        print(f"\n{'--- Trade Statistics ---'}")
        print(f"{'Total Trades:':<25} {result.total_trades}")
        print(f"{'Win Rate:':<25} {result.win_rate:.2%}")
        print(f"{'Profit Factor:':<25} {result.profit_factor:.2f}")
        print(f"{'Avg Trade PnL:':<25} ${result.avg_trade_pnl:.2f}")
        print(f"{'Avg Win:':<25} ${result.avg_win:.2f}")
        print(f"{'Avg Loss:':<25} ${result.avg_loss:.2f}")

        # Exit Reason 분석
        if result.trades:
            exit_reasons = {}
            for t in result.trades:
                reason = t.exit_reason
                if reason not in exit_reasons:
                    exit_reasons[reason] = {"count": 0, "pnl": 0}
                exit_reasons[reason]["count"] += 1
                exit_reasons[reason]["pnl"] += t.pnl

            print(f"\n{'--- Exit Analysis ---'}")
            for reason, stats in exit_reasons.items():
                print(f"{reason:<20} Count: {stats['count']:>3}, PnL: ${stats['pnl']:>10,.2f}")

        # 방향별 분석
        if result.trades:
            long_trades = [t for t in result.trades if t.direction == "long"]
            short_trades = [t for t in result.trades if t.direction == "short"]

            print(f"\n{'--- Direction Analysis ---'}")
            if long_trades:
                long_wins = len([t for t in long_trades if t.pnl > 0])
                long_pnl = sum(t.pnl for t in long_trades)
                print(f"{'Long:':<10} {len(long_trades)} trades, WR: {long_wins/len(long_trades):.2%}, PnL: ${long_pnl:,.2f}")
            if short_trades:
                short_wins = len([t for t in short_trades if t.pnl > 0])
                short_pnl = sum(t.pnl for t in short_trades)
                print(f"{'Short:':<10} {len(short_trades)} trades, WR: {short_wins/len(short_trades):.2%}, PnL: ${short_pnl:,.2f}")

        print("\n" + "=" * 60)
