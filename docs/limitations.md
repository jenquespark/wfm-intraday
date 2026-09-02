# Limitations

## No live WFM sync

The engine works from exported CSV data.  It does not connect to live
WFM databases or APIs.

## No agent‑level scheduling

Staffing analysis is at capacity level (FTE per interval).  The tool
does not produce individual agent schedules, shift patterns, or rotation
plans.

## Redistribution is advisory

Redistribution recommendations suggest capacity moves.  They do not
account for agent skills, preferences, labour contracts, break timing,
or shift‑length constraints.  A human planner must validate every move.

## No multi‑skill or proficiency matrix

The model assumes single‑skill queues.  It does not model agents who
handle multiple queues with different proficiency levels.

## No shift optimisation

There is no shift‑generation, schedule‑optimisation, or labour‑rule
engine.

## No intra‑day pattern learning

The reforecast uses a simple cumulative‑deviation scaler.  It does not
learn intra‑day arrival patterns or apply advanced time‑series models.

## Async not supported

Async/back-office staffing is not supported in version 0.2.  Any input row
with `channel=async` is rejected.  Voice and chat are the supported channels.

## No DST or timezone handling

Dates and interval times are preserved as‑is from the source CSV.
Daylight saving time transitions and timezone conversions are not
handled.

## Chat model simplified

The chat model does not account for abandon rate, response‑time
targets, or customer wait‑time distributions.  It is a capacity
estimation model, not a chat‑specific SLA calculator.

## No vendor‑specific adapters

The GenericCSVAdapter handles arbitrary CSV formats through column
mapping.  Native adapters for Calabrio, NICE, Verint, Genesys, or
Aspect exports are not included.