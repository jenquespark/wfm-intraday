# Changelog

All notable changes to WFM Intraday are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Documentation and repository description refreshed for the v0.2.1 release.

## [0.2.1] - 2026-09-01

### Fixed

- Full forecast spine is preserved when actuals cover only completed intervals
  (left join instead of inner join).
- Duplicate canonical keys now hard-fail instead of warning.
- Key mismatches now hard-fail (exit code 2) instead of "passed with warnings".
  In `as-of` mode, forecast-only keys (future intervals) remain allowed.
- `as-of` mode without a checkpoint now fails (exit code 2).
- Single checkpoint authority: completion is key/time-based from the request
  checkpoint parameter; positional/modulo masking removed; the
  `reforecast_checkpoint_interval` config field removed.
- Future actual volume and AHT can no longer leak into the as-of reforecast.
- Future staffing uses the reforecast requirement, not a zero-actual requirement.
- Zero actual volume yields a real zero requirement; zero scheduled FTE is a
  real scheduled zero (not `no_schedule`).

### Changed

- Unknown channels (e.g. `fax`) hard-fail; removed silent fallback to voice.
- Async/back-office channel removed (unreachable from CLI, web, and public API).
- Version is now sourced from a single authoritative location
  (`wfm_intraday/_version.py`).
- CLI, web, and Python API share one analysis service.
- Excel, CSV, and JSON reporters consume one canonical `AnalysisResult`.
- Output writer failure returns exit code 4.

### Added

- Non-vacuous regression tests for the hardening requirements.
- Ruff and formatting checks in CI.
- `CONTRIBUTING.md` and this `CHANGELOG.md`.

## [0.2.0] - 2026-09-01

### Changed

- Project renamed from "WFM Reforecast Engine" to "WFM Intraday"
  (package `wfm_intraday`, CLI `wfm-intraday`, repo `jenquespark/wfm-intraday`).