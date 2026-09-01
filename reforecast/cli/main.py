#!/usr/bin/env python3
"""WFM Reforecast Engine — CLI entry point.

Usage::

    wfm-reforecast validate --forecast data/forecast.csv --actual data/actual.csv
    wfm-reforecast analyze --forecast data/forecast.csv --actual data/actual.csv
    wfm-reforecast sample
    wfm-reforecast web
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import List, Optional

from reforecast import __version__
from reforecast.domain.models import AnalysisResult
from reforecast.validation.inputs import validate_input_files, reconcile_keys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Exit codes — deterministic and documented
EXIT_SUCCESS = 0
EXIT_CONFIG_ERROR = 1
EXIT_INPUT_ERROR = 2
EXIT_CALC_ERROR = 3
EXIT_OUTPUT_ERROR = 4


def _common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--forecast", required=True, help="Forecast CSV path")
    parser.add_argument("--actual", required=True, dest="actuals", help="Actuals CSV path")
    parser.add_argument("--staffing", default=None, help="Schedule/staffing CSV path (optional)")
    parser.add_argument("--config", default=None,
                        help="Config YAML path (default: config.yaml in cwd, or built-in defaults)")
    parser.add_argument("--lob", default=None, help="Filter to one LOB")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wfm-reforecast",
        description="Interval-level forecast vs actual gap analysis for contact centers",
    )
    parser.add_argument("--version", action="store_true", help="Print version and exit")

    sub = parser.add_subparsers(dest="command")

    # validate
    vp = sub.add_parser("validate", help="Validate input files without running analysis")
    _common_args(vp)

    # analyze
    ap = sub.add_parser("analyze", help="Run full analysis")
    _common_args(ap)
    ap.add_argument("--output-dir", default="output", help="Output directory (default: output/)")
    ap.add_argument("--date", default=None, help="Analysis date (YYYY-MM-DD)")
    ap.add_argument("--checkpoint", default=None, help="Checkpoint time (HH:MM)")
    ap.add_argument("--mode", default="retrospective", choices=["retrospective", "as-of"],
                    help="retrospective (all data) or as-of (checkpoint-aware)")

    # sample
    sub.add_parser("sample", help="Generate sample data in ./data/")

    # web
    sub.add_parser("web", help="Launch local web interface (requires streamlit)")

    return parser


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate input files and print reconciliation report."""
    try:
        fc_df, ac_df, sd_df, warns = validate_input_files(
            args.forecast, args.actuals, args.staffing
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    report = reconcile_keys(fc_df, ac_df, sd_df)

    print("=== INPUT VALIDATION ===")
    print(f"  Forecast: {report.forecast_rows} rows")
    print(f"  Actuals:  {report.actual_rows} rows")
    if sd_df is not None:
        print(f"  Staffing: {report.scheduled_rows} rows")
    else:
        print("  Staffing: not provided")
    print(f"  Matched keys: {report.matched_keys}")
    if report.has_mismatch:
        print("  WARNINGS:")
        if report.forecast_only:
            print(f"    Forecast-only keys: {len(report.forecast_only)}")
        if report.actual_only:
            print(f"    Actual-only keys:   {len(report.actual_only)}")
    if warns:
        for w in warns:
            print(f"  WARNING: {w}")
    print("  Validation: OK" if not report.has_mismatch else "  Validation: PASSED WITH WARNINGS")
    return EXIT_SUCCESS


def cmd_analyze(args: argparse.Namespace) -> int:
    """Run the full analysis pipeline."""
    from reforecast import analyze as run_analysis
    from reforecast.config import Config

    # Load config
    config_path = args.config
    if config_path is None:
        try:
            config = Config.from_yaml("config.yaml")
        except FileNotFoundError:
            config = Config()
            print("Using built-in default configuration (config.yaml not found)")
    else:
        try:
            config = Config.from_yaml(config_path)
        except FileNotFoundError:
            print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
            return EXIT_CONFIG_ERROR
        except ValueError as e:
            print(f"ERROR: Invalid config: {e}", file=sys.stderr)
            return EXIT_CONFIG_ERROR

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
    except Exception as e:
        print(f"CALCULATION ERROR: {e}", file=sys.stderr)
        return EXIT_CALC_ERROR

    # Write outputs — any failure returns non-zero
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)
    output_errors = 0

    try:
        from reforecast.reporting.excel import write_excel_report
        excel_path = os.path.join(output_dir, "reforecast_report.xlsx")
        write_excel_report(excel_path, result)
        print(f"Excel: {excel_path}")
    except Exception as e:
        print(f"ERROR: Excel write failed: {e}", file=sys.stderr)
        output_errors += 1

    try:
        from reforecast.reporting.json import write_analysis_json
        json_path = os.path.join(output_dir, "accuracy_summary.json")
        write_analysis_json(json_path, result)
        print(f"JSON:  {json_path}")
    except Exception as e:
        print(f"ERROR: JSON write failed: {e}", file=sys.stderr)
        output_errors += 1

    try:
        from reforecast.reporting.csv import write_interval_csv, write_redistribution_csv
        csv_path = os.path.join(output_dir, "interval_analysis.csv")
        write_interval_csv(csv_path, result)
        if result.redistribution:
            redist_path = os.path.join(output_dir, "redistribution_plan.csv")
            write_redistribution_csv(redist_path, result)
    except Exception as e:
        print(f"ERROR: CSV write failed: {e}", file=sys.stderr)
        output_errors += 1

    # Print summary
    _print_summary(result)

    if output_errors > 0:
        return EXIT_OUTPUT_ERROR
    return EXIT_SUCCESS


def _print_summary(result: AnalysisResult) -> None:
    print("\n" + "=" * 60)
    print("ANALYSIS SUMMARY")
    print("=" * 60)

    if result.validation and result.validation.has_mismatch:
        print("\n⚠ KEY MISMATCHES")
        if result.validation.forecast_only:
            print(f"  Forecast-only: {len(result.validation.forecast_only)}")
        if result.validation.actual_only:
            print(f"  Actual-only:   {len(result.validation.actual_only)}")

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
    from reforecast import generate_sample_data
    generate_sample_data("data")
    print("Sample data generated in data/")
    return EXIT_SUCCESS


def cmd_web(args: argparse.Namespace) -> int:
    """Launch the local web interface."""
    try:
        import streamlit  # noqa: F401
    except ImportError:
        print(
            "Web interface dependencies are not installed.\n"
            "Install with:\n\n"
            "    pip install -e \".[web]\"\n",
            file=sys.stderr,
        )
        return EXIT_INPUT_ERROR

    import subprocess
    web_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "app.py")
    subprocess.run([sys.executable, "-m", "streamlit", "run", web_path])
    return EXIT_SUCCESS


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if hasattr(args, "version") and args.version:
        print(f"wfm-reforecast {__version__}")
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