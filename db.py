"""
Data access layer.

Thin wrappers around pyodbc that return pandas DataFrames. All queries are
parameterised and read-only. The heavier pulls are cached by the Streamlit
layer; this module stays framework-agnostic so it can also be used from
scripts / notebooks.
"""
from __future__ import annotations

import pandas as pd
import pyodbc

import config


def get_connection(timeout: int = 30) -> pyodbc.Connection:
    return pyodbc.connect(config.connection_string(), timeout=timeout)


def _in_clause(values: list[str]) -> tuple[str, list[str]]:
    """Return a parameter placeholder list and the params for a SQL IN (...)."""
    placeholders = ", ".join("?" for _ in values)
    return placeholders, list(values)


def _version_filter_sql() -> tuple[str, list[str]]:
    """
    Standard Version filter: Actuals, Forecast, and any TSFR-ADJ variant
    (Plan/QRF), excluding weekly Outlook (WK) versions -- unless one is
    explicitly allow-listed in config.INCLUDE_OUTLOOK_VERSIONS.
    """
    extra = config.INCLUDE_OUTLOOK_VERSIONS
    base = ("([Version] = 'Actuals' OR [Version] = 'Forecast' "
            "OR ([Version] LIKE '%TSFR ADJ' AND [Version] NOT LIKE '%Outlook%'))")
    if not extra:
        return base, []
    extra_ph, extra_params = _in_clause(extra)
    return f"({base} OR [Version] IN ({extra_ph}))", extra_params


def query(sql: str, params: list | None = None) -> pd.DataFrame:
    """Run a read-only query and return a DataFrame.

    Builds the frame straight from the pyodbc cursor so we don't need
    SQLAlchemy (and avoids pandas' DBAPI2 warning under pandas 3.x).
    """
    with get_connection() as cn:
        cur = cn.cursor()
        cur.execute(sql, params or [])
        cols = [c[0] for c in cur.description]
        rows = [tuple(r) for r in cur.fetchall()]
    return pd.DataFrame.from_records(rows, columns=cols)


# --------------------------------------------------------------------------
# Metadata helpers (used to populate filters)
# --------------------------------------------------------------------------
def list_segments() -> list[str]:
    sql = (
        f"SELECT DISTINCT [{config.SEGMENT_COLUMN}] AS seg "
        f"FROM {config.EXPENSE_VIEW} "
        f"WHERE [{config.SEGMENT_COLUMN}] IS NOT NULL ORDER BY seg"
    )
    return query(sql)["seg"].tolist()


def list_fiscal_years(segments: list[str]) -> list[str]:
    ph, params = _in_clause(segments)
    sql = (
        f"SELECT DISTINCT [Fiscal Year] AS fy FROM {config.EXPENSE_VIEW} "
        f"WHERE [{config.SEGMENT_COLUMN}] IN ({ph}) ORDER BY fy"
    )
    return query(sql, params)["fy"].dropna().tolist()


def current_quarter() -> str | None:
    """The live current fiscal quarter, straight from the view's own marker.

    Using `Curr Fiscal Qtr/Year` means the report auto-rolls to the new quarter
    the moment finance advances it -- no code or config change needed.
    """
    sql = (
        f"SELECT DISTINCT [Curr Fiscal Qtr/Year] AS q FROM {config.EXPENSE_VIEW} "
        f"WHERE [Curr Fiscal Qtr/Year] IS NOT NULL"
    )
    df = query(sql)
    vals = df["q"].dropna().tolist()
    return vals[0] if vals else None


def latest_outlook_year() -> str | None:
    """Most recent fiscal year that actually has Outlook versions (for defaults)."""
    sql = (
        f"SELECT MAX([Fiscal Year]) AS fy FROM {config.EXPENSE_VIEW} "
        f"WHERE [Version] LIKE '%Outlook%'"
    )
    df = query(sql)
    return df["fy"].iloc[0] if not df.empty else None


def list_versions(view: str, fiscal_year: str) -> list[str]:
    sql = (
        f"SELECT DISTINCT [Version] AS v FROM {view} "
        f"WHERE [Fiscal Year] = ? ORDER BY v"
    )
    return query(sql, [fiscal_year])["v"].dropna().tolist()


