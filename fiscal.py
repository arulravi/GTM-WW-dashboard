"""
Fiscal-calendar and version-resolution helpers.

Adobe's fiscal year runs December -> November, split into four quarters of
(roughly) 4-4-5 weeks. The SQL views already carry the derived fiscal fields
(`Fiscal Year`, `Fiscal Qtr/Year`, `Fiscal Period`), so we never recompute the
calendar from raw dates. What we DO need is to translate a business scenario
("the WK 10 Outlook for FY26 Q2") into the exact `Version` string stored in the
data -- and to do it defensively, because the naming has small variations.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import config


# A scenario is one column of the walk: a label plus the version(s) that
# populate it. We keep a list of candidates and resolve to whichever actually
# exists in the data.
@dataclass(frozen=True)
class Scenario:
    label: str          # what leaders see, e.g. "WK 10 OL"
    kind: str           # actuals | plan | qrf | outlook
    version: str        # the resolved version string in the data


def _short_fy(fiscal_year: str) -> str:
    """'2026' -> '26'."""
    return fiscal_year[-2:]


def _quarter_num(qtr: str) -> str:
    """'2026-Q2' -> '2'."""
    m = re.search(r"Q(\d)", qtr or "")
    return m.group(1) if m else ""


def _first_match(candidates: list[str], available: list[str]) -> str | None:
    for c in candidates:
        if c in available:
            return c
    return None


def _prefer(base: str) -> list[str]:
    """Order TSFR-ADJ vs plain according to config preference."""
    adj = f"{base} TSFR ADJ"
    return [adj, base] if config.PREFER_TSFR_ADJ else [base, adj]


def resolve_scenarios(
    fiscal_year: str,
    quarter: str,
    outlook_weeks: list[int],
    available_versions: list[str],
    include_plan: bool = True,
    include_qrf: bool = True,
) -> list[Scenario]:
    """
    Build the ordered list of scenario columns for the current quarter.

    `outlook_weeks` are the OL week numbers the user wants to compare, e.g.
    [6, 10]. Plan and QRF are added when present. Anything that cannot be
    matched to a real version is silently dropped, so the walk only ever shows
    columns that have data behind them.
    """
    fy = _short_fy(fiscal_year)
    q = _quarter_num(quarter)
    scenarios: list[Scenario] = []

    if include_plan:
        v = _first_match(_prefer(f"FY{fy} Plan"), available_versions)
        if v:
            scenarios.append(Scenario(f"FY{fy} Plan", "plan", v))

    if include_qrf:
        v = _first_match(_prefer(f"FY{fy} Q{q} QRF"), available_versions)
        if v:
            scenarios.append(Scenario(f"Q{q} QRF", "qrf", v))

    for wk in sorted(set(outlook_weeks)):
        # e.g. "Q2 FY26 Outlook WK 10"
        base = f"Q{q} FY{fy} Outlook WK {wk}"
        v = _first_match(_prefer(base), available_versions)
        if v:
            scenarios.append(Scenario(f"WK {wk} OL", "outlook", v))

    return scenarios


def resolve_reporting_scenarios(
    fiscal_year: str,
    quarter: str,
    available_versions: list[str],
    include_qtd_actuals: bool = True,
    include_plan: bool = True,
    include_qrf: bool = True,
    include_forecast: bool = True,
) -> list[Scenario]:
    """
    The current reporting layout leaders asked for (no weekly Outlook columns):

        [Q# QTD Actuals]  ->  FY## Plan  ->  Q# QRF  ->  Forecast

    Forecast is the live current-quarter forecast and is treated as the
    headline scenario. Anything without a matching version is dropped.
    """
    fy = _short_fy(fiscal_year)
    q = _quarter_num(quarter)
    scn: list[Scenario] = []

    if include_qtd_actuals and config.ACTUALS_VERSION in available_versions:
        scn.append(Scenario(f"Q{q} QTD Act", "actuals_qtd", config.ACTUALS_VERSION))

    if include_plan:
        v = _first_match(_prefer(f"FY{fy} Plan"), available_versions)
        if v:
            scn.append(Scenario(f"FY{fy} Plan", "plan", v))

    if include_qrf:
        v = _first_match(_prefer(f"FY{fy} Q{q} QRF"), available_versions)
        if v:
            scn.append(Scenario(f"Q{q} QRF", "qrf", v))

    if include_forecast:
        v = _first_match(_prefer(config.FORECAST_VERSION), available_versions)
        if v:
            scn.append(Scenario("Forecast", "forecast", v))

    return scn


def headline_label(scenarios: list[Scenario]) -> str | None:
    """The scenario leaders anchor on: Forecast if present, else the last one."""
    fc = next((s.label for s in scenarios if s.kind == "forecast"), None)
    return fc or (scenarios[-1].label if scenarios else None)


def available_outlook_weeks(
    fiscal_year: str, quarter: str, available_versions: list[str]
) -> list[int]:
    """Discover which OL week numbers exist for a quarter, sorted ascending."""
    fy = _short_fy(fiscal_year)
    q = _quarter_num(quarter)
    pat = re.compile(rf"^Q{q} FY{fy} Outlook WK (\d+)", re.IGNORECASE)
    weeks: set[int] = set()
    for v in available_versions:
        m = pat.match(v)
        if m:
            weeks.add(int(m.group(1)))
    return sorted(weeks)


def quarter_sort_key(qtr: str) -> tuple[int, int]:
    """Sort '2025-Q4' before '2026-Q1'."""
    m = re.match(r"(\d{4})-Q(\d)", qtr or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)
