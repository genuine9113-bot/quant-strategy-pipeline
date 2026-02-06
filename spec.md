# Strategy Specification: Regime-Adaptive Aggressive Alpha (RAAA)

## 1. Overview
Multi-Asset, Multi-Timeframe, Regime-Switching 전략. 시장 상태를 4가지로 분류하고 각 Regime에 최적화된 공격적 매매 실행.

-   **Core Philosophy**: "Adapt to the Regime, Attack with Precision, Compound Aggressively."
-   **Exchange**: OKX (Perpetual Futures / USDT-Margined Swap)
-   **Assets**: BTC/USDT Perp, ETH/USDT Perp
-   **Leverage**: 5× (고정)
-   **Margin Mode**: Isolated
-   **Direction**: Long & Short (양방향)
-   **Frequency**: High (15m Entry, 일 평균 2-5 trades 목표)
-   **Performance Target**: CAGR > 100%, Profit Factor > 1.8, Max DD < 30%

## 2. Timeframes & Data

### 2.1 Timeframe Hierarchy
| Layer | Timeframe | Purpose |
|---|---|---|
| Regime | 4H | 시장 상태 분류 (Trend/Chop/Squeeze) |
| Signal | 1H | 방향성 확인 + 신호 생성 |
| Entry | 15m | 정밀 진입 타이밍 |

### 2.2 Data Sources
-   **Price Data (Core)**: OKX API - BTC/USDT-SWAP, ETH/USDT-SWAP (Perpetual Futures OHLCV)
    -   라이브러리: `ccxt` (통합 거래소 API) 또는 OKX Python SDK
    -   Rate Limit: 20 req/2s (OKX Public API)
-   **Funding Rate (Core)**: OKX API - 8시간마다 정산 (00:00, 08:00, 16:00 UTC)
    -   Funding Rate는 백테스트 P&L에 필수 반영
    -   Endpoint: `/api/v5/public/funding-rate-history`
-   **On-Chain Data (Enhanced)**: Glassnode / CryptoQuant API (옵션)
    -   Exchange Netflow, MVRV Z-Score, Whale Tx Count, SOPR
    -   *Note: 가격 데이터만으로 Core 전략 동작. On-Chain은 신호 강도 보정용.*

## 3. Regime Classification (4H)

4H 데이터 기반으로 시장을 4가지 상태로 분류. 매 4H Bar Close마다 재평가.

### State 1: Trending Bull
```
조건: EMA(20) > EMA(50) > EMA(200)
      AND ADX(14) > 25
      AND +DI > -DI
```
-   **허용 방향**: Long Only
-   **ETH 조건**: BTC도 Trending Bull이고 BTC 포지션이 활성화 상태일 때만 ETH Long 진입 허용
-   **전략**: Momentum Continuation, Pullback Entry

### State 2: Trending Bear
```
조건: EMA(20) < EMA(50) < EMA(200)
      AND ADX(14) > 25
      AND -DI > +DI
```
-   **허용 방향**: Short Only
-   **전략**: Momentum Short, Breakdown Short

### State 3: High Volatility Chop
```
조건: ADX(14) < 20
      AND ATR Percentile(50) > 70th
```
-   **허용 방향**: Long & Short (Mean Reversion)
-   **전략**: BB Mean Reversion, RSI Extreme Reversal

### State 4: Low Volatility Squeeze
```
조건: ADX(14) < 20
      AND ATR Percentile(50) < 30th
      AND BB Width Percentile(50) < 20th
```
-   **허용 방향**: Long & Short (Breakout)
-   **전략**: Volatility Breakout, Squeeze Fire

### Regime Transition Rules
-   Regime 전환 시 **기존 포지션 유지** (Stop/TP가 관리)
-   단, **Trending → 반대 Trending 전환**(Bull→Bear, Bear→Bull) 시 즉시 전 포지션 청산
-   Regime 전환 후 **2 bars (8H) 쿨다운** 후 새 Regime 전략 적용

### Undefined Regime (No-Trade Zone)
-   **ADX 20~25 구간**: Trending과 Chop/Squeeze의 중간 지대
-   **EMA 순서 불완전**: EMA(20), EMA(50), EMA(200)가 명확한 순서가 아닌 경우 (예: 20 > 200 > 50)
-   **조치**: 신규 진입 중단, 기존 포지션은 Stop/TP로만 관리
-   **Regime 재확인**: 다음 4H Bar Close에서 재평가