# --------------------------------------------------------------------------
# Fact pulls
# --------------------------------------------------------------------------
def expense_by_cost_element(
    segments: list[str], fiscal_year: str, versions: list[str]
) -> pd.DataFrame:
    """
    One row per (Version, Fiscal Qtr/Year, Major Cost Element Grp Desc) with the
    summed USD value. Sales commissions are excluded to match the Opex walk.
    """
    seg_ph, seg_params = _in_clause(segments)
    ver_ph, ver_params = _in_clause(versions)
    excl_ph, excl_params = _in_clause(config.EXCLUDE_COST_ELEMENT_GRP)
    sql = f"""
        SELECT [Version]                    AS version,
               [Fiscal Qtr/Year]            AS qtr,
               [Fiscal Period]              AS period,
               [Major Cost Element Grp Desc] AS cost_element,
               SUM([Value USD @ Plan Rates]) AS value_usd
        FROM {config.EXPENSE_VIEW}
        WHERE [{config.SEGMENT_COLUMN}] IN ({seg_ph})
          AND [Fiscal Year] = ?
          AND [Version] IN ({ver_ph})
          AND ([Cost Element Grp Desc] NOT IN ({excl_ph})
               OR [Cost Element Grp Desc] IS NULL)
        GROUP BY [Version], [Fiscal Qtr/Year], [Fiscal Period],
                 [Major Cost Element Grp Desc]
    """
    params = seg_params + [fiscal_year] + ver_params + excl_params
    return query(sql, params)


def headcount_by_period(
    segments: list[str], fiscal_year: str, versions: list[str]
) -> pd.DataFrame:
    """One row per (Version, Fiscal Qtr/Year, Fiscal Period) with summed HC."""
    seg_ph, seg_params = _in_clause(segments)
    ver_ph, ver_params = _in_clause(versions)
    sql = f"""
        SELECT [Version]         AS version,
               [Fiscal Qtr/Year] AS qtr,
               [Fiscal Period]   AS period,
               SUM([Headcount])  AS headcount
        FROM {config.HEADCOUNT_VIEW}
        WHERE [{config.SEGMENT_COLUMN}] IN ({seg_ph})
          AND [Fiscal Year] = ?
          AND [Version] IN ({ver_ph})
        GROUP BY [Version], [Fiscal Qtr/Year], [Fiscal Period]
    """
    params = seg_params + [fiscal_year] + ver_params
    return query(sql, params)


def opex_facts(fiscal_years: list[str]) -> pd.DataFrame:
    """
    Compact opex fact table for the offline dashboard: aggregated at
    L2/L3/L4 x cost element x quarter x version, in $M, commissions excluded.
    Weekly Outlook (WK) versions are dropped -- only Actuals, Plan, QRF, Forecast.

    Sums [Value USD @ Plan Rates], NOT the plain [Value USD] column -- Actuals
    posts at the FX rate on the transaction date, while every forward-looking
    version (Plan/QRF/WK Outlook/Forecast) only ever exists at the fixed plan
    rate, so summing plain [Value USD] made Actuals alone drift from Finance's
    own Excel walk (which reports constant-currency) by the FX swing since
    those rates were set -- correct on WK/QRF/Plan (no FX difference there)
    but off by real $ on Actuals specifically, confirmed by comparing both
    columns directly against a live SQL pull (2026-Q3, GTM WW: [Value USD]
    Actuals = $267.499M vs [Value USD @ Plan Rates] = $267.240M, matching the
    Finance team's own Excel to the dollar; WK 12 OL was $280.061M either way).
    """
    fy_ph, fy_params = _in_clause(fiscal_years)
    excl_ph, excl_params = _in_clause(config.EXCLUDE_COST_ELEMENT_GRP)
    l3_ph, l3_params = _in_clause(config.SCOPE_L3)
    ver_sql, ver_params = _version_filter_sql()
    sql = f"""
        SELECT [CCH Lvl 2 Name] AS l2, [CCH Lvl 3 Name] AS l3, [CCH Lvl 4 Name] AS l4,
               [Major Cost Element Grp Desc] AS ce, [Fiscal Qtr/Year] AS qtr,
               [Version] AS ver, SUM([Value USD @ Plan Rates]) / 1000000.0 AS v
        FROM {config.EXPENSE_VIEW}
        WHERE [Fiscal Year] IN ({fy_ph})
          AND [CCH Lvl 3 Name] IN ({l3_ph})
          AND ([Cost Element Grp Desc] NOT IN ({excl_ph}) OR [Cost Element Grp Desc] IS NULL)
          AND {ver_sql}
        GROUP BY [CCH Lvl 2 Name], [CCH Lvl 3 Name], [CCH Lvl 4 Name],
                 [Major Cost Element Grp Desc], [Fiscal Qtr/Year], [Version]
    """
    return query(sql, fy_params + l3_params + excl_params + ver_params)


