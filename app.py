"""
Opex & HC Outlook dashboard.

Run with:  streamlit run app.py
Connects live to the finance SQL server (Windows auth), lets you pick a
segment / fiscal year / quarter and the Outlook weeks to compare, and renders
the P&L walk with headcount, per-head metrics, variances and charts. Everything
on screen can be exported to Excel / PDF / CSV for leaders.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
import db
import export
import fiscal
import store
import transform

st.set_page_config(page_title="Opex & HC Outlook", layout="wide", page_icon="📊")


# --------------------------------------------------------------------------
# Cached data access (cleared by the Refresh button)
# --------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner="Querying finance SQL…")
def _segments():
    return db.list_segments()


@st.cache_data(ttl=3600, show_spinner="Loading fiscal years…")
def _fiscal_years(segments):
    return db.list_fiscal_years(segments)


@st.cache_data(ttl=3600)
def _default_year():
    return db.latest_outlook_year()


@st.cache_data(ttl=3600)
def _current_quarter():
    """The live fiscal quarter from the view's own marker (auto-rolls)."""
    return db.current_quarter()


@st.cache_data(ttl=3600, show_spinner="Loading versions…")
def _versions(view, fy):
    return db.list_versions(view, fy)


@st.cache_data(ttl=3600, show_spinner="Pulling opex…")
def _expense(segments, fy, versions):
    return db.expense_by_cost_element(segments, fy, versions)


@st.cache_data(ttl=3600, show_spinner="Pulling headcount…")
def _headcount(segments, fy, versions):
    return db.headcount_by_period(segments, fy, versions)


@st.cache_data(ttl=3600, show_spinner="Pulling historical actuals…")
def _actuals(segments, fys):
    return db.actuals_by_quarter(segments, fys)


def _fmt(df, decimals=1):
    return df.style.format(f"{{:,.{decimals}f}}")


