"""
Run RAAA Strategy Backtest

Execute full backtest simulation with multi-asset, multi-timeframe data.
"""

import pandas as pd
import logging
from backtest.engine import BacktestEngine

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_data():
    """Load all required data files"""
    logger.info("Loading data files...")

    # Load BTC data
    btc_15m = pd.read_parquet('data/processed/BTC_15m.parquet')
    btc_1h = pd.read_parquet('data/processed/BTC_1h.parquet')
    btc_4h = pd.read_parquet('data/processed/BTC_4h.parquet')
    btc_funding = pd.read_parquet('data/processed/BTC_funding.parquet')

    # Load ETH data
    eth_15m = pd.read_parquet('data/processed/ETH_15m.parquet')
    eth_1h = pd.read_parquet('data/processed/ETH_1h.parquet')
    eth_4h = pd.read_parquet('data/processed/ETH_4h.parquet')
    eth_funding = pd.read_parquet('data/processed/ETH_funding.parquet')

    logger.info(f"BTC 15m: {len(btc_15m)} bars, Date range: {btc_15m.index[0]} to {btc_15m.index[-1]}")
    logger.info(f"BTC 1h: {len(btc_1h)} bars")
    logger.info(f"BTC 4h: {len(btc_4h)} bars")
    logger.info(f"ETH 15m: {len(eth_15m)} bars, Date range: {eth_15m.index[0]} to {eth_15m.index[-1]}")
    logger.info(f"ETH 1h: {len(eth_1h)} bars")
    logger.info(f"ETH 4h: {len(eth_4h)} bars")

    return btc_15m, btc_1h, btc_4h, eth_15m, eth_1h, eth_4h, btc_funding, eth_funding


def main():
    """Main backtest execution"""
    logger.info("=" * 80)
    logger.info("RAAA STRATEGY BACKTEST")
    logger.info("=" * 80)

    # Load data
    btc_15m, btc_1h, btc_4h, eth_15m, eth_1h, eth_4h, btc_funding, eth_funding = load_data()

    # Initialize backtest engine
    engine = BacktestEngine(
        initial_capital=100000,
        leverage=3,  # UPDATED: 5x -> 3x for more conservative risk
        fee_rate=0.0005,  # 0.05%
        slippage_rate=0.0002,  # 0.02%
        start_date='2025-03-06',
        end_date='2026-02-01'
    )

    # Run backtest
    logger.info("\nStarting backtest simulation...\n")
    report = engine.run(
        btc_15m=btc_15m,
        btc_1h=btc_1h,
        btc_4h=btc_4h,
        eth_15m=eth_15m,
        eth_1h=eth_1h,
        eth_4h=eth_4h,
        funding_btc=btc_funding,
        funding_eth=eth_funding
    )

    # Display summary
    logger.info("\n" + "=" * 80)
    logger.info("BACKTEST RESULTS SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Initial Capital: ${report['summary']['initial_capital']:,.2f}")
    logger.info(f"Final Equity: ${report['summary']['final_equity']:,.2f}")
    logger.info(f"Total Return: {report['summary']['total_return_pct']:+.2f}%")
    logger.info(f"CAGR: {report['summary']['cagr_pct']:+.2f}%")
    logger.info(f"Max Drawdown: {report['summary']['max_drawdown_pct']:.2f}%")
    logger.info(f"Sharpe Ratio: {report['summary']['sharpe_ratio']:.2f}")
    logger.info(f"Calmar Ratio: {report['summary']['calmar_ratio']:.2f}")
    logger.info("")
    logger.info(f"Total Trades: {report['trades']['total_trades']}")
    logger.info(f"Win Rate: {report['trades']['win_rate']*100:.2f}%")
    logger.info(f"Profit Factor: {report['trades'].get('profit_factor', 0):.2f}")
    logger.info(f"Avg Win: ${report['trades'].get('avg_win', 0):,.2f}")
    logger.info(f"Avg Loss: ${report['trades'].get('avg_loss', 0):,.2f}")
    logger.info(f"Liquidations: {report['trades'].get('liquidations', 0)}")
    logger.info("")
    logger.info(f"Total Fees Paid: ${report['summary']['total_fees_paid']:,.2f}")
    logger.info(f"Net Funding P&L: ${report['summary']['net_funding']:+,.2f}")
    logger.info("=" * 80)

    # Performance evaluation
    logger.info("\nPERFORMANCE VS TARGETS:")
    logger.info(f"  CAGR > 100%: {'✅ PASS' if report['summary']['cagr'] > 1.0 else '❌ FAIL'} ({report['summary']['cagr_pct']:.2f}%)")
    logger.info(f"  Max DD < 30%: {'✅ PASS' if report['summary']['max_drawdown'] > -0.30 else '❌ FAIL'} ({abs(report['summary']['max_drawdown_pct']):.2f}%)")
    logger.info(f"  Profit Factor > 1.8: {'✅ PASS' if report['trades'].get('profit_factor', 0) > 1.8 else '❌ FAIL'} ({report['trades'].get('profit_factor', 0):.2f})")
    logger.info(f"  Win Rate > 45%: {'✅ PASS' if report['trades'].get('win_rate', 0) > 0.45 else '❌ FAIL'} ({report['trades'].get('win_rate', 0)*100:.2f}%)")
    logger.info("")

    logger.info("Results saved to:")
    logger.info("  - results/trade_log.csv")
    logger.info("  - results/equity_curve.csv")
    logger.info("  - results/backtest_report.md")
    logger.info("")


if __name__ == '__main__':
    main()
