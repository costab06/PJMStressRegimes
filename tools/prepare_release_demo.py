"""Generate synthetic hourly data for the offline demonstration (not PJM observations)."""
from pathlib import Path
import pandas as pd

def make_fixture(path):
    path = Path(path)
    hours = pd.date_range("2026-07-02T00:00:00Z", periods=25, freq="h")
    data = pd.DataFrame({
        "timestamp_utc": hours,
        "demand_mwh": [90000 + 200*i + (1000 if i >= 12 else 0) for i in range(25)],
        "forecast_mwh": [90000 + 180*i for i in range(25)],
        "interchange_mwh": [-500 + 15*i for i in range(25)],
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(path, index=False)
    return path

if __name__ == "__main__":
    print("SYNTHETIC DATA ONLY:", make_fixture("data/raw/eia930/PJM_2026-07.parquet"))
