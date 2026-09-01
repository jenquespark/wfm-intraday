# WFM Reforecast Engine

> **Interval-level forecast vs actual gap analysis and reforecasting tool for contact center workforce management teams.**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Business Problem

Contact center WFM teams publish a weekly forecast that drives scheduling. When actual call volume deviates from the forecast — and it always does — analysts must quickly determine:

- **Which intervals are overstaffed or understaffed?**
- **How accurate was the forecast?** (WAPE, MAPE, forecast bias)
- **Where to redistribute flexible hours to close the gap?**
- **What if call volume continues at its current pace?** (intra-day reforecast)

This tool answers those questions from exported CSV data — no live system access required.

## What It Does

- **Forecast accuracy analysis** — WAPE, MAPE, and forecast bias per LOB and overall
- **Erlang C staffing gap detection** — required vs scheduled FTE per interval per LOB
- **Redistribution recommendations** — move flexible hours from overstaffed to understaffed intervals
- **Intra-day reforecast** — at a configurable checkpoint, scale remaining intervals based on actuals-to-date
- **Multi-LOB support** — analyze inbound calls, email, chat, or any contact type simultaneously
- **Export** — Excel report, redistribution plan CSV, accuracy summary JSON, optional matplotlib charts

## Quick Start

### Prerequisites

```bash
python -m venv .venv
source .venv/bin/activate
pip install pandas numpy openpyxl pyyaml matplotlib
```

### Generate Sample Data

```bash
python scripts/generate_sample_data.py
```

This creates 5 weeks of realistic synthetic data for 3 LOBs (inbound_calls, email, chat) in `data/`.

### Run Analysis

```bash
python reforecast.py --forecast data/forecast.csv --actuals data/actuals.csv
```

Or analyze a single LOB:

```bash
python reforecast.py --forecast data/forecast.csv --actuals data/actuals.csv --lob inbound_calls
```

Generate charts:

```bash
python reforecast.py --forecast data/forecast.csv --actuals data/actuals.csv --charts
```

### Output

| File | Description |
|------|-------------|
| `output/reforecast_report.xlsx` | Multi-sheet Excel: one sheet per LOB + Summary |
| `output/redistribution_plan.csv` | Advisory hour redistribution recommendations |
| `output/accuracy_summary.json` | Machine-readable accuracy metrics |
| `output/forecast_vs_actual_*.png` | Forecast vs actual charts (when `--charts` flag used) |

### Sample Terminal Output

```
📊 FORECAST ACCURACY
  inbound_calls    WAPE:   9.95%  MAPE:  10.28%  Bias: +0.0024
  email            WAPE:  12.37%  MAPE:  13.35%  Bias: -0.0100
  chat             WAPE:   8.37%  MAPE:   8.48%  Bias: -0.0022
  OVERALL          WAPE:   9.90%  MAPE:  10.70%  Bias: -0.0006

📋 STAFFING GAP ANALYSIS
  Understaffed intervals:  651
  Overstaffed intervals:   403
  Balanced intervals:      2201
  Redistribution moves:    691

🔄 REFORECAST CHECKPOINT
  Checkpoint=10, blend=50%
  Original forecast total: 2033486 → Adjusted total: 2003816
```

## Input Format

### Forecast CSV

```csv
date,lob,interval_start,forecast_volume,forecast_aht
2026-05-04,inbound_calls,08:00,45.2,280
```

### Actuals CSV

```csv
date,lob,interval_start,actual_volume,actual_aht
2026-05-04,inbound_calls,08:00,42.1,285
```

Both files must have the same date/LOB/interval_start combinations.

## Configuration

Edit `config.yaml`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `interval_length` | 30 | Interval length in minutes |
| `aht_seconds` | 270 | Average handle time in seconds |
| `shrinkage_pct` | 0.34 | Shrinkage factor (breaks, training, PTO) |
| `service_level` | 0.80 | Service level target (80/20) |
| `sl_threshold_seconds` | 20 | Service level answer threshold |
| `max_occupancy` | 0.85 | Maximum agent occupancy |
| `overstaff_threshold_pct` | 0.15 | Threshold for overstaffed classification |
| `understaff_threshold_pct` | 0.10 | Threshold for understaffed classification |
| `reforecast_checkpoint_interval` | 10 | Interval index for reforecast checkpoint |
| `reforecast_blend_factor` | 0.50 | How much deviation persists (0–1) |

## Methodology

### Erlang C

Uses the standard exponential approximation for service level:

```
P(wait > t) = Pw × exp(-(N - E) × t / AHT)
```

Positions are iterated upward until the service level target is met, with an occupancy ceiling. No external queueing library required — implemented in pure Python without scipy.

### Forecast Accuracy

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| **WAPE** | Σ\|A-F\| / ΣA × 100 | Weighted Absolute Percentage Error (volume-weighted) |
| **MAPE** | mean( \|A-F\| / A ) × 100 | Mean Absolute Percentage Error (per-interval) |
| **Bias** | Σ(A-F) / ΣA | Positive = underforecast, Negative = overforecast |

### Reforecasting

At the configurable checkpoint interval, the cumulative deviation is calculated:

```
deviation_pct = (cumulative_actual - cumulative_forecast) / cumulative_forecast
scale = 1 + blend_factor × deviation_pct
adjusted_forecast[i] = forecast[i] × scale  (for i >= checkpoint)
```

## WFM Context

This tool targets the real reforecasting workflow that WFM teams face daily. The methodology aligns with COPC WFM standards and is vendor-agnostic — it works with data exported from NICE IEX, Teleopti, Verint, Calabrio, or any platform that exports interval-level forecast and actual data.

**What this is NOT:**
- NOT a full WFM platform replacement
- NOT connected to live ACD or WFM systems
- NOT a scheduling optimizer (redistribution is advisory)

**What this IS:**
- A portable, transparent WFM gap analysis tool
- An offline reforecasting engine for weekly planning
- A methodology reference for interval-level WFM analysis

## Limitations

- Requires exported CSV data with the specified column schema
- Erlang C assumes single-skill, single-queue (does not model multi-skill routing)
- Redistribution recommendations are heuristic-based, not optimization-solved
- All sample data is synthetic and labeled as such
- No real-time/live system connections

## License

MIT License — see [LICENSE](LICENSE).

Copyright (c) 2026 Cenk Yigitoglu, [Onpoint.Works](https://www.onpoint.works)