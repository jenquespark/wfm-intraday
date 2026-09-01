#!/usr/bin/env python3
"""Generate synthetic contact centre data for testing the WFM Reforecast Engine.

Outputs:
    data/forecast.csv   — interval-level forecasts for 3 LOBs × 2 channels
    data/actuals.csv    — interval-level actuals with realistic deviations
    data/schedule.csv   — scheduled staffing (computed from forecast requirement)

All data is synthetic and labelled as such.  No real customer data is used.
"""

from __future__ import annotations

import logging
import os
from typing import List

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

WEEKS = 5
INTERVAL_MINUTES = 30
INTERVALS_PER_DAY = 30  # 08:00–23:00

LOB_CONFIG = {
    "inbound_calls": {
        "channel": "voice",
        "base_daily_volume": 1200,
        "aht": 280,
        "peak_factor": 1.8,
    },
    "chat_support": {
        "channel": "chat",
        "base_daily_volume": 600,
        "aht": 120,
        "peak_factor": 1.5,
    },
    "email_backlog": {
        "channel": "async",
        "base_daily_volume": 400,
        "aht": 180,
        "peak_factor": 1.3,
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

INTRADAY_PROFILE = [
    0.30, 0.40, 0.55, 0.65, 0.75, 0.85,
    0.95, 1.15, 1.30, 1.40, 1.45, 1.50,
    1.45, 1.40, 1.35, 1.30, 1.25, 1.20,
    1.15, 1.10, 1.05, 1.00, 0.95, 0.90,
    0.80, 0.70, 0.60, 0.50, 0.45, 0.40,
]


def generate_dates() -> List[pd.Timestamp]:
    """Five weeks starting Monday."""
    start = pd.Timestamp("2026-05-04")
    return [start + pd.Timedelta(days=i) for i in range(WEEKS * 7)]


def generate_interval_times() -> List[str]:
    """08:00–23:00 at 30-minute intervals."""
    times: List[str] = []
    for hour in range(8, 23):
        for minute in (0, 30):
            times.append(f"{hour:02d}:{minute:02d}")
    return times


def generate_synthetic_data(output_dir: str = "data") -> None:
    """Generate forecast, actuals, and schedule CSVs."""
    os.makedirs(output_dir, exist_ok=True)

    dates = generate_dates()
    interval_times = generate_interval_times()
    rng = np.random.default_rng(seed=42)

    forecast_rows: List[dict] = []
    actuals_rows: List[dict] = []
    schedule_rows: List[dict] = []

    for date in dates:
        weekday = date.day_name()
        weekday_factor = WEEKDAY_FACTORS.get(weekday, 1.0)

        for lob_name, lob_cfg in LOB_CONFIG.items():
            base_daily = lob_cfg["base_daily_volume"]
            aht = lob_cfg["aht"]
            channel = lob_cfg["channel"]
            daily_volume = base_daily * weekday_factor * lob_cfg["peak_factor"]

            for i, interval_time in enumerate(interval_times):
                profile = INTRADAY_PROFILE[i % len(INTRADAY_PROFILE)]
                n_int = len(interval_times)
                forecast_volume = max(0.5, round(daily_volume * profile * (n_int / sum(INTRADAY_PROFILE)), 1))

                # Forecast row
                forecast_rows.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "lob": lob_name,
                    "interval_start": interval_time,
                    "channel": channel,
                    "forecast_volume": forecast_volume,
                    "forecast_aht_seconds": aht,
                })

                # Actuals: forecast + noise + occasional deviation
                noise = 1.0 + rng.normal(0, 0.12)
                deviation = 1.0
                if i == 5 and lob_name == "inbound_calls" and date.dayofweek < 5:
                    deviation = 1.15
                elif rng.random() < 0.05:
                    deviation = 1.0 + rng.uniform(-0.2, 0.2)

                actual_volume = max(0.5, round(forecast_volume * noise * deviation, 1))
                actual_aht = max(30, round(aht * (1.0 + rng.normal(0, 0.03))))

                actuals_rows.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "lob": lob_name,
                    "interval_start": interval_time,
                    "channel": channel,
                    "actual_volume": actual_volume,
                    "actual_aht_seconds": actual_aht,
                })

                # Schedule: forecast requirement + shrinkage (synthetic staffing plan)
                from reforecast.config import Config
                from reforecast.calculator import compute_staffing_requirement
                config = Config()
                req = compute_staffing_requirement(
                    volume=forecast_volume,
                    aht_seconds=aht,
                    interval_seconds=INTERVAL_MINUTES * 60,
                    config=config,
                    channel=channel,
                )
                schedule_rows.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "lob": lob_name,
                    "interval_start": interval_time,
                    "channel": channel,
                    "scheduled_fte": round(req.gross_fte, 2),
                })

    pd.DataFrame(forecast_rows).to_csv(os.path.join(output_dir, "forecast.csv"), index=False)
    pd.DataFrame(actuals_rows).to_csv(os.path.join(output_dir, "actuals.csv"), index=False)
    pd.DataFrame(schedule_rows).to_csv(os.path.join(output_dir, "schedule.csv"), index=False)

    logger.info("Synthetic data written to %s/", output_dir)
    for lob in LOB_CONFIG:
        fc = pd.DataFrame(forecast_rows)
        fc = fc[fc["lob"] == lob]
        logger.info("  %20s: %4d rows, total forecast volume: %8.0f", lob, len(fc), fc["forecast_volume"].sum())


if __name__ == "__main__":
    generate_synthetic_data()