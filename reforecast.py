#!/usr/bin/env python3
"""WFM Reforecast Engine — CLI entry point.

Compares forecast vs actual contact center demand, detects staffing gaps,
recommends flexible-hour redistribution, and performs intra-day reforecasting.

Usage:
    python reforecast.py --forecast data/forecast.csv --actuals data/actuals.csv --config config.yaml
    python reforecast.py --forecast data/forecast.csv --actuals data/actuals.csv --lob inbound_calls
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Dict, List, Any

from reforecast import Config
from reforecast.metrics import calculate_all, calculate_per_lob
from reforecast.io import (
    load_forecast,
    load_actuals,
    merge_forecast_actuals,
    write_excel_report,
    write_redistribution_csv,
    write_accuracy_json,
)
from reforecast.calculator import (
    calculate_staffing_gap,
    calculate_redistribution,
    calculate_reforecast,
    format_summary,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="WFM Reforecast Engine — Forecast vs Actual Gap Analysis for Contact Centers",
    )
    parser.add_argument(
        "--forecast",
        required=True,
        help="Path to forecast CSV (columns: date, lob, interval_start, forecast_volume, forecast_aht)",
    )
    parser.add_argument(
        "--actuals",
        required=True,
        help="Path to actuals CSV (columns: date, lob, interval_start, actual_volume, actual_aht)",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config YAML (default: config.yaml)",
    )
    parser.add_argument(
        "--lob",
        default=None,
        help="Optional LOB filter — analyze only one line of business",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Output directory (default: output/)",
    )
    parser.add_argument(
        "--charts",
        action="store_true",
        default=False,
        help="Generate matplotlib charts (requires matplotlib)",
    )
    return parser.parse_args()


def main() -> int:
    """Main entry point. Returns 0 on success, 1 on error."""
    args = parse_args()

    # Load config
    try:
        config = Config.from_yaml(args.config)
        logger.info("Config loaded from %s", args.config)
    except FileNotFoundError:
        logger.error("Config file not found: %s", args.config)
        logger.error("Create config.yaml or specify --config path")
        return 1
    except ValueError as e:
        logger.error("Invalid config: %s", e)
        return 1

    # Load data
    try:
        forecast_df = load_forecast(args.forecast)
        actuals_df = load_actuals(args.actuals)
        logger.info(
            "Loaded %s forecast rows and %s actuals rows",
            len(forecast_df),
            len(actuals_df),
        )
    except (FileNotFoundError, ValueError) as e:
        logger.error("Data load error: %s", e)
        return 1

    # Merge
    try:
        merged_df = merge_forecast_actuals(forecast_df, actuals_df)
        logger.info("Merged data: %s rows", len(merged_df))
    except ValueError as e:
        logger.error("Merge error: %s", e)
        return 1

    # Filter by LOB if specified
    if args.lob:
        merged_df = merged_df[merged_df["lob"] == args.lob].copy()
        logger.info("Filtered to LOB '%s': %s rows", args.lob, len(merged_df))
        if merged_df.empty:
            logger.error("No data found for LOB '%s'", args.lob)
            return 1

    # Calculate accuracy metrics
    per_lob_metrics = calculate_per_lob(merged_df)
    overall = calculate_all(
        merged_df["actual_volume"].to_numpy(),
        merged_df["forecast_volume"].to_numpy(),
    )
    logger.info(
        "Overall accuracy — WAPE: %.2f%%, MAPE: %.2f%%, Bias: %+.4f",
        overall.wape,
        overall.mape,
        overall.bias,
    )

    # Calculate staffing gaps
    gaps = calculate_staffing_gap(merged_df, config, lob_filter=args.lob)
    gap_counts: Dict[str, int] = {"understaffed": 0, "overstaffed": 0, "balanced": 0}
    for g in gaps:
        gap_counts[g.status] = gap_counts.get(g.status, 0) + 1
    logger.info(
        "Staffing gaps — understaffed: %d, overstaffed: %d, balanced: %d",
        gap_counts.get("understaffed", 0),
        gap_counts.get("overstaffed", 0),
        gap_counts.get("balanced", 0),
    )

    # Calculate redistribution
    recommendations = calculate_redistribution(gaps, config)
    logger.info("Redistribution recommendations: %d", len(recommendations))

    # Calculate reforecast
    reforecast_results = calculate_reforecast(
        forecast_df, actuals_df, config, lob_filter=args.lob
    )

    # Determine output dir
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    # Transform merged data into per-LOB DataFrames for Excel
    lob_dfs: Dict[str, Any] = {}
    for lob_name, group in merged_df.groupby("lob"):
        lob_dfs[str(lob_name)] = group

    # Write Excel report
    excel_path = os.path.join(output_dir, "reforecast_report.xlsx")
    try:
        write_excel_report(excel_path, lob_dfs, per_lob_metrics, overall)
        logger.info("Excel report written to %s", excel_path)
    except Exception as e:
        logger.warning("Could not write Excel report: %s", e)

    # Write redistribution CSV
    redist_path = os.path.join(output_dir, "redistribution_plan.csv")
    try:
        write_redistribution_csv(redist_path, recommendations)
        logger.info("Redistribution plan written to %s", redist_path)
    except Exception as e:
        logger.warning("Could not write redistribution plan: %s", e)

    # Write accuracy JSON
    json_path = os.path.join(output_dir, "accuracy_summary.json")
    try:
        write_accuracy_json(json_path, per_lob_metrics, overall)
        logger.info("Accuracy summary written to %s", json_path)
    except Exception as e:
        logger.warning("Could not write accuracy summary: %s", e)

    # Generate charts if requested
    if args.charts:
        _generate_charts(merged_df, output_dir, args.lob)

    # Print summary
    summary = format_summary(
        per_lob_metrics=per_lob_metrics,
        overall_metrics=overall,
        gap_counts=gap_counts,
        redistribution_count=len(recommendations),
        reforecast_results=reforecast_results,
    )
    print(summary)

    return 0


def _generate_charts(merged_df: Any, output_dir: str, lob_filter: str = None) -> None:
    """Generate matplotlib charts for the analysis.

    Gracefully handles the case where matplotlib is not installed.

    Args:
        merged_df: Merged forecast/actuals DataFrame.
        output_dir: Output directory for chart files.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning(
            "matplotlib not installed — skipping chart generation. "
            "Install with: pip install matplotlib"
        )
        return

    lobs = [lob_filter] if lob_filter else merged_df["lob"].unique()

    for lob in lobs:
        lob_data = merged_df[merged_df["lob"] == lob].copy()
        if lob_data.empty:
            continue
        lob_data = lob_data.sort_values(["date", "interval_start"]).reset_index(drop=True)

        # Forecast vs Actual line chart
        fig, ax = plt.subplots(figsize=(12, 4))
        x = range(len(lob_data))
        ax.plot(x, lob_data["forecast_volume"], label="Forecast", marker=".", linestyle="--", alpha=0.7)
        ax.plot(x, lob_data["actual_volume"], label="Actual", marker=".", linestyle="-", alpha=0.9)
        ax.set_title(f"Forecast vs Actual — {lob}")
        ax.set_xlabel("Interval")
        ax.set_ylabel("Volume")
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        path = os.path.join(output_dir, f"forecast_vs_actual_{lob}.png")
        fig.savefig(path, dpi=100)
        plt.close(fig)
        logger.info("Chart saved: %s", path)


if __name__ == "__main__":
    sys.exit(main())