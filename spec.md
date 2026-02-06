# Volatility Breakout Strategy Spec (BTC) — OKX Perpetual Futures
> **v1.1** — 리뷰 반영, BTC 단일 자산 단순화

---

## 0) 개요

**전략 한 줄 요약**: 전일 변동폭(Range)의 k배를 당일 시가에 더한 가격을 돌파하면 진입, ATR 기반으로 청산.

**핵심 원칙**:
- 파라미터 최소화 (핵심 파라미터 k값 1개)
- 단일 자산 (BTC), 단일 타임프레임 신호
- 매일 기회 탐색, 방향별 하루 1회 진입 (최대 Long 1 + Short 1 = 2회)
- 피라미딩 금지

**운용 조건**:
- 거래소: OKX (USDT-Margined Perpetual Swap)
- 자산: BTC/USDT-SWAP
- 방향: Long & Short
- 레버리지: 3× (Isolated Margin)
- 초기 자본: $10,000

---

## 1) 데이터

### 1.1 캔들
- **15m OHLCV**: 돌파 신호 감지, 진입 실행, SL/TP 모니터링
- **1H OHLCV**: 인디케이터 계산 (ATR, EMA)
- **Daily OHLCV**: 전일 Range 계산

### 1.2 인디케이터
| 인디케이터 | 타임프레임 | 용도 |
|---|---|---|
| ATR(14) | 1H | 손절/익절 거리 |
| EMA(50) | 1H | 방향 필터 |
| Volume SMA(20) | 1H | 거래량 필터 (선택) |
| Daily Range | Daily | 돌파 레벨 계산 |
| Daily Range 20일 Percentile | Daily | 노이즈 필터 (최근 20일 Range 중 순위) |

### 1.3 펀딩 레이트
- 수집: OKX `/api/v5/public/funding-rate-history`
- 정산: 8H (00:00, 08:00, 16:00 UTC)
- 기준: **현재 Predicted Funding Rate** 사용
- 용도: P&L 반영, 극단 펀딩 시 진입 제한

---

## 2) 핵심 로직

### 2.1 일간 기준 정의
- **1일(Day)**: UTC 00:00 ~ 23:59
- **당일 시가(today_open)**: UTC 00:00 시점의 가격
- **전일 Range**: `yesterday_high - yesterday_low` (UTC 기준 전일)

### 2.2 돌파 레벨 계산 (매일 UTC 00:00에 갱신)
```
long_trigger  = today_open + k * yesterday_range
short_trigger = today_open - k * yesterday_range
```
- `k`: 0.5 (기본값, 최적화 대상)
- 범위: 0.3 ~ 0.7에서 탐색

### 2.3 신호 판정 (매 15m 봉 마감 시)
```
Long Signal:  close_15m >= long_trigger
Short Signal: close_15m <= short_trigger
```
- 같은 방향 재진입: 하루 1회 (실패한 동일 신호 재배팅 방지)
- 반대 방향 진입: 허용 (쿨다운 충족 시)
- 하루 최대 거래: 2회 (Long 1회 + Short 1회)

---

## 3) 진입 규칙

### 3.1 방향 필터
```
Long 허용:  latest_1h_close > EMA(50)_1h
Short 허용: latest_1h_close < EMA(50)_1h
```
- 돌파 신호가 발생해도 방향 필터와 불일치하면 진입하지 않음
- EMA(50)는 가장 최근 확정된 1H 봉 기준

### 3.2 노이즈 필터
```
yesterday_range < 20th percentile(최근 20일 Daily Range) → 진입 스킵
```
- 전일 변동폭이 극단적으로 작으면 의미 없는 돌파 가능성 높음

### 3.3 펀딩 필터
```
|current_predicted_funding| > 0.30% → 해당 방향 신규 진입 금지
```
- Long 진입 시: predicted funding > +0.30%이면 스킵
- Short 진입 시: predicted funding < -0.30%이면 스킵

### 3.4 진입 실행
- 신호 발생한 15m 봉 마감 시점에 시장가 진입
- 진입과 동시에 손절/익절 가격 설정

