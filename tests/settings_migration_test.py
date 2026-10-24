"""Settings migration checks. Run inside the font-hub image with STATE_DIR/CONFIG_DIR mounts."""
import json
import os
from pathlib import Path

from app import db, preview_settings, project_settings, settings_store
from app.config import CONFIG_DIR, CONFIG_FILE
from app.settings_defaults import DEFAULT_PREVIEW

STATE = Path(os.environ["STATE_DIR"])
STATE.mkdir(parents=True, exist_ok=True)
db.init_db()
conn = db.connect()
conn.execute("DELETE FROM settings")
for key, value in (
    ("preview_cn", "数据库简体"),
    ("preview_en", "DATABASE ENGLISH"),
    ("preview_punct", "数据库标点"),
    ("preview_special", "数据库特殊"),
    ("recycle_days", "7"),
):
    conn.execute("INSERT INTO settings(key, value) VALUES(?, ?)", (key, value))
conn.commit()

assert not CONFIG_FILE.exists()
data = settings_store.load(conn)
assert CONFIG_FILE.is_file()
payload = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
assert payload["preview"]["preview_cn"] == "数据库简体", payload
assert payload["recycle_days"] == 7, payload
assert preview_settings.get_preview_settings(conn)["preview"]["preview_cn"] == "数据库简体"
assert project_settings.get_project_settings(conn)["recycle_days"] == 7

assert project_settings.save_project_settings(conn, 3)["recycle_days"] == 3
payload = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
assert payload["recycle_days"] == 3, payload

payload["preview"]["preview_cn"] = "文件简体"
payload["recycle_days"] = 0
CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
assert settings_store.load(conn)["preview"]["preview_cn"] == "文件简体"
assert project_settings.get_project_settings(conn)["recycle_days"] == 0

preview_settings.save_preview_settings(conn, {"preview_cn": "保存简体"})
payload = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
assert payload["preview"]["preview_cn"] == "保存简体", payload
assert payload["recycle_days"] == 0, payload
preview_settings.save_preview_settings(conn, {"preview_cn": ""})
payload = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
assert payload["preview"]["preview_cn"] == DEFAULT_PREVIEW["preview_cn"], payload

CONFIG_FILE.write_text("{broken", encoding="utf-8")
data = settings_store.load(conn)
assert data["preview"]["preview_cn"] == DEFAULT_PREVIEW["preview_cn"], data
backups = list(CONFIG_DIR.glob("settings.json.invalid-*"))
assert backups, backups
assert json.loads(CONFIG_FILE.read_text(encoding="utf-8"))["preview"]["preview_cn"] == DEFAULT_PREVIEW["preview_cn"]
conn.close()
print("ALL SETTINGS MIGRATION CHECKS PASSED")
