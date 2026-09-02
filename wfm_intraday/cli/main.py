#!/usr/bin/env python3
"""WFM Intraday — CLI entry point.

Usage::

    wfm-intraday validate --forecast data/forecast.csv --actual data/actual.csv
    wfm-intraday analyze --forecast data/forecast.csv --actual data/actual.csv
    wfm-intraday sample
    wfm-intraday web
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from wfm_intraday import __version__
from wfm_intraday.domain.models import AnalysisResult

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Exit codes — deterministic and documented
EXIT_SUCCESS = 0
EXIT_CONFIG_ERROR = 1
EXIT_INPUT_ERROR = 2
EXIT_CALC_ERROR = 3
EXIT_OUTPUT_ERROR = 4


def _load_config_for_cli(config_path: str | None):
    """Load the config for a CLI command, mapping every config failure to exit 1.

    The CLI exit-code contract is:
        * 0 = success
        * 1 = config error (missing or malformed config file)
        * 2 = input/validation error

    Args:
        config_path: Explicit ``--config`` path, or None to use ``config.yaml``
            in the current directory (falling back to built-in defaults when
            it does not exist).

    Returns:
        A ``(config, exit_code, used_defaults)`` tuple.  When *exit_code* is not
        None the config is malformed or missing and the error has already been
        printed to stderr — the caller must return it.  *used_defaults* is True
        when no config file existed and built-in defaults were used.
    """
    from wfm_intraday.config import Config

    if config_path is None:
        try:
            return Config.from_yaml("config.yaml"), None, False
        except FileNotFoundError:
            return Config(), None, True
        except ValueError as e:
            # A malformed default config.yaml must fail cleanly (exit 1),
            # never raise a traceback.
            print(f"ERROR: Invalid config: {e}", file=sys.stderr)
            return None, EXIT_CONFIG_ERROR, False
    try:
        return Config.from_yaml(config_path), None, False
    except FileNotFoundError:
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        return None, EXIT_CONFIG_ERROR, False
    except ValueError as e:
        print(f"ERROR: Invalid config: {e}", file=sys.stderr)
        return None, EXIT_CONFIG_ERROR, False


def _common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--forecast", required=True, help="Forecast CSV path")
    parser.add_argument("--actual", required=True, dest="actuals", help="Actuals CSV path")
    parser.add_argument("--staffing", default=None, help="Schedule/staffing CSV path (optional)")
    parser.add_argument(
        "--config",
        default=None,
        help="Config YAML path (default: config.yaml in cwd, or built-in defaults)",
    )
    parser.add_argument("--lob", default=None, help="Filter to one LOB")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wfm-intraday",
        description="Interval-level forecast variance, reforecasting, and staffing gap analysis for contact center WFM teams",
    )
    parser.add_argument("--version", action="store_true", help="Print version and exit")

    sub = parser.add_subparsers(dest="command")

    # validate
    vp = sub.add_parser("validate", help="Validate input files without running analysis")
    _common_args(vp)
    vp.add_argument("--mode", default="retrospective", choices=["retrospective", "as-of"])
    vp.add_argument("--checkpoint", default=None, help="Checkpoint time (HH:MM), for as-of")
    vp.add_argument("--date", default=None, help="Analysis date (YYYY-MM-DD)")

    # analyze
    ap = sub.add_parser("analyze", help="Run full analysis")
    _common_args(ap)
    ap.add_argument("--output-dir", default="output", help="Output directory (default: output/)")
    ap.add_argument("--date", default=None, help="Analysis date (YYYY-MM-DD)")
    ap.add_argument("--checkpoint", default=None, help="Checkpoint time (HH:MM)")
    ap.add_argument(
        "--mode",
        default="retrospective",
        choices=["retrospective", "as-of"],
        help="retrospective (all data) or as-of (checkpoint-aware)",
    )

    # sample
    sub.add_parser("sample", help="Generate sample data in ./data/")

    # web
    sub.add_parser("web", help="Launch local web interface (requires streamlit)")

    return parser


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate input files and print reconciliation report.

    Routes through the single strict public ``validate()`` service shared with
    analyze() and the web interface.  Duplicate keys, true key mismatches,
    NaN/inf/non-numeric values, malformed dates / interval_start / checkpoint,
    and unsupported channels HARD-FAIL with exit 2.  A missing or malformed
    config file returns exit 1.  Supports as-of mode with a checkpoint (a
    genuinely future forecast-only interval is valid; a completed interval
    missing an actual hard-fails).
    """
    from wfm_intraday import validate as run_validate

    # Load config FIRST so config errors exit 1; only input errors exit 2.
    config, cfg_error, _ = _load_config_for_cli(args.config)
    if cfg_error is not None:
        return cfg_error

    try:
        report = run_validate(
            args.forecast,
            args.actuals,
            args.staffing,
            config_obj=config,
            mode=args.mode,
            checkpoint=args.checkpoint,
            date_filter=args.date,
            lob_filter=args.lob,
        )
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    print("=== INPUT VALIDATION ===")
    print(f"  Forecast: {report.forecast_rows} rows")
    print(f"  Actuals:  {report.actual_rows} rows")
    if args.staffing:
        print(f"  Staffing: {report.scheduled_rows} rows")
    else:
        print("  Staffing: not provided")
    print(f"  Matched keys: {report.matched_keys}")
    print(f"  Mode: {args.mode}")
    if args.checkpoint:
        print(f"  Checkpoint: {args.checkpoint}")
    if args.date:
        print(f"  Date: {args.date}")
    if args.lob:
        print(f"  LOB: {args.lob}")
    print("  Validation: OK")
    return EXIT_SUCCESS


