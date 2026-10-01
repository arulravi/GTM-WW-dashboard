# How the GTM WW Opex + HC Dashboard (localhost:8770) Actually Works

**Purpose of this note:** explain how the app is set up today, so we can judge whether the same pattern is good enough for another team's app — and where its real limits are.

## The short version

The app runs **locally on each person's own laptop**, not from one shared server. It looks
like a shared app because the *financial data* really is centrally shared — but the
*editable commentary* is not. Those are two different things living in the same app.

## The two layers

**1. The numbers (Opex/HC figures) — genuinely shared, in real time**
Every laptop connects directly to Adobe's central Finance SQL Server
(`FinSys.corp.adobe.com`) when someone clicks "Refresh." This is one real, always-on
database that everyone reads from. This part works exactly the way people assume a
"shared app" should work.

**2. The commentary (the notes people type in) — shared through OneDrive sync**
- The application code may now be checked out from GitHub, but the shared data
  remains in the SharePoint folder synced by OneDrive.
- `server.py` resolves that shared folder from the user's OneDrive location (or
  `GTM_WW_SHARED_APP_DIR`) independently of the GitHub checkout. It refuses to
  silently create a private copy next to the code.
- Each person runs a local copy of `server.py` on their laptop. A save records
  only the edited commentary cells, with the value each editor last saw, as a
  unique append-only record in `commentary_updates`; `commentary.json` is the
  merged, readable view. Updating one cell cannot replace other cells in that
  L3 or another L3.
- Refresh, restart, and API reads rebuild the view from the recovered baseline
  and journal. Stale edits to cells that have changed are rejected; if two
  laptops submit a same-cell edit before syncing, replay applies the first
  journal event by UTC timestamp, then event ID. The other edit must be
  explicitly re-applied after seeing the winner.
- OneDrive synchronization is still eventually consistent, so another laptop
  sees updates after sync completes. The browser pulls shared commentary on
  startup, on focus, and periodically while open.

## What this means in practice

- Notes eventually show up for everyone once OneDrive finishes syncing, provided
  each user is running the journal-aware server version.
- **The JSON view can still produce OneDrive conflict copies**, but unique
  journal records preserve and merge separate cell edits back into the view.
  This protects unrelated commentary cells without claiming OneDrive is a
  real-time transactional database.
- **The app is not "always on."** If nobody's laptop has the local program running, the
  editable/commentary part of the app isn't reachable — although the OneDrive-synced
  files themselves are still safe and visible in the folder.
- This is **the same underlying pattern** as a per-laptop local database file synced via
  OneDrive (e.g. a `.db` file) — just using small JSON text files instead of a database
  file. Same benefits, same limitation: fine for "one person, or people taking turns,"
  not real simultaneous multi-user editing.

## If we want true simultaneous access (everyone editing live, always on)

There's no way to get that without *some* central, always-on place for the editable
data to live — that's just what "simultaneous" requires, regardless of which tool builds
it. The realistic options, roughly from least new infrastructure to most:

1. **Write the editable notes into a table in the same Finance SQL Server** we already
   read from (needs a small scratch table + write access from IT/DBA). No new server to
   run — we'd be using infrastructure IT already keeps alive 24/7.
2. **A SharePoint List or Excel-Online workbook** for the editable notes — Microsoft 365
   already hosts this, supports real simultaneous co-editing, and stays up regardless of
   whose laptop is on.
3. **A small always-on server that isn't anyone's laptop** — a low-cost cloud instance or
   IT-hosted VM running the same local program continuously, so every laptop's browser
   talks to one shared, always-on copy instead of everyone running their own.

Options 1 and 2 don't require anyone to personally run or maintain a server — they just
need write access to something the company already keeps running.
