# Input adapters

WFM Intraday loads all CSV input through a single adapter pipeline.  In
v0.2.1 the only adapter is **GenericCSVAdapter**.  There are no native vendor
adapters — Calabrio, NICE, Verint, Genesys, and Aspect exports are handled
through column mapping, not dedicated connectors.

## GenericCSVAdapter

`GenericCSVAdapter` reads CSV files and maps external (vendor) column names
onto the canonical schema:

| File     | Canonical columns                                                                  |
|----------|------------------------------------------------------------------------------------|
| forecast | `date`, `lob`, `interval_start`, `channel`, `forecast_volume`, `forecast_aht_seconds` |
| actuals  | `date`, `lob`, `interval_start`, `channel`, `actual_volume`, `actual_aht_seconds`     |
| staffing | `date`, `lob`, `interval_start`, `channel`, `scheduled_fte`                           |

With no mapping, the adapter expects canonical column names directly and still
runs the same strict validations.  Because `can_handle` always returns
`True`, it is the fallback adapter — CLI, web, and Python API all share this
one load path.

## Canonical → source mapping

`column_mapping` in `config.yaml` (or passed directly to `analyze` /
`validate`) is written **canonical → source**:

```yaml
column_mapping:
  forecast:
    date: "Contact Date"
    lob: "Queue Name"
    interval_start: "Time Slot"
    channel: "Channel"
    forecast_volume: "Calls Forecast"
    forecast_aht_seconds: "AHT"
```

The adapter reverses the mapping internally before renaming the CSV columns.
A flat mapping (`date: "Contact Date"`, …) applies the key columns to every
source type.  Mappings are validated strictly: unknown sections, unknown
canonical columns, non-string/empty source values, and duplicate source
columns all hard-fail (config error, exit 1).

## Strict validation

Every file is validated after mapping — hard errors, no warnings-only path:

* required canonical columns are present
* `date` is a real `YYYY-MM-DD` calendar date
* `interval_start` is `HH:MM` (hour 0–23, minute 0–59); values are normalized
  to zero-padded `HH:MM` so `8:00` and `08:00` are the same key
* `channel` normalizes to `voice` or `chat` (anything else fails)
* required numeric fields are finite (no NaN / Inf / non-numeric) and
  non-negative; AHT fields must be strictly positive
* no duplicate `(date, lob, interval_start, channel)` keys

## Duplicate handling

Duplicate canonical keys are a **hard error** in every input file.  There is
no first/last-wins and no warning-only deduplication.

## Reconciliation behavior

Reconciliation runs after request scoping (date/LOB filters) and BEFORE any
calculation, in both `analyze` and `validate`:

* **actual-only keys** (an actual with no forecast) — always a hard error.
* **schedule-only keys** (a schedule row with no forecast/actual) — always a
  hard error.
* **forecast-only keys**:
  * retrospective mode: hard error (a forecast interval should have an
    actual).
  * as-of mode: allowed only for genuinely FUTURE intervals (interval end >
    checkpoint).  A COMPLETED interval missing its actual is a hard error.

A reconciliation mismatch raises `ValueError`, which maps to CLI exit 2.

## Retrospective versus as-of

* **Retrospective** (`--mode retrospective`) — uses all actuals; every
  forecast interval must have a matching actual.  Full-day analysis.
* **As-of** (`--mode as-of --checkpoint HH:MM`) — uses actuals observed up to
  the checkpoint only.  Future intervals retain the full forecast spine with
  missing actuals rendered blank; the reforecast scales future forecasts from
  the completed-interval deviation.  A checkpoint is required and must be a
  valid `HH:MM`.

Completion is key/time based — an interval is completed iff its END time
(interval_start + interval_length) is ≤ the checkpoint — and is therefore
independent of input row order.

## Redistribution direction

Redistribution recommendations move FTE from an **overstaffed LATER** interval
(donor) to an **understaffed EARLIER** interval (recipient).  The opposite
direction (earlier donor → later recipient) is never generated.  Moves are
constrained to the same date/LOB/channel, bounded by
`max_movement_window_minutes`, and a donor's surplus is consumed exactly once
(donor-conserving).  In as-of mode only FUTURE intervals are eligible as
donors or recipients.

## Exit codes

| Code | Meaning |
|------|---------|
| 0    | success |
| 1    | config error (missing or malformed config file, including a malformed default `config.yaml`) |
| 2    | input/validation error (missing files, invalid values, mismatched keys, unsupported channel, invalid checkpoint/date) |
| 3    | calculation error |
| 4    | output/reporting error (e.g. output directory cannot be created) |