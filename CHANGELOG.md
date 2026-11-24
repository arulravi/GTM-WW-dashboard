# Changelog

Application changes and deployments are recorded here. Entries should identify the root cause, user-visible or data-flow change, validation performed, and any limitations that remain.

## 2026-11-24

### Added pre-deployment QA gate and regression coverage

- Added `scripts/predeploy-check.ps1` to run the complete Python unittest suite, validate inline dashboard JavaScript syntax, and check patch whitespace. The gate exits non-zero on any failure and explicitly does not claim browser E2E or cross-device validation.
- Added isolated regression tests for Opex unit conversion/variance, Headcount aggregation and per-head calculation, refresh preservation of shared commentary, and generated data-file round-tripping.
- **Coverage gaps:** There is no supported browser-driver suite or production SQL test fixture in this repository. Frontend autosave timing/feedback, UI filter accuracy, full live-vs-downloaded HTML comparison, Excel output, browser console, and actual OneDrive multi-device synchronization remain manual checks in `docs/REGRESSION_CHECKLIST.md`.
- **Validation:** The pre-deployment gate passed with 56 Python tests; inline dashboard JavaScript syntax and `git diff --check` passed. No live application deployment or cross-device test was performed.

### Added permanent development and QA guidance

- Added repository instructions, architecture documentation, and a production regression checklist covering financial-data integrity, authoritative commentary flow, browser-level verification, controlled deployment, rollback, and explicit OneDrive testing limitations.
- Updated the README's snapshot status description to match the current commentary-only persistent save status.
- **Validation:** Documentation review and `git diff --check`; no application code or production data changed.

### Fixed finalized HTML snapshot commentary consistency

- **Root cause:** Generated snapshots embedded server commentary but still allowed browser `localStorage` commentary overlays to participate in rendering. Snapshot textarea markup could also carry live DOM values rather than the confirmed embedded values. Pending local drafts outside the currently rendered scope were not reliably included before export.
- **Changes:** Snapshot generation now reconciles pending drafts across scopes with their saved expected-value baselines, stops on unresolved conflicts or unbased drafts, fetches authoritative commentary after save confirmation, embeds the confirmed data, and marks generated snapshots frozen/read-only so localStorage cannot replace or mutate their commentary.
- **Validation:** 52 Python regression tests passed. Browser checks verified that embedded commentary remained authoritative in the presence of stale localStorage, intentional blanks stayed blank, and all 42 scopes / 495 fields matched the generated embedded data. `localhost:8770` served the deployed dashboard; financial data and commentary materialized-file hashes were unchanged.
- **Deployment / backup:** Deployed to the existing `localhost:8770` application. Rollback copy: `C:\Users\arravi\AppData\Local\GTM-WW-dashboard-backups\snapshot-commentary-fix-20261124-135858\dashboard.html`.
- **Limitation:** Cross-laptop OneDrive synchronization latency was not tested. Browser checks used the live dashboard and synthetic in-memory snapshot data; no production commentary was changed.