# --------------------------------------------------------------------------
# Sidebar filters
# --------------------------------------------------------------------------
st.sidebar.title("📊 Opex & HC Outlook")
if st.sidebar.button("🔄 Refresh data from SQL", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

try:
    all_segments = _segments()
except Exception as e:
    st.error(f"Could not connect to SQL server ({config.SQL_SERVER}).\n\n{e}")
    st.stop()

default_segs = [s for s in config.DEFAULT_SEGMENTS if s in all_segments] or all_segments[:1]
segments = st.sidebar.multiselect(
    "Segment (CCH Lvl 3)", all_segments, default=default_segs
)
if not segments:
    st.info("Pick at least one segment to begin.")
    st.stop()

# fiscal quarters available for this FY (light distinct query)
@st.cache_data(ttl=3600)
def _quarters(segments, fy):
    sql = (
        f"SELECT DISTINCT [Fiscal Qtr/Year] q FROM {config.EXPENSE_VIEW} "
        f"WHERE [Fiscal Year]=? ORDER BY q"
    )
    return db.query(sql, [fy])["q"].dropna().tolist()


# --- Auto-detect the current quarter and default everything to it -----------
live_quarter = _current_quarter()          # e.g. '2026-Q3'
live_fy = live_quarter.split("-")[0] if live_quarter else _default_year()

fiscal_years = _fiscal_years(segments)
_fy_idx = fiscal_years.index(live_fy) if live_fy in fiscal_years else (len(fiscal_years) - 1)

with st.sidebar.expander("Reporting period", expanded=False):
    st.caption(f"Live current quarter: **{live_quarter or 'n/a'}** (auto-rolls each quarter)")
    fy = st.selectbox("Fiscal Year", fiscal_years, index=_fy_idx if fiscal_years else 0)
    exp_versions = _versions(config.EXPENSE_VIEW, fy)
    quarters = _quarters(segments, fy)
    _q_idx = quarters.index(live_quarter) if live_quarter in quarters else (len(quarters) - 1 if quarters else 0)
    current_quarter = st.selectbox("Quarter", quarters, index=_q_idx)

st.sidebar.markdown("**Columns to show**")
include_qtd = st.sidebar.checkbox("Quarter-to-date Actuals", value=True)
include_plan = st.sidebar.checkbox("Plan", value=True)
include_qrf = st.sidebar.checkbox("QRF", value=True)
include_forecast = st.sidebar.checkbox("Forecast (current)", value=True)

hc_measure_label = st.sidebar.selectbox(
    "Headcount convention", list(transform.HC_MEASURES.keys()), index=0,
    help="How to collapse a quarter's monthly headcount into one figure.",
)
hc_measure = transform.HC_MEASURES[hc_measure_label]

n_hist = st.sidebar.slider("Prior actual quarters to show", 0, 12, 6)

# --------------------------------------------------------------------------
# Resolve scenarios + pull data
# --------------------------------------------------------------------------
scenarios = fiscal.resolve_reporting_scenarios(
    fy, current_quarter, exp_versions,
    include_qtd_actuals=include_qtd, include_plan=include_plan,
    include_qrf=include_qrf, include_forecast=include_forecast,
)
if not scenarios:
    st.warning("No matching Actuals/Plan/QRF/Forecast versions for this selection.")
    st.stop()

scenario_versions = [s.version for s in scenarios]

# historical quarters (chronological), excluding the current one
hist_quarters = [q for q in quarters if fiscal.quarter_sort_key(q) < fiscal.quarter_sort_key(current_quarter)]
hist_quarters = hist_quarters[-n_hist:] if n_hist else []
hist_fys = sorted({q.split("-")[0] for q in hist_quarters}) or [fy]

expense_df = _expense(segments, fy, scenario_versions)
hc_df = _headcount(segments, fy, scenario_versions)
actuals_df = _actuals(segments, hist_fys)

walk = transform.build_opex_walk(
    expense_df, actuals_df, scenarios, current_quarter, hist_quarters
)
hc_row = transform.headcount_row(hc_df, scenarios, current_quarter, hc_measure)
per_head = transform.per_head_metrics(
    walk, hc_row,
    ["Comp & Benefits", "Bonuses & Commissions", "Travel & Entertainment"],
)
var_df = transform.variances(walk, scenarios)
ro = transform.risks_and_opportunities(walk, scenarios, hc_row)
headline = fiscal.headline_label(scenarios)

title = f"{' + '.join(segments)}  —  FY{fy[-2:]} {current_quarter.split('-')[1]}"

# Load any saved commentary for this segment-set + quarter
saved = store.load_commentary(segments, current_quarter)

# --------------------------------------------------------------------------
# Main view
# --------------------------------------------------------------------------
st.title(title)
st.caption("Amount in $M · live from finance_systems · " + ", ".join(s.label for s in scenarios))

# KPI strip anchored on the Forecast
qrf_lbl = next((s.label for s in scenarios if s.kind == "qrf"), None)
plan_lbl = next((s.label for s in scenarios if s.kind == "plan"), None)
k1, k2, k3, k4 = st.columns(4)
if headline:
    k1.metric(f"Total Opex ({headline})", f"${walk.loc['Total', headline]:,.1f}M")
    if hc_row.get(headline):
        k2.metric(f"Headcount ({headline})", f"{hc_row[headline]:,.0f}")
    if qrf_lbl:
        d = walk.loc["Total", headline] - walk.loc["Total", qrf_lbl]
        k3.metric(f"{headline} vs {qrf_lbl}", f"${d:,.1f}M", delta=f"{d:,.1f}", delta_color="inverse")
    if plan_lbl:
        d = walk.loc["Total", headline] - walk.loc["Total", plan_lbl]
        k4.metric(f"{headline} vs {plan_lbl}", f"${d:,.1f}M", delta=f"{d:,.1f}", delta_color="inverse")

tab_walk, tab_hc, tab_var, tab_ro, tab_chart, tab_export = st.tabs(
    ["💰 Opex Walk", "👥 Headcount", "📐 Variances", "🎯 Risks & Opportunities",
     "📈 Charts", "⬇️ Export & Snapshot"]
)

with tab_walk:
    st.subheader("Opex by Cost Element")
    st.dataframe(_fmt(walk), use_container_width=True, height=520)

    st.subheader("✏️ Commentary (editable — saved for this quarter)")
    cmt_rows = [r for r in walk.index if r != "Total"] + ["Total"]
    cmt_df = pd.DataFrame(
        {"Cost Element": cmt_rows,
         "Commentary": [saved.get("lines", {}).get(r, "") for r in cmt_rows]}
    )
    edited = st.data_editor(
        cmt_df, use_container_width=True, hide_index=True, key="cmt_editor",
        column_config={
            "Cost Element": st.column_config.TextColumn(disabled=True, width="medium"),
            "Commentary": st.column_config.TextColumn(width="large"),
        },
    )
    commentary_map = dict(zip(edited["Cost Element"], edited["Commentary"].fillna("")))
    if st.button("💾 Save commentary"):
        saved["lines"] = commentary_map
        store.save_commentary(segments, current_quarter, saved)
        st.success("Commentary saved.")

    if not per_head.empty:
        st.subheader("Per Head Metrics ($'000s)")
        st.dataframe(_fmt(per_head), use_container_width=True)

with tab_hc:
    st.subheader(f"Headcount — {hc_measure_label}")
    st.dataframe(_fmt(hc_row.to_frame().T, 0), use_container_width=True)
    st.caption("The quarter headcount convention is a business rule — switch it in the sidebar.")
    period_hc = (
        hc_df[hc_df["qtr"] == current_quarter]
        .pivot_table(index="period", columns="version", values="headcount", aggfunc="sum")
        .rename(columns={s.version: s.label for s in scenarios})
    )
    st.subheader("Headcount by fiscal period")
    st.dataframe(_fmt(period_hc, 0), use_container_width=True)

with tab_var:
    st.subheader("Variances ($M)  ·  positive = higher spend")
    if var_df.empty:
        st.info("Enable Plan/QRF and Forecast to see variances.")
    else:
        st.dataframe(_fmt(var_df, 2), use_container_width=True)

with tab_ro:
    st.subheader("🎯 Risks & Opportunities")
    st.caption(f"Auto-generated from **{ro['forecast']} vs {ro['baseline']}** movement. Edit freely.")
    if ro.get("summary"):
        st.info(ro["summary"])
    cA, cB = st.columns(2)
    with cA:
        st.markdown("**Risks (spend pressure)**")
        for line in ro["risks"] or ["_None above threshold._"]:
            st.markdown("- " + line)
    with cB:
        st.markdown("**Opportunities (savings)**")
        for line in ro["opportunities"] or ["_None above threshold._"]:
            st.markdown("- " + line)

    st.markdown("**Your notes (editable & saved):**")
    risks_txt = st.text_area(
        "Risks", value=saved.get("risks", "") or "\n".join(export._strip_md(x) for x in ro["risks"]),
        height=140, key="risks_txt",
    )
    opps_txt = st.text_area(
        "Opportunities", value=saved.get("opps", "") or "\n".join(export._strip_md(x) for x in ro["opportunities"]),
        height=140, key="opps_txt",
    )
    if st.button("💾 Save risks & opportunities"):
        saved["risks"], saved["opps"] = risks_txt, opps_txt
        store.save_commentary(segments, current_quarter, saved)
        st.success("Saved.")

with tab_chart:
    st.subheader("Total Opex across scenarios")
    st.bar_chart(walk.loc["Total"])
    if headline:
        st.subheader(f"Cost element mix ({headline})")
        st.bar_chart(walk.drop(index="Total")[headline].sort_values(ascending=False))

with tab_export:
    st.subheader("Download leader-ready files")
    # bundle current commentary + notes for the exports
    cmt_for_export = {k: v for k, v in commentary_map.items() if v}
    ro_export = dict(ro, risks_text=risks_txt, opps_text=opps_txt)
    c1, c2, c3 = st.columns(3)
    xlsx = export.to_excel(walk, hc_row, per_head, var_df, title, cmt_for_export, ro_export)
    c1.download_button(
        "📗 Excel (formatted)", xlsx, file_name=f"{title}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    pdf = export.to_pdf(walk, hc_row, title)
    c2.download_button(
        "📕 PDF summary", pdf, file_name=f"{title}.pdf",
        mime="application/pdf", use_container_width=True,
    )
    c3.download_button(
        "📄 CSV (raw walk)", export.to_csv(walk),
        file_name=f"{title}.csv", mime="text/csv", use_container_width=True,
    )

    st.divider()
    st.subheader("📸 Finalize a snapshot")
    st.caption(
        "Freezes the current numbers + commentary to a timestamped Excel in the "
        "`snapshots` folder. Live data can move afterwards — the snapshot won't. "
        "Refreshing is always manual (the button in the sidebar)."
    )
    if st.button("📸 Save finalized snapshot", type="primary"):
        saved["lines"] = commentary_map
        saved["risks"], saved["opps"] = risks_txt, opps_txt
        store.save_commentary(segments, current_quarter, saved)
        path = store.save_snapshot(segments, current_quarter, xlsx)
        st.success(f"Snapshot saved: {path}")

    snaps = store.list_snapshots()
    if snaps:
        st.markdown("**Recent snapshots:**")
        for p in snaps[:8]:
            st.markdown(f"- `{p}`")
