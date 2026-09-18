# Solution: Real Simultaneous Multi-User Access — Without Personally Hosting a Server

**For:** [Manager]'s app (currently: local SQLite `.db` file synced via OneDrive, one
process per laptop)
**Problem being solved:** two people cannot safely use the app at the same time today,
and the app must be reachable even when no specific person's laptop is on.

## Why this is happening (root cause, not a bug)

The app currently gives **every laptop its own private copy** of the database:
- The `.db` file lives inside a OneDrive-synced folder → each laptop has a separate
  local copy on its own disk, not one shared file.
- The app's own little web server only listens on `127.0.0.1` ("localhost") on
  whichever laptop it's running on → no other laptop can ever reach it over the network.

So "two people run it at the same time" doesn't mean two people share one dataset — it
means two *separate* databases exist, silently drifting apart, with OneDrive occasionally
trying (and sometimes failing) to reconcile the raw `.db` file in the background. That's
also why a laptop being off makes the app unreachable — there is no copy of it running
anywhere except on people's individual machines.

**This is a structural fact about "sync a folder, run a local server per laptop," not
something that can be patched from inside that model.** Real simultaneous access
requires the editable data to live in exactly one place that is always running and that
every user's browser can reach — that's what "simultaneous" means, independent of which
tool builds it.

## The fix: move the *editable data* to something already centrally hosted

The read-only numbers (whatever this app pulls from Finance SQL) can stay exactly as
they are — every laptop already queries the same central SQL Server for those today,
and that part already works correctly and simultaneously. **Only the editable/write
layer (the local `.db` file) needs to move.** Two ways to do that without anyone having
to personally run or maintain a new server:

### Option A (recommended if a DBA can grant a table) — a small table in the existing SQL Server

Since the app already connects to a central Finance SQL Server for its read-only data,
ask IT/DBA for one small scratch table with write access, e.g.:

```sql
CREATE TABLE dbo.AppEditableData (
    scope_key   VARCHAR(200) NOT NULL,
    field_name  VARCHAR(200) NOT NULL,
    value_text  NVARCHAR(MAX) NULL,
    updated_by  VARCHAR(100) NULL,
    updated_at  DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    PRIMARY KEY (scope_key, field_name)
);
```

Change the app so that instead of reading/writing the local SQLite file, it does an
`INSERT ... ON DUPLICATE KEY UPDATE` (or `MERGE`) against this table via the same
`pyodbc`/SQL connection the app already uses for reads. Every laptop now reads and
writes the *same* row set, live — a real database properly handles two people editing
at once (something a local SQLite file synced by OneDrive cannot do). No new server for
anyone to run: SQL Server is already hosted and always on.

### Option B (recommended if there's no DB write access available) — SharePoint List or Excel Online

Microsoft 365 already hosts this, supports genuine simultaneous multi-editor use, and
stays reachable regardless of whose laptop is on. Replace the local `.db` file with a
SharePoint List (one item per `scope_key` + `field_name`, a `value` column) and have the
app read/write it via the Microsoft Graph API instead of local SQLite. Slower to query
than a real database, but zero infrastructure to provision — most orgs already have this
available.

### What NOT to do

A cheap "always on" fix — e.g., just leaving one laptop running 24/7 as the de facto
server — was already correctly ruled out: it makes the whole team dependent on one
specific machine staying powered on and network-connected, and still doesn't solve the
"two people editing at once" problem underneath. It just moves the single point of
failure, it doesn't remove it.

## Bottom line to relay

> "Real simultaneous access needs the editable data to live in one always-on shared
> place — that's not optional. The good news is that place doesn't have to be a server
> we stand up and maintain ourselves: we can reuse the SQL Server we already read from
> (Option A), or SharePoint/Excel Online we already have (Option B). Either removes the
> local SQLite-file-per-laptop problem entirely, with no new infrastructure for anyone
> to personally run."
