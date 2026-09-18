"""
Transform layer: turn the raw fact pulls into the P&L "walk" that leaders read.

Shapes produced:
  * opex_walk   -> cost elements (rows) x scenario columns (values in $M)
  * headcount   -> HC per scenario, plus the quarterly figure
  * per_head    -> selected cost elements / HC, in $'000s
  * variances   -> week-over-week and plan/QRF deltas

Everything is expressed in millions and rounded only at display time.
"""
from __future__ import annotations

import pandas as pd

import config
from fiscal import Scenario, quarter_sort_key


# How to collapse a quarter's monthly headcount into one number.
# This is a business convention (see notes in fiscal/README); exposed in the UI.
HC_MEASURES = {
    "Current actual month": "current",   # latest period that has actuals
    "Quarter ending (last period)": "ending",
    "Quarter average": "average",
}


def _to_millions(series: pd.Series) -> pd.Series:
    return series / config.MILLIONS


def build_opex_walk(
    current_qtr_df: pd.DataFrame,
    actuals_df: pd.DataFrame,
    scenarios: list[Scenario],
    current_quarter: str,
    history_quarters: list[str],
) -> pd.DataFrame:
    """
    Assemble the walk table.

    Columns are: historical actual quarters (in order) + one column per
    scenario for the current quarter. Rows are the cost elements in the
    configured order, plus a Total row.
    """
    # --- historical actual quarters -> columns ------------------------------
    hist = actuals_df.copy()
    hist["value_m"] = _to_millions(hist["value_usd"])
    hist_pivot = hist.pivot_table(
        index="cost_element", columns="qtr", values="value_m", aggfunc="sum"
    )
    hist_cols = sorted(
        [q for q in hist_pivot.columns if q in history_quarters],
        key=quarter_sort_key,
    )
    hist_pivot = hist_pivot.reindex(columns=hist_cols)

    # --- current-quarter scenarios -> columns -------------------------------
    cur = current_qtr_df.copy()
    cur = cur[cur["qtr"] == current_quarter]
    cur["value_m"] = _to_millions(cur["value_usd"])
    cur_pivot = cur.pivot_table(
        index="cost_element", columns="version", values="value_m", aggfunc="sum"
    )
    # rename version -> friendly scenario label, keep scenario order
    version_to_label = {s.version: s.label for s in scenarios}
    cur_pivot = cur_pivot.rename(columns=version_to_label)
    scenario_cols = [s.label for s in scenarios if s.label in cur_pivot.columns]
    cur_pivot = cur_pivot.reindex(columns=scenario_cols)

    walk = pd.concat([hist_pivot, cur_pivot], axis=1)

    # order rows, keep only known cost elements, add any stragglers at the end
    ordered = [c for c in config.COST_ELEMENT_ORDER if c in walk.index]
    extras = [c for c in walk.index if c not in config.COST_ELEMENT_ORDER]
    walk = walk.reindex(index=ordered + extras).fillna(0.0)

    # Total row
    walk.loc["Total"] = walk.sum(axis=0)
    walk.index.name = "Cost Element"
    return walk


def collapse_headcount(
    hc_df: pd.DataFrame, current_quarter: str, measure: str = "current"
) -> pd.DataFrame:
    """
    Return one HC number per version for the current quarter, using the chosen
    convention. `measure` in {current, ending, average}.
    """
    cur = hc_df[hc_df["qtr"] == current_quarter].copy()
    out = {}
    for version, g in cur.groupby("version"):
        by_period = g.groupby("period")["headcount"].sum().sort_index()
        if by_period.empty:
            continue
        if measure == "average":
            out[version] = by_period.mean()
        elif measure == "ending":
            out[version] = by_period.iloc[-1]
        else:  # current actual month: the max period that is non-zero actual;
               # approximated as the second-to-last when a forecast tail exists,
               # else the last. Kept simple + transparent.
            out[version] = (
                by_period.iloc[-2] if len(by_period) >= 3 else by_period.iloc[-1]
            )
    return pd.Series(out, name="headcount")


def headcount_row(
    hc_df: pd.DataFrame,
    scenarios: list[Scenario],
    current_quarter: str,
    measure: str = "current",
) -> pd.Series:
    """HC per scenario label, ordered to match the walk columns."""
    by_version = collapse_headcount(hc_df, current_quarter, measure)
    row = {}
    for s in scenarios:
        # The 'Actuals' HC version double-counts (Active+Termed rows) and HC is a
        # point-in-time measure, so we don't show it for the QTD-Actuals column.
        if s.kind == "actuals_qtd":
            continue
        if s.version in by_version.index:
            row[s.label] = float(by_version[s.version])
    return pd.Series(row, name="Headcount")


def per_head_metrics(
    walk: pd.DataFrame, hc_row: pd.Series, elements: list[str]
) -> pd.DataFrame:
    """Cost per head in $'000s for the selected elements, current-qtr columns."""
    cols = [c for c in hc_row.index if c in walk.columns]
    data = {}
    for el in elements:
        if el not in walk.index:
            continue
        data[el] = {
            c: (walk.loc[el, c] * 1000.0 / hc_row[c]) if hc_row.get(c) else 0.0
            for c in cols
        }
    return pd.DataFrame(data).T


def _forecast_label(scenarios: list[Scenario], walk: pd.DataFrame) -> str | None:
    fc = next((s.label for s in scenarios if s.kind == "forecast" and s.label in walk.columns), None)
    if fc:
        return fc
    # fall back to the last non-actuals scenario present
    for s in reversed(scenarios):
        if s.kind != "actuals_qtd" and s.label in walk.columns:
            return s.label
    return None


def variances(walk: pd.DataFrame, scenarios: list[Scenario]) -> pd.DataFrame:
    """
    Forecast-centric leadership deltas on every cost element (and Total):
      * Forecast vs Plan
      * Forecast vs QRF
    Positive = higher spend than the comparison (a risk on an expense line).
    """
    fc = _forecast_label(scenarios, walk)
    out = pd.DataFrame(index=walk.index)
    if not fc:
        return out
    for kind in ("plan", "qrf"):
        lbl = next((s.label for s in scenarios if s.kind == kind and s.label in walk.columns), None)
        if lbl:
            out[f"{fc} vs {lbl}"] = walk[fc] - walk[lbl]
    return out


def risks_and_opportunities(
    walk: pd.DataFrame,
    scenarios: list[Scenario],
    hc_row: pd.Series | None = None,
    threshold: float = 0.10,
) -> dict:
    """
    Data-driven suggestions from the Forecast-vs-baseline movement.

    An *increase* in a forecasted expense line vs the baseline is flagged as a
    RISK; a *decrease* as an OPPORTUNITY. The baseline is the QRF if present,
    else the Plan. Returns ranked lists plus ready-to-edit narrative bullets.
    `threshold` is in $M -- movements smaller than this are ignored as noise.
    """
    fc = _forecast_label(scenarios, walk)
    # Compare to the budget (Plan) by default -- that's where the real spend
    # pressure vs commitment shows up. Fall back to QRF if Plan isn't shown.
    base = next((s.label for s in scenarios if s.kind == "plan" and s.label in walk.columns), None)
    if base is None:
        base = next((s.label for s in scenarios if s.kind == "qrf" and s.label in walk.columns), None)

    result = {"forecast": fc, "baseline": base, "risks": [], "opportunities": [], "summary": ""}
    if not fc or not base:
        return result

    delta = (walk[fc] - walk[base]).drop(index="Total", errors="ignore")
    risks = delta[delta >= threshold].sort_values(ascending=False)
    opps = delta[delta <= -threshold].sort_values()

    result["risks"] = [
        f"⚠️ **{el}** forecast ${walk.loc[el, fc]:,.1f}M is **${d:,.1f}M higher** than {base} "
        f"— pressure to watch."
        for el, d in risks.items()
    ]
    result["opportunities"] = [
        f"✅ **{el}** forecast ${walk.loc[el, fc]:,.1f}M is **${-d:,.1f}M lower** than {base} "
        f"— potential savings."
        for el, d in opps.items()
    ]

    total_delta = walk.loc["Total", fc] - walk.loc["Total", base]
    hc_note = ""
    if hc_row is not None and fc in hc_row.index and base in hc_row.index and hc_row[base]:
        hc_note = f" Headcount {fc} {hc_row[fc]:,.0f} vs {base} {hc_row[base]:,.0f} ({hc_row[fc]-hc_row[base]:+,.0f})."
    direction = "above" if total_delta >= 0 else "below"
    result["summary"] = (
        f"Total Opex forecast of ${walk.loc['Total', fc]:,.1f}M is ${abs(total_delta):,.1f}M "
        f"{direction} {base}, driven mainly by "
        f"{', '.join(risks.index[:2]) if len(risks) else '—'} on the risk side and "
        f"{', '.join(opps.index[:2]) if len(opps) else '—'} on the opportunity side.{hc_note}"
    )
    return result
