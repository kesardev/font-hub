"""Recycle bin API smoke test. Usage: FONT_ROOT=/tmp/recycle-fonts STATE_DIR=/tmp/recycle-state python3 recycle_smoke.py http://127.0.0.1:13580"""
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:13580").rstrip("/")
FONT_ROOT = Path(os.environ["FONT_ROOT"])


def request(method, path, payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    return urllib.request.urlopen(req)


def get_json(path):
    with request("GET", path) as response:
        return json.load(response)


def send_json(method, path, payload=None):
    with request(method, path, payload) as response:
        return json.load(response)


def expect_status(method, path, status):
    try:
        request(method, path)
    except urllib.error.HTTPError as exc:
        assert exc.code == status, (exc.code, status)
        return
    raise AssertionError(f"{method} {path} should return {status}")


def wait_ready():
    for _ in range(60):
        try:
            health = get_json("/api/health")
            if health["fonts"] >= 3 and not health["scan"]["running"]:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise AssertionError("server did not become ready")


def items():
    return get_json("/api/fonts?page_size=100")["items"]


def item_path(item):
    return FONT_ROOT / item["rel_path"]


wait_ready()
fonts = [item for item in items() if item["parse_status"] == "ok" and item["ext"] in (".ttf", ".otf")]
assert len(fonts) >= 3, fonts
first, second, third = fonts[:3]

settings = send_json("PUT", "/api/settings/project", {"recycle_days": 30})
assert settings["recycle_days"] == 30, settings

deleted = send_json("DELETE", f"/api/fonts/{first['id']}?permanent=false")
assert deleted["mode"] == "recycled", deleted
assert not item_path(first).exists()
expect_status("GET", f"/api/fonts/{first['id']}", 404)
recycle = get_json("/api/recycle")
assert recycle["total"] == 1, recycle
entry = recycle["items"][0]
assert entry["rel_path"] == first["rel_path"]
assert entry["expires_at"] and entry["days_left"] > 0, entry

settings = send_json("PUT", "/api/settings/project", {"recycle_days": 7})
assert settings["recycle_days"] == 7
entry = get_json("/api/recycle")["items"][0]
assert 1 <= entry["days_left"] <= 7, entry
settings = send_json("PUT", "/api/settings/project", {"recycle_days": 30})
assert settings["recycle_days"] == 30

item_path(first).parent.mkdir(parents=True, exist_ok=True)
item_path(first).write_bytes(b"conflict")
expect_status("POST", f"/api/recycle/{entry['id']}/restore", 409)
item_path(first).unlink()
restored = send_json("POST", f"/api/recycle/{entry['id']}/restore")
assert restored["mode"] == "restored", restored
assert item_path(first).exists()
assert get_json("/api/recycle")["total"] == 0

deleted = send_json("DELETE", f"/api/fonts/{first['id']}?permanent=false")
assert deleted["mode"] == "recycled", deleted
entry = get_json("/api/recycle")["items"][0]
removed = send_json("DELETE", f"/api/recycle/{entry['id']}")
assert removed["mode"] == "deleted", removed
assert not item_path(first).exists()
assert get_json("/api/recycle")["total"] == 0

deleted = send_json("DELETE", f"/api/fonts/{second['id']}?permanent=true")
assert deleted["mode"] == "deleted", deleted
assert not item_path(second).exists()
assert get_json("/api/recycle")["total"] == 0

settings = send_json("PUT", "/api/settings/project", {"recycle_days": 0})
assert settings["recycle_days"] == 0, settings
deleted = send_json("DELETE", f"/api/fonts/{third['id']}?permanent=false")
assert deleted["mode"] == "recycled", deleted
entry = get_json("/api/recycle")["items"][0]
assert entry["expires_at"] is None, entry
send_json("POST", f"/api/recycle/{entry['id']}/restore")

try:
    send_json("PUT", "/api/settings/project", {"recycle_days": 5000})
except urllib.error.HTTPError as exc:
    assert exc.code == 400, exc.code
else:
    raise AssertionError("invalid retention should be rejected")
settings = send_json("PUT", "/api/settings/project", {"recycle_days": 30})
assert settings["recycle_days"] == 30

deleted = send_json("DELETE", f"/api/fonts/{third['id']}?permanent=false")
assert deleted["mode"] == "recycled", deleted
entry = get_json("/api/recycle")["items"][0]
db_path = Path(os.environ["STATE_DIR"]) / "fonts.db"
conn = sqlite3.connect(db_path)
conn.execute(
    "UPDATE recycle_items SET expires_at=? WHERE id=?",
    ("2000-01-01T00:00:00+00:00", entry["id"]),
)
conn.commit()
conn.close()
recycle = get_json("/api/recycle")
assert recycle["purged"] == 1, recycle
assert recycle["total"] == 0, recycle
assert not item_path(third).exists()
expect_status("GET", f"/api/fonts/{third['id']}", 404)
print("ALL RECYCLE CHECKS PASSED")
