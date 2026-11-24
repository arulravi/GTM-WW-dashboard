# GTM WW Dashboard Regression Checklist

Run the targeted test for the requested change and the relevant checks below before deployment. A Python test run or JavaScript syntax check by itself is not end-to-end validation. Use isolated test data; never alter production commentary or financial data to test.

## Standard automated gate

From the repository root, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\predeploy-check.ps1
```

The script runs the complete Python unittest suite, checks inline dashboard JavaScript syntax with Node.js, and runs `git diff --check`. Any missing required tool or failing check returns a non-zero exit and must block deployment. It does not deploy the application, run a browser, connect to production SQL, or validate real OneDrive synchronization. Complete the applicable browser/live and cross-device checks below separately; record unavailable checks as not tested.

## Current automated-coverage map

| Checklist area | Existing/added automated coverage | Remaining validation |
| --- | --- | --- |
| Commentary cell saves, conflict checks, independent-cell concurrency, same-cell conflicts, persistence reads, and append-only journal behavior | `tests/test_commentary_api.py`, `tests/test_commentary_store.py` | Frontend autosave debounce and button feedback are not browser-automated; real separate-device OneDrive sync remains a cross-device test |
| Snapshot HTTP write, uniqueness, failures, and server confirmation | `tests/test_commentary_api.py` | Browser save-button workflow, opening downloaded HTML, and full live-vs-file comparison remain browser E2E |
| Snapshot commentary import | `tests/test_snapshot_commentary_import.py` | Does not exercise browser snapshot generation |
| Refresh commentary preservation and generated data-file writing | `tests/test_refresh.py` | Uses mocked SQL results; live SQL connectivity/data freshness require an approved environment |
| Opex unit conversion, forecast/plan variance sign, Headcount period choice, and cost-per-head | `tests/test_transform.py` | Does not certify production SQL outputs or full dashboard calculation display |
| Organized/flat directory layout and refresh output path | `tests/test_layout.py` | Does not verify every startup script in Windows user context |
| Outlook/QRF, L3/L4 and quarter/version filters, Excel output, visual layout, dark mode, and actual browser console | No automated browser-driver suite is configured at present | Perform browser E2E from this checklist; add driver-based tests only when a supported browser runner is established |
| Real simultaneous edits from multiple OneDrive-connected devices | Not covered by the local automated suite | Must be separately tested across devices if available |

## Pre-deployment safety

- [ ] Inspect the worktree and preserve unrelated/user-owned changes.
- [ ] Identify affected files, functions, data stores, and neighboring features.
- [ ] Back up every affected live application file and verify the backup.
- [ ] Record hashes or equivalent integrity markers for protected financial data, commentary materialized data, and relevant journal entries.
- [ ] Confirm no test will write to production financial data, commentary, or journal.
- [ ] Keep SQL automatic refresh enabled and configured as before.

## Automated and browser checks

| Area | Expected result | Evidence |
| --- | --- | --- |
| Application startup | App serves at `localhost:8770` with no startup failure | HTTP/browser load and startup logs |
| Organization tabs | Each configured organization tab renders and filters correctly | Browser smoke test |
| L3/L4 filters | Correct organizational financial data and commentary mappings | Test L3 and L4 selections |
| Quarter/version filters | Quarter, current version, target version, Outlook and QRF selections remain valid | Exercise representative and edge comparison pairs |
| Financial calculations | Opex, HC, variances, and comparisons are unchanged unless explicitly requested | Targeted calculations/tests and representative UI checks |
| Opex and Headcount | Both reporting surfaces render correctly and retain their existing controls | Browser smoke test |
| Commentary auto-save | Edit one field; verify the request saves it and status reflects persistence | Browser plus API/store read |
| Manual commentary save | Save only pending cells; verify backend confirmation and no-op behavior | Browser plus API/store read |
| Commentary deletion/clear | Cleared value remains cleared after reload and refresh | Browser plus authoritative store read |
| Multi-user saving | Independent sessions editing different cells retain both changes; same-cell stale conflict is surfaced without silent overwrite | Independent browser contexts plus API/store assertions |
| Commentary persistence | Saved text survives browser reload and application restart | Browser and authoritative API |
| Overall Commentaries | Correct scope, quarter, and comparison text is shown | Browser check |
| Variance Walk | Values and commentary remain correctly mapped | Browser check |
| Risks & Opportunities / Additional Notes | Existing content and save behavior remain intact | Browser check |
| Save Final Snapshot | Pending commentary is committed or snapshot fails clearly; server confirms saved HTML | Browser plus snapshot endpoint/file |
| Downloaded HTML | Opens independently, reflects embedded frozen data, and ignores stale localStorage values | Open generated HTML in a separate context/profile; compare data and commentary |
| Excel export | Export reflects the active view, data, and commentary | Generate and inspect export |
| Manual SQL refresh | Refresh updates financial data while preserving shared commentary | Refresh in isolated/safe conditions; compare commentary before/after |
| Automatic SQL refresh | Existing automatic configuration remains enabled and operational | Inspect configuration/logs; do not disable for testing |
| Dark Mode | Theme still renders correctly | Browser check |
| Browser console | No unexpected JavaScript errors or failed required requests | Browser console review |
| Backend logs | No unexpected errors, exceptions, or failed writes | Log review |
| Performance | No material regression in affected save/render paths | Compare timings under normal conditions |
| Data integrity | Financial data, commentary file, and journal entries are unchanged except for explicitly intended records | Compare pre/post hashes or record-level diff |

### Concurrency and OneDrive limitations

Use independent browser sessions with isolated localStorage to verify backend conflict handling. This validates application-level concurrency, not OneDrive's cross-device sync latency or simultaneous file synchronization. If separate OneDrive-connected laptops are unavailable, record cross-laptop synchronization as **not tested** rather than implying it passed.

### Deployment and live validation

- [ ] Deploy only after all relevant checks pass; retain a verified rollback copy.
- [ ] Confirm `http://localhost:8770/` serves the deployed version and the process remains healthy.
- [ ] Re-run the affected browser workflow against the live process.
- [ ] Verify protected data hashes and inspect backend/browser errors after deployment.
- [ ] Roll back the affected application file if live validation fails; do not restore or overwrite production data as a rollback shortcut.

## Per-change completion record

Report the root cause, files/functions changed, potential impact, automated/browser checks and results, performance observations, data integrity evidence, live validation, and all outstanding limitations. Do not claim full resolution when an applicable end-to-end check was not completed.
