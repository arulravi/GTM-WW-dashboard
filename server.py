#!/usr/bin/env python3
"""
Opex & HC Outlook -- local app server
=====================================
Turns the dashboard into a proper little desktop app: serves dashboard.html and
exposes a refresh button that re-pulls live data from SQL on demand.

    python server.py            # starts on http://localhost:8770 and opens the app

Endpoints
---------
  GET  /                        -> dashboard.html
  GET  /<file>                  -> static files (data.js, manifest, …)
  POST /api/refresh             -> re-run the SQL ETL, rewrite data.js, return meta
  POST /api/commentary          -> save commentary.json (so it survives refreshes)
  GET  /api/commentary          -> live read of commentary.json + its metadata
  GET  /api/deletion-requests   -> list all deletion-approval requests
  POST /api/deletion-requests   -> file a new deletion-approval request
  POST /api/deletion-requests/resolve -> approve or reject a pending request
  POST /api/snapshot            -> save a finalized, self-contained HTML snapshot to snapshots/
  GET  /api/snapshots           -> list saved snapshots (name, size, modified)

Uses only the Python standard library -- nothing to install.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import socket
import sys
import threading
import uuid
import webbrowser
import subprocess
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import refresh

HERE = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PORT = 8770
SNAPSHOT_DIR = os.path.join(HERE, "snapshots")
COMMENTARY_PATH = os.path.join(HERE, "commentary.json")
COMMENTARY_META_PATH = os.path.join(HERE, "commentary_meta.json")
DELETION_REQUESTS_PATH = os.path.join(HERE, "deletion_requests.json")
PROTECT_AFTER_DAYS = 10

# ThreadingHTTPServer runs each request in its own thread; with multiple
# people saving commentary at once, two threads could otherwise both read the
# same commentary.json, merge in memory, and write back -- the second write
# wins and silently drops whatever the first one added. This lock serializes
# the whole read-merge-write so saves stack instead of racing. The deletion
# request queue is a separate file, so it gets its own lock rather than
# contending with every ordinary commentary save.
_commentary_lock = threading.Lock()
_deletion_lock = threading.Lock()


def _load_json(path, default):
    if not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json_atomic(path, obj):
    tmp_path = path + f".tmp{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


# ---- Deletion-approval protection -----------------------------------------
# A field with NO metadata record at all is one that existed before this
# feature shipped (the metadata store only ever gets a row the moment a field
# is first saved through the code below) -- treated as permanently protected,
# exactly like every other pre-existing commentary. A field WITH a record is
# one created after this feature shipped: protected only once it's at least
# PROTECT_AFTER_DAYS old, measured from whichever is more recent, its
# creation or its last material edit (both stamped below).
def _is_protected(scope, field, meta):
    m = (meta.get(scope) or {}).get(field)
    if not m:
        return True
    if m.get("baseline"):
        return True
    ts_str = m.get("updated_at") or m.get("created_at")
    if not ts_str:
        return True
    try:
        ts = datetime.datetime.fromisoformat(ts_str)
    except Exception:
        return True
    age_days = (datetime.datetime.now() - ts).total_seconds() / 86400.0
    return age_days >= PROTECT_AFTER_DAYS


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=HERE, **k)

    def log_message(self, fmt, *args):
        pass  # keep the console clean

    def end_headers(self):
        # This app is actively edited/refreshed -- never let the browser cache a
        # stale dashboard.html/data.js after a code change or a data refresh.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()

    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(n) if n else b""

    def do_POST(self):
        if self.path == "/api/refresh":
            try:
                data = refresh.build_data()
                refresh.write_data_js(data)
                self._send_json({"ok": True, "generated_at": data["meta"]["generated_at"],
                                 "current_quarter": data["meta"]["current_quarter"]})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
        elif self.path == "/api/commentary":
            try:
                payload = json.loads(self._read_body() or b"{}")
                # Merge rather than overwrite, and merge at the FIELD level
                # (not just the scope-key level): a browser tab only knows the
                # scopes/fields it has loaded or edited via its own
                # localStorage, so replacing a whole scope-key's dict would
                # silently drop a colleague's fields for that same scope that
                # this tab never saw (e.g. their note on a different cost
                # element in the same quarter). Field-level merge means two
                # people editing the same scope, on different machines, both
                # keep their notes even if neither has the other's yet.
                #
                # Locked + atomic (write to a temp file, then os.replace): with
                # multiple people saving at once, this serializes the
                # read-merge-write so one save can never clobber another's,
                # and a crash or concurrent read mid-write can never see a
                # half-written file.
                with _commentary_lock:
                    existing = _load_json(COMMENTARY_PATH, {})
                    meta = _load_json(COMMENTARY_META_PATH, {})
                    now = _now_iso()
                    blocked = []  # [(scope, field)] -- protected deletes we refused
                    for scope_key, fields in payload.items():
                        if isinstance(fields, dict):
                            tgt = existing.setdefault(scope_key, {})
                            for f, v in fields.items():
                                is_delete = v is None or (isinstance(v, str) and v.strip() == "")
                                if is_delete:
                                    # An empty/blank value is normally an explicit
                                    # DELETE of that field -- but a protected
                                    # field (see Add Commentary Deletion
                                    # Approval Control) can only ever be removed
                                    # through the approve step in
                                    # /api/deletion-requests/resolve. This is
                                    # the real backstop: even if the UI's own
                                    # confirm/request-instead flow gets
                                    # bypassed or a stale page is still open,
                                    # the server itself refuses to drop a
                                    # protected value here. We just skip it --
                                    # `existing` keeps whatever it already had,
                                    # so the very next GET/merge shows the
                                    # untouched value again.
                                    if f in tgt and _is_protected(scope_key, f, meta):
                                        blocked.append((scope_key, f))
                                        continue
                                    tgt.pop(f, None)
                                    (meta.get(scope_key) or {}).pop(f, None)
                                else:
                                    is_new = f not in tgt
                                    tgt[f] = v
                                    mscope = meta.setdefault(scope_key, {})
                                    if is_new:
                                        mscope[f] = {"baseline": False, "created_at": now, "updated_at": now}
                                    elif f in mscope:
                                        # Material edit to a field we're already
                                        # tracking -- resets the 10-day clock.
                                        # (Nothing to do for a pre-existing/
                                        # baseline field with no record: it has
                                        # no clock to reset, it's just always
                                        # protected.)
                                        mscope[f]["updated_at"] = now
                            if not tgt:               # scope emptied out -> drop it
                                existing.pop(scope_key, None)
                                meta.pop(scope_key, None)
                            elif not meta.get(scope_key):
                                meta.pop(scope_key, None)
                        else:
                            existing[scope_key] = fields
                    _save_json_atomic(COMMENTARY_PATH, existing)
                    _save_json_atomic(COMMENTARY_META_PATH, meta)
                resp = {"ok": True, "commentary": existing}
                if blocked:
                    resp["blocked"] = [{"scope": s, "field": f} for s, f in blocked]
                self._send_json(resp)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
        elif self.path == "/api/deletion-requests":
            try:
                body = json.loads(self._read_body() or b"{}")
                scope = (body.get("scope") or "").strip()
                field = (body.get("field") or "").strip()
                requested_by = (body.get("requested_by") or "Unknown").strip() or "Unknown"
                if not scope or not field:
                    self._send_json({"ok": False, "error": "scope and field are required"}, 400)
                    return
                with _commentary_lock:
                    existing = _load_json(COMMENTARY_PATH, {})
                    value = (existing.get(scope) or {}).get(field)
                if value is None or not str(value).strip():
                    self._send_json({"ok": False, "error": "nothing to delete for that scope/field"}, 400)
                    return
                with _deletion_lock:
                    requests = _load_json(DELETION_REQUESTS_PATH, [])
                    # Don't pile up duplicate pending requests for the same
                    # scope+field -- surface the existing one instead.
                    dup = next((r for r in requests
                                if r["scope"] == scope and r["field"] == field and r["status"] == "pending"), None)
                    if dup:
                        self._send_json({"ok": True, "request": dup, "duplicate": True})
                        return
                    rec = {
                        "id": uuid.uuid4().hex[:12],
                        "scope": scope, "field": field, "value": value,
                        "requested_by": requested_by, "requested_at": _now_iso(),
                        "status": "pending", "resolved_by": None, "resolved_at": None,
                    }
                    requests.append(rec)
                    _save_json_atomic(DELETION_REQUESTS_PATH, requests)
                self._send_json({"ok": True, "request": rec})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
        elif self.path == "/api/deletion-requests/resolve":
            try:
                body = json.loads(self._read_body() or b"{}")
                req_id = body.get("id")
                action = body.get("action")
                resolved_by = (body.get("resolved_by") or "Unknown").strip() or "Unknown"
                if action not in ("approve", "reject"):
                    self._send_json({"ok": False, "error": "action must be approve or reject"}, 400)
                    return
                with _deletion_lock:
                    requests = _load_json(DELETION_REQUESTS_PATH, [])
                    rec = next((r for r in requests if r["id"] == req_id), None)
                    if not rec:
                        self._send_json({"ok": False, "error": "request not found"}, 404)
                        return
                    if rec["status"] != "pending":
                        self._send_json({"ok": False, "error": f"request already {rec['status']}"}, 409)
                        return
                    if action == "approve":
                        # This is the ONLY code path allowed to actually drop a
                        # protected field's value -- everywhere else (the
                        # regular /api/commentary save) refuses to.
                        with _commentary_lock:
                            existing = _load_json(COMMENTARY_PATH, {})
                            meta = _load_json(COMMENTARY_META_PATH, {})
                            scope_dict = existing.get(rec["scope"])
                            if scope_dict is not None:
                                scope_dict.pop(rec["field"], None)
                                if not scope_dict:
                                    existing.pop(rec["scope"], None)
                            (meta.get(rec["scope"]) or {}).pop(rec["field"], None)
                            _save_json_atomic(COMMENTARY_PATH, existing)
                            _save_json_atomic(COMMENTARY_META_PATH, meta)
                    rec["status"] = "approved" if action == "approve" else "rejected"
                    rec["resolved_by"] = resolved_by
                    rec["resolved_at"] = _now_iso()
                    _save_json_atomic(DELETION_REQUESTS_PATH, requests)
                self._send_json({"ok": True, "request": rec})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
        elif self.path == "/api/snapshot":
            try:
                html = self._read_body().decode("utf-8", errors="replace")
                os.makedirs(SNAPSHOT_DIR, exist_ok=True)
                stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
                name = self.headers.get("X-Snapshot-Name") or "Snapshot"
                name = re.sub(r"[^A-Za-z0-9_\-]+", "_", name)[:80]
                fname = f"{name}_{stamp}.html"
                path = os.path.join(SNAPSHOT_DIR, fname)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(html)
                self._send_json({"ok": True, "file": fname, "path": path})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
        else:
            self.send_error(404)

    def do_GET(self):
        path_only = self.path.split("?", 1)[0]
        if path_only in ("/", ""):
            self.path = "/dashboard.html" + (self.path[len(path_only):] or "")
        if path_only == "/api/snapshots":
            try:
                os.makedirs(SNAPSHOT_DIR, exist_ok=True)
                items = []
                for fn in sorted(os.listdir(SNAPSHOT_DIR), reverse=True):
                    if fn.lower().endswith(".html"):
                        fp = os.path.join(SNAPSHOT_DIR, fn)
                        items.append({"name": fn, "kb": round(os.path.getsize(fp) / 1024),
                                      "modified": datetime.datetime.fromtimestamp(
                                          os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M")})
                self._send_json({"ok": True, "items": items})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return
        if path_only == "/api/commentary":
            # Live read of the on-disk commentary.json, independent of the last
            # SQL refresh -- this is what lets one person's saved note show up
            # for a colleague (once OneDrive syncs the file) without anyone
            # needing to click the full 🔄 Refresh. `meta` rides along so the
            # client can tell which fields are protected (see Add Commentary
            # Deletion Approval Control) without a second round trip.
            try:
                data = _load_json(COMMENTARY_PATH, {})
                meta = _load_json(COMMENTARY_META_PATH, {})
                self._send_json({"ok": True, "commentary": data, "meta": meta,
                                  "modified": os.path.getmtime(COMMENTARY_PATH) if os.path.isfile(COMMENTARY_PATH) else 0})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return
        if path_only == "/api/deletion-requests":
            try:
                requests = _load_json(DELETION_REQUESTS_PATH, [])
                self._send_json({"ok": True, "requests": requests})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return
        super().do_GET()


def find_port(start=DEFAULT_PORT):
    for p in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def open_app_window(url):
    """Open in Edge/Chrome app mode (own window) if available, else default browser."""
    candidates = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for exe in candidates:
        if os.path.isfile(exe):
            subprocess.Popen([exe, f"--app={url}", "--window-size=1480,940"])
            return
    webbrowser.open(url)


def main():
    # ensure data.js exists on first run
    if not os.path.isfile(os.path.join(HERE, "data.js")):
        print("[server] no data.js yet — pulling initial data from SQL…")
        try:
            refresh.write_data_js(refresh.build_data())
        except Exception as e:
            print("[server] initial refresh failed:", e)

    argv = sys.argv[1:]
    fixed = next((int(a) for a in argv if a.isdigit()), None)
    no_browser = ("--no-browser" in argv) or bool(os.environ.get("OPEX_NO_BROWSER"))
    app_window = "--app" in argv          # native-style window instead of a browser tab
    port = fixed or DEFAULT_PORT

    # If our web app is already running on this port, just open the link again.
    if port_in_use(port):
        url = f"http://localhost:{port}/"
        print(f"[server] Already running at {url}")
        if not no_browser:
            (open_app_window if app_window else webbrowser.open)(url)
        return

    url = f"http://localhost:{port}/"
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[server] Opex & HC Outlook web app running at {url}")
    print(f"[server] Open this link in any browser:  {url}")
    print("[server] Close this window to stop the web app.")
    if not no_browser:
        opener = open_app_window if app_window else webbrowser.open
        threading.Timer(0.8, lambda: opener(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