def opex_gl(fiscal_years: list[str]) -> pd.DataFrame:
    """
    GL-level opex for the drill-down: one row per
    L3/L4 x cost-element group x GL account x quarter x version ($M).
    Same filters as opex_facts, one level deeper (adds GL Account Desc).
    """
    fy_ph, fy_params = _in_clause(fiscal_years)
    excl_ph, excl_params = _in_clause(config.EXCLUDE_COST_ELEMENT_GRP)
    l3_ph, l3_params = _in_clause(config.SCOPE_L3)
    ver_sql, ver_params = _version_filter_sql()
    sql = f"""
        SELECT [CCH Lvl 3 Name] AS l3, [CCH Lvl 4 Name] AS l4,
               [Major Cost Element Grp Desc] AS ce, [GL Account Desc] AS gl,
               [Fiscal Qtr/Year] AS qtr, [Version] AS ver,
               SUM([Value USD @ Plan Rates]) / 1000000.0 AS v
        FROM {config.EXPENSE_VIEW}
        WHERE [Fiscal Year] IN ({fy_ph})
          AND [CCH Lvl 3 Name] IN ({l3_ph})
          AND ([Cost Element Grp Desc] NOT IN ({excl_ph}) OR [Cost Element Grp Desc] IS NULL)
          AND {ver_sql}
        GROUP BY [CCH Lvl 3 Name], [CCH Lvl 4 Name],
                 [Major Cost Element Grp Desc], [GL Account Desc],
                 [Fiscal Qtr/Year], [Version]
    """
    return query(sql, fy_params + l3_params + excl_params + ver_params)


def hc_facts(fiscal_years: list[str]) -> pd.DataFrame:
    """Headcount per L2/L3/L4 x quarter x version x fiscal period."""
    fy_ph, fy_params = _in_clause(fiscal_years)
    l3_ph, l3_params = _in_clause(config.SCOPE_L3)
    ver_sql, ver_params = _version_filter_sql()
    sql = f"""
        SELECT [CCH Lvl 2 Name] AS l2, [CCH Lvl 3 Name] AS l3, [CCH Lvl 4 Name] AS l4,
               [Fiscal Qtr/Year] AS qtr, [Version] AS ver, [Fiscal Period] AS period,
               SUM([Headcount]) AS hc
        FROM {config.HEADCOUNT_VIEW}
        WHERE [Fiscal Year] IN ({fy_ph})
          AND [CCH Lvl 3 Name] IN ({l3_ph})
          AND {ver_sql}
        GROUP BY [CCH Lvl 2 Name], [CCH Lvl 3 Name], [CCH Lvl 4 Name],
                 [Fiscal Qtr/Year], [Version], [Fiscal Period]
    """
    return query(sql, fy_params + l3_params + ver_params)


def hc_actuals_ending(fiscal_years: list[str]) -> pd.DataFrame:
    """
    Clean historical headcount: **active** employees per fiscal period.

    The raw 'Actuals' HC version is transactional (it sums every period and
    every status — Active + Terminated + Future Hire — so a quarter balloons to
    ~6x). For a point-in-time headcount we keep only Active status; the caller
    takes the quarter's last period as the quarter-ending headcount.
    """
    fy_ph, fy_params = _in_clause(fiscal_years)
    l3_ph, l3_params = _in_clause(config.SCOPE_L3)
    sql = f"""
        SELECT [CCH Lvl 2 Name] AS l2, [CCH Lvl 3 Name] AS l3, [CCH Lvl 4 Name] AS l4,
               [Fiscal Qtr/Year] AS qtr, [Fiscal Period] AS period,
               SUM([Headcount]) AS hc
        FROM {config.HEADCOUNT_VIEW}
        WHERE [Fiscal Year] IN ({fy_ph})
          AND [CCH Lvl 3 Name] IN ({l3_ph})
          AND [Version] = 'Actuals'
          AND [Employee Status] = 'Active'
        GROUP BY [CCH Lvl 2 Name], [CCH Lvl 3 Name], [CCH Lvl 4 Name],
                 [Fiscal Qtr/Year], [Fiscal Period]
    """
    return query(sql, fy_params + l3_params)


