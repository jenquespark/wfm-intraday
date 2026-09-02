# Channels

WFM Intraday supports two contact channels in v0.2.1: **voice** and **chat**.
Async (back-office) work has no staffing model and is rejected at validation.

## Voice

Voice rows are staffed with the classical **Erlang C** queueing model.  The
required number of agents is the minimum N that meets the configured
service-level target (`service_level`, `sl_threshold_seconds`) at or below
the occupancy ceiling (`max_occupancy`).  Net FTE is the resulting N; gross
FTE uplifts it for shrinkage (`gross = net / (1 - shrinkage_pct)`).

## Chat

Chat rows are staffed with a simplified **concurrency-aware** capacity model:

    effective_load = (chats × AHT) / interval_seconds / concurrency
    required = ceil(effective_load / occupancy_target)

One agent handles `chat_concurrency` chats simultaneously.  This is
deliberately simpler than Erlang C — the chat model does not simulate queue
abandonment, response-time targets, or customer wait-time distributions.  It
is a capacity-estimation model, not a chat-specific SLA calculator.

## Async (not supported)

Async/back-office staffing is NOT supported.  There is no async staffing
model, and any input row whose `channel` is not `voice` or `chat` — including
`async`, `fax`, `email`, and typo'd variants — fails input validation (CLI
exit 2).

## Channel values in the data

The `channel` column in every input file is normalized (whitespace-stripped
and lower-cased) and then restricted.  The only accepted values are:

* `voice`
* `chat`

The staffing model for a row is selected by its normalized `channel` value:
`voice` → Erlang C, `chat` → concurrency-aware.  Channel normalization is
applied BEFORE duplicate-key detection, so `" VOICE "` and `"voice"` are the
same canonical key.

## The `channels` config block

`config.yaml` may declare a `channels` block keyed by **arbitrary application
labels**, for example:

```yaml
channels:
  inbound_calls:
    channel_type: voice
  chat_support:
    channel_type: chat
    concurrency: 3
```

The keys are free-form labels — they are NOT restricted to `voice`/`chat`,
are NEVER interpreted as input channel values, and are NEVER rejected.  Only
each entry's fields are validated:

* `channel_type` must be `voice` or `chat`.
* `concurrency` must be >= 1.
* Unknown fields inside an entry are rejected (hard config error, exit 1).

In v0.2.1 the staffing parameters are global (`chat_concurrency`,
`service_level`, `shrinkage_pct`, …); the `channels` block is parsed and
strictly validated but does not itself change the staffing calculation.  It
exists so a deployment's channel inventory is explicit and self-describing.

## Zero-value semantics

Real numeric zeros are meaningful and always preserved end-to-end:

* `actual_volume = 0.0` — a real zero-call interval — stays `0.0` in CSV,
  Excel, JSON, and the web UI.  It is never rendered blank, and it produces a
  real zero staffing requirement.
* `scheduled_fte = 0.0` — a real interval with zero agents scheduled — stays
  `0.0`.  It is classified against the gap (usually `understaffed`), never as
  `no_schedule`.
* `staffing_gap_fte = 0.0` — a real balanced interval — stays `0.0`.
* Zero FTE requirements (`forecast`/`actual`/`reforecast_required_*`) are real
  zeros, never missing values.

Only `None` (missing data) is rendered as a blank CSV/Excel/web cell.  The
Excel staffing-gaps sheet uses `"N/A"` specifically for a missing schedule
row.  Missing future actuals in as-of mode are `None` → blank.  In short:
`0.0` is data, blank is missing.