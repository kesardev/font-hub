import logging
import math
import shutil
import uuid
from datetime import datetime, timedelta, timezone

from . import db, fonts, project_settings
from .config import FONT_ROOT, RECYCLE_DIR

log = logging.getLogger("font-hub.recycle")


class RecycleError(Exception):
    pass


class RecycleConflict(RecycleError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _item_dir(storage_key: str):
    root = RECYCLE_DIR.resolve()
    candidate = (RECYCLE_DIR / storage_key).resolve()
    candidate.relative_to(root)
    if candidate == root:
        raise RecycleError("回收站存储路径无效")
    return candidate


def _storage_target(storage_key: str, rel_path: str):
    item_dir = _item_dir(storage_key)
    candidate = (item_dir / rel_path).resolve()
    candidate.relative_to(item_dir)
    return candidate


def _active_target(rel_path: str):
    root = FONT_ROOT.resolve()
    candidate = (FONT_ROOT / rel_path).resolve()
    candidate.relative_to(root)
    if candidate == root:
        raise RecycleError("目标路径无效")
    return candidate


def _remove_storage(row: dict) -> None:
    item_dir = _item_dir(row["storage_key"])
    if item_dir.exists():
        shutil.rmtree(item_dir)


def _serialize(row: dict) -> dict:
    expires_at = row.get("expires_at")
    days_left = None
    if expires_at:
        try:
            remaining = datetime.fromisoformat(expires_at) - _now()
            days_left = max(0, math.ceil(remaining.total_seconds() / 86400))
        except ValueError:
            days_left = None
    return {
        "id": row["id"],
        "font_id": row["font_id"],
        "rel_path": row["rel_path"],
        "name": row["name"],
        "size": row["size"],
        "sha1": row.get("sha1"),
        "deleted_at": row["deleted_at"],
        "expires_at": expires_at,
        "days_left": days_left,
    }


def delete_font(conn, data: dict, permanent: bool = False) -> dict:
    source = fonts.safe_font_path(data["rel_path"])
    if permanent:
        source.unlink()
        db.delete_font_row(conn, int(data["id"]))
        conn.commit()
        return {"mode": "deleted"}

    settings = project_settings.get_project_settings(conn)
    days = int(settings["recycle_days"])
    now = _now()
    deleted_at = _iso(now)
    expires_at = None if days == 0 else _iso(now + timedelta(days=days))
    storage_key = now.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    item_dir = _item_dir(storage_key)
    target = _storage_target(storage_key, data["rel_path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(source), str(target))
        item_id = db.insert_recycle_item(
            conn,
            {
                "font_id": int(data["id"]),
                "rel_path": data["rel_path"],
                "name": data["name"],
                "size": int(data.get("size") or 0),
                "sha1": data.get("sha1"),
                "storage_key": storage_key,
                "deleted_at": deleted_at,
                "expires_at": expires_at,
            },
        )
        db.set_present(conn, int(data["id"]), False)
        conn.commit()
    except Exception:
        conn.rollback()
        try:
            if target.exists() and not source.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(source))
        except OSError:
            log.exception("failed to roll back recycle move for %s", data["rel_path"])
        shutil.rmtree(item_dir, ignore_errors=True)
        raise
    return {
        "mode": "recycled",
        "item_id": item_id,
        "expires_at": expires_at,
    }


def restore_item(conn, item_id: int) -> dict:
    row = db.get_recycle_item(conn, item_id)
    if row is None:
        raise RecycleError("回收站项目不存在")
    source = _storage_target(row["storage_key"], row["rel_path"])
    if not source.is_file():
        raise RecycleError("回收站中的字体文件已不存在")
    target = _active_target(row["rel_path"])
    if target.exists():
        raise RecycleConflict("目标路径已存在，无法恢复")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    try:
        db.delete_recycle_item(conn, item_id)
        db.set_present(conn, int(row["font_id"]), True)
        conn.commit()
    except Exception:
        conn.rollback()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(source))
        except OSError:
            log.exception("failed to roll back restore for %s", row["rel_path"])
        raise
    shutil.rmtree(_item_dir(row["storage_key"]), ignore_errors=True)
    return {"mode": "restored", "rel_path": row["rel_path"]}


def permanent_delete_item(conn, item_id: int) -> dict:
    row = db.get_recycle_item(conn, item_id)
    if row is None:
        raise RecycleError("回收站项目不存在")
    if not RECYCLE_DIR.is_dir():
        raise RecycleError("回收站目录不可用")
    try:
        _remove_storage(row)
    except OSError as exc:
        raise RecycleError(f"删除回收站文件失败: {exc}") from exc
    db.delete_recycle_item(conn, item_id)
    db.delete_font_row(conn, int(row["font_id"]))
    conn.commit()
    return {"mode": "deleted", "rel_path": row["rel_path"]}


def purge_expired(conn) -> list[dict]:
    if not RECYCLE_DIR.is_dir():
        log.warning("recycle dir missing; skip purge")
        return []
    now = _iso(_now())
    rows = db.list_expired_recycle_items(conn, now)
    purged = []
    for row in rows:
        try:
            _remove_storage(row)
        except OSError as exc:
            log.warning("failed to purge %s: %s", row["rel_path"], exc)
            continue
        db.delete_recycle_item(conn, int(row["id"]))
        db.delete_font_row(conn, int(row["font_id"]))
        conn.commit()
        purged.append(row)
    return purged


def list_items(conn) -> dict:
    rows = db.list_recycle_items(conn)
    items = [_serialize(row) for row in rows]
    return {
        "items": items,
        "total": len(items),
        "total_size": sum(int(item["size"] or 0) for item in items),
        "recycle_days": int(project_settings.get_project_settings(conn)["recycle_days"]),
    }