def hc_movement(fiscal_years: list[str]) -> pd.DataFrame:
    """
    Full HC movement build per L3 x quarter x version — every driver row, for the
    trended HC walk. Actuals carry past quarters; Forecast carries current/future.
    Beginning/Ending Headcount by Quarter is the single source of truth for HC
    (matches the official Adobe Expense & Headcount BI tool's walk methodology) --
    every headcount figure in the app should trace back to this bridge, never to
    a raw monthly 'Headcount' snapshot.
    """
    fy_ph, fy_params = _in_clause(fiscal_years)
    l3_ph, l3_params = _in_clause(config.SCOPE_L3)
    sql = f"""
        SELECT [CCH Lvl 3 Name] AS l3, [CCH Lvl 4 Name] AS l4, [Fiscal Qtr/Year] AS qtr, [Version] AS ver,
               SUM([Beginning Headcount by Quarter]) AS beg,
               SUM([Actual Hires]) AS hires, SUM([Committed]) AS committed,
               SUM([Open Reqs]) AS open_reqs,
               SUM([Published Positions w/o Reqs]) AS pub,
               SUM([Unpublished Positions]) AS unpub,
               SUM([Attrition Backfills]) AS abf,
               SUM([Internal Adj]) AS iadj, SUM([Internal Move Out]) AS imo,
               SUM([Transfer In]) AS tin, SUM([Transfer Out]) AS tout,
               SUM([Actual Terms]) AS terms, SUM([Known Terms]) AS known,
               SUM([Attrition]) AS attr,
               SUM([Mgmt Hedge]) AS mgmt_hedge, SUM([Mgmt Transfer In]) AS mgmt_tin,
               SUM([Mgmt Transfer Out]) AS mgmt_tout, SUM([Forecast Adj]) AS fcst_adj,
               SUM([Ending Headcount by Quarter]) AS endhc
        FROM {config.HEADCOUNT_VIEW}
        WHERE [Fiscal Year] IN ({fy_ph})
          AND [CCH Lvl 3 Name] IN ({l3_ph})
          AND [Version] IN ('Actuals', 'Forecast')
        GROUP BY [CCH Lvl 3 Name], [CCH Lvl 4 Name], [Fiscal Qtr/Year], [Version]
    """
    return query(sql, fy_params + l3_params)


def hc_monthly_hires(fiscal_years: list[str]) -> pd.DataFrame:
    """
    True calendar-month hire counts per L3/L4, derived from each hired
    employee/position's own `Req Hire Date`.

    Takes a list of fiscal years (e.g. ["2025", "2026"]) so the Monthly Hiring
    view can show a prior-year trend alongside the current year, not just the
    current fiscal year.

    IMPORTANT: `Actual Hires` is a quarter-cumulative figure that only posts on
    ONE fiscal period per quarter (the latest reported period) -- summing it by
    period does NOT give monthly hires (e.g. all of Q1's hires appear at period
    03, none at 01/02). Validated fix: for the rows that carry that quarter's
    `Actual Hires` value, grouping by the calendar month of their own
    `Req Hire Date` reconstructs the true monthly split, and the sum across
    months ties exactly to the already-validated quarterly total (checked
    100/88/37 for Q1/Q2/Q3 FY26, CXO+Eco). The caller must first find, per
    quarter, the single fiscal period where the quarter's total is posted, then
    keep only that period's rows (same period is used across every org).
    """
    fy_ph, fy_params = _in_clause(fiscal_years)
    l3_ph, l3_params = _in_clause(config.SCOPE_L3)
    sql = f"""
        SELECT [CCH Lvl 3 Name] AS l3, [CCH Lvl 4 Name] AS l4,
               [Fiscal Qtr/Year] AS qtr, [Fiscal Period] AS period,
               FORMAT([Req Hire Date], 'yyyy-MM') AS hire_month,
               SUM([Actual Hires]) AS hires
        FROM {config.HEADCOUNT_VIEW}
        WHERE [Fiscal Year] IN ({fy_ph})
          AND [CCH Lvl 3 Name] IN ({l3_ph})
          AND [Version] = 'Actuals'
          AND [Actual Hires] <> 0
        GROUP BY [CCH Lvl 3 Name], [CCH Lvl 4 Name], [Fiscal Qtr/Year],
                 [Fiscal Period], FORMAT([Req Hire Date], 'yyyy-MM')
    """
    return query(sql, fy_params + l3_params)


