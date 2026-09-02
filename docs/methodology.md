# Methodology

## Forecast accuracy

WAPE, MAPE, and bias are computed from actual and forecast volume arrays.

* **WAPE** = Σ|actual − forecast| / Σ(actual) × 100
* **MAPE** = mean(|actual − forecast| / actual) × 100 (zero‑actual intervals excluded)
* **Bias** = Σ(actual − forecast) / Σ(actual)

Positive bias means actuals exceeded forecast (under‑forecast).

In as‑of mode, only intervals completed up to the checkpoint are included.

## Voice staffing (Erlang C)

The Erlang C formula gives the probability an arriving call must wait:

C(E, N) = N · B(E, N) / (N − E · (1 − B(E, N)))

where E is offered load in Erlangs and B(E, N) is the Erlang B blocking
probability.  Service level uses the exponential‑tail approximation:

P(wait ≤ t) = 1 − C(E, N) · exp(−(N − E) · t / AHT)

Staffing search starts at ceil(E + 1) and increments N until the target
service level and occupancy constraint are met.

**Offered load:**  E = (volume × AHT) / interval_seconds  
**Shrinkage:**  gross_fte = net_fte / (1 − shrinkage_pct)

## Chat staffing

Chat uses a concurrency‑aware model:

effective_load = (chats × AHT) / interval_seconds / concurrency  
required = ceil(effective_load / occupancy_target)

This is intentionally simpler than Erlang C because agents handle
multiple chat sessions in parallel.  It is suitable for capacity
estimation, not chat‑specific SLA guarantees.

## Async staffing

Async/back-office staffing is not supported in version 0.2.1.  See
`docs/limitations.md`.

## Reforecast

For each (date, lob, channel), cumulative actuals and forecast volume
at the checkpoint are compared:

deviation = (cum_actual − cum_forecast) / cum_forecast  
scale = 1 + blend_factor × deviation  
adjusted_forecast[i] = forecast[i] × scale

The reforecast is applied only to future (post‑checkpoint) intervals.
Each operating day is processed independently.

## Staffing gap

gap_fte = required_gross_fte − scheduled_fte

* **Positive** → understaffed (shortage)
* **Negative** → overstaffed (surplus)

For completed intervals, required_gross_fte is derived from actual volume.
For future intervals, it is derived from reforecast volume.

## Redistribution

Advisory FTE moves from overstaffed donor intervals to understaffed
recipient intervals.  Constraints:

* Same date, same LOB, same channel only
* Donor surplus consumed exactly once
* Movement window: max_movement_window_intervals
* Transfer amounts in FTE and agent‑hours