## 4. Entry Strategies by Regime

### 4.1 Trending Bull Strategies

#### A. Momentum Continuation (1H Signal → 15m Entry)
**1H 조건**:
-   RSI(14) > 50 AND RSI < 80 (과매수 아닌 상승 모멘텀)
-   Close > EMA(20)
-   Volume > SMA(20) of Volume × 1.3

**15m Entry**:
-   EMA(9) 터치 후 반등 (Pullback to fast MA)
-   또는 직전 15m High 돌파 + Volume Surge (> 2× avg)

#### B. Pullback Entry (1H Signal → 15m Entry)
**1H 조건**:
-   RSI(14) drops to 40-50 range (건강한 조정)
-   Price touches EMA(50) or BB Middle Band(20)
-   ADX still > 25 (추세 유지 확인)

**15m Entry**:
-   Bullish engulfing 또는 hammer 캔들 패턴
-   RSI(14) 15m이 30 이하에서 반등 시작

#### C. Breakout Continuation
**1H 조건**:
-   Close > Donchian Channel(20) Upper
-   Volume > SMA(20) × 2.0 (Strong Volume Confirmation)

**15m Entry**:
-   Breakout bar close 이후 첫 pullback에서 진입
-   Stop: Donchian midline 아래

### 4.2 Trending Bear Strategies
Bull 전략의 **Mirror** (방향만 반전):
-   Momentum Short: RSI < 50, Close < EMA(20), Volume surge
-   Rally Short: RSI rises to 50-60, touches EMA(50) from below
-   Breakdown Short: Close < Donchian(20) Lower

### 4.3 High Volatility Chop Strategies

#### A. BB Mean Reversion
**1H 조건**:
-   **Long**: Price ≤ Lower BB(20, 2.5) AND RSI(14) < 25
-   **Short**: Price ≥ Upper BB(20, 2.5) AND RSI(14) > 75

**15m Entry**:
-   Reversal candle confirmation (engulfing, pin bar)
-   Target: BB Middle Band (20)
-   Stop: 1 ATR beyond the BB band

#### B. RSI Divergence Reversal
**1H 조건**:
-   Bullish Divergence: Price makes Lower Low, RSI makes Higher Low
-   Bearish Divergence: Price makes Higher High, RSI makes Lower High

**15m Entry**:
-   Divergence 확인 후 RSI가 방향 전환 시작할 때

### 4.4 Low Volatility Squeeze Strategies

#### A. Bollinger-Keltner Squeeze Breakout
**1H 조건**:
-   BB(20, 2.0) 상단/하단이 Keltner Channel(20, 1.5 ATR) 내부로 수축
-   Squeeze 해제 시 (BB가 KC 외부로 확장)
-   **방향 결정**: Momentum Oscillator(12) 부호로 판단

**15m Entry**:
-   Squeeze 해제 첫 15m Bar의 방향으로 진입
-   Volume > 2× avg 확인

#### B. Volume Spike Breakout
**1H 조건**:
-   Volume > SMA(20) × 3.0 (극단적 볼륨)
-   Price가 최근 10bar 레인지 돌파

**15m Entry**:
-   돌파 방향 1st pullback에서 진입

## 5. Cross-Asset Signals (BTC ↔ ETH)

### 5.1 Correlation-Based Adjustments
-   **Rolling Correlation(48H)** 모니터링
-   `Corr > 0.85`: 동일 방향 시그널 → 양쪽 모두 진입 (높은 확신)
-   `Corr 0.5-0.85`: 독립적 판단 (각 자산별 시그널 기준)
-   `Corr < 0.5`: Pair Divergence 기회 탐색 (하나 Long, 하나 Short)

### 5.2 Leader-Follower
-   BTC가 먼저 Breakout/Breakdown → ETH에서 Follow-through 시그널 대기
-   ETH/BTC ratio가 극단값(±2σ) → Mean Reversion 진입

### 5.3 Confidence Multiplier
시그널 강도에 따라 포지션 사이즈 조정:
| 조건 | Confidence | Size Multiplier |
|---|---|---|
| 부정적 신호 (On-Chain/Funding 역풍) | Dampened | 0.5× |
| 단일 자산 시그널 | Normal | 1.0× |
| 양쪽 자산 동일 방향 확인 | High | 1.5× |
| Cross-Asset + On-Chain 확인 | Very High | 2.0× |

**중요**: Confidence Multiplier 적용 후에도 **단일 포지션 마진 25% 상한 유지** (초과 시 25%로 캡)