def hc_monthly_pipeline(fiscal_years: list[str]) -> pd.DataFrame:
    """
    Forward-looking hiring pipeline for the current + future quarters, by the
    calendar month each position is expected to start: Committed, Open Reqs,
    Published Positions w/o Reqs, Unpublished Positions.

    Uses `Start Date` (each position's own expected start), NOT `Req Hire Date`
    -- validated: `Req Hire Date` is populated for Committed rows (31/31) but
    mostly NULL for Open Reqs/Published/Unpublished (2/68, 0/68, 0/15), while
    `Start Date` is populated on every row across all four categories. Grouping
    by Start Date's month ties exactly to the already-validated Q3 quarterly
    totals (Committed 27, Open Reqs 20, Published 2, Unpublished 0).
    Only the Forecast version carries this pipeline detail.
    """
    fy_ph, fy_params = _in_clause(fiscal_years)
    l3_ph, l3_params = _in_clause(config.SCOPE_L3)
    sql = f"""
        SELECT [CCH Lvl 3 Name] AS l3, [CCH Lvl 4 Name] AS l4,
               [Fiscal Qtr/Year] AS qtr, FORMAT([Start Date], 'yyyy-MM') AS start_month,
               SUM([Committed]) AS committed, SUM([Open Reqs]) AS open_reqs,
               SUM([Published Positions w/o Reqs]) AS published,
               SUM([Unpublished Positions]) AS unpublished
        FROM {config.HEADCOUNT_VIEW}
        WHERE [Fiscal Year] IN ({fy_ph})
          AND [CCH Lvl 3 Name] IN ({l3_ph})
          AND [Version] = 'Forecast'
        GROUP BY [CCH Lvl 3 Name], [CCH Lvl 4 Name], [Fiscal Qtr/Year],
                 FORMAT([Start Date], 'yyyy-MM')
    """
    return query(sql, fy_params + l3_params)


def hc_by_role(fiscal_qtr: str) -> pd.DataFrame:
    """Headcount by role type for the given quarter (per L3/L4/version/period).
    The caller groups Role Type Descriptions into families and picks the same
    representative period used elsewhere, so totals tie to the HC measure."""
    l3_ph, l3_params = _in_clause(config.SCOPE_L3)
    sql = f"""
        SELECT [CCH Lvl 3 Name] AS l3, [CCH Lvl 4 Name] AS l4,
               [Role Type Description] AS role, [Version] AS ver,
               [Fiscal Period] AS period, SUM([Headcount]) AS hc
        FROM {config.HEADCOUNT_VIEW}
        WHERE [Fiscal Qtr/Year] = ?
          AND [CCH Lvl 3 Name] IN ({l3_ph})
          AND ([Version] = 'Forecast'
               OR ([Version] LIKE '%TSFR ADJ' AND [Version] NOT LIKE '%Outlook%'))
        GROUP BY [CCH Lvl 3 Name], [CCH Lvl 4 Name], [Role Type Description],
                 [Version], [Fiscal Period]
    """
    return query(sql, [fiscal_qtr] + l3_params)


