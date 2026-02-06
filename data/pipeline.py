"""
BTC Volatility Breakout Strategy - Data Pipeline
OKX API를 통한 데이터 수집 및 인디케이터 계산
"""

import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class DataPipeline:
    """OKX 데이터 수집 및 인디케이터 계산 파이프라인"""

    def __init__(self):
        self.exchange = ccxt.okx({
            "enableRateLimit": True,
            "options": {"defaultType": "swap"}
        })
        self.symbol = "BTC/USDT:USDT"
        self.data_dir = Path(__file__).parent

    def fetch_ohlcv(
        self, timeframe: str, start_date: str, end_date: str, max_retries: int = 3
    ) -> pd.DataFrame:
        """
        OKX에서 OHLCV 데이터 수집

        Args:
            timeframe: 캔들 타임프레임 ('15m', '1h', '1d')
            start_date: 시작 날짜 (YYYY-MM-DD)
            end_date: 종료 날짜 (YYYY-MM-DD)
            max_retries: 최대 재시도 횟수

        Returns:
            OHLCV DataFrame
        """
        logger.info(f"Fetching {timeframe} OHLCV from {start_date} to {end_date}")

        start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
        end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)

        all_data = []
        current_ts = start_ts

        while current_ts < end_ts:
            for attempt in range(max_retries):
                try:
                    ohlcv = self.exchange.fetch_ohlcv(
                        self.symbol,
                        timeframe=timeframe,
                        since=current_ts,
                        limit=300
                    )
                    if not ohlcv:
                        break
                    all_data.extend(ohlcv)
                    current_ts = ohlcv[-1][0] + 1
                    time.sleep(0.1)  # Rate limit
                    break
                except Exception as e:
                    logger.warning(f"Attempt {attempt + 1} failed: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                    else:
                        raise

            if not ohlcv:
                break

        df = pd.DataFrame(
            all_data,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df[df["timestamp"] < end_date].drop_duplicates(subset=["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        logger.info(f"Fetched {len(df)} {timeframe} bars")
        return df

    def fetch_funding_rates(
        self, start_date: str, end_date: str, max_retries: int = 3
    ) -> pd.DataFrame:
        """펀딩 레이트 히스토리 수집"""
        logger.info(f"Fetching funding rates from {start_date} to {end_date}")

        start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
        end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)

        all_data = []
        current_ts = start_ts

        while current_ts < end_ts:
            for attempt in range(max_retries):
                try:
                    # OKX funding rate history
                    params = {"instId": "BTC-USDT-SWAP", "before": str(current_ts)}
                    response = self.exchange.publicGetPublicFundingRateHistory(params)
                    data = response.get("data", [])
                    if not data:
                        break
                    all_data.extend(data)
                    current_ts = int(data[-1]["fundingTime"]) + 1
                    time.sleep(0.1)
                    break
                except Exception as e:
                    logger.warning(f"Funding rate attempt {attempt + 1} failed: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                    else:
                        # 펀딩 데이터 실패 시 빈 DataFrame 반환
                        logger.warning("Failed to fetch funding rates, using empty data")
                        return pd.DataFrame(columns=["timestamp", "funding_rate"])

            if not data:
                break

        if not all_data:
            return pd.DataFrame(columns=["timestamp", "funding_rate"])

        df = pd.DataFrame(all_data)
        df["timestamp"] = pd.to_datetime(df["fundingTime"].astype(int), unit="ms", utc=True)
        df["funding_rate"] = df["fundingRate"].astype(float)
        df = df[["timestamp", "funding_rate"]].drop_duplicates(subset=["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        logger.info(f"Fetched {len(df)} funding rate records")
        return df

    def calculate_indicators(
        self, df_15m: pd.DataFrame, df_1h: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        """
        인디케이터 계산 및 15m 데이터에 병합

        Args:
            df_15m: 15분봉 데이터
            df_1h: 1시간봉 데이터
            df_daily: 일봉 데이터

        Returns:
            인디케이터가 추가된 15m DataFrame
        """
        logger.info("Calculating indicators...")

        # 1H 인디케이터 계산
        df_1h = df_1h.copy()
        df_1h["atr_14"] = self._calculate_atr(df_1h, period=14)
        df_1h["ema_50"] = df_1h["close"].ewm(span=50, adjust=False).mean()

        # Daily Range 계산
        df_daily = df_daily.copy()
        df_daily["daily_range"] = df_daily["high"] - df_daily["low"]
        # range_pct_20: 전일 Range가 최근 20일 중 몇 번째 백분위인지 (높을수록 변동성 높음)
        df_daily["range_pct_20"] = df_daily["daily_range"].rolling(20).apply(
            lambda x: (x.rank(pct=True).iloc[-1] * 100) if len(x) == 20 else np.nan,
            raw=False
        )
        df_daily["today_open"] = df_daily["open"]
        df_daily["yesterday_range"] = df_daily["daily_range"].shift(1)

        # 15m 데이터에 1H 인디케이터 병합
        df_15m = df_15m.copy()
        df_15m["hour_ts"] = df_15m["timestamp"].dt.floor("h")
        df_1h["hour_ts"] = df_1h["timestamp"].dt.floor("h")

        df_15m = df_15m.merge(
            df_1h[["hour_ts", "atr_14", "ema_50"]].rename(
                columns={"atr_14": "atr_14_1h", "ema_50": "ema_50_1h"}
            ),
            on="hour_ts",
            how="left"
        )
        # Forward fill 1H indicators
        df_15m["atr_14_1h"] = df_15m["atr_14_1h"].ffill()
        df_15m["ema_50_1h"] = df_15m["ema_50_1h"].ffill()

        # 15m 데이터에 Daily 인디케이터 병합
        df_15m["date"] = df_15m["timestamp"].dt.date
        df_daily["date"] = df_daily["timestamp"].dt.date

        df_15m = df_15m.merge(
            df_daily[["date", "daily_range", "range_pct_20", "today_open", "yesterday_range"]],
            on="date",
            how="left"
        )

        # Breakout triggers 계산 (k=0.5 기본값)
        k = 0.5
        df_15m["long_trigger"] = df_15m["today_open"] + k * df_15m["yesterday_range"]
        df_15m["short_trigger"] = df_15m["today_open"] - k * df_15m["yesterday_range"]

        # 정리
        df_15m = df_15m.drop(columns=["hour_ts", "date"])

        logger.info(f"Indicators calculated for {len(df_15m)} bars")
        return df_15m

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average True Range 계산"""
        high = df["high"]
        low = df["low"]
        close = df["close"].shift(1)

        tr1 = high - low
        tr2 = abs(high - close)
        tr3 = abs(low - close)

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(span=period, adjust=False).mean()
        return atr

    def merge_funding_rates(
        self, df: pd.DataFrame, df_funding: pd.DataFrame
    ) -> pd.DataFrame:
        """펀딩 레이트를 15m 데이터에 병합"""
        if df_funding.empty:
            df["funding_rate"] = 0.0
            return df

        df = df.copy()
        df_funding = df_funding.copy()

        # 펀딩 타임스탬프를 8시간 단위로 정렬
        df["funding_ts"] = df["timestamp"].dt.floor("8h")
        df_funding["funding_ts"] = df_funding["timestamp"].dt.floor("8h")

        df = df.merge(
            df_funding[["funding_ts", "funding_rate"]],
            on="funding_ts",
            how="left"
        )
        df["funding_rate"] = df["funding_rate"].ffill().fillna(0)
        df = df.drop(columns=["funding_ts"])

        return df

    def run(
        self,
        start_date: str = "2025-02-01",
        end_date: str = "2026-02-01",
        save: bool = True
    ) -> pd.DataFrame:
        """
        전체 파이프라인 실행

        Args:
            start_date: 시작 날짜
            end_date: 종료 날짜
            save: 파일 저장 여부

        Returns:
            최종 DataFrame
        """
        logger.info(f"Running pipeline from {start_date} to {end_date}")

        # 워밍업 기간 추가 (EMA 50 + Range Percentile 20)
        warmup_start = (
            datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=60)
        ).strftime("%Y-%m-%d")

        # 데이터 수집
        df_15m = self.fetch_ohlcv("15m", warmup_start, end_date)
        df_1h = self.fetch_ohlcv("1h", warmup_start, end_date)
        df_daily = self.fetch_ohlcv("1d", warmup_start, end_date)
        df_funding = self.fetch_funding_rates(warmup_start, end_date)

        # 인디케이터 계산
        df = self.calculate_indicators(df_15m, df_1h, df_daily)
        df = self.merge_funding_rates(df, df_funding)

        # 워밍업 기간 제거
        df = df[df["timestamp"] >= start_date].reset_index(drop=True)

        # 결측치 확인
        missing = df.isnull().sum()
        if missing.any():
            logger.warning(f"Missing values:\n{missing[missing > 0]}")

        # 저장
        if save:
            output_path = self.data_dir / "btc_vb_data.parquet"
            df.to_parquet(output_path, index=False)
            logger.info(f"Saved to {output_path}")

        return df


if __name__ == "__main__":
    pipeline = DataPipeline()
    df = pipeline.run()
    print(f"\nData shape: {df.shape}")
    print(f"\nColumns: {df.columns.tolist()}")
    print(f"\nDate range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"\nSample data:")
    print(df.head())
