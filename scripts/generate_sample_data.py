#!/usr/bin/env python3
"""Generate synthetic contact center data for WFM Reforecast Engine testing.

Outputs:
    data/forecast.csv — 5 weeks of interval-level forecasts for 3 LOBs
    data/actuals.csv  — 5 weeks of interval-level actuals with realistic deviations

All data is synthetic and clearly labeled as such.
"""

from __future__ import annotations

import logging
import os
from typing import List

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Configuration
WEEKS = 5
INTERVAL_MINUTES = 30
INTERVALS_PER_DAY = 30  # 08:00 to 23:00
LOB_CONFIG = {
    "inbound_calls": {
        "base_daily_volume": 1200,
        "aht": 280,
        "peak_factor": 1.8,
        "noise_pct": 0.12,
    },
    "email": {
        "base_daily_volume": 400,
        "aht": 180,
        "peak_factor": 1.3,
        "noise_pct": 0.15,
    },
    "chat": {
        "base_daily_volume": 600,
        "aht": 120,
        "peak_factor": 1.5,
        "noise_pct": 0.10,
    },
}

WEEKDAY_FACTORS = {
    "Monday": 1.15,
    "Tuesday": 1.05,
    "Wednesday": 1.00,
    "Thursday": 1.00,
    "Friday": 1.08,
    "Saturday": 0.55,
    "Sunday": 0.40,
}

# Intraday profile: typical 30-min interval multipliers (08:00-23:00, 30 intervals)
INTRADAY_PROFILE = [
    0.30, 0.40, 0.55, 0.65, 0.75, 0.85,  # 08:00-10:30
    0.95, 1.15, 1.30, 1.40, 1.45, 1.50,  # 10:30-13:00
    1.45, 1.40, 1.35, 1.30, 1.25, 1.20,  # 13:00-15:30
    1.15, 1.10, 1.05, 1.00, 0.95, 0.90,  # 15:30-18:00
    0.80, 0.70, 0.60, 0.50, 0.45, 0.40,  # 18:00-20:30
    0.35, 0.30, 0.25, 0.20,              # 20:30-22:30 (partial)
]


def generate_dates() -> List[pd.Timestamp]:
    """Generate 5 weeks of dates (Mon-Sun, starting Monday)."""
    start = pd.Timestamp("2026-05-04")  # A Monday
    return [start + pd.Timedelta(days=i) for i in range(WEEKS * 7)]


def generate_interval_times() -> List[str]:
    """Generate interval_start strings (HH:MM format)."""
    start_hour = 8
    end_hour = 23
    times: List[str] = []
    hour = start_hour
    minute = 0
    while hour < end_hour or (hour == end_hour and minute == 0):
        times.append(f"{hour:02d}:{minute:02d}")
        minute += INTERVAL_MINUTES
        if minute >= 60:
            hour += 1
            minute = 0
    return times


def generate_synthetic_data(output_dir: str = "data") -> None:
    """Generate synthetic forecast and actuals CSVs.

    Args:
        output_dir: Directory to write output files.
    """
    os.makedirs(output_dir, exist_ok=True)

    dates = generate_dates()
    interval_times = generate_interval_times()
    rng = np.random.default_rng(seed=42)

    forecast_rows: List[dict] = []
    actuals_rows: List[dict] = []

    for date in dates:
        weekday = date.day_name()
        weekday_factor = WEEKDAY_FACTORS.get(weekday, 1.0)

        for lob_name, lob_cfg in LOB_CONFIG.items():
            base_daily = lob_cfg["base_daily_volume"]
            aht = lob_cfg["aht"]
            peak = lob_cfg["peak_factor"]
            noise = lob_cfg["noise_pct"]

            daily_volume = base_daily * weekday_factor * peak

            for i, interval_time in enumerate(interval_times):
                profile_idx = i % len(INTRADAY_PROFILE)
                interval_profile = INTRADAY_PROFILE[profile_idx]

                # Normalize profile multipliers so sum matches daily volume
                forecast_volume = daily_volume * interval_profile * (len(interval_times) / sum(INTRADAY_PROFILE))
                forecast_volume = max(0.5, round(forecast_volume, 1))

                forecast_rows.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "lob": lob_name,
                    "interval_start": interval_time,
                    "forecast_volume": forecast_volume,
                    "forecast_aht": aht,
                })

                # Actuals: forecast + noise + occasional deviation
                noise_factor = 1.0 + rng.normal(0, noise)
                deviation = 1.0

                # Simulate some intervals where actuals run ahead (10-15% above)
                # and some where they run behind
                if i == 5 and lob_name == "inbound_calls" and date.dayofweek < 5:
                    deviation = 1.15  # Wednesday morning spike
                elif i == 12 and lob_name == "email":
                    deviation = 0.85  # Email trough
                elif rng.random() < 0.05:
                    deviation = 1.0 + rng.uniform(-0.2, 0.2)

                actual_volume = max(0.5, round(forecast_volume * noise_factor * deviation, 1))
                actual_aht = max(30, round(aht * (1.0 + rng.normal(0, 0.03))))

                actuals_rows.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "lob": lob_name,
                    "interval_start": interval_time,
                    "actual_volume": actual_volume,
                    "actual_aht": actual_aht,
                })

    forecast_df = pd.DataFrame(forecast_rows)
    actuals_df = pd.DataFrame(actuals_rows)

    forecast_path = os.path.join(output_dir, "forecast.csv")
    actuals_path = os.path.join(output_dir, "actuals.csv")

    forecast_df.to_csv(forecast_path, index=False)
    actuals_df.to_csv(actuals_path, index=False)

    logger.info("Synthetic data generated:")
    logger.info("  Forecast:  %s (%s rows, %s columns)", forecast_path, len(forecast_df), len(forecast_df.columns))
    logger.info("  Actuals:   %s (%s rows, %s columns)", actuals_path, len(actuals_df), len(actuals_df.columns))

    for lob in LOB_CONFIG:
        fc = forecast_df[forecast_df["lob"] == lob]
        ac = actuals_df[actuals_df["lob"] == lob]
        logger.info(
            "  %15s: %4d forecast rows, %4d actuals rows, total fcst vol: %8.0f",
            lob,
            len(fc),
            len(ac),
            fc["forecast_volume"].sum(),
        )


if __name__ == "__main__":
    generate_synthetic_data()