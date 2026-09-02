# Input file format

## Forecast CSV

Required columns:

| Column | Type | Unit | Description |
|--------|------|------|-------------|
| `date` | string | YYYY-MM-DD | Operating date |
| `lob` | string | — | Line of business (queue, skill group) |
| `interval_start` | string | HH:MM | Interval start time |
| `channel` | string | voice/chat | Contact channel |
| `forecast_volume` | float | count | Forecast contact volume |
| `forecast_aht_seconds` | float | seconds | Forecast average handle time |

## Actuals CSV

| Column | Type | Unit | Description |
|--------|------|------|-------------|
| `date` | string | YYYY-MM-DD | Operating date |
| `lob` | string | — | Line of business |
| `interval_start` | string | HH:MM | Interval start time |
| `channel` | string | voice/chat | Contact channel |
| `actual_volume` | float | count | Actual contact volume |
| `actual_aht_seconds` | float | seconds | Actual average handle time |

## Schedule (staffing) CSV

| Column | Type | Unit | Description |
|--------|------|------|-------------|
| `date` | string | YYYY-MM-DD | Operating date |
| `lob` | string | — | Line of business |
| `interval_start` | string | HH:MM | Interval start time |
| `channel` | string | voice/chat | Contact channel |
| `scheduled_fte` | float | FTE | Staffing planned for the interval |

Schedule data is optional.  When absent, staffing‑gap analysis is
unavailable and intervals are marked `no_schedule`.

## Key uniqueness

The combination `(date, lob, interval_start, channel)` must be unique
within each file.  Duplicates are hard errors (analysis fails).

## Column mapping

If your export uses different column names, use `column_mapping` in
`config.yaml`:

```yaml
column_mapping:
  date: "Contact Date"
  lob: "Queue Name"
  interval_start: "Time Slot"
  channel: "Channel"
  forecast_volume: "Calls Forecast"
  forecast_aht_seconds: "AHT"
```

This maps canonical field names (keys) to source column names (values).

## Validation rules

* Negative volume, AHT, or FTE values are rejected.
* Channel must be `voice` or `chat`.
* Missing required columns produce a clear error.