## Project: BTC Volatility Breakout (VB) Strategy
OKX BTC/USDT-SWAP perpetual futures. Full spec: `spec.md`

## Structure
```
data/pipeline.py          # OKX API 데이터 수집 + 인디케이터 계산
strategies/vb_strategy.py # 진입/청산 로직 + 리스크 관리
backtest/engine.py        # 백테스트 엔진 + 리포트 생성
run_backtest.py           # 실행 진입점
```

## Strategy Summary
- **Logic**: 전일 Range × k 돌파 → 진입, ATR 기반 SL/TP
- **Asset**: BTC/USDT-SWAP only (단일 자산)
- **Leverage**: 3× Isolated Margin, Initial Capital $10,000
- **Timeframes**: 15m (진입/모니터링), 1H (ATR/EMA), Daily (Range)
- **Entry**: 15m close crosses trigger + EMA(50) 방향필터 + 노이즈필터 + 펀딩필터
- **Exit**: SL 1.5×ATR, TP 2.5×ATR, Time Stop 24H
- **Sizing**: 1.5% NAV risk, max 25% margin, max 1 position
- **Risk**: DD 3단계(8%/13%/18%), 일간 2.5% 한도, 쿨다운
- **NO**: Regime, Pyramiding, Multi-asset, Partial TP, Trailing Stop

## Coding Standards
- Python 3.10+, Black formatter, PEP 8
- Dependencies: ccxt, pandas, numpy (in `requirements.txt`)
- Logging: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- API calls: exponential backoff (3 retries)
- Data validation: check missing bars, schema validation

## Key Interfaces
```python
# pipeline.py → DataFrame columns:
# timestamp, open, high, low, close, volume,
# atr_14_1h, ema_50_1h, daily_range, range_pct_20,
# today_open, long_trigger, short_trigger, funding_rate

# vb_strategy.py:
# check_entry(bar, state) -> Signal | None
# check_exit(position, bar) -> ExitReason | None
# calc_position_size(nav, atr, entry_price) -> float
# check_risk_limits(nav, peak_nav, daily_pnl) -> RiskAction

# engine.py:
# run_backtest(df, params) -> BacktestResult
```

## Backtest Params
- Period: 2025-02-01 ~ 2026-02-01 (warmup ~20 days)
- Fees: 0.05% taker + 0.03% slippage (per side)
- Funding: 8H settlement (real data)
- Targets (OOS): PF>1.3, WR>45%, DD<20%, CAGR>20%, Liquidation=0
- Optimization: Walk-Forward (IS 180d / OOS 60d), k=0.3~0.7
