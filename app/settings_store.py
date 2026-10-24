import json
import logging
import os
import threading
from datetime import datetime, timezone

from .config import CONFIG_DIR, CONFIG_FILE
from .settings_defaults import (
    DEFAULT_PREVIEW,
    DEFAULT_RECYCLE_DAYS,
    MAX_PREVIEW_CHARS,
    MAX_RECYCLE_DAYS,
    PREVIEW_KEYS,
)

log = logging.getLogger("font-hub.settings")
_LOCK = threading.RLock()
_INVALID = object()
_MIGRATION_KEY = "settings_config_migrated"


def _default_payload() -> dict:
    return {
        "version": 1,
        "preview": dict(DEFAULT_PREVIEW),
        "recycle_days": DEFAULT_RECYCLE_DAYS,
    }


def _normalize(payload) -> dict:
    data = _default_payload()
    if not isinstance(payload, dict):
        return data
    preview = payload.get("preview")
    if isinstance(preview, dict):
        for key in PREVIEW_KEYS:
            value = preview.get(key)
            if isinstance(value, str):
                data["preview"][key] = value[:MAX_PREVIEW_CHARS] if value else DEFAULT_PREVIEW[key]
    try:
        days = int(payload.get("recycle_days"))
        if days == 0 or 1 <= days <= MAX_RECYCLE_DAYS:
            data["recycle_days"] = days
    except (TypeError, ValueError):
        pass
    return data


def _read_file():
    try:
        raw = CONFIG_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        log.warning("cannot read settings file %s: %s", CONFIG_FILE, exc)
        return _INVALID
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        log.warning("invalid settings json %s: %s", CONFIG_FILE, exc)
        return _INVALID
    return _normalize(payload)


def _has_migrated(conn) -> bool:
    if conn is None:
        return False
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (_MIGRATION_KEY,)
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _mark_migrated(conn) -> None:
    if conn is None:
        return
    try:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_MIGRATION_KEY, "1"),
        )
        conn.commit()
    except Exception:
        log.exception("cannot mark settings migration")


def _from_db(conn) -> dict:
    data = _default_payload()
    if conn is None:
        return data
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        values = {row["key"]: row["value"] for row in rows}
    except Exception:
        log.exception("cannot read legacy settings")
        return data
    for key in PREVIEW_KEYS:
        value = values.get(key)
        if isinstance(value, str) and value:
            data["preview"][key] = value[:MAX_PREVIEW_CHARS]
    try:
        days = int(values.get("recycle_days"))
        if days == 0 or 1 <= days <= MAX_RECYCLE_DAYS:
            data["recycle_days"] = days
    except (TypeError, ValueError):
        pass
    return data


def _backup_invalid() -> None:
    try:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = CONFIG_FILE.with_name(CONFIG_FILE.name + f".invalid-{stamp}")
        CONFIG_FILE.replace(backup)
        log.warning("invalid settings moved to %s", backup)
    except OSError:
        log.exception("cannot back up invalid settings")


def save(payload: dict) -> dict:
    data = _normalize(payload)
    with _LOCK:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        temp = CONFIG_FILE.with_name(CONFIG_FILE.name + f".{os.getpid()}.tmp")
        temp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, CONFIG_FILE)
    return data


def load(conn=None) -> dict:
    with _LOCK:
        payload = _read_file()
        if payload is _INVALID:
            _backup_invalid()
            needs_migration = not _has_migrated(conn)
            data = _from_db(conn) if needs_migration else _default_payload()
            try:
                save(data)
            except OSError:
                log.exception("cannot write migrated settings")
            if needs_migration:
                _mark_migrated(conn)
            return data
        if payload is None:
            needs_migration = not _has_migrated(conn)
            data = _from_db(conn) if needs_migration else _default_payload()
            try:
                save(data)
            except OSError:
                log.exception("cannot write initial settings")
            if needs_migration:
                _mark_migrated(conn)
            return data
        if not _has_migrated(conn):
            _mark_migrated(conn)
        return payload
