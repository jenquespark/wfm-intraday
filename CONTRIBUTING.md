# Contributing to WFM Intraday

WFM Intraday is a focused utility for interval-level forecast variance,
reforecasting, and staffing gap analysis.  Contributions that keep the scope
tight and the behavior correct are welcome.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running tests

```bash
python -m pytest
```

## Lint and format

```bash
ruff check .
ruff format --check .
```

## Build

```bash
python -m build
```

## Pull request checklist

- Tests pass (`python -m pytest`).
- `ruff check .` and `ruff format --check .` are clean.
- New behavior has a non-vacuous regression test.
- Docs are updated where behavior changed.

## Versioning

The version lives in exactly one place: `wfm_intraday/_version.py`.  Do not
add a second version literal elsewhere.

## Scope

WFM Intraday is vendor-neutral and works on exported CSV data.  Contributions
should not add vendor-specific adapters, agent-level scheduling, or shift
optimisation without prior discussion.