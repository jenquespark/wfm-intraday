# WFM Reforecast Engine — Build Brief

## Goal
Build a production-quality Python project: **wfm-reforecast-engine** — a weekly reforecasting tool for contact center workforce management teams that compares forecast vs actual demand, detects staffing gaps, and recommends flexible-hour redistribution.

## Business Context
This tool serves WFM (Workforce Management) analysts and consultants who work with **exported CSV data** from platforms like NICE IEX, Teleopti, or Verint. They need to quickly detect when actual contact volume deviates from the weekly forecast and know:
- Which intervals are overstaffed or understaffed
- How accurate the forecast was (WAPE, MAPE, bias)
- Where to move flexible hours to close the gap
- What if AHT or shrinkage changes?

This is the exact methodology used in contact center WFM forecasting. The repo must look like a professional, domain-expert tool — NOT a toy or generic Python project.

## Deliverables (all in /root/wfm-reforecast-engine)

### 1. Core module: `reforecast/` package
A proper Python package with clean module structure:

- `reforecast/__init__.py` — package init, exports main classes
- `reforecast/models.py` — dataclasses for Forecast, Actuals, IntervalData, StaffingGap
- `reforecast/calculator.py` — core logic: forecast vs actual comparison, demand calculation (Erlang C), staffing gap detection, flexible-hour redistribution
- `reforecast/metrics.py` — WAPE, MAPE, Forecast Bias calculation
- `reforecast/config.py` — dataclass config: AHT, shrinkage, service level, occupancy, interval length, thresholds
- `reforecast/io.py` — CSV/Excel loaders and writers

### 2. CLI entry point: `reforecast.py`
Runnable via:
```
python reforecast.py --forecast data/forecast.csv --actuals data/actuals.csv --config config.yaml
```
Generates:
- `output/reforecast_report.xlsx` — interval-level gap analysis
- `output/redistribution_plan.csv` — recommended hour adjustments
- `output/accuracy_summary.json` — WAPE, MAPE, bias

### 3. Config: `config.yaml`
- interval_length (minutes): 30
- aht_seconds: 270
- shrinkage_pct: 0.34
- service_level: 0.80
- sl_threshold_seconds: 20
- max_occupancy: 0.85
- overstaff_threshold_pct: 0.15
- understaff_threshold_pct: 0.10

### 4. Sample data generator: `scripts/generate_sample_data.py`
Generates realistic synthetic contact center data:
- `data/forecast.csv` — 5 weeks, 8-23h, 30-min intervals, multi-LOB (3 LOBs: inbound_calls, email, chat)
- `data/actuals.csv` — 5 weeks actuals with realistic deviation (some intervals over, some under, some volatile)
- Weekly seasonality, intraday profile (peak at 10-12 and 14-16), day-of-week pattern
- LOBs have different volumes and AHT
- Label data as synthetic in README

### 5. Reports
- **Accuracy metrics**: WAPE (overall + per LOB), MAPE, forecast bias, per-interval deviation
- **Staffing analysis**: Erlang C required staff per interval, scheduled vs required, gap detection, overstaff/understaff by interval
- **Redistribution recommendations**: which agents move where (e.g., "move 3 flex hours 10:00-11:00 to 14:00-15:00")
- **Excel report**: multi-sheet workbook with per-LOB tabs
- **Accuracy summary JSON**: machine-readable for CI

### 6. Charts (optional but high value)
Use matplotlib to generate:
- `output/forecast_vs_actual.png` — one chart per LOB
- `output/staffing_gap_heatmap.png` — staffing gap by LOB × interval (heatmap)
- `output/redistribution_recommendation.png` — before/after coverage chart
If matplotlib is not available, still produce CSV/Excel/JSON.

### 7. README.md
Professional README with:
- Title: WFM Reforecast Engine
- Business Problem section
- What It Does (feature list)
- Input/Output table
- How to Run
- Sample Result (with actual output shown)
- WFM Context section explaining methodology
- Limitations section (honest)
- License: MIT

### 8. requirements.txt
```
pandas
numpy
openpyxl
pyyaml
matplotlib
```

### 9. tests/ (basic)
- `tests/test_metrics.py` — WAPE/MAPE correctness with known values
- `tests/test_calculator.py` — gap detection correctness
- `tests/test_io.py` — CSV/Excel round-trip
Run via: `python -m pytest` (if pytest available; fallback to simple assert-based `tests/run_tests.py`)

### 10. .gitignore
```
__pycache__/
*.pyc
output/
.env
*.log
.pytest_cache/
```

### 11. LICENSE — MIT

## Code Quality Standards
- Type hints on all public functions and dataclasses
- Google-style docstrings
- Clean PEP8, 4-space indent
- No `print()` debugging — use a `logging` setup
- Error handling: raise clear exceptions with actionable messages (e.g., "Column 'interval_start' missing from forecast.csv — expected columns: ...")
- Defensive: validate all inputs, clear error messages
- Realistic data, labeled synthetic

## WFM Domain Knowledge (critical — must be correct)
- **Erlang C**: required_positions = Erlang C formula output + shrinkage uplift. Inputs: calls per interval, AHT, interval length, service level target, max occupancy.
- **Erlangs**: offered_load = (calls_per_interval * aht_seconds) / interval_seconds
- **FTE**: required FTE includes shrinkage: scheduled_fte = on_phone_fte / (1 - shrinkage_pct)
- **WAPE** = sum(|actual - forecast|) / sum(actual)
- **Forecast bias** = sum(actual - forecast) / sum(actual) — positive = underforecast, negative = overforecast
- **Reforecasting**: when actuals run ahead/behind forecast at a certain point in the day, the remaining interval forecasts get scaled. E.g. if through interval 10 actuals are +15% above forecast, remaining intervals scale up by blend factor (e.g., 50% persistence: scale = 1 + 0.5*deviation).

## Final Acceptance Criteria
1. `python reforecast.py --forecast data/forecast.csv --actuals data/actuals.csv --config config.yaml` runs with **zero errors** and produces all outputs.
2. Output files exist: reforecast_report.xlsx, redistribution_plan.csv, accuracy_summary.json.
3. The tool correctly identifies at least one understaffed and one overstaffed interval in the synthetic data (due to the deviation pattern baked in).
4. WAPE values computed correctly and match a hand calculation.
5. README documents how to run and what it does.
6. Tests pass.
7. The whole project reads as a **domain-expert WFM tool**, not a generic tutorial repo.

## Notes
- Do NOT connect to any live WFM platform. This is file-based.
- All data is synthetic and must be labeled as such.
- The tool must work offline entirely (no API calls).
- Keep the business framing: this solves a real, painful WFM problem (reforecasting when the plan drifts from reality).
