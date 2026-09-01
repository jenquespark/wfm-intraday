# Getting started

## Prerequisites

* Python 3.11 or later
* pip

## Installation

```bash
git clone https://github.com/jenquespark/wfm-intraday.git
cd wfm-intraday
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Verify:

```bash
wfm-intraday --version
wfm-intraday --help
```

## Generate sample data

```bash
wfm-intraday sample
```

Creates `data/forecast.csv`, `data/actuals.csv`, and `data/schedule.csv`
with 5 weeks of synthetic data for 3 lines of business.

## Validate input files

```bash
wfm-intraday validate --forecast data/forecast.csv --actual data/actuals.csv \
    --staffing data/schedule.csv
```

## Run analysis

```bash
wfm-intraday analyze --forecast data/forecast.csv --actual data/actuals.csv \
    --staffing data/schedule.csv --output-dir output
```

Output:

* `output/intraday_report.xlsx`
* `output/analysis.json`
* `output/interval_analysis.csv`

## Run as-of (intra-day) analysis

```bash
wfm-intraday analyze --forecast data/forecast.csv --actual data/actuals.csv \
    --staffing data/schedule.csv --mode as-of --checkpoint 12:00 \
    --date 2026-05-04 --output-dir output
```

Only actuals up to the checkpoint influence the reforecast.  Future
intervals use reforecast‑based staffing requirements.

## Launch the web interface

```bash
pip install -e ".[web]"
wfm-intraday web
```

## Programmatic use

```python
from wfm_intraday import analyze, validate

result = analyze("data/forecast.csv", "data/actuals.csv",
                 staffing_path="data/schedule.csv",
                 mode="as-of", checkpoint="12:00")
print(result.forecast_accuracy["overall"]["wape"])
```
