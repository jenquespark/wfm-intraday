"""Input validation and reconciliation."""

from __future__ import annotations

import re
from datetime import date

import numpy as np
import pandas as pd

from wfm_intraday.domain.models import (
    ACTUALS_COLUMNS,
    BASE_KEY_COLUMNS,
    FORECAST_COLUMNS,
    SCHEDULE_COLUMNS,
    ReconciliationReport,
    validate_columns,
)

# The canonical join/identity keys shared by every input file.
KEY_COLUMNS: list[str] = BASE_KEY_COLUMNS

# Required numeric fields per source type.  These must be finite numbers,
# and AHT fields must additionally be > 0.  Volume/FTE may be 0 (a real zero).
_NUMERIC_FIELDS: dict[str, list[str]] = {
    "forecast": ["forecast_volume", "forecast_aht_seconds"],
    "actuals": ["actual_volume", "actual_aht_seconds"],
    "staffing": ["scheduled_fte"],
}
_AHT_FIELDS = {"forecast_aht_seconds", "actual_aht_seconds"}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INTERVAL_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def validate_input_files(
    forecast_path: str,
    actuals_path: str,
    staffing_path: str | None = None,
    column_mapping: dict[str, str] | dict[str, dict[str, str]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame | None, list[str]]:
    """Load and validate input CSV files through the single adapter pipeline.

    Loading ALWAYS goes through :class:`GenericCSVAdapter` — with or without a
    ``column_mapping`` — so CLI, API, and web all share one code path.  When no
    mapping is given, the adapter expects canonical column names directly and
    still runs the same hard-fail validations (duplicate keys, negative
    values, unsupported channels, NaN/inf/non-numeric, date & interval formats).

    ``column_mapping`` may be:
      * flat: ``{'date': 'Contact Date', ...}`` (canonical → source; key
        columns apply to every source), or
      * per-section: ``{'forecast': {'date': 'Contact Date', ...}, ...}``.

    Args:
        forecast_path: Path to forecast CSV.
        actuals_path: Path to actuals CSV.
        staffing_path: Optional path to schedule CSV.
        column_mapping: Optional flat or per-section canonical → source mapping.

    Returns:
        (forecast_df, actuals_df, staffing_df_or_None, warnings)

    Raises:
        FileNotFoundError: If a required file does not exist.
        ValueError: If required columns are missing, values are invalid
            (duplicate keys, NaN/inf/non-numeric, negative, malformed date or
            interval_start, unsupported channel), or other structural issues.
    """
    warnings: list[str] = []
    from wfm_intraday.adapters.generic_csv import GenericCSVAdapter

    per_source = _normalize_column_mapping(column_mapping)
    adapter = GenericCSVAdapter(per_source)

    forecast_df = _load_through_adapter(adapter, "forecast", forecast_path)
    actuals_df = _load_through_adapter(adapter, "actuals", actuals_path)
    staffing_df = None
    if staffing_path:
        staffing_df = _load_through_adapter(adapter, "staffing", staffing_path)

    return forecast_df, actuals_df, staffing_df, warnings


def _normalize_column_mapping(
    column_mapping: dict[str, str] | dict[str, dict[str, str]] | None,
) -> dict[str, dict[str, str]]:
    """Normalize flat or per-section mapping to ``{section: {canonical: source}}``.

    * flat (canonical → source): key columns apply to every source type;
      other canonical columns route to their owning section.
    * per-section: used as-is (already validated by Config/validate_column_mapping).

    The returned mapping is validated by :func:`validate_column_mapping`.
    """
    from wfm_intraday.config import validate_column_mapping

    if not column_mapping:
        return {}

    # Per-section form: top-level keys are section names, values are dicts.
    if all(isinstance(v, dict) for v in column_mapping.values()) and set(column_mapping.keys()) <= {
        "forecast",
        "actuals",
        "staffing",
    }:
        per_source: dict[str, dict[str, str]] = {k: dict(v) for k, v in column_mapping.items()}
        validate_column_mapping(per_source)
        return per_source

    # Flat form: canonical → source.
    key_canonical = set(BASE_KEY_COLUMNS)
    flat: dict[str, dict[str, str]] = {}
    for canonical, source in column_mapping.items():
        if canonical in key_canonical:
            for src in ("forecast", "actuals", "staffing"):
                flat.setdefault(src, {})[canonical] = source
        else:
            flat.setdefault(_source_type_for(canonical), {})[canonical] = source
    validate_column_mapping(flat)
    return flat


def _load_through_adapter(adapter, source_type: str, path: str) -> pd.DataFrame:
    """Load through the adapter, then run hard-fail validation.

    The adapter maps source→canonical columns; the validation pass then
    enforces duplicates/negatives/unknown-channels on the canonical frame.
    """
    loader = getattr(adapter, f"load_{source_type}")
    df = loader(path)
    expected = {
        "forecast": FORECAST_COLUMNS,
        "actuals": ACTUALS_COLUMNS,
        "staffing": SCHEDULE_COLUMNS,
    }[source_type]
    return _validate_canonical(df, expected, source_type)


def _source_type_for(canonical: str) -> str:
    """Return the source file type a canonical column belongs to."""
    if canonical in FORECAST_COLUMNS:
        return "forecast"
    if canonical in ACTUALS_COLUMNS:
        return "actuals"
    if canonical in SCHEDULE_COLUMNS:
        return "staffing"
    return "forecast"  # key columns default to forecast


def _validate_canonical(
    df: pd.DataFrame,
    expected_cols: list[str],
    label: str,
) -> pd.DataFrame:
    """Validate a canonical-schema frame with hard-fail checks.

    Assumes the frame is already loaded and column-mapped (by the adapter).
    Enforces (all hard errors):
      * required columns present
      * canonical keys (date/interval_start) well-formed
      * channel values normalized (strip + lowercase) and supported
      * required numeric fields are finite numbers (no NaN / inf / non-numeric)
      * AHT fields are strictly positive
      * no negative values other than AHT-signed semantics
      * no duplicate canonical keys (checked AFTER channel normalization)

    Returns the frame with channel normalized so the SAME canonical values
    flow through the rest of the pipeline.
    """
    # Validate required canonical columns exist.
    try:
        validate_columns(expected_cols, list(df.columns))
    except ValueError as e:
        raise ValueError(f"{label}: {e}")

    # ── Channel normalization (strip + lowercase) BEFORE dup detection ──
    if "channel" in df.columns:
        df = _normalize_channel(df, label)

    # ── Required numeric fields: finite, non-negative, AHT > 0 ─────────
    _validate_numeric(df, label)

    # ── Canonical key formats (date + interval_start) ──────────────────
    if "date" in df.columns:
        _validate_dates(df, label)
    if "interval_start" in df.columns:
        _validate_interval_starts(df, label)

    # ── Duplicate canonical keys (AFTER normalization) ─────────────────
    key_cols = [c for c in KEY_COLUMNS if c in df.columns]
    if key_cols:
        dup_mask = df.duplicated(subset=key_cols, keep=False)
        if dup_mask.any():
            dups = df.loc[dup_mask, key_cols].drop_duplicates()
            examples = ", ".join(
                "(" + ", ".join(str(v) for v in row) + ")"
                for row in dups.head(5).itertuples(index=False, name=None)
            )
            raise ValueError(
                f"{label}: {int(dup_mask.sum())} duplicate key rows across "
                f"{len(dups)} unique canonical key(s). "
                f"Representative keys: {examples}"
            )

    return df


def _normalize_channel(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """Normalize channel values (strip + lowercase) and validate support.

    Normalized canonical values are written back to the frame so every
    downstream consumer (merge, reforecast, staffing, redistribution) uses
    the same normalized channel.  Unsupported channels hard-fail here.
    """
    from wfm_intraday.config import SUPPORTED_CHANNELS

    df = df.copy()
    # Strip whitespace and lowercase.  NaN channels stay NaN (caught below).
    norm = df["channel"].map(lambda v: v.strip().lower() if isinstance(v, str) else v)
    df["channel"] = norm
    bad = set(norm.dropna().unique()) - SUPPORTED_CHANNELS
    if bad:
        raise ValueError(
            f"{label}: unsupported channel(s) {sorted(bad)}. "
            f"Supported channels: {sorted(SUPPORTED_CHANNELS)}. "
            f"Async/back-office is not supported."
        )
    # A null/empty channel is invalid.
    if norm.isna().any() or (norm.astype(str).str.strip() == "").any():
        raise ValueError(f"{label}: channel column contains a missing/empty value.")
    return df


def _validate_numeric(df: pd.DataFrame, label: str) -> None:
    """Ensure required numeric fields are finite non-negative numbers.

    * NaN / infinity -> error (a present row must carry a real number).
    * non-numeric strings (e.g. ``"abc"``) -> error (must be numeric).
    * negative volume / FTE -> error.
    * AHT fields must be strictly positive (zero AHT is invalid).
    """
    for col in _NUMERIC_FIELDS.get(label, []):
        if col not in df.columns:
            continue
        series = df[col]
        # Coerce to numeric to detect non-numeric strings.
        coerced = pd.to_numeric(series, errors="coerce")
        # non-numeric string present?
        non_numeric = series.notna() & coerced.isna()
        if non_numeric.any():
            bad = sorted({str(v) for v in series[non_numeric].head(5)})
            raise ValueError(
                f"{label}: column '{col}' contains non-numeric value(s) {bad}. "
                f"Expected a number (e.g. 100.0), not {bad[0] if bad else ''}."
            )
        # NaN present?
        if coerced.isna().any():
            raise ValueError(
                f"{label}: column '{col}' contains {int(coerced.isna().sum())} "
                f"missing/NaN value(s). A present row must carry a numeric value."
            )
        # Infinity present?
        if bool(np.isinf(coerced.to_numpy(dtype=float)).any()):
            raise ValueError(
                f"{label}: column '{col}' contains infinite (Inf) value(s). "
                f"All required numeric fields must be finite."
            )
        # Negative values (volume / AHT / FTE).
        if bool((coerced < 0).any()):
            raise ValueError(
                f"{label}: column '{col}' has negative value(s). "
                f"Negative volume, AHT, or FTE is invalid operational data."
            )
        # AHT must be strictly positive (zero AHT is invalid — no handling time).
        if col in _AHT_FIELDS and bool((coerced <= 0).any()):
            raise ValueError(
                f"{label}: column '{col}' has a non-positive AHT value. "
                f"AHT must be > 0 seconds; zero/negative AHT is invalid."
            )
        # Write back the coerced numeric values so downstream uses clean floats.
        df[col] = coerced


def _validate_dates(df: pd.DataFrame, label: str) -> None:
    """Ensure date values are valid ``YYYY-MM-DD`` calendar dates."""
    for v in df["date"]:
        s = str(v).strip()
        if not _DATE_RE.match(s):
            raise ValueError(
                f"{label}: invalid date '{s}'. Expected format YYYY-MM-DD (e.g. 2026-09-01)."
            )
        # Verify it is a real calendar date (rejects e.g. 2026-13-40).
        try:
            date.fromisoformat(s)
        except ValueError:
            raise ValueError(
                f"{label}: invalid calendar date '{s}'. Expected a real YYYY-MM-DD date."
            )


def _validate_interval_starts(df: pd.DataFrame, label: str) -> None:
    """Ensure interval_start is ``HH:MM`` with hour 0..23 and minute 0..59."""
    for v in df["interval_start"]:
        s = str(v).strip()
        m = _INTERVAL_RE.match(s)
        if not m:
            raise ValueError(f"{label}: invalid interval_start '{s}'. Expected HH:MM (e.g. 08:30).")
        hour = int(m.group(1))
        minute = int(m.group(2))
        if hour > 23:
            raise ValueError(
                f"{label}: invalid interval_start '{s}': hour {hour} is outside 0..23."
            )
        if minute > 59:
            raise ValueError(
                f"{label}: invalid interval_start '{s}': minute {minute} is outside 0..59."
            )


def _key_set(df: pd.DataFrame | None) -> set:
    if df is None or df.empty:
        return set()
    cols = [c for c in KEY_COLUMNS if c in df.columns]
    if not cols:
        return set()
    return set(zip(*[df[c].astype(str) for c in cols]))


def reconcile_keys(
    forecast_df: pd.DataFrame,
    actuals_df: pd.DataFrame,
    staffing_df: pd.DataFrame | None = None,
) -> ReconciliationReport:
    """Compare key sets across input files and build a reconciliation report.

    This function only *describes* the alignment; it does not raise.  Callers
    that require strict alignment (the public ``analyze`` pipeline and the
    CLI) must inspect ``has_mismatch`` and raise/exit themselves.  See
    ``require_no_mismatch``.
    """
    fc_keys = _key_set(forecast_df)
    ac_keys = _key_set(actuals_df)
    sd_keys = _key_set(staffing_df) if staffing_df is not None else set()

    matched = fc_keys & ac_keys

    return ReconciliationReport(
        forecast_rows=len(forecast_df),
        actual_rows=len(actuals_df),
        scheduled_rows=len(staffing_df) if staffing_df is not None else 0,
        matched_keys=len(matched),
        forecast_only=sorted(str(k) for k in (fc_keys - ac_keys)),
        actual_only=sorted(str(k) for k in (ac_keys - fc_keys)),
        schedule_only=sorted(str(k) for k in (sd_keys - fc_keys - ac_keys)),
    )


def require_no_mismatch(report: ReconciliationReport, mode: str = "retrospective") -> None:
    """Raise ``ValueError`` if the reconciliation report has a hard mismatch.

    * In ``retrospective`` mode, both forecast-only and actual-only keys are
      hard errors (full alignment required).
    * In ``as-of`` mode, forecast-only keys are ALLOWED — they represent future
      intervals whose actuals are not yet observed (the normal intra-day case).
      Actual-only keys remain a hard error (an actual with no forecast is
      always invalid).
    """
    parts: list[str] = []
    if report.actual_only:
        parts.append(f"{len(report.actual_only)} actual-only key(s)")
    if report.schedule_only:
        parts.append(f"{len(report.schedule_only)} schedule-only key(s)")
    if mode != "as-of" and report.forecast_only:
        parts.append(f"{len(report.forecast_only)} forecast-only key(s)")

    if parts:
        raise ValueError("Key mismatch between input files: " + ", ".join(parts) + ".")