## 6. Position Management

### 6.1 Position Sizing (공격적, 레버리지 반영)
```
Base Risk = 3% of Equity per trade
Size (USD) = (Equity × 0.03) / (1.5 × ATR(14))
Asset Quantity = Size (USD) / Current Price
Required Margin = Size (USD) / Leverage(5×)
```
-   Stop Width: **1.5 ATR** (기존 2 ATR 대비 공격적)
-   단일 포지션 최대 명목가치: Equity의**125%** (= Equity 25% × 5× Leverage)
-   단일 포지션 최대 마진: Equity의 **25%**
-   *Note: 레버리지는 자본 효율성 용도. 포지션 명목가치가 아닌 마진 기준으로 리스크 관리.*

### 6.2 Pyramiding (추가 진입 - Trending Regime Only)
-   **적용 조건**: 현재 Regime이 **Trending Bull** 또는 **Trending Bear**일 때만 허용
-   **수익 조건**: 기존 포지션이 **1.5R 이상 수익** 중일 때
-   **추가 사이즈**: 초기 사이즈의 **50%**
-   **최대 추가**: 1회만 (총 2단계: 100% + 50% = 150%)
-   **평균 단가 재계산**:
    ```
    새 평균가 = (Entry1 × Size1 + Entry2 × Size2) / (Size1 + Size2)
    ```
-   **손절 재계산**:
    ```
    Long: 새 Stop = 평균 단가 - 1.5 × ATR(14)
    Short: 새 Stop = 평균 단가 + 1.5 × ATR(14)
    ```
-   **R 기준 재계산**:
    ```
    피라미딩 후 1R = 재계산된 Stop 거리 (평균가 기준 1.5 ATR)
    Partial TP의 2R/3R/4R은 새 평균가 + 새 R 기준으로 계산
    ```
-   **Trailing Stop**: 전체 포지션 기준 최고점/최저점에서 2 ATR 추적
-   **제한사항**:
    -   Mean Reversion 전략 (State 3): 피라미딩 금지
    -   Squeeze Breakout 전략 (State 4): 피라미딩 금지
    -   **Partial TP 후 피라미딩 금지**: 포지션 일부 청산 시작 후에는 추가 진입 불가
    -   피라미딩 이후 Regime이 Chop/Squeeze로 전환되어도 기존 포지션 유지 (Stop/TP가 관리)

### 6.3 Concurrent Positions
| 항목 | 제한 |
|---|---|
| 자산별 최대 포지션 | 1 (Pyramid 포함 시 최대 2단계) |
| 전체 최대 포지션 | **2 (BTC 1개 + ETH 1개)** |
| 전체 최대 마진 사용 | Equity의 **50%** (2 positions × 25% each) |
| 전체 최대 명목가치 | Equity의 **250%** (= 50% × 5× Leverage) |
| 동일 방향 최대 | 2 (BTC + ETH both Long or both Short) |

### 6.4 Cooldown
-   **손실 청산 후**: 30분 (2 × 15m bars)
-   **수익 청산 후**: 15분 (1 × 15m bar)
-   **Regime 전환 후**: 8시간 (2 × 4H bars)
-   **적용 시점**: 포지션 **전량 청산** 시에만 적용 (Partial TP에는 미적용)

## 7. Exit & Risk Management

### 7.1 Initial Stop Loss
-   **Stop Width**: 1.5 × ATR(14) (Entry Price 기준)
-   **Long**: Entry - 1.5 ATR
-   **Short**: Entry + 1.5 ATR

### 7.2 Trailing Stop (Chandelier Exit)
-   **활성화**: 수익 > 1R
-   **Trail**: Highest High(Long) / Lowest Low(Short) 기준 2 ATR
-   **업데이트 주기**: 매 15m Bar Close
-   **단, Mean Reversion 전략 (State 3)**: Trailing Stop 미사용, 고정 TP만

### 7.3 Take Profit (Partial Exit)
수익 극대화를 위한 분할 청산:
| 수익 도달 | 청산 비율 | 잔여 포지션 |
|---|---|---|
| 2R | 40% | 60% |
| 3R | 30% | 30% |
| 4R+ | Trail | Trailing Stop까지 보유 |

**Mean Reversion (State 3) 전용**:
| Target | 청산 비율 |
|---|---|
| BB Middle Band | 60% |
| 반대편 BB(1σ) | 40% |