---

## 4) 청산 규칙

### 4.1 손절 (Stop Loss)
```
Long:  entry_price - 1.5 * ATR(14)_1h
Short: entry_price + 1.5 * ATR(14)_1h
```

### 4.2 익절 (Take Profit)
```
Long:  entry_price + 2.5 * ATR(14)_1h
Short: entry_price - 2.5 * ATR(14)_1h
```

### 4.3 시간 청산 (Time Stop)
```
진입 후 24시간 경과 시 → 현재가로 전량 청산
```
- 24시간 내 SL/TP 미도달 = 돌파 모멘텀 소멸로 판단

### 4.4 SL/TP 모니터링 (15m 기반)
- 매 15m 봉의 High/Low로 SL/TP 도달 여부 판정
- SL 판정: Low ≤ SL (Long) 또는 High ≥ SL (Short)
- TP 판정: High ≥ TP (Long) 또는 Low ≤ TP (Short)
- **동일 15m 봉에서 SL/TP 동시 도달 시**: SL 우선 (보수적 처리)

### 4.5 청산 우선순위
```
1순위: 손절 (SL 도달 시 즉시)
2순위: 익절 (TP 도달 시 즉시)
3순위: 시간 청산 (24H 경과)
```

### 4.6 청산 실행
- 손절: 시장가
- 익절: 시장가
- 시간 청산: 시장가

---

## 5) 포지션 사이징

### 5.1 기본 공식
```
risk_per_trade = 1.5% * NAV
sl_distance = 1.5 * ATR(14)_1h
sl_distance_pct = sl_distance / entry_price

position_size_usd = risk_per_trade / sl_distance_pct
margin_required = position_size_usd / leverage(3)
```

### 5.2 사이즈 제한
```
max_margin = 25% * NAV
max_notional = 75% * NAV  (= 25% * 3×)

if margin_required > max_margin:
    position_size_usd = max_margin * leverage
```
> **참고**: BTC의 일반적 ATR(14)_1H 수준($200~$800)에서는 마진 캡(25%)이 대부분 binding됨.
> 고변동성 구간(ATR > ~$1,100)에서만 리스크 공식이 직접 사이즈를 결정.
> 이는 의도된 설계로, 마진 캡이 최대 노출을 제한하는 안전장치 역할.

### 5.3 예시 ($10,000 계좌, BTC $80,000, ATR 1H = $400)
```
risk = $10,000 * 1.5% = $150
sl_distance = 1.5 * $400 = $600
sl_pct = $600 / $80,000 = 0.75%
position_size = $150 / 0.0075 = $20,000 (0.25 BTC)
margin = $20,000 / 3 = $6,667

→ 마진 한도 $2,500(25%) 초과 → 축소
→ 실제 포지션 = $2,500 * 3 = $7,500 (0.094 BTC)
→ 실제 리스크 = $7,500 * 0.75% = $56.25 (0.56% NAV)
```

---

## 6) 리스크 관리

### 6.1 포지션 한도
- 동시 포지션: 최대 1개
- 최대 마진: NAV 25%
- 최대 명목가치: NAV 75% (= 25% × 3×)

### 6.2 Drawdown 3단계
| 단계 | 조건 | 조치 |
|---|---|---|
| 1단계 | DD ≥ 8% | risk_per_trade 50% 축소 |
| 2단계 | DD ≥ 13% | 신규 진입 중지, 기존 관리만 |
| 3단계 | DD ≥ 18% | 전 포지션 청산, 전략 정지 → **운영자 수동 해제 시까지 유지** |

```
DD = (Peak_NAV - Current_NAV) / Peak_NAV
```

### 6.3 일간 가드레일
- 일 손실 ≥ 2.5% NAV 시 → 당일 신규 진입 중지 (UTC 기준 리셋)
- 당일 2거래 모두 손절 시 → 당일 추가 진입 중지
- 직전 4거래 연속 손절 시 → 다음 24시간 진입 중지

