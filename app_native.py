#!/usr/bin/env python3
"""
Opex & HC Outlook -- native desktop app
=======================================
Opens the dashboard in a real native window (Windows WebView2 via pywebview):
no console, no browser tabs, no address bar. A local server runs in the
background so the in-app 🔄 Refresh button can re-pull live data from SQL.
Closing the window quits the app cleanly.

Run:  pythonw app_native.py     (or the packaged Opex HC Outlook.exe)
"""
from __future__ import annotations

import os
import sys
import threading
from http.server import ThreadingHTTPServer

HERE = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import server
import refresh


def start_server() -> int:
    # make sure there is data to show on first launch
    if not os.path.isfile(os.path.join(HERE, "data.js")):
        try:
            refresh.write_data_js(refresh.build_data())
        except Exception as e:
            print("initial refresh failed:", e)
    port = server.find_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return port


def main():
    # taskbar identity (so the window groups under our own icon, not python)
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Adobe.OpexHCOutlook")
    except Exception:
        pass

    port = start_server()

    if os.environ.get("OPEX_HEADLESS"):
        import time
        print("SERVING", port)
        time.sleep(2)
        return

    import webview
    webview.create_window(
        "GTM WW — Opex + HC Summary",
        f"http://localhost:{port}/",
        width=1480, height=940, min_size=(1120, 720),
    )
    icon = os.path.join(HERE, "app.ico")  # WinForms backend needs an .ico
    if os.path.isfile(icon):
        try:
            webview.start(icon=icon)
            return
        except TypeError:
            pass  # older pywebview without icon= support
    webview.start()


if __name__ == "__main__":
    main()
