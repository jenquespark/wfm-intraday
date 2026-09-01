# Interpreting results

## Forecast accuracy

| Metric | Meaning | |
|--------|---------|------|
| WAPE | Weighted error across all intervals | Lower is better |
| MAPE | Average per-interval error | Sensitive to low-volume intervals |
| Bias | Systematic over/under-forecast | ±0.05 is typical |

Positive bias: actuals exceed forecast (under-forecast).  
Negative bias: forecast exceeds actuals (over-forecast).

## Staffing gap sign convention

```
gap_fte = required_gross_fte - scheduled_fte
```

| gap_fte | Status | Meaning |
|---------|--------|---------|
| Positive | Understaffed | More staff needed than scheduled |
| Negative | Overstaffed | More staff scheduled than needed |
| Near zero | Balanced | Schedule matches requirement |

## Staffing requirement types

| Field | Description |
|-------|-------------|
| forecast_required_fte | Staffing needed based on original forecast |
| actual_required_fte | Staffing needed based on actual volume (completed intervals only) |
| reforecast_required_fte | Staffing needed based on reforecast volume (future intervals in as‑of mode) |
| scheduled_fte | Staffing actually planned (from schedule input) |

For future intervals in as‑of mode, `actual_required_fte` is not
available.  Use `reforecast_required_fte` instead.

## Net vs gross FTE

* **Net FTE** = agents handling contacts (Erlang C output)
* **Gross FTE** = net / (1 − shrinkage) — accounts for breaks, training, etc.

## Redistribution

Recommendations are capacity‑level advisory moves.  Verify:

* Transfer amount ≤ donor original surplus
* Same date, LOB, and channel
* Within the configured movement window
* Humanly feasible (break timing, agent skills)

## As‑of vs retrospective mode

| Mode | What is used | Accuracy scope |
|------|-------------|----------------|
| Retrospective | All actuals | Full day |
| As‑of | Actuals up to checkpoint only | Completed intervals only |

In as‑of mode, reforecast for future intervals uses only the deviation
observed through the checkpoint.  Modifying future actuals in the input
will not change the as‑of reforecast.