### 7.4 Time Stop
-   **Trending 전략**: 24시간(96 × 15m bars) 내 1R 미도달 시 청산
-   **Mean Reversion**: 12시간(48 × 15m bars) 내 TP 미도달 시 청산
-   **Squeeze Breakout**: 6시간(24 × 15m bars) 내 1R 미도달 시 청산

### 7.5 Regime Change Exit
-   **Trending Bull → Trending Bear** (또는 반대): 즉시 전 포지션 Market Close
-   **Trending → Chop/Squeeze**: 기존 포지션 유지, Trailing Stop이 관리
-   **Chop/Squeeze → Trending**: 기존 Mean Reversion 포지션의 Stop 타이트닝 (1 ATR로 축소)

### 7.6 Liquidation Defense (선물 전용)
-   **Isolated Margin** 모드이므로 각 포지션별 청산가 독립 관리
-   **청산가 버퍼**: 진입 시 청산가 대비 최소 **3 ATR** 이상 거리 확보
-   **마진 비율 모니터링**: 포지션 마진 비율 > 80% → 포지션 50% 축소
-   **ADL(Auto-Deleveraging) 방어**: 미실현 수익 큰 포지션은 분할 청산으로 ADL 리스크 완화

## 8. Global Risk Controls

### 8.1 Drawdown Limits
| Level | 조치 |
|---|---|
| DD > 15% | 포지션 사이즈 50%로 축소 |
| DD > 20% | 신규 진입 중단, 기존 포지션만 관리 |
| DD > 30% | 전 포지션 청산, 전략 완전 정지 |

### 8.2 Daily Loss Limit
-   일일 손실 > **Equity의 5%** → 당일 신규 진입 중단 (UTC 기준)
-   익일 00:00 UTC에 리셋

### 8.3 Volatility Scaling
-   ATR Percentile > 90th → 포지션 사이즈 **50%로 축소** (극단적 변동성)
-   ATR Percentile > 95th → **신규 진입 중단** (Black Swan 방어)

### 8.4 Correlation Risk
-   BTC-ETH Correlation > 0.9 → 전체 마진 합계를 **Equity 40%로 제한** (기본 50% → 40% 축소)
-   *이유: 높은 상관관계 = 사실상 단일 포지션과 동일한 리스크*

### 8.5 Funding Rate Risk
-   **Funding Rate > ±0.1%**: 해당 방향 신규 진입 시 Confidence -1 (비용 부담 큼)
-   **Funding Rate > ±0.3%**: 해당 방향 신규 진입 중단 (극단적 Funding 비용)
-   **포지션 보유 시**: 8시간마다 Funding 비용/수익을 P&L에 반영
-   *Note: 역방향 포지션(Funding 수취 측)은 Confidence +1 보너스*

### 8.6 Leverage & Liquidation Risk
-   **레버리지**: 5× 고정 (변경 금지)
-   **마진 모드**: Isolated (포지션 간 리스크 격리)
-   **계좌 잔고 대비 총 마진 사용률 > 50%**: 신규 진입 중단 (전체 최대 마진 한도)
-   **개별 포지션 마진 비율 > 80%**: 해당 포지션 50% 강제 축소

## 9. On-Chain & Funding Signals (Enhanced Layer)

Core 전략은 가격 데이터 + Funding Rate로 동작. On-Chain은 **신호 강도 조정** 용도.

### 9.1 Signal Boosters (Confidence +1 Level)
-   **Exchange Netflow < 0** (순유출): Long 시그널 강화
-   **MVRV Z-Score < 0**: 역사적 저평가 구간 → Long 강화
-   **SOPR < 1.0**: 손실 매도 구간 → Contrarian Long 강화
-   **Whale Tx Count 급증 + Price 상승**: 대형 매수 확인 → Long 강화

### 9.2 Signal Dampeners (Confidence -1 Level)
-   **Exchange Netflow > 0** (순유입): Long 시그널 약화 / Short 강화
-   **MVRV Z-Score > 3**: 역사적 과열 → Long 약화
-   **Funding Rate > 0.05%**: 과도한 롱 포지션 → Long 주의 (OKX 실시간 Funding Rate 사용)
-   **SOPR > 1.05**: 차익 실현 구간 → 신규 Long 자제

### 9.3 Confidence → Size Mapping
| Confidence Level | Size Multiplier |
|---|---|
| Dampened (-1) | 0.5× |
| Normal (0) | 1.0× |
| Boosted (+1) | 1.5× |
| Strong (+2) | 2.0× |

