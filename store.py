"""
Local persistence for editable commentary and finalized snapshots.

Commentary is saved as JSON keyed by segment-set + quarter, so notes stick to
the report they were written for and survive refreshes / restarts. Snapshots
are timestamped Excel files that freeze a finalized version -- they never change
when the live data is refreshed.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

import config


def _key(segments: list[str], quarter: str) -> str:
    raw = "+".join(sorted(segments)) + "_" + quarter
    return re.sub(r"[^A-Za-z0-9_+-]", "_", raw)


def commentary_path(segments: list[str], quarter: str) -> str:
    return os.path.join(config.COMMENTARY_DIR, _key(segments, quarter) + ".json")


def load_commentary(segments: list[str], quarter: str) -> dict:
    """Return {'lines': {cost_element: text}, 'risks': str, 'opps': str}."""
    path = commentary_path(segments, quarter)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"lines": {}, "risks": "", "opps": ""}


def save_commentary(segments: list[str], quarter: str, data: dict) -> None:
    with open(commentary_path(segments, quarter), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def save_snapshot(segments: list[str], quarter: str, content: bytes, ext: str = "xlsx") -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    name = f"{_key(segments, quarter)}_{stamp}.{ext}"
    path = os.path.join(config.SNAPSHOT_DIR, name)
    with open(path, "wb") as f:
        f.write(content)
    return path


def list_snapshots() -> list[str]:
    if not os.path.isdir(config.SNAPSHOT_DIR):
        return []
    files = [
        os.path.join(config.SNAPSHOT_DIR, f)
        for f in os.listdir(config.SNAPSHOT_DIR)
        if f.lower().endswith((".xlsx", ".pdf"))
    ]
    return sorted(files, key=os.path.getmtime, reverse=True)
