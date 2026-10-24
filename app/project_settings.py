from datetime import datetime, timedelta

from . import settings_store
from .settings_defaults import DEFAULT_RECYCLE_DAYS, MAX_RECYCLE_DAYS


def get_project_settings(conn) -> dict:
    data = settings_store.load(conn)
    return {
        "recycle_days": int(data["recycle_days"]),
        "default_recycle_days": DEFAULT_RECYCLE_DAYS,
        "max_recycle_days": MAX_RECYCLE_DAYS,
    }


def save_project_settings(conn, recycle_days: int) -> dict:
    try:
        days = int(recycle_days)
    except (TypeError, ValueError) as exc:
        raise ValueError("保留天数必须是整数") from exc
    if days != 0 and not 1 <= days <= MAX_RECYCLE_DAYS:
        raise ValueError(f"保留天数范围为 1-{MAX_RECYCLE_DAYS} 天，或 0 表示永久")

    data = settings_store.load(conn)
    data["recycle_days"] = days
    settings_store.save(data)

    for row in conn.execute("SELECT id, deleted_at FROM recycle_items").fetchall():
        expires_at = None
        if days:
            try:
                deleted_at = datetime.fromisoformat(row["deleted_at"])
                expires_at = (deleted_at + timedelta(days=days)).isoformat(timespec="seconds")
            except ValueError:
                continue
        conn.execute(
            "UPDATE recycle_items SET expires_at=? WHERE id=?",
            (expires_at, row["id"]),
        )
    conn.commit()
    return get_project_settings(conn)