def hc_role_ending(quarter: str, version: str, active_only: bool = False) -> pd.DataFrame:
    """Role-family headcount for one (quarter, version), per L3/L4/role/period,
    so the caller can take the quarter's ENDING fiscal period as the year-end
    point-in-time headcount. `active_only` restricts to Active status -- used
    for the Actuals year-end so terminated/future-hire rows don't inflate it
    (same reasoning as hc_actuals_ending)."""
    l3_ph, l3_params = _in_clause(config.SCOPE_L3)
    status = " AND [Employee Status] = 'Active'" if active_only else ""
    sql = f"""
        SELECT [CCH Lvl 3 Name] AS l3, [CCH Lvl 4 Name] AS l4,
               [Role Type Description] AS role, [Fiscal Period] AS period,
               SUM([Headcount]) AS hc
        FROM {config.HEADCOUNT_VIEW}
        WHERE [Fiscal Qtr/Year] = ? AND [Version] = ?
          AND [CCH Lvl 3 Name] IN ({l3_ph}){status}
        GROUP BY [CCH Lvl 3 Name], [CCH Lvl 4 Name], [Role Type Description],
                 [Fiscal Period]
    """
    return query(sql, [quarter, version] + l3_params)


def hc_planning(fiscal_years: list[str]) -> pd.DataFrame:
    """
    HC movement (hires / terms / attrition / open reqs / begin-end) per
    L2/L3/L4 x quarter x version -- powers the HC executive cards and the
    by-org walk. Covers all four scenarios (Actuals, Plan, QRF, Forecast) so
    every headline HC number -- Actual QTD, Plan, QRF, Forecast -- comes from
    the same Beginning/Ending Headcount by Quarter bridge, never a raw snapshot.
    Spans every fiscal year the app shows (not just the current one) so the
    walk's historical columns can also read Ending HC from this same source.
    """
    fy_ph, fy_params = _in_clause(fiscal_years)
    l3_ph, l3_params = _in_clause(config.SCOPE_L3)
    ver_sql, ver_params = _version_filter_sql()
    sql = f"""
        SELECT [CCH Lvl 2 Name] AS l2, [CCH Lvl 3 Name] AS l3, [CCH Lvl 4 Name] AS l4,
               [Role Type L2] AS role_l2, [Role Type Description] AS role_l3,
               [Fiscal Qtr/Year] AS qtr, [Version] AS ver,
               SUM([Actual Hires]) AS hires, SUM([Actual Terms]) AS terms,
               SUM([Known Terms]) AS known_terms, SUM([Open Reqs]) AS open_reqs,
               SUM([Attrition]) AS attrition, SUM([Committed]) AS committed,
               SUM([Transfer In]) AS tin, SUM([Transfer Out]) AS tout,
               SUM([Internal Adj]) AS internal_adj,
               SUM([Mgmt Hedge]) AS mgmt_hedge, SUM([Forecast Adj]) AS forecast_adj,
               SUM([Beginning Headcount by Quarter]) AS beg_hc,
               SUM([Ending Headcount by Quarter]) AS end_hc
        FROM {config.HEADCOUNT_VIEW}
        WHERE [Fiscal Year] IN ({fy_ph})
          AND [CCH Lvl 3 Name] IN ({l3_ph})
          AND {ver_sql}
        GROUP BY [CCH Lvl 2 Name], [CCH Lvl 3 Name], [CCH Lvl 4 Name],
                 [Fiscal Qtr/Year], [Version]
    """
    return query(sql, fy_params + l3_params + ver_params)


