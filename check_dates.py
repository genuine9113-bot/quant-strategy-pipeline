import pandas as pd
from pathlib import Path

data_dir = Path("data/processed")
files = list(data_dir.glob("*.parquet"))

for f in files:
    try:
        df = pd.read_parquet(f)
        if "Date" in df.columns:
            start = df["Date"].min()
            end = df["Date"].max()
            count = len(df)
            print(f"{f.name}: {start} to {end} ({count} rows)")
    except Exception as e:
        print(f"Error reading {f.name}: {e}")