def cmd_analyze(args: argparse.Namespace) -> int:
    """Run the full analysis pipeline."""
    from wfm_intraday import analyze as run_analysis

    # Load config — every config failure (missing OR malformed default
    # config.yaml included) returns exit 1 without a traceback.
    config, cfg_error, used_defaults = _load_config_for_cli(args.config)
    if cfg_error is not None:
        return cfg_error
    if used_defaults:
        print("Using built-in default configuration (config.yaml not found)")

    # Run analysis
    try:
        result = run_analysis(
            forecast_path=args.forecast,
            actuals_path=args.actuals,
            staffing_path=args.staffing,
            config_obj=config,
            lob_filter=args.lob,
            date_filter=args.date,
            checkpoint=args.checkpoint,
            mode=args.mode,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    except Exception as e:  # noqa: BLE001 — top-level CLI boundary maps any error to exit 3
        print(f"CALCULATION ERROR: {e}", file=sys.stderr)
        return EXIT_CALC_ERROR

    # Write outputs — any failure returns EXIT_OUTPUT_ERROR (4).
    output_dir = args.output_dir
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        print(f"ERROR: Cannot create output directory '{output_dir}': {e}", file=sys.stderr)
        return EXIT_OUTPUT_ERROR
    output_errors = 0

    try:
        from wfm_intraday.reporting.excel import write_excel_report

        excel_path = os.path.join(output_dir, "intraday_report.xlsx")
        write_excel_report(excel_path, result)
        print(f"Excel: {excel_path}")
    except Exception as e:  # noqa: BLE001 — reporter failure must be reported, not crash
        print(f"ERROR: Excel write failed: {e}", file=sys.stderr)
        output_errors += 1

    try:
        from wfm_intraday.reporting.json import write_analysis_json

        json_path = os.path.join(output_dir, "analysis.json")
        write_analysis_json(json_path, result)
        print(f"JSON:  {json_path}")
    except Exception as e:  # noqa: BLE001 — reporter failure must be reported, not crash
        print(f"ERROR: JSON write failed: {e}", file=sys.stderr)
        output_errors += 1

    try:
        from wfm_intraday.reporting.csv import write_interval_csv, write_redistribution_csv

        csv_path = os.path.join(output_dir, "interval_analysis.csv")
        write_interval_csv(csv_path, result)
        if result.redistribution:
            redist_path = os.path.join(output_dir, "redistribution_plan.csv")
            write_redistribution_csv(redist_path, result)
    except Exception as e:  # noqa: BLE001 — reporter failure must be reported, not crash
        print(f"ERROR: CSV write failed: {e}", file=sys.stderr)
        output_errors += 1

    # Print summary
    _print_summary(result, mode=args.mode)

    if output_errors > 0:
        return EXIT_OUTPUT_ERROR
    return EXIT_SUCCESS


def _print_summary(result: AnalysisResult, mode: str = "retrospective") -> None:
    print("\n" + "=" * 60)
    print("ANALYSIS SUMMARY")
    print("=" * 60)

    validation = result.validation
    if validation:
        if validation.actual_only:
            # Actual-only keys are always a true mismatch.
            print("\n⚠ ACTUAL-ONLY KEYS (no matching forecast)")
            print(f"  Actual-only: {len(validation.actual_only)}")
        if mode != "as-of" and validation.forecast_only:
            # In retrospective mode, forecast-only keys are a true mismatch.
            # In as-of mode they are legitimately future intervals.
            print("\n⚠ FORECAST-ONLY KEYS")
            print(f"  Forecast-only: {len(validation.forecast_only)}")

    fa = result.forecast_accuracy
    if "overall" in fa:
        o = fa["overall"]
        print(f"\n📊 WAPE: {o['wape']:.2f}%  MAPE: {o['mape']:.2f}%  Bias: {o['bias']:+.4f}")

    if "per_lob" in fa:
        for lob, m in sorted(fa["per_lob"].items()):
            print(f"  {lob:20s}  WAPE: {m['wape']:.2f}%  Bias: {m['bias']:+.4f}")

    gaps = result.staffing_gaps
    if gaps:
        counts = {}
        for g in gaps:
            counts[g.status] = counts.get(g.status, 0) + 1
        print("\n📋 STAFFING")
        print(f"  Understaffed:  {counts.get('understaffed', 0)}")
        print(f"  Overstaffed:   {counts.get('overstaffed', 0)}")
        print(f"  Balanced:      {counts.get('balanced', 0)}")
        if counts.get("no_schedule", 0):
            print(f"  No schedule:   {counts.get('no_schedule', 0)}")

    if result.redistribution:
        print(f"  Redistribution moves: {len(result.redistribution)}")

    if result.reforecast_results:
        print(f"\n🔄 REFORECAST ({len(result.reforecast_results)} groups)")
        for rr in result.reforecast_results[:3]:
            print(f"  {rr.date} / {rr.lob}: Δ={rr.deviation_pct:+.1%}")

    print("\n" + "=" * 60)


def cmd_sample(args: argparse.Namespace) -> int:
    """Generate sample data."""
    from wfm_intraday import generate_sample_data

    generate_sample_data("data")
    print("Sample data generated in data/")
    return EXIT_SUCCESS


def cmd_web(args: argparse.Namespace) -> int:
    """Launch the local web interface."""
    try:
        import streamlit
    except ImportError:
        print(
            "Web interface dependencies are not installed.\n"
            "Install with:\n\n"
            '    pip install -e ".[web]"\n',
            file=sys.stderr,
        )
        return EXIT_INPUT_ERROR

    import subprocess

    web_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "app.py")
    subprocess.run([sys.executable, "-m", "streamlit", "run", web_path], check=False)
    return EXIT_SUCCESS


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if hasattr(args, "version") and args.version:
        print(f"wfm-intraday {__version__}")
        return EXIT_SUCCESS

    commands = {
        "validate": cmd_validate,
        "analyze": cmd_analyze,
        "sample": cmd_sample,
        "web": cmd_web,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)

    parser.print_help()
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
