"""
Central configuration for the Opex & HC Outlook dashboard.

Everything that is likely to change (connection details, report scope,
cost-element ordering, version-naming rules) lives here so the rest of the
code stays generic and the app can be re-pointed without editing logic.
"""
from __future__ import annotations

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
# Windows / AD integrated auth against the corporate finance SQL server.
SQL_SERVER = "FinSys.corp.adobe.com,1433"
SQL_DATABASE = "finance_systems"
SQL_DRIVER = "SQL Server"  # the driver that is present on the finance laptops

EXPENSE_VIEW = "[dbo].[vw_Expense_Final_LDAP_Filtered]"
HEADCOUNT_VIEW = "[dbo].[vw_Headcount_Final_LDAP_Filtered]"


def connection_string() -> str:
    return (
        f"DRIVER={{{SQL_DRIVER}}};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DATABASE};"
        f"Trusted_Connection=yes;"
    )


# --------------------------------------------------------------------------
# Report scope
# --------------------------------------------------------------------------
# The hierarchy level the report is grouped/segmented on.
SEGMENT_COLUMN = "CCH Lvl 3 Name"

# Default segments for the AMER CXO + Ecosystems view. The UI lets the user
# pick any combination of the segments that actually exist in the data, so this
# is only the initial selection.
DEFAULT_SEGMENTS = ["Americas CXO L3", "Global Ecosystem L3"]

# The offline executive dashboard (dashboard.html / refresh.py / server.py) is
# scoped to these L3 orgs — all other orgs are excluded from the data pull.
# This is the full GTM roster: AMER CXO + Ecosystem (kept as their own combo
# tab) plus the remaining six L3s, each broken out as its own tab, with a
# "GTM WW" tab combining all eight.
SCOPE_L3 = [
    "Americas CXO L3", "Global Ecosystem L3", "Americas C&P L3",
    "APAC L3", "EMEA L3", "Japan L3", "Global Mgmt L3", "Sales Ops L3",
]

# --------------------------------------------------------------------------
# Opex model
# --------------------------------------------------------------------------
# The expense view groups GL accounts into "Major Cost Element Grp Desc".
# These are the rows of the P&L walk, in the order leaders expect to see them.
COST_ELEMENT_ORDER = [
    "Comp & Benefits",
    "Bonuses & Commissions",
    "Travel & Entertainment",
    "Depreciation",
    "Outside Labor",
    "Facilities & Telecom",
    "Marketing",
    "Other Expenses",
    "Cloud Expense",
    "Equipment & Software",
    "Other COGS",
    "Transaction Fees",
]

# Sales commissions are reported separately from Opex, so they are excluded
# from the walk. This was reconciled against the WK10 workbook total (142.1M):
# excluding the 'Commission' cost-element group ties opex to 142.4M.
EXCLUDE_COST_ELEMENT_GRP = ["Commission"]

# Values are stored in USD; the report is in millions.
MILLIONS = 1_000_000.0

# --------------------------------------------------------------------------
# Version / Outlook-week naming
# --------------------------------------------------------------------------
# Adobe's fiscal year runs Dec -> Nov. The views already carry the fiscal
# period/quarter/year fields, so we do not recompute the calendar; we only need
# to translate a chosen scenario into the matching `Version` string.
#
# Observed version families (FY26 Q2 example):
#   Actuals
#   FY26 Plan / FY26 Plan TSFR ADJ
#   FY26 Q2 QRF / FY26 Q2 QRF TSFR ADJ
#   Q2 FY26 Outlook WK 6 TSFR ADJ ... Q2 FY26 Outlook WK 13 (+ TSFR ADJ)
#
# The workbook reconciles against the "TSFR ADJ" (transfer-adjusted) variants,
# so those are preferred when both exist.
PREFER_TSFR_ADJ = True

ACTUALS_VERSION = "Actuals"
FORECAST_VERSION = "Forecast"  # the live rolling forecast for the current quarter

# Weekly Outlook (WK) versions are excluded by default (see db.py) so the
# walk stays to Actuals/Plan/QRF/Forecast. Add specific WK version strings
# here (exact `Version` text from the SQL view) to pull them in as extra
# columns that show up automatically alongside Plan/QRF/Forecast.
#
# These are the checkpoint snapshot weeks for the current reporting cadence
# (WK7 -> WK10 -> WK12 this quarter). Listing a week here before finance has
# actually published that snapshot is harmless -- the SQL simply returns no
# rows for it, and it appears in the app the moment real data shows up under
# that Version string. No further code change needed as the quarter rolls
# from one checkpoint to the next; just add next quarter's weeks here when
# planning starts.
INCLUDE_OUTLOOK_VERSIONS: list[str] = [
    # WK 6 (Q2/Q4 early checkpoint) and WK 7 (Q1/Q3 early checkpoint) --
    # listed for all four quarters since harmless-if-unpublished, per the
    # comment above; dashboard.html already shows only the one relevant to
    # whichever quarter is selected (WK7 for Q1/Q3, WK6 for Q2/Q4).
    "Q1 FY26 Outlook WK 6 TSFR ADJ",
    "Q1 FY26 Outlook WK 7 TSFR ADJ",
    "Q2 FY26 Outlook WK 6 TSFR ADJ",
    "Q2 FY26 Outlook WK 7 TSFR ADJ",
    "Q3 FY26 Outlook WK 6 TSFR ADJ",
    "Q3 FY26 Outlook WK 7 TSFR ADJ",
    "Q4 FY26 Outlook WK 6 TSFR ADJ",
    "Q4 FY26 Outlook WK 7 TSFR ADJ",
    "Q3 FY26 Outlook WK 10 TSFR ADJ",
    "Q3 FY26 Outlook WK 12 TSFR ADJ",
]

# --------------------------------------------------------------------------
# Local storage (commentary + finalized snapshots). Kept next to the app.
# --------------------------------------------------------------------------
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_DIR = os.path.join(APP_DIR, "snapshots")
COMMENTARY_DIR = os.path.join(APP_DIR, "commentary")
for _d in (SNAPSHOT_DIR, COMMENTARY_DIR):
    os.makedirs(_d, exist_ok=True)
