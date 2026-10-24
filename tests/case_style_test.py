"""Case-style analysis checks. Run inside the font-hub image with FONT_ROOT/STATE_DIR mounts."""
import os
import time
from pathlib import Path

from fontTools.ttLib import TTFont

from app import case_style

ROOT = Path(os.environ["FONT_ROOT"])
STATE = Path(os.environ["STATE_DIR"])
SOURCE = Path(os.environ.get("SOURCE_FONT", "/fonts/latin/DejaVu/DejaVuSans.ttf"))
ROOT.mkdir(parents=True, exist_ok=True)
STATE.mkdir(parents=True, exist_ok=True)


def make_variant(name, caps):
    font = TTFont(str(SOURCE))
    for table in font["cmap"].tables:
        if not table.isUnicode():
            continue
        for index in range(26):
            upper = chr(ord("A") + index)
            lower = chr(ord("a") + index)
            source, target = (upper, lower) if caps else (lower, upper)
            if ord(source) in table.cmap:
                table.cmap[ord(target)] = table.cmap[ord(source)]
    out = ROOT / name
    font.save(str(out))
    font.close()
    return out


def make_single_case(name, keep_upper):
    font = TTFont(str(SOURCE))
    for table in font["cmap"].tables:
        if not table.isUnicode():
            continue
        for index in range(26):
            upper = chr(ord("A") + index)
            lower = chr(ord("a") + index)
            drop = lower if keep_upper else upper
            table.cmap.pop(ord(drop), None)
    out = ROOT / name
    font.save(str(out))
    font.close()
    return out


def data_for(path):
    stat = path.stat()
    return {
        "rel_path": path.name,
        "face_count": 1,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha1": None,
    }


normal = ROOT / "normal.ttf"
normal.write_bytes(SOURCE.read_bytes())
caps = make_variant("caps.ttf", True)
lower = make_variant("lower.ttf", False)
upper_only = make_single_case("upper-only.ttf", True)
lower_only = make_single_case("lower-only.ttf", False)

normal_result = case_style.analyze(data_for(normal), 0)
caps_result = case_style.analyze(data_for(caps), 0)
lower_result = case_style.analyze(data_for(lower), 0)
upper_only_result = case_style.analyze(data_for(upper_only), 0)
lower_only_result = case_style.analyze(data_for(lower_only), 0)
print("normal:", normal_result)
print("caps:", caps_result)
print("lower:", lower_result)
print("upper-only:", upper_only_result)
print("lower-only:", lower_only_result)
assert normal_result["style"] == "mixed", normal_result
assert caps_result["style"] == "upper", caps_result
assert lower_result["style"] == "lower", lower_result
assert upper_only_result["style"] == "upper-only", upper_only_result
assert lower_only_result["style"] == "lower-only", lower_only_result

caps_data = data_for(caps)
cache_path = case_style.CACHE_DIR / case_style._cache_key(caps_data, 0)
assert cache_path.is_file(), cache_path
before = cache_path.stat().st_mtime_ns
time.sleep(0.02)
again = case_style.analyze(caps_data, 0)
after = cache_path.stat().st_mtime_ns
assert again == caps_result
assert before == after, (before, after)
print("cache hit:", cache_path.name)

upper_only_data = data_for(upper_only)
upper_cache = case_style.CACHE_DIR / case_style._cache_key(upper_only_data, 0)
assert upper_cache.is_file(), upper_cache
upper_before = upper_cache.stat().st_mtime_ns
time.sleep(0.02)
upper_again = case_style.analyze(upper_only_data, 0)
upper_after = upper_cache.stat().st_mtime_ns
assert upper_again == upper_only_result
assert upper_before == upper_after, (upper_before, upper_after)
print("single-case cache hit:", upper_cache.name)

for path in (normal, caps, lower, upper_only, lower_only):
    path.unlink(missing_ok=True)
print("ALL CASE STYLE CHECKS PASSED")
