"""
BTC Volatility Breakout Strategy - Run Backtest
백테스트 실행 진입점 (config.yaml에서 파라미터 로드)
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import yaml
import logging

from data.pipeline import DataPipeline
from strategies.vb_strategy import VBStrategy
from backtest.engine import BacktestEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_config(config_path: str = "config.yaml") -> dict:
    """YAML 설정 파일 로드"""
    config_file = Path(__file__).parent / config_path
    
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")
    
    with open(config_file, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    logger.info(f"Loaded config from {config_file}")
    return config


def main(config_path: str = "config.yaml"):
    """메인 실행 함수"""
    # 설정 로드
    config = load_config(config_path)
    
    # 백테스트 설정
    bt_config = config["backtest"]
    START_DATE = bt_config["start_date"]
    END_DATE = bt_config["end_date"]
    INITIAL_CAPITAL = bt_config["initial_capital"]

    # 데이터 파일 경로
    data_path = Path(__file__).parent / "data" / "btc_vb_data.parquet"

    # 데이터 로드 또는 다운로드
    if data_path.exists():
        logger.info(f"Loading data from {data_path}")
        df = pd.read_parquet(data_path)
    else:
        logger.info("Data file not found, running pipeline...")
        pipeline = DataPipeline()
        df = pipeline.run(start_date=START_DATE, end_date=END_DATE, save=True)

    logger.info(f"Data loaded: {len(df)} bars from {df['timestamp'].min()} to {df['timestamp'].max()}")

    # 전략 설정
    strat_config = config["strategy"]
    filter_config = config["filters"]
    sizing_config = config["sizing"]
    risk_config = config["risk"]
    cooldown_config = config["cooldown"]
    
    # 전략 초기화
    strategy = VBStrategy(
        # 핵심 파라미터
        k=strat_config["k"],
        sl_atr_mult=strat_config["sl_atr_mult"],
        tp_atr_mult=strat_config["tp_atr_mult"],
        time_stop_hours=strat_config["time_stop_hours"],
        # 필터
        ema_period=filter_config["ema_period"],
        range_pct_threshold=filter_config["range_pct_threshold"],
        funding_threshold=filter_config["funding_threshold"],
        # 포지션 사이징
        risk_per_trade=sizing_config["risk_per_trade"],
        max_margin_pct=sizing_config["max_margin_pct"],
        leverage=sizing_config["leverage"],
        initial_capital=INITIAL_CAPITAL,
        # 리스크 관리
        dd_stage1=risk_config["dd_stage1"],
        dd_stage2=risk_config["dd_stage2"],
        dd_stage3=risk_config["dd_stage3"],
        daily_loss_limit=risk_config["daily_loss_limit"],
        # 쿨다운
        cooldown_sl_hours=cooldown_config["cooldown_sl_hours"],
        cooldown_time_hours=cooldown_config["cooldown_time_hours"],
    )

    # 실행 비용 설정
    exec_config = config["execution"]
    
    # 백테스트 엔진 초기화
    engine = BacktestEngine(
        strategy=strategy,
        initial_capital=INITIAL_CAPITAL,
        taker_fee=exec_config["taker_fee"],
        slippage=exec_config["slippage"],
    )

    # 현재 설정 출력
    print("\n" + "=" * 60)
    print("CURRENT CONFIGURATION")
    print("=" * 60)
    print(f"k: {strat_config['k']}, SL: {strat_config['sl_atr_mult']}×ATR, TP: {strat_config['tp_atr_mult']}×ATR")
    print(f"Time Stop: {strat_config['time_stop_hours']}H, EMA: {filter_config['ema_period']}")
    print(f"Risk/Trade: {sizing_config['risk_per_trade']*100:.1f}%, Max Margin: {sizing_config['max_margin_pct']*100:.0f}%")
    print("=" * 60)

    # 백테스트 실행
    logger.info("Starting backtest...")
    result = engine.run(df)

    # 결과 출력
    engine.print_report(result)

    # 에쿼티 커브 저장
    equity_path = Path(__file__).parent / "data" / "equity_curve.csv"
    result.equity_curve.to_csv(equity_path, index=False)
    logger.info(f"Equity curve saved to {equity_path}")

    # 거래 내역 저장
    if result.trades:
        trades_data = [
            {
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "size_usd": t.size_usd,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "exit_reason": t.exit_reason,
                "fees": t.fees,
                "funding_paid": t.funding_paid,
            }
            for t in result.trades
        ]
        trades_df = pd.DataFrame(trades_data)
        trades_path = Path(__file__).parent / "data" / "trades.csv"
        trades_df.to_csv(trades_path, index=False)
        logger.info(f"Trades saved to {trades_path}")

    return result


if __name__ == "__main__":
    # 커맨드라인에서 config 경로 지정 가능
    config_file = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    main(config_file)
