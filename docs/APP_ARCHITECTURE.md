# GTM WW Opex + HC Dashboard Architecture

## Runtime and directories

The application has a flat development checkout and an organized OneDrive runtime layout. `layout.py` resolves paths based on whether the application is running from an `App` directory:

| Runtime location | Purpose |
| --- | --- |
| `App/` | Dashboard HTML, Python server, ETL, and application modules |
| `Data/data.js` | Active financial data snapshot loaded by the dashboard |
| `Commentaries/commentary.json` | Materialized/legacy commentary view |
| `Commentaries/commentary_updates/` | Append-only shared commentary update journal |
| `Commentaries/snapshots_seen.json` | Outlook snapshot-rollover tracking |
| `Backups/` | Historical/backup artifacts |
| `Backups/Snapshots/` | Server-saved finalized HTML snapshots |
| `Logs/` | Runtime startup and error logs |

`Start Web App.bat` launches the web application. In the organized layout, paths are resolved relative to `App/`; in a flat development checkout, `layout.py` uses the repository root and its development data folders.

## Financial-data flow

1. `server.py` serves `dashboard.html` and the active data file, and exposes the refresh endpoint.
2. `refresh.py` builds data from the configured SQL sources through the database/configuration modules and the transformation logic.
3. Before writing refreshed data, the refresh process reads shared commentary through `commentary_store.py` and includes it in the generated dashboard data. SQL refresh must not replace commentary with an empty or stale copy.
4. The resulting `Data/data.js` is loaded by the browser as `window.OPEX_DATA`; the dashboard derives Opex, Headcount, comparisons, hierarchy views, and exports from this data.

The financial calculations and mappings are separate from commentary persistence. Do not change data transformations or calculation logic to solve a commentary-only issue.

## Authoritative commentary flow

```text
Dashboard fields
  ├─ localStorage draft + expected-value baseline (temporary browser safety)
  └─ changed cells + expected values
        ↓ POST /api/commentary
server.py → commentary_store.py
        ↓ append uniquely named cell-update journal entry
Commentaries/commentary_updates/
        ↓ merge/cache for authoritative reads
GET /api/commentary → browser D.commentary → UI
        ↓ explicit materialization only
Commentaries/commentary.json
```

- `commentary_store.py` resolves the locally synced OneDrive `Commentaries` directory (or the explicit `GTM_WW_SHARED_APP_DIR` setting). It must not silently fall back to a private checkout copy.
- The journal is the live, append-only record of field changes. Normal writes append only changed cells with expected prior values; conflict checking prevents an older browser session from silently replacing a newer value.
- If independent OneDrive clients submit edits before syncing, the journal applies its deterministic event ordering; a losing same-cell edit is not silently merged and must be reviewed and re-entered after the winning value syncs.
- `commentary.json` is retained as a materialized/legacy view. Full materialization is reserved for explicit operations; normal saves should not replay and rewrite the entire view.
- The server uses a cache to avoid unnecessary full journal replay. Cache invalidation/incremental application must still reflect updates discovered from disk.
- `localStorage` holds unsaved drafts and their conflict baselines. It is not authoritative shared state. On save failure, drafts remain available for retry; missing baselines must fail safely rather than silently rebase.
- An intentional clear is represented as a cell-level clearing update and must remain clear after reload, refresh, and snapshot creation.
- OneDrive synchronizes files between independent machines; local tests cannot prove the timing or conflict behavior of real cross-device synchronization. Test it separately when possible and report this limit honestly.

## Snapshot flow

1. The dashboard gathers pending edits across scopes, preserving each draft's expected-value baseline. Unresolvable conflicts or missing baselines stop snapshot creation with an error.
2. Pending saves are confirmed through the commentary API. The dashboard then fetches the authoritative merged commentary from `GET /api/commentary`.
3. `buildSnapshotHtml()` embeds the confirmed data into the snapshot's `window.OPEX_DATA`. The snapshot's frozen mode prevents localStorage overlays and commentary edits from changing that embedded state.
4. The browser uploads the HTML to `POST /api/snapshot`. `server.py` validates and writes a uniquely named file under `Backups/Snapshots/`.
5. The downloaded HTML is independently viewable and must display its embedded commentary without contacting the live server or reading local draft data.

The snapshot represents committed server commentary at generation time, not an unconfirmed browser draft. If a pending edit cannot be committed, generation must fail rather than report success with mismatched content.

## Other application surfaces

- Outlook and QRF modes, quarter/version comparisons, L3/L4 hierarchy, commentary cards, Variance Walk, and Opex/Headcount views are rendered in `dashboard.html`.
- Excel export is generated by the dashboard from the active view and must retain the intended data and commentary.
- Manual and automatic SQL refresh use the same refresh implementation. Do not disable or alter automatic refresh without approval.
- AI commentary support is currently gated/configured separately. Do not connect an external AI service, install an SDK, or transmit dashboard data without explicit authorization and required approval.
- Tests live in `tests/`; add a targeted regression for each feasible bug fix. Run `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\predeploy-check.ps1` before deployment, then complete applicable browser and live checks from `docs/REGRESSION_CHECKLIST.md`.

## Key modules

| Module | Responsibility |
| --- | --- |
| `server.py` | HTTP endpoints, static files, refresh, commentary API, snapshot storage |
| `commentary_store.py` | OneDrive shared-store resolution, journal replay/cache, conflict checks, append-only writes, explicit materialization |
| `refresh.py` | SQL-backed data build, commentary preservation, active data-file generation |
| `layout.py` | Development/runtime path resolution |
| `config.py`, `db.py` | Runtime configuration and database access |
| `transform.py`, `fiscal.py` | Financial-data transformation and fiscal-period logic |
| `dashboard.html` | Browser rendering, filters, commentary draft UX, snapshots, and exports |
| `tests/` | Unit and API regression coverage |
