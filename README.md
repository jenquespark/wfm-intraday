# WFM Reforecast Engine

Interval-level forecast vs actual gap analysis and intra-day reforecasting
for contact centre workforce management teams.  The tool reads exported CSV
data and produces staffing gap analysis, redistribution recommendations,
and reforecast projections — no live WFM system access required.

## What it does

- **Forecast accuracy:** WAPE, MAPE, and bias per line of business.
- **Staffing gap analysis:** Compares scheduled FTE against Erlang‑C
  (voice), concurrency‑aware (chat), or workload‑based (async) requirements.
- **Intra‑day reforecast:** Scales remaining intervals based on actuals
  observed up to a checkpoint.
- **Redistribution recommendations:** Advisory FTE moves from overstaffed
  to understaffed intervals, constrained by date, LOB, and movement window.
- **Multi‑channel:** Voice, chat, and async/back‑office models.
- **Multi‑output:** Excel workbook, CSV interval report, JSON accuracy
  summary, and optional Streamlit web interface.

## Quick start

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Generate sample data
wfm-reforecast sample

# Validate input files
wfm-reforecast validate --forecast data/forecast.csv --actual data/actuals.csv \
    --staffing data/schedule.csv

# Run full analysis
wfm-reforecast analyze --forecast data/forecast.csv --actual data/actuals.csv \
    --staffing data/schedule.csv --output-dir output

# With as‑of checkpoint
wfm-reforecast analyze --forecast data/forecast.csv --actual data/actuals.csv \
    --staffing data/schedule.csv --mode as-of --checkpoint 12:00 --date 2026-09-01
```

Output files appear in `output/`:
- `reforecast_report.xlsx`  — multi‑sheet Excel workbook
- `accuracy_summary.json`   — machine‑readable accuracy + interval data
- `interval_analysis.csv`   — interval‑level detail

## Supported channels

| Channel | Model | Status |
|---------|-------|--------|
| Voice   | Erlang C with service‑level constraint | Supported |
| Chat    | Concurrency‑aware throughput model | Supported |
| Async   | Workload / capacity model | Experimental (v0.2) |

The async model is experimental.  See `docs/channels.md` for details.

## Documentation

- [Getting started](docs/getting-started.md)
- [User guide](docs/user-guide.md)
- [Input file format](docs/input-files.md)
- [Methodology](docs/methodology.md)
- [Interpreting results](docs/interpreting-results.md)
- [Limitations](docs/limitations.md)
- [Adapters](docs/adapters.md)

## Requirements

Python 3.11+.  Core dependencies: `pandas`, `numpy`, `pyyaml`, `openpyxl`.

Optional: `streamlit` for the local web interface (`pip install -e ".[web]"`).

## License

MIT — see [LICENSE](LICENSE).