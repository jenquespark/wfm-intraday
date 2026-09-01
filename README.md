# WFM Reforecast Engine

Compares forecast and actual contact volume at interval level, recalculates
staffing requirements as the day develops, and identifies gaps between what
was planned and what was actually needed.

Works from exported operational data — no live WFM platform integration, no
API credentials, no real-time access.  You give it CSVs; it gives you
numbers.

---

## What it does

- **Forecast accuracy** — WAPE, MAPE, and bias, per LOB and overall.
- **Staffing requirements** — net and gross FTE from forecast volume and
  from actual volume, using the appropriate model per channel (Erlang C for
  voice, concurrency-aware for chat, workload-based for async).
- **Staffing gaps** — comparing required FTE against an explicit schedule
  input.  If you don't provide a schedule, it reports that gap analysis is
  unavailable rather than inventing scheduled FTE from forecast data.
- **Advisory redistribution** — recommends moving capacity from overstaffed
  to understaffed intervals on the same day, same LOB, same channel, within
  a configurable time window.  Recommendations are capacity-level, not
  agent-level, and donor surplus is tracked so it cannot be double-counted.
- **Intra-day reforecast** — at a configurable checkpoint, scales remaining
  interval forecasts by the observed deviation.  Each (date, LOB, channel)
  is computed independently — Monday's deviation does not touch Tuesday.
- **Multi-channel support** — voice (Erlang C), chat (concurrency-aware),
  async/back-office (workload model).  Each channel uses a staffing model
  appropriate to its queueing behaviour.

## What it doesn't do

- Does not connect to WFM platforms, ACDs, or any live system.
- Does not generate agent-level schedules (redistribution is advisory).
- Does not solve multi-skill scheduling optimisation.
- Does not claim COPC or any other certification.
- Voice and async channels are not interchangeable — the tool uses the
  calculation you configure, not the same one for everything.

---

## Input

Three CSV files, two required and one optional:

### forecast.csv (required)

```csv
date,lob,interval_start,channel,forecast_volume,forecast_aht_seconds
2026-05-04,inbound_calls,08:00,voice,45.2,280
2026-05-04,chat_support,08:00,chat,18.5,120
```

### actuals.csv (required)

```csv
date,lob,interval_start,channel,actual_volume,actual_aht_seconds
2026-05-04,inbound_calls,08:00,voice,42.1,285
2026-05-04,chat_support,08:00,chat,20.3,115
```

### schedule.csv (optional)

```csv
date,lob,interval_start,channel,scheduled_fte
2026-05-04,inbound_calls,08:00,voice,14.5
```

When a schedule file is provided, the tool compares required FTE against
scheduled FTE and classifies each interval as understaffed, overstaffed, or
balanced.  Without it, gap analysis is reported as unavailable.

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For charts (optional):

```bash
pip install matplotlib
```

## Usage

Generate sample data (5 weeks, 3 LOBs, 2 channels):

```bash
python scripts/generate_sample_data.py
```

Run analysis:

```bash
python reforecast.py --forecast data/forecast.csv --actuals data/actuals.csv
```

With schedule data:

```bash
python reforecast.py --forecast data/forecast.csv --actuals data/actuals.csv \
    --schedule data/schedule.csv
```

Single LOB:

```bash
python reforecast.py --forecast data/forecast.csv --actuals data/actuals.csv \
    --lob inbound_calls
```

With charts:

```bash
python reforecast.py --forecast data/forecast.csv --actuals data/actuals.csv \
    --chart
```

---

## Output

| File | Contents |
|------|----------|
| `output/reforecast_report.xlsx` | Per-LOB interval data, accuracy summary, staffing gaps, redistribution recommendations |
| `output/redistribution_plan.csv` | Advisory capacity moves |
| `output/accuracy_summary.json` | WAPE, MAPE, bias per LOB and overall |
| `output/forecast_vs_actual_*.png` | Volume charts (when `--charts` is used) |

Example terminal output:

```
📊 FORECAST ACCURACY
  inbound_calls     WAPE:   9.95%  MAPE:  10.28%  Bias: +0.0024
  chat_support      WAPE:   8.37%  MAPE:   8.48%  Bias: -0.0022
  email_backlog     WAPE:  12.37%  MAPE:  13.35%  Bias: -0.0100
  OVERALL           WAPE:   9.90%  MAPE:  10.70%  Bias: -0.0006
```

---

## FTE terminology

| Term | Meaning |
|------|---------|
| **Net FTE** | Agents actively handling contacts (Erlang C result for voice) |
| **Gross FTE** | Net FTE uplifted for shrinkage: `net / (1 - shrinkage_pct)` |
| **Forecast required FTE** | Staffing needed based on forecast volume |
| **Actual required FTE** | Staffing needed based on actual volume |
| **Scheduled FTE** | Staffing actually planned (from schedule input, never derived) |
| **Gap FTE** | `actual_required_gross - scheduled` (positive = understaffed) |

---

## Configuration

Parameters are in `config.yaml`.  The defaults suit a 30-minute interval,
80/20 service level, 34 % shrinkage, and 85 % max occupancy.

Key parameters:

| Parameter | Default | Notes |
|-----------|---------|-------|
| `interval_length_minutes` | 30 | |
| `aht_seconds` | 270 | Fallback when per-row AHT is missing |
| `shrinkage_pct` | 0.34 | Must be < 1 |
| `service_level` | 0.80 | Voice only |
| `max_occupancy` | 0.85 | Voice only |
| `chat_concurrency` | 3 | Chats per agent simultaneously |
| `reforecast_checkpoint_interval` | 10 | Interval index where scaling starts |
| `reforecast_blend_factor` | 0.50 | How much deviation persists |

---

## Channel models

### Voice

Uses Erlang C with the exponential tail approximation.  Service level is
calculated as `P(wait <= threshold)`.  Positions are searched upward until
the target is met, capped by maximum occupancy.

### Chat

Uses a concurrency model: `required_agents = ceil(load / concurrency /
occupancy_target)`.  One agent can handle multiple simultaneous chats, so
Erlang C would overstate the requirement.

### Async (email, back-office)

Uses a workload / throughput model: `required_agents = ceil(volume * AHT /
daily_capacity)`.  There is no queueing in the Erlang sense — the question
is whether the team has enough processing capacity.

---

## Reforecast methodology

At the checkpoint interval, the cumulative deviation is:

```
deviation_pct = (cumulative_actual - cumulative_forecast) / cumulative_forecast
scale = 1 + blend_factor * deviation_pct
adjusted_forecast[i] = forecast[i] * scale   (for i >= checkpoint)
```

Each (date, LOB, channel) is processed independently.  A deviation on Monday
never rescales Tuesday.

---

## Redistribution

Redistribution recommendations are advisory.  They suggest moving capacity
from overstaffed to understaffed intervals on the same date, same LOB, same
channel, within a configurable time window.  Donor surplus is tracked and
consumed — one interval's surplus cannot be allocated to more recipients
than it can cover.

---

## Development

```bash
pip install -e ".[dev]"
python -m pytest
```

---

## License

MIT.  See `LICENSE`.

Copyright (c) 2026 Cenk Yigitoglu, Onpoint.Works.