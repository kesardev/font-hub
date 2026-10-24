from . import settings_store
from .settings_defaults import DEFAULT_PREVIEW, MAX_PREVIEW_CHARS, PREVIEW_KEYS


def get_preview_settings(conn) -> dict:
    data = settings_store.load(conn)
    return {"preview": dict(data["preview"]), "defaults": DEFAULT_PREVIEW}


def save_preview_settings(conn, preview: dict) -> dict:
    data = settings_store.load(conn)
    for key in PREVIEW_KEYS:
        if key in preview:
            data["preview"][key] = str(preview[key])[:MAX_PREVIEW_CHARS]
    settings_store.save(data)
    return get_preview_settings(conn)


def reset_preview_settings(conn) -> dict:
    data = settings_store.load(conn)
    data["preview"] = dict(DEFAULT_PREVIEW)
    settings_store.save(data)
    return get_preview_settings(conn)
