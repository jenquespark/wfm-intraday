# TODOS — Deferred Work

Deferred scope decisions from the /autoplan review of the wfm-reforecast-engine plan (2026-09-01). Non-blocking; add when the trigger fires.

## Deferred Items

- **pyproject.toml packaging** — add `console_scripts` entry + `pyproject.toml` so `reforecast` is pip-installable. Currently CLI runs via `python reforecast.py` (brief-specified). Add when users ask to install it as a package.
- **Jupyter `analysis.ipynb` notebook** — same engine behind a point-and-click interface for analysts. Add when a non-CLI user wants it.
- **`--day` / `--week` window filters** — scope analysis to a day or week without editing CSVs. Add on request.
- **`--json-only` mode flag** — skip Excel/matplotlib when only the accuracy JSON is wanted. Add on request.
- **Per-platform CSV adapters (NICE/Teleopti/Verint)** — schema variants only testable against real exports. Add when a real export is available; document schema expectations in README meanwhile.
- **Agent-constraint redistribution solver** — current redistribution is advisory (gap-hours moved over→under). A full optimizer honoring skills/shift windows/contracts is the documented upgrade path. Add when executors need schedule-constrained plans.

## Watch
- Matplotlib must degrade gracefully (Agg backend) so charts don't block CSV/Excel/JSON output.
