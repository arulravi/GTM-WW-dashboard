"""Durable shared-file storage for commentary updates."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import tempfile
import uuid


SHARED_APP_RELATIVE_PATH = os.path.join(
    "Expenses", "FY26", "Claude Project", "GTM WW dashboard"
)
JOURNAL_DIR_NAME = "commentary_updates"


def resolve_shared_app_dir() -> str:
    configured = os.environ.get("GTM_WW_SHARED_APP_DIR")
    if configured:
        path = os.path.abspath(os.path.expandvars(os.path.expanduser(configured)))
        if not os.path.isdir(path):
            raise RuntimeError(
                f"GTM_WW_SHARED_APP_DIR does not exist: {path}. "
                "Set it to the locally synced GTM WW dashboard SharePoint folder."
            )
        return path

    roots = [
        os.environ.get("OneDriveCommercial"),
        os.environ.get("OneDrive"),
        os.path.join(os.path.expanduser("~"), "OneDrive - Adobe"),
    ]
    seen = set()
    for root in roots:
        if not root:
            continue
        root = os.path.abspath(os.path.expandvars(os.path.expanduser(root)))
        if root in seen:
            continue
        seen.add(root)
        candidate = os.path.join(root, SHARED_APP_RELATIVE_PATH)
        if os.path.isdir(candidate):
            return candidate

    raise RuntimeError(
        "The shared GTM WW dashboard SharePoint folder was not found. "
        "Sync it with OneDrive, or set GTM_WW_SHARED_APP_DIR to its local path. "
        "Commentary is not saved beside a GitHub checkout because that would "
        "create a private copy that other users cannot see."
    )


def _read_object(path: pathlib.Path, *, missing_ok: bool = False) -> dict:
    if not path.exists():
        if missing_ok:
            return {}
        raise RuntimeError(f"Required commentary storage file is missing: {path}")
    try:
        with path.open("r", encoding="utf-8-sig") as source:
            value = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected a JSON object in {path}")
    return value


def _atomic_write(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(value, target, indent=2, ensure_ascii=False)
            target.flush()
            os.fsync(target.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _apply_changes(target: dict, changes: object, *, baseline: bool = False) -> None:
    if not isinstance(changes, dict):
        raise RuntimeError("Commentary journal entry has invalid changes")
    for scope, fields in changes.items():
        if not isinstance(scope, str) or not isinstance(fields, dict):
            raise RuntimeError("Commentary journal entry has invalid scope data")
        for field, value in fields.items():
            if not isinstance(field, str):
                raise RuntimeError("Commentary journal entry has an invalid field")
            current = target.get(scope)
            if baseline:
                if not isinstance(current, dict):
                    current = target.setdefault(scope, {})
                if field in current and isinstance(current[field], str) and current[field].strip():
                    continue
                if value is not None and (not isinstance(value, str) or value.strip()):
                    current[field] = value
                continue
            if value is None or (isinstance(value, str) and not value.strip()):
                if isinstance(current, dict):
                    current.pop(field, None)
                    if not current:
                        target.pop(scope, None)
            elif isinstance(value, str):
                target.setdefault(scope, {})[field] = value
            else:
                raise RuntimeError("Commentary journal values must be text or null")


def _apply_meta_changes(target: dict, changes: object) -> None:
    if not isinstance(changes, dict):
        raise RuntimeError("Commentary journal entry has invalid metadata changes")
    for scope, fields in changes.items():
        if not isinstance(scope, str) or not isinstance(fields, dict):
            raise RuntimeError("Commentary journal entry has invalid metadata scope")
        for field, value in fields.items():
            if not isinstance(field, str):
                raise RuntimeError("Commentary journal entry has an invalid metadata field")
            if value is None:
                current = target.get(scope)
                if isinstance(current, dict):
                    current.pop(field, None)
                    if not current:
                        target.pop(scope, None)
            elif isinstance(value, dict):
                target.setdefault(scope, {})[field] = value
            else:
                raise RuntimeError("Commentary journal metadata must be an object or null")


def _journal_entries(shared_dir: str) -> list[tuple[pathlib.Path, dict]]:
    journal_dir = pathlib.Path(shared_dir) / JOURNAL_DIR_NAME
    if not journal_dir.exists():
        return []
    if not journal_dir.is_dir():
        raise RuntimeError(f"Commentary journal path is not a directory: {journal_dir}")

    entries = []
    for path in journal_dir.glob("*.json"):
        entry = _read_object(path)
        if entry.get("version") != 1 or not isinstance(entry.get("event_id"), str):
            raise RuntimeError(f"Invalid commentary journal entry: {path}")
        entries.append((path, entry))
    return sorted(
        entries,
        key=lambda item: (
            0 if item[1].get("kind") == "baseline" else 1,
            str(item[1].get("created_at", "")),
            item[1]["event_id"],
        ),
    )


def read_shared_data(shared_dir: str) -> tuple[dict, dict]:
    shared = pathlib.Path(shared_dir)
    commentary = _read_object(shared / "commentary.json")
    meta = _read_object(shared / "commentary_meta.json", missing_ok=True)
    if any(not isinstance(fields, dict) for fields in commentary.values()):
        raise RuntimeError("Every commentary scope must contain a JSON object")
    if any(not isinstance(fields, dict) for fields in meta.values()):
        raise RuntimeError("Every commentary metadata scope must contain a JSON object")
    for _, entry in _journal_entries(shared_dir):
        if entry.get("kind") == "baseline":
            _apply_changes(commentary, entry.get("changes"), baseline=True)
            _apply_meta_changes(meta, entry.get("meta_changes", {}))
        elif entry.get("kind") == "update":
            _apply_changes(commentary, entry.get("changes"))
            _apply_meta_changes(meta, entry.get("meta_changes", {}))
        else:
            raise RuntimeError("Commentary journal entry has an unknown kind")
    return commentary, meta


def shared_data_revision(shared_dir: str) -> str:
    shared = pathlib.Path(shared_dir)
    paths = [shared / "commentary.json"]
    journal_dir = shared / JOURNAL_DIR_NAME
    if journal_dir.is_dir():
        paths.extend(journal_dir.glob("*.json"))
    stamps = []
    for path in sorted(paths, key=lambda item: str(item)):
        if path.exists():
            stat = path.stat()
            stamps.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}")
    return hashlib.sha256("|".join(stamps).encode("utf-8")).hexdigest()


def append_update(
    shared_dir: str,
    changes: dict,
    meta_changes: dict | None = None,
    *,
    kind: str = "update",
) -> str:
    if kind not in ("baseline", "update"):
        raise ValueError("kind must be baseline or update")
    event_id = uuid.uuid4().hex
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="microseconds"
    )
    entry = {
        "version": 1,
        "kind": kind,
        "event_id": event_id,
        "created_at": created_at,
        "changes": changes,
        "meta_changes": meta_changes or {},
    }
    path = pathlib.Path(shared_dir) / JOURNAL_DIR_NAME / f"{event_id}.json"
    _atomic_write(path, entry)
    return event_id


def materialize_shared_data(shared_dir: str) -> tuple[dict, dict]:
    commentary, meta = read_shared_data(shared_dir)
    shared = pathlib.Path(shared_dir)
    _atomic_write(shared / "commentary.json", commentary)
    _atomic_write(shared / "commentary_meta.json", meta)
    return commentary, meta
