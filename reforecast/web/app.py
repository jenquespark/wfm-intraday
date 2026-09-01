#!/usr/bin/env python3
"""WFM Reforecast Engine — Local web interface.

Start with::

    wfm-reforecast web

Or::

    streamlit run reforecast/web/app.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import streamlit as st
import pandas as pd

from reforecast import analyze, validate, __version__

st.set_page_config(page_title="WFM Reforecast Engine", layout="wide")
st.title("WFM Reforecast Engine")
st.caption(f"v{__version__} — Forecast vs actual gap analysis")

# Session state
if "validated" not in st.session_state:
    st.session_state.validated = False
if "result" not in st.session_state:
    st.session_state.result = None
if "warnings" not in st.session_state:
    st.session_state.warnings = []

# ------------- Sidebar: config -------------
st.sidebar.header("Configuration")

uploaded_forecast = st.sidebar.file_uploader("Forecast CSV", type=["csv"])
uploaded_actuals = st.sidebar.file_uploader("Actuals CSV", type=["csv"])
uploaded_staffing = st.sidebar.file_uploader("Staffing CSV (optional)", type=["csv"])

analysis_date = st.sidebar.text_input("Analysis date (YYYY-MM-DD)", "")
checkpoint = st.sidebar.text_input("Checkpoint (HH:MM)", "")
mode = st.sidebar.selectbox("Mode", ["retrospective", "as-of"], index=0)
lob_filter = st.sidebar.text_input("LOB filter (optional)", "")

col1, col2 = st.sidebar.columns(2)
validate_btn = col1.button("Validate", use_container_width=True)
analyze_btn = col2.button("Run analysis", use_container_width=True, disabled=not st.session_state.validated)

# ------------- Validate -------------
if validate_btn and uploaded_forecast and uploaded_actuals:
    with tempfile.TemporaryDirectory() as tmpdir:
        fc_path = os.path.join(tmpdir, "forecast.csv")
        ac_path = os.path.join(tmpdir, "actuals.csv")
        with open(fc_path, "wb") as f:
            f.write(uploaded_forecast.getbuffer())
        with open(ac_path, "wb") as f:
            f.write(uploaded_actuals.getbuffer())

        sd_path = None
        if uploaded_staffing:
            sd_path = os.path.join(tmpdir, "staffing.csv")
            with open(sd_path, "wb") as f:
                f.write(uploaded_staffing.getbuffer())

        try:
            report = validate(fc_path, ac_path, sd_path)
            st.session_state.validated = True
            st.session_state.warnings = []
            st.success(f"Validation OK — {report.matched_keys} matched keys")
            if report.has_mismatch:
                if report.forecast_only:
                    st.warning(f"Forecast-only keys: {len(report.forecast_only)}")
                if report.actual_only:
                    st.warning(f"Actual-only keys: {len(report.actual_only)}")
        except Exception as e:
            st.session_state.validated = False
            st.error(f"Validation failed: {e}")

# ------------- Analyze -------------
if analyze_btn and st.session_state.validated and uploaded_forecast and uploaded_actuals:
    with st.spinner("Running analysis..."):
        with tempfile.TemporaryDirectory() as tmpdir:
            fc_path = os.path.join(tmpdir, "forecast.csv")
            ac_path = os.path.join(tmpdir, "actuals.csv")
            with open(fc_path, "wb") as f:
                f.write(uploaded_forecast.getbuffer())
            with open(ac_path, "wb") as f:
                f.write(uploaded_actuals.getbuffer())

            sd_path = None
            if uploaded_staffing:
                sd_path = os.path.join(tmpdir, "staffing.csv")
                with open(sd_path, "wb") as f:
                    f.write(uploaded_staffing.getbuffer())

            try:
                result = analyze(
                    forecast_path=fc_path,
                    actuals_path=ac_path,
                    staffing_path=sd_path,
                    date_filter=analysis_date or None,
                    checkpoint_override=checkpoint or None,
                    mode=mode,
                    lob_filter=lob_filter or None,
                )
                st.session_state.result = result

                # Show results
                fa = result.forecast_accuracy
                if "overall" in fa:
                    o = fa["overall"]
                    col1, col2, col3 = st.columns(3)
                    col1.metric("WAPE", f"{o['wape']:.1f}%")
                    col2.metric("MAPE", f"{o['mape']:.1f}%")
                    col3.metric("Bias", f"{o['bias']:+.4f}")

                if result.staffing_gaps:
                    counts = {}
                    for g in result.staffing_gaps:
                        counts[g.status] = counts.get(g.status, 0) + 1
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Understaffed", counts.get("understaffed", 0))
                    c2.metric("Overstaffed", counts.get("overstaffed", 0))
                    c3.metric("Balanced", counts.get("balanced", 0))

                if result.validation and result.validation.has_mismatch:
                    st.warning(f"Key mismatch: {len(result.validation.forecast_only)} forecast-only, {len(result.validation.actual_only)} actual-only")

                # Interval table
                with st.expander("Interval Analysis", expanded=True):
                    rows = []
                    for iv in result.intervals[:200]:
                        rows.append({
                            "Date": iv.date,
                            "Interval": iv.interval_start,
                            "LOB": iv.lob,
                            "Chan": iv.channel,
                            "Fcst Vol": iv.forecast_volume,
                            "Actual Vol": iv.actual_volume or "",
                            "Fcst AHT": iv.forecast_aht_seconds,
                            "Sched FTE": iv.scheduled_fte or "",
                        })
                    st.dataframe(pd.DataFrame(rows), use_container_width=True)
                    if len(result.intervals) > 200:
                        st.caption(f"Showing 200 of {len(result.intervals)} intervals")

                # Redistribution table
                if result.redistribution:
                    with st.expander("Redistribution Recommendations"):
                        rows = []
                        for r in result.redistribution:
                            rows.append({
                                "Date": r.date,
                                "LOB": r.lob,
                                "From": r.from_interval_start,
                                "To": r.to_interval_start,
                                "FTE": r.recommended_transfer_fte,
                                "Hours": r.recommended_transfer_hours,
                            })
                        st.dataframe(pd.DataFrame(rows), use_container_width=True)

                # Download buttons
                st.subheader("Download")
                out_dir = os.path.join(tmpdir, "output")
                os.makedirs(out_dir, exist_ok=True)

                from reforecast.reporting.excel import write_excel_report
                excel_path = os.path.join(out_dir, "reforecast_report.xlsx")
                write_excel_report(excel_path, result)
                with open(excel_path, "rb") as f:
                    st.download_button("Download Excel Report", f, file_name="reforecast_report.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

                from reforecast.reporting.json import write_analysis_json
                json_path = os.path.join(out_dir, "analysis.json")
                write_analysis_json(json_path, result)
                with open(json_path, "rb") as f:
                    st.download_button("Download JSON", f, file_name="analysis.json", mime="application/json")

                from reforecast.reporting.csv import write_interval_csv
                csv_path = os.path.join(out_dir, "interval_analysis.csv")
                write_interval_csv(csv_path, result)
                with open(csv_path, "rb") as f:
                    st.download_button("Download Interval CSV", f, file_name="interval_analysis.csv", mime="text/csv")

            except Exception as e:
                st.error(f"Analysis failed: {e}")
                import traceback
                st.code(traceback.format_exc())

# ------------- Footer help -------------
if not st.session_state.validated:
    st.info("Upload forecast and actuals CSV files, then click Validate.")

st.sidebar.markdown("---")
st.sidebar.caption(
    "WFM Reforecast Engine compares forecast and actual contact volume "
    "at interval level and recalculates staffing requirements."
)