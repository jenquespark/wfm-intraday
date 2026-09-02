# WFM Intraday

WFM Intraday compares interval-level forecasts with actual contact volumes,
reforecasts the remaining day from an operational checkpoint, and measures
staffing requirements against scheduled FTE.

It works with exported CSV files and produces Excel, CSV, and JSON reports.
Voice staffing uses Erlang C. Chat uses a simplified concurrency-aware
capacity model. Async staffing is not supported in version 0.2.

## What it does

- **Forecast accuracy:** WAPE, MAPE, and bias per line of business.
- **Staffing gap analysis:** Compares scheduled FTE against Erlang-C (voice)
  or concurrency-aware (chat) requirements.
- **Intra-day reforecast:** Scales remaining future intervals based on actuals
  observed up to a checkpoint.
- **Redistribution recommendations:** Advisory forward-only FTE moves between
  overstaffed and understaffed intervals, constrained to the same date, LOB,
  and channel.
- **Multi-output:** Excel workbook, CSV interval report, JSON summary, and an
  optional local web interface.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Generate sample data
wfm-intraday sample

# Validate input files
wfm-intraday validate --forecast data/forecast.csv --actual data/actuals.csv \
    --staffing data/schedule.csv

# Run full analysis
wfm-intraday analyze --forecast data/forecast.csv --actual data/actuals.csv \
    --staffing data/schedule.csv --output-dir output

# As-of analysis (intra-day checkpoint)
wfm-intraday analyze --forecast data/forecast.csv --actual data/actuals.csv \
    --staffing data/schedule.csv --mode as-of --checkpoint 12:00 \
    --date 2026-05-04 --output-dir output
```

Output files appear in `output/`:

- `intraday_report.xlsx` — multi-sheet Excel workbook
- `analysis.json` — machine-readable accuracy and interval data
- `interval_analysis.csv` — interval-level detail
- `redistribution_plan.csv` — advisory capacity moves (when any)

## Supported channels

| Channel | Model | Status |
|---------|-------|--------|
| Voice   | Erlang C with service-level constraint | Supported |
| Chat    | Concurrency-aware throughput model    | Supported |
| Async   | —                                    | Not supported |

## Documentation

- [Getting started](docs/getting-started.md)
- [Input file format](docs/input-files.md)
- [Methodology](docs/methodology.md)
- [Interpreting results](docs/interpreting-results.md)
- [Limitations](docs/limitations.md)

## Requirements

Python 3.11+.  Core dependencies: `pandas`, `numpy`, `openpyxl`, `pyyaml`.

Optional: `streamlit` for the local web interface (`pip install -e ".[web]"`).

## License

MIT — see [LICENSE](LICENSE).