def position_pipeline_rows(fiscal_years: list[str]) -> pd.DataFrame:
    """
    Row-level position/req detail behind the forward-looking hiring pipeline
    (Committed / Open Reqs / Published / Unpublished -- see hc_monthly_pipeline
    for the aggregated version this must tie back to). Powers the Monthly
    Hiring drill-through: click a forecast cell, see the actual positions/reqs
    that sum to it.

    Column mappings confirmed against the live view schema (some requested
    fields have no exact match, so the closest available field is used):
      Job Level        -> SAP Mgmt Level Rollup
      University Cohort -> "Univ. Hire – Funding Type" (en-dash, not hyphen)
      Planned Start Date -> Start Date
      Status            -> brought back as three variants (Requisition Stage,
                            Position Master Status, Position Status WD) so the
                            best one can be picked after comparing real values.
    """
    fy_ph, fy_params = _in_clause(fiscal_years)
    l3_ph, l3_params = _in_clause(config.SCOPE_L3)
    sql = f"""
        SELECT [CCH Lvl 3 Name] AS l3, [CCH Lvl 4 Name] AS l4,
               [Fiscal Qtr/Year] AS qtr, [Position ID] AS pid,
               [Requisition Number] AS req,
               [Job Family Group] AS job_family, [SAP Mgmt Level Rollup] AS job_level,
               [Position Creation Date] AS created_dt,
               [Requisition Stage] AS status_stage,
               [Position Master Status] AS status_master,
               [Position Status WD] AS status_wd,
               [Work City] AS work_city, [Position Description] AS pdesc,
               [Manager's Full Name] AS manager, [Candidate Full Name] AS candidate,
               [Univ. Hire – Funding Type] AS univ_cohort,
               [Start Date] AS planned_start, [Req Hire Date] AS req_hire_date,
               [Planned Term Date] AS planned_term,
               [Functional Controller] AS func_controller,
               [Committed] AS committed, [Open Reqs] AS open_reqs,
               [Published Positions w/o Reqs] AS published,
               [Unpublished Positions] AS unpublished
        FROM {config.HEADCOUNT_VIEW}
        WHERE [Fiscal Year] IN ({fy_ph})
          AND [CCH Lvl 3 Name] IN ({l3_ph})
          AND [Version] = 'Forecast'
          AND [Position ID] IS NOT NULL AND [Position ID] <> ''
          AND (COALESCE([Committed],0)<>0 OR COALESCE([Open Reqs],0)<>0
               OR COALESCE([Published Positions w/o Reqs],0)<>0
               OR COALESCE([Unpublished Positions],0)<>0)
    """
    return query(sql, fy_params + l3_params)


def position_snapshot(fiscal_qtr: str) -> pd.DataFrame:
    """
    Row-level position/req detail for the current quarter, across every
    version the walk shows (Actuals/Plan/QRF/Forecast/WK-Outlook). Powers the
    Analysis tab's pushed-out / pulled-in / backfill-delay detection: the same
    Position ID's Start Date / Planned Term Date is compared across two
    versions (e.g. WK7 OL vs Forecast) to see whether a hire or termination
    date moved. Not aggregated -- the view carries multiple rows per
    Position ID/Version (one per pipeline stage), so the caller groups them.
    """
    l3_ph, l3_params = _in_clause(config.SCOPE_L3)
    ver_sql, ver_params = _version_filter_sql()
    sql = f"""
        SELECT [Position ID] AS pid, [Requisition Number] AS req,
               [Position Title] AS title, [Position Description] AS pdesc,
               [CCH Lvl 3 Name] AS l3, [CCH Lvl 4 Name] AS l4,
               [Version] AS ver, [Start Date] AS start_dt,
               [Planned Term Date] AS term_dt,
               [Committed] AS committed, [Open Reqs] AS open_reqs,
               [Published Positions w/o Reqs] AS pub, [Unpublished Positions] AS unpub,
               [To Be Hired Name] AS tbh
        FROM {config.HEADCOUNT_VIEW}
        WHERE [Fiscal Qtr/Year] = ?
          AND [CCH Lvl 3 Name] IN ({l3_ph})
          AND [Position ID] IS NOT NULL AND [Position ID] <> ''
          AND {ver_sql}
    """
    return query(sql, [fiscal_qtr] + l3_params + ver_params)


def actuals_by_quarter(
    segments: list[str], fiscal_years: list[str]
) -> pd.DataFrame:
    """
    Historical actuals across (potentially several) fiscal years, grouped by
    quarter and cost element. Feeds the historical columns of the walk.
    """
    seg_ph, seg_params = _in_clause(segments)
    fy_ph, fy_params = _in_clause(fiscal_years)
    excl_ph, excl_params = _in_clause(config.EXCLUDE_COST_ELEMENT_GRP)
    sql = f"""
        SELECT [Fiscal Qtr/Year]             AS qtr,
               [Major Cost Element Grp Desc] AS cost_element,
               SUM([Value USD @ Plan Rates])  AS value_usd
        FROM {config.EXPENSE_VIEW}
        WHERE [{config.SEGMENT_COLUMN}] IN ({seg_ph})
          AND [Fiscal Year] IN ({fy_ph})
          AND [Version] = ?
          AND ([Cost Element Grp Desc] NOT IN ({excl_ph})
               OR [Cost Element Grp Desc] IS NULL)
        GROUP BY [Fiscal Qtr/Year], [Major Cost Element Grp Desc]
    """
    params = seg_params + fy_params + [config.ACTUALS_VERSION] + excl_params
    return query(sql, params)