## 10. Required Indicators

### 10.1 Trend & Momentum
-   EMA: 9, 20, 50, 200
-   RSI: 14
-   ADX: 14 (with +DI, -DI)
-   Momentum Oscillator: 12

### 10.2 Volatility
-   ATR: 14 (+ Percentile Rank over 50 bars)
-   Bollinger Bands: (20, 2.0) and (20, 2.5)
-   Keltner Channel: (20, 1.5 × ATR)
-   BB Width Percentile: 50 bars

### 10.3 Structure
-   Donchian Channel: 20
-   Volume SMA: 20

### 10.4 Cross-Asset
-   BTC-ETH Rolling Correlation: 48 bars (4H 기준)
-   ETH/BTC Ratio: Bollinger Bands(20, 2.0)

## 11. Backtest Parameters
-   **Period**: 2025-02-01 to 2026-02-01 (1 Year)
-   **Exchange**: OKX
-   **Assets**: BTC/USDT-SWAP, ETH/USDT-SWAP (Perpetual Futures)
-   **Timeframes**: 4H, 1H, 15m
-   **Initial Capital**: $100,000 (USDT)
-   **Leverage**: 5× (Isolated Margin)
-   **Order Type**: Market Orders
-   **Fees**: 0.05% per trade (OKX Taker Fee, Tier 1 기준)
-   **Slippage**: 0.02% per trade (고빈도 매매 반영)
-   **Funding Rate**: 8시간마다 정산 (OKX 히스토리컬 Funding Rate 데이터 사용)
    -   Long 포지션: Funding > 0이면 비용 지불, Funding < 0이면 수취
    -   Short 포지션: Funding > 0이면 수취, Funding < 0이면 비용 지불
-   **Liquidation**: Isolated 모드 청산가 시뮬레이션 포함

## 12. Walk-Forward Validation
-   **Method**: Anchored Walk-Forward
-   **Split**: 70% In-Sample / 30% Out-of-Sample
-   **Optimization Objective**: Maximize CAGR while DD < 30%
-   **Stability Check**: OOS Profit Factor > 1.5, OOS Win Rate > 45%
-   **Parameter Sensitivity**: ±20% 변동에도 성과 유지 확인

## 13. Implementation Plan
1.  **Data Pipeline** (`data/pipeline.py`):
    -   OKX API (`ccxt` 라이브러리) 통한 BTC/USDT-SWAP, ETH/USDT-SWAP 15m/1H/4H OHLCV 수집
    -   OKX Funding Rate 히스토리 수집 (`/api/v5/public/funding-rate-history`)
    -   전체 Indicator 계산 (Section 10 참조)
    -   Cross-Asset Correlation 계산
    -   ATR/BB Width Percentile 계산
2.  **Regime Engine** (`strategies/regime.py`):
    -   4H Regime 분류 로직
    -   Regime 전환 감지 및 쿨다운 관리
3.  **Strategy Module** (`strategies/raaa_strategy.py`):
    -   Regime별 Entry 로직 (Section 4)
    -   Cross-Asset Signal 처리 (Section 5)
    -   Position/Exit Management (Section 6-7)
    -   레버리지 반영 포지션 사이징 (Section 6.1)
4.  **Risk Manager** (`strategies/risk_manager.py`):
    -   Global Risk Controls (Section 8)
    -   Drawdown/Daily Limit 모니터링
    -   Volatility/Correlation Scaling
    -   Funding Rate 비용 관리 (Section 8.5)
    -   청산 방어 로직 (Section 7.6, 8.6)
    -   **Position Limit 관리**: 전체 2-position (BTC 1 + ETH 1), 전체 마진 50% 한도 적용
    -   **Confidence Multiplier 마진 캡**: Confidence 적용 후 단일 포지션 마진 25% 초과 시 제한
5.  **Backtest Engine** (`backtest/engine.py`):
    -   Multi-asset 동시 시뮬레이션
    -   Partial Exit 지원
    -   Pyramiding 지원
    -   **Funding Rate 정산 시뮬레이션** (8시간 주기)
    -   **Isolated Margin 청산가 시뮬레이션**
6.  **On-Chain Module** (`data/onchain.py`) - Optional:
    -   API Integration (Glassnode/CryptoQuant)
    -   Confidence Score 계산
7.  **Optimization** (`results/optimization_report.md`):
    -   Walk-Forward 최적화
    -   Parameter Stability Analysis
