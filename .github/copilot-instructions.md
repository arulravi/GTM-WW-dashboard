# GTM WW Dashboard Development Instructions

These instructions apply to every change in this repository. Treat the dashboard as a production-grade, multi-user financial reporting application.

## Before changing code

- Read the relevant implementation, tests, configuration, and documentation before editing. Trace the data flow and understand why the existing behavior exists.
- Identify affected surfaces and dependencies, including Outlook and QRF, all quarters and comparison versions, L3/L4 scopes, refresh, commentaries, snapshots, and exports.
- Fix the verified root cause. Preserve working behavior and avoid unrelated refactors, redesigns, or speculative workarounds.
- Do not modify financial inputs, calculations, historical records, or production commentary unless explicitly required by the task.
- Read the current worktree diff before editing. Preserve unrelated and user-owned changes; never reset or overwrite them.

## Authoritative data and integrity

- Financial data is built by `refresh.py` from configured SQL sources and written to the active `Data/data.js`. Commentary is independent of SQL refresh and must remain preserved across refreshes.
- Shared commentary is resolved by `commentary_store.py` to the locally OneDrive-synced `Commentaries` directory. Its `commentary_updates` journal is the append-only source of cell-level updates; `commentary.json` is the materialized/legacy view. Do not initialize an empty store when required shared files are missing or invalid.
- Saves must contain only changed fields and their expected prior values. Preserve conflict checks and append-only journal behavior. Do not replace whole commentary files for ordinary saves, rebase stale drafts silently, or drop intentionally cleared fields.
- Browser `localStorage` is a draft/safety layer, not shared authority. Never let stale browser data overwrite a newer backend/journal value.
- Before a snapshot is generated, pending drafts must be committed or snapshot generation must fail clearly. Embed the confirmed commentary into the HTML; frozen snapshots must not restore commentary from `localStorage` or mutate their embedded values.
- Back up affected production files before deployment. Record and compare financial-data and commentary hashes before and after deployment; investigate any unexpected difference and roll back the application file when safe.
- Do not use production commentary or financial data as a test fixture. Use isolated temporary data/directories and independent browser profiles for multi-session tests.

## Implementation and testing

- Keep changes surgical, type-safe, and consistent with existing patterns. Update directly related docs and add a regression test for every feasible bug fix.
- Run the smallest relevant test set first, then run `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\predeploy-check.ps1` from the repository root. A non-zero exit is a deployment blocker; investigate and resolve failures before proceeding. Follow the remaining requirements in `docs/REGRESSION_CHECKLIST.md`. Python tests or syntax checks alone do not prove browser behavior.
- Validate the actual application in a browser for UI, persistence, snapshot, export, and refresh changes. Test independent browser sessions for concurrency. Do not claim cross-laptop OneDrive synchronization was tested unless it actually was.
- Review browser console and backend logs for unexpected errors. Validate the affected feature as well as neighboring functionality.
- Do not disable SQL automatic refresh, alter refresh scheduling, or bypass existing behavior without explicit user approval.
- Do not deploy until the relevant browser and regression checks pass. Back up, deploy in a controlled manner, then verify the running application at `http://localhost:8770/`. Keep a rollback copy.
- Avoid installing SDKs, providers, packages, authenticating, or transmitting financial/commentary data to an external service without explicit authorization.

## Completion report

Report the root cause; files/functions changed; potentially affected existing functions; tests and end-to-end checks actually completed; performance observations; data-integrity checks; live validation; and remaining limitations. State plainly when a requested validation was not performed. Do not claim a fix is fully resolved without verifying the affected end-to-end behavior.
