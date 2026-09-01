# Getting started

## Prerequisites

* Python 3.11 or later
* pip

## Installation

```bash
git clone https://github.com/jenquespark/wfm-reforecast-engine.git
cd wfm-reforecast-engine
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Verify:

```bash
wfm-reforecast --version
wfm-reforecast --help
```

## Generate sample data

```bash
wfm-reforecast sample
```

Creates `data/forecast.csv`, `data/actuals.csv`, and `data/schedule.csv`
with 5 weeks of synthetic data for 3 lines of business.

## Validate input files

```bash
wfm-reforecast validate --forecast data/forecast.csv --actual data/actuals.csv \
    --staffing data/schedule.csv
```

## Run analysis

```bash
wfm-reforecast analyze --forecast data/forecast.csv --actual data/actuals.csv \
    --staffing data/schedule.csv --output-dir output
```

Output:

* `output/reforecast_report.xlsx`
* `output/accuracy_summary.json`
* `output/interval_analysis.csv`

## Run as-of (intra-day) analysis

```bash
wfm-reforecast analyze --forecast data/forecast.csv --actual data/actuals.csv \
    --staffing data/schedule.csv --mode as-of --checkpoint 12:00 \
    --date 2026-05-04 --output-dir output
```

Only actuals up to the checkpoint influence the reforecast.  Future
intervals use reforecast‑based staffing requirements.

## Launch the web interface

```bash
pip install -e ".[web]"
wfm-reforecast web
```

## Programmatic use

```python
from reforecast import analyze, validate

result = analyze("data/forecast.csv", "data/actuals.csv",
                 staffing_path="data/schedule.csv",
                 mode="as-of", checkpoint="12:00")
print(result.forecast_accuracy["overall"]["wape"])
```