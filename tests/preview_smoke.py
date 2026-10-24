"""Preview API smoke test. Usage: python3 preview_smoke.py http://127.0.0.1:13579"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:13579").rstrip("/")


def request(path, payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    return urllib.request.urlopen(req)


def get_json(path):
    with request(path) as response:
        return json.load(response)


def post_json(path, payload):
    with request(path, payload) as response:
        return json.load(response)


def get_bytes(path):
    with request(path) as response:
        return response.status, response.headers.get("Content-Type", ""), response.read()


health = get_json("/api/health")
assert health["status"] == "ok", health
print("health:", health["fonts"], "fonts")

items = get_json("/api/fonts?page_size=500")["items"]
ttf = next(item for item in items if item["ext"] in (".ttf", ".otf") and item["parse_status"] == "ok")
ttc = next(item for item in items if item["ext"] == ".ttc" and item["parse_status"] == "ok")

status, media, body = get_bytes(f"/api/fonts/{ttf['id']}/preview")
assert status == 200 and media.startswith("font/") and len(body) == ttf["size"], (status, media, len(body))
print("ttf preview:", media, len(body))

face = min(2, ttc["face_count"] - 1)
started = time.time()
status, media, body = get_bytes(f"/api/fonts/{ttc['id']}/preview?face={face}")
elapsed = time.time() - started
assert status == 200 and media.startswith("font/") and len(body) > 1000, (status, media, len(body))
print(f"ttc preview: face={face} {media} {len(body)} bytes {elapsed:.2f}s")
assert elapsed < 30, "TTC face extraction too slow"

case_style = get_json(f"/api/fonts/{ttf['id']}/case-style?face=0")
assert case_style["pairs"] >= 20, case_style
assert case_style["style"] in ("mixed", "unicase", "upper", "lower", "upper-only", "lower-only"), case_style
print("case style:", case_style["style"], "pairs", case_style["pairs"], "identical", case_style["identical"])

started = time.time()
ttc_case = get_json(f"/api/fonts/{ttc['id']}/case-style?face={face}")
ttc_elapsed = time.time() - started
assert ttc_case["pairs"] >= 20, ttc_case
assert ttc_case["style"] in ("mixed", "unicase", "upper", "lower", "upper-only", "lower-only"), ttc_case
print(f"ttc case style: face={face} {ttc_case['style']} {ttc_elapsed:.2f}s")

coverage = post_json(
    f"/api/fonts/{ttc['id']}/coverage",
    {
        "face": face,
        "texts": {
            "cn": "天地玄黄",
            "en": "Hamburgefonstiv",
            "punct": "0123456789，。！？",
            "special": "✗✗✗",
            "empty": "",
        },
    },
)
results = coverage["results"]
assert coverage["face"] == face
assert results["cn"]["missing_count"] == 0
assert results["en"]["missing_count"] == 0
assert results["punct"]["missing_count"] == 0
assert results["special"]["missing_count"] == 1, results["special"]
assert results["special"]["missing_occurrences"] == 3, results["special"]
assert results["special"]["coverage"] == 0.0, results["special"]
assert results["empty"]["coverage"] == 1.0
print("coverage:", {key: (value["missing_count"], value["coverage"]) for key, value in results.items()})

settings = get_json("/api/settings/preview")
assert set(settings["preview"]) == {"preview_cn", "preview_en", "preview_punct", "preview_special"}
defaults = settings["defaults"]
assert len(defaults["preview_cn"].splitlines()) == 2
assert "黄" in defaults["preview_cn"] and "黃" in defaults["preview_cn"]
assert len(defaults["preview_en"].splitlines()) == 2
assert defaults["preview_en"].splitlines()[0].isupper()
assert defaults["preview_en"].splitlines()[1].islower()
assert len(defaults["preview_punct"].splitlines()) == 3
assert defaults["preview_punct"].splitlines()[2] == "0123456789"
assert len(defaults["preview_special"].splitlines()) == 1
print("preview settings: cn 2 lines, en 2 lines, punct 3 lines, special 1 line")

status, media, css = get_bytes("/static/style.css")
assert status == 200 and b".missing-glyph" in css and b".preview-warning" in css
status, media, js = get_bytes("/static/app.js")
assert status == 200 and b"renderPreviewBlocks" in js and b"no_cmap" in js
print("static assets: preview hooks present")

try:
    request(f"/api/fonts/{ttc['id']}/coverage", {"face": 99, "texts": {"x": "A"}})
except urllib.error.HTTPError as exc:
    assert exc.code == 400, exc.code
    print("invalid face rejected:", exc.code)
else:
    raise AssertionError("invalid face should be rejected")

print("ALL PREVIEW CHECKS PASSED")