### 6.4 쿨다운
- 손절 청산 후: 2시간 대기
- 시간 청산 후: 1시간 대기
- 익절 청산 후: 쿨다운 없음

---

## 7) 실행 / 비용 모델

### 7.1 주문
- 진입: 시장가
- 청산: 시장가 (SL/TP/시간청산 모두)

### 7.2 비용 (백테스트 기준)
| 항목 | 값 |
|---|---|
| Taker 수수료 | 0.05% |
| 슬리피지 | 0.03% |
| 펀딩 | 8H 실데이터 반영 |

> 모든 주문이 시장가이므로 Maker 수수료 불필요.

### 7.3 청산(Liquidation) 방어
```
liq_price (Long) = entry * (1 - 1/leverage + maintenance_margin_rate)
```
- 진입 시 청산가까지 거리가 3 × ATR 미만이면 사이즈 축소
- **참고**: 3× 레버리지에서 청산가 거리 ≈ 33%로, SL(~0.75%)보다 훨씬 멀어 실질 트리거 가능성 극히 낮음. 안전장치로 유지.

---

## 8) 백테스트

### 8.1 기간
- 전체: 2025-02-01 ~ 2026-02-01
- 워밍업: EMA(50) ≈ 50 × 1H bars + Daily Range Percentile ≈ 20 Daily bars
- **실 시작: ~2025-02-21** (워밍업 약 20일 소요)

### 8.2 검증 방법
- **Anchored Walk-Forward**: 초기 IS 180일, OOS 60일, 60일 단위 전진
  - Fold 1: IS Day 1~180, OOS Day 181~240
  - Fold 2: IS Day 1~240, OOS Day 241~300
  - Fold 3: IS Day 1~300, OOS Day 301~365
- k값 최적화는 IS 구간에서만 수행

### 8.3 합격 기준 (OOS)
| 지표 | 최소 기준 | 목표 |
|---|---|---|
| Profit Factor | > 1.3 | > 1.6 |
| Win Rate | > 45% | > 52% |
| Max DD | < 20% | < 15% |
| CAGR | > 20% | > 50% |
| 강제 청산 | 0회 | 0회 |

### 8.4 안정성 체크
- k값 ±0.1 변동 시 성과 급변 여부 확인
- ATR 배수 ±20% 변동 시 성과 급변 여부 확인

---

## 부록 A) 파라미터 요약

| 카테고리 | 파라미터 | 기본값 | 최적화 범위 |
|---|---|---|---|
| 핵심 | k (돌파 계수) | 0.5 | 0.3 ~ 0.7 |
| 손절 | SL ATR 배수 | 1.5 | 1.0 ~ 2.5 |
| 익절 | TP ATR 배수 | 2.5 | 2.0 ~ 4.0 |
| 시간 | Time Stop | 24H | 12H ~ 36H |
| 필터 | EMA 기간 | 50 | 20 ~ 100 |
| 필터 | Range Percentile 기준 | 20th | 10 ~ 30 |
| 사이징 | risk_per_trade | 1.5% | 1.0 ~ 2.5% |
| 사이징 | max_margin | 25% | 20 ~ 30% |
| 리스크 | DD 1단계 | 8% | 고정 |
| 리스크 | DD 2단계 | 13% | 고정 |
| 리스크 | DD 3단계 | 18% | 고정 (수동 해제) |
| 실행 | 레버리지 | 3× | 고정 |
| 쿨다운 | 손절 후 대기 | 2H | 1 ~ 4H |

> **최적화 대상**: k, SL/TP ATR 배수, Time Stop, EMA 기간 (총 5개)
> **고정 파라미터**: DD 단계, 레버리지, 포지션 한도 (리스크 관리는 건드리지 않음)

---

## 부록 B) v2 확장 후보
- ETH/USDT-SWAP 추가 (멀티 에셋 확장)
- Funding Rate Exploitation 엔진
- 세션별 k값 분리 (아시아/유럽/미국)
- 거래량 가중 돌파 레벨
- 변동성 국면별 k값 자동 조절
