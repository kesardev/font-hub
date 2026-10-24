"""Batch delete API smoke test. Usage: FONT_ROOT=/tmp/batch-fonts python3 batch_delete_smoke.py http://127.0.0.1:13581"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:13581").rstrip("/")
FONT_ROOT = Path(os.environ["FONT_ROOT"])


def call(method, path, payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as response:
        return json.load(response)


def status(method, path, payload=None):
    try:
        call(method, path, payload)
    except urllib.error.HTTPError as exc:
        return exc.code
    return 200


def wait_ready():
    for _ in range(60):
        try:
            health = call("GET", "/api/health")
            if health["fonts"] >= 3 and not health["scan"]["running"]:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise AssertionError("server not ready")


def items():
    return call("GET", "/api/fonts?page_size=100")["items"]


wait_ready()
fonts = [item for item in items() if item["parse_status"] == "ok" and item["ext"] in (".ttf", ".otf")]
assert len(fonts) >= 3, fonts
first, second, third = fonts[:3]


def path_for(item):
    return FONT_ROOT / item["rel_path"]


result = call("POST", "/api/fonts/batch-delete", {"ids": [first["id"], second["id"]], "permanent": False})
assert result["recycled"] == 2 and result["deleted"] == 0 and not result["failed"], result
assert len(items()) == 1
recycle = call("GET", "/api/recycle")
assert recycle["total"] == 2, recycle
for entry in recycle["items"]:
    call("POST", f"/api/recycle/{entry['id']}/restore")
assert len(items()) == 3
assert call("GET", "/api/recycle")["total"] == 0

result = call("POST", "/api/fonts/batch-delete", {"ids": [first["id"], second["id"]], "permanent": True})
assert result["recycled"] == 0 and result["deleted"] == 2 and not result["failed"], result
assert not path_for(first).exists() and not path_for(second).exists()
assert len(items()) == 1
assert call("GET", "/api/recycle")["total"] == 0

result = call("POST", "/api/fonts/batch-delete", {"ids": [third["id"], 999999], "permanent": False})
assert result["recycled"] == 1 and result["deleted"] == 0, result
assert len(result["failed"]) == 1 and result["failed"][0]["id"] == 999999, result
recycle = call("GET", "/api/recycle")
assert recycle["total"] == 1
call("DELETE", f"/api/recycle/{recycle['items'][0]['id']}")
assert not path_for(third).exists()
assert call("GET", "/api/recycle")["total"] == 0

assert status("POST", "/api/fonts/batch-delete", {"ids": [], "permanent": False}) == 400
print("ALL BATCH DELETE CHECKS PASSED")
