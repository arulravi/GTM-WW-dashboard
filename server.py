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
  GET  /api/commentary          -> live read of commentary.json
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
import webbrowser
import subprocess
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import refresh
from commentary_store import (
    append_update,
    find_conflicts,
    materialize_shared_data,
    read_shared_data,
    resolve_shared_app_dir,
    shared_data_revision,
)

HERE = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PORT = 8770
SNAPSHOT_DIR = os.path.join(HERE, "snapshots")

SHARED_APP_DIR = resolve_shared_app_dir()
COMMENTARY_PATH = os.path.join(SHARED_APP_DIR, "commentary.json")

# The lock serializes local requests. Cross-device writes are separate
# immutable journal entries, so OneDrive cannot make one user's whole-file
# replacement erase another user's save.
_commentary_lock = threading.Lock()


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
                request_data = json.loads(self._read_body() or b"{}")
                if not isinstance(request_data, dict) or not {
                    "changes", "expected"
                }.issubset(request_data):
                    self._send_json(
                        {
                            "ok": False,
                            "error": "This page uses an outdated save format. Reload the dashboard before saving.",
                        },
                        409,
                    )
                    return
                payload = request_data["changes"]
                expected = request_data["expected"]
                with _commentary_lock:
                    existing = read_shared_data(SHARED_APP_DIR)
                    conflicts = find_conflicts(existing, payload, expected)
                    conflict_keys = {(item["scope"], item["field"]) for item in conflicts}
                    changes = {}
                    applied = {}
                    for scope_key, fields in payload.items():
                        if not isinstance(scope_key, str) or not isinstance(fields, dict):
                            raise ValueError("Each commentary scope must contain a JSON object")
                        tgt = existing.setdefault(scope_key, {})
                        for field, value in fields.items():
                            if not isinstance(field, str) or not (
                                value is None or isinstance(value, str)
                            ):
                                raise ValueError("Commentary fields must be text or null")
                            if (scope_key, field) in conflict_keys:
                                continue
                            is_delete = value is None or not value.strip()
                            if is_delete:
                                if field not in tgt:
                                    applied.setdefault(scope_key, {})[field] = None
                                    continue
                                tgt.pop(field, None)
                                changes.setdefault(scope_key, {})[field] = None
                                applied.setdefault(scope_key, {})[field] = None
                            else:
                                is_new = field not in tgt
                                applied.setdefault(scope_key, {})[field] = value
                                if is_new or tgt[field] != value:
                                    tgt[field] = value
                                    changes.setdefault(scope_key, {})[field] = value
                        if not tgt:
                            existing.pop(scope_key, None)
                    if changes:
                        expected_changes = {
                            scope: {
                                field: expected[scope][field]
                                for field in fields
                            }
                            for scope, fields in changes.items()
                        }
                        append_update(
                            SHARED_APP_DIR,
                            changes,
                            expected_changes=expected_changes,
                        )
                        existing = materialize_shared_data(SHARED_APP_DIR)
                resp = {
                    "ok": True,
                    "commentary": existing,
                    "applied": applied,
                    "conflicts": conflicts,
                }
                self._send_json(resp)
            except ValueError as e:
                self._send_json({"ok": False, "error": str(e)}, 400)
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
            # needing to click the full 🔄 Refresh.
            try:
                data = read_shared_data(SHARED_APP_DIR)
                self._send_json({"ok": True, "commentary": data,
                                  "modified": shared_data_revision(SHARED_APP_DIR)})
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
    print(f"[server] shared commentary source: {COMMENTARY_PATH}", flush=True)
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
