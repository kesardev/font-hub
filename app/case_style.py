import hashlib
import json
import os
from pathlib import Path

from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTCollection, TTFont

try:
    from fontTools.pens.recordingPen import DecomposingRecordingPen
except ImportError:
    DecomposingRecordingPen = None

from . import fonts
from .config import STATE_DIR

CACHE_DIR = STATE_DIR / "cache" / "case-style"
CACHE_VERSION = "case-v1"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MIN_PRESENT = 20
MIN_IDENTICAL = 25


class CaseStyleError(Exception):
    pass


def _face_count(data: dict) -> int:
    return max(1, int(data.get("face_count") or 1))


def _cache_key(data: dict, face: int) -> str:
    digest = data.get("sha1") or data.get("md5") or "nohash"
    return f"{CACHE_VERSION}-{digest}-{data.get('size')}-{data.get('mtime_ns')}-face{face}.json"


def _glyph_case(name: str | None) -> str | None:
    if not name:
        return None
    base = name.split(".")[0]
    if len(base) == 1 and base.isalpha():
        return "upper" if base.isupper() else "lower"
    for prefix, start in (("uni", 3), ("u", 1)):
        if not base.startswith(prefix):
            continue
        hex_part = base[start:]
        if not 4 <= len(hex_part) <= 6:
            continue
        try:
            codepoint = int(hex_part, 16)
        except ValueError:
            return None
        if 0x41 <= codepoint <= 0x5A:
            return "upper"
        if 0x61 <= codepoint <= 0x7A:
            return "lower"
    return None


def _outline_hash(glyph_set, name: str, cache: dict) -> str:
    if name in cache:
        return cache[name]
    if DecomposingRecordingPen is not None:
        pen = DecomposingRecordingPen(glyph_set)
    else:
        pen = RecordingPen()
    glyph_set[name].draw(pen)
    digest = hashlib.sha1(repr(pen.value).encode("utf-8")).hexdigest()
    cache[name] = digest
    return digest


def _classify(pairs: list, upper_present: int, lower_present: int) -> str:
    both = [item for item in pairs if item["upper"] and item["lower"]]
    identical = [item for item in both if item["same_outline"]]
    same_glyph = [item for item in identical if item["same_glyph"]]
    if upper_present < MIN_PRESENT and lower_present < MIN_PRESENT:
        return "unknown"
    if lower_present == 0 and upper_present >= MIN_PRESENT:
        return "upper-only"
    if upper_present == 0 and lower_present >= MIN_PRESENT:
        return "lower-only"
    if len(both) < MIN_IDENTICAL or len(identical) < MIN_IDENTICAL:
        return "mixed"
    if len(same_glyph) >= MIN_IDENTICAL:
        upper_votes = sum(1 for item in same_glyph if _glyph_case(item["upper"]) == "upper")
        lower_votes = sum(1 for item in same_glyph if _glyph_case(item["upper"]) == "lower")
        if lower_votes > upper_votes:
            return "lower"
        if upper_votes > lower_votes:
            return "upper"
        return "unicase"
    upper_votes = sum(1 for item in identical if _glyph_case(item["upper"]) == "upper")
    lower_votes = sum(1 for item in identical if _glyph_case(item["lower"]) == "lower")
    if upper_votes >= MIN_IDENTICAL and lower_votes >= MIN_IDENTICAL:
        return "unicase"
    if lower_votes == 0 and upper_votes >= MIN_IDENTICAL:
        return "upper"
    if upper_votes == 0 and lower_votes >= MIN_IDENTICAL:
        return "lower"
    return "unicase"


def _result(face: int, style: str, pairs: int, identical: int, same_glyph: int,
            upper_present: int, lower_present: int) -> dict:
    return {
        "face": face,
        "style": style,
        "pairs": pairs,
        "identical": identical,
        "same_glyph": same_glyph,
        "upper_present": upper_present,
        "lower_present": lower_present,
    }


def _read_cache(path: Path) -> dict | None:
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(cached, dict) and cached.get("style"):
        return cached
    return None


def _write_cache(path: Path, result: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + f".{os.getpid()}.tmp")
        temp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)
    except OSError:
        pass


def analyze(data: dict, face: int = 0) -> dict:
    path = fonts.safe_font_path(data["rel_path"])
    if face < 0 or face >= _face_count(data):
        raise CaseStyleError("face 索引超出范围")
    cache_path = CACHE_DIR / _cache_key(data, face)
    cached = _read_cache(cache_path)
    if cached is not None:
        return cached

    collection = None
    font = None
    try:
        if path.suffix.lower() == ".ttc":
            collection = TTCollection(str(path), lazy=True)
            font = collection.fonts[face]
        else:
            font = TTFont(str(path), lazy=True)
        cmap = font.getBestCmap() or {}
        if not cmap:
            result = _result(face, "unknown", 0, 0, 0, 0, 0)
        else:
            glyph_set = font.getGlyphSet()
            outline_cache = {}
            pairs = []
            upper_present = 0
            lower_present = 0
            for letter in LETTERS:
                upper = cmap.get(ord(letter))
                lower = cmap.get(ord(letter.lower()))
                if upper == ".notdef":
                    upper = None
                if lower == ".notdef":
                    lower = None
                if upper:
                    upper_present += 1
                if lower:
                    lower_present += 1
                item = {
                    "letter": letter,
                    "upper": upper,
                    "lower": lower,
                    "same_outline": False,
                    "same_glyph": False,
                }
                if upper and lower:
                    try:
                        upper_hash = _outline_hash(glyph_set, upper, outline_cache)
                        lower_hash = _outline_hash(glyph_set, lower, outline_cache)
                        item["same_outline"] = upper_hash == lower_hash
                        item["same_glyph"] = upper == lower
                    except Exception:
                        item["error"] = True
                pairs.append(item)
            both = [item for item in pairs if item["upper"] and item["lower"]]
            identical = [item for item in both if item["same_outline"]]
            same_glyph = [item for item in identical if item["same_glyph"]]
            style = _classify(pairs, upper_present, lower_present)
            result = _result(
                face, style, len(both), len(identical), len(same_glyph),
                upper_present, lower_present,
            )
        _write_cache(cache_path, result)
        return result
    except CaseStyleError:
        raise
    except Exception as exc:
        raise CaseStyleError(f"字形比较失败: {exc}") from exc
    finally:
        if collection is not None:
            collection.close()
        elif font is not None:
            font.close()
