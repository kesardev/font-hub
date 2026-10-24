import os
import unicodedata
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph

from . import fonts
from .config import STATE_DIR

CACHE_DIR = STATE_DIR / "cache" / "previews"
PREVIEW_CACHE_MAX_BYTES = max(0, int(os.environ.get("PREVIEW_CACHE_MAX_MB", "512"))) * 1024 * 1024


class PreviewError(Exception):
    pass


def _media_type(suffix: str) -> str:
    return {
        ".ttf": "font/ttf",
        ".otf": "font/otf",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
    }.get(suffix, "application/octet-stream")


def _face_count(data: dict) -> int:
    return max(1, int(data.get("face_count") or 1))


def _cache_key(data: dict, face: int) -> str:
    digest = data.get("sha1") or data.get("md5") or "nohash"
    return f"{digest}-{data.get('size')}-{data.get('mtime_ns')}-face{face}"


def _prune_preview_cache(keep: Path) -> None:
    if PREVIEW_CACHE_MAX_BYTES <= 0:
        return
    files = []
    total = 0
    for item in CACHE_DIR.iterdir():
        if not item.is_file():
            continue
        try:
            stat = item.stat()
        except OSError:
            continue
        total += stat.st_size
        if item != keep:
            files.append((stat.st_mtime, stat.st_size, item))
    if total <= PREVIEW_CACHE_MAX_BYTES:
        return
    files.sort(key=lambda entry: entry[0])
    for _, size, item in files:
        if total <= PREVIEW_CACHE_MAX_BYTES:
            break
        try:
            item.unlink()
            total -= size
        except OSError:
            continue


def _sanitize_glyf(font) -> int:
    try:
        glyf = font["glyf"]
    except KeyError:
        return 0
    fixed = 0
    for name in list(glyf.glyphs.keys()):
        glyph = glyf.glyphs[name]
        try:
            glyph.expand(glyf)
        except Exception:
            empty = Glyph()
            empty.numberOfContours = 0
            glyf.glyphs[name] = empty
            fixed += 1
    return fixed


def get_preview_font(data: dict, face: int = 0) -> tuple[Path, str]:
    path = fonts.safe_font_path(data["rel_path"])
    if face < 0 or face >= _face_count(data):
        raise PreviewError("face 索引超出范围")
    suffix = path.suffix.lower()
    if suffix != ".ttc":
        return path, _media_type(suffix)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    base = CACHE_DIR / _cache_key(data, face)
    for ext in (".otf", ".ttf"):
        cached = base.with_suffix(ext)
        if cached.is_file() and cached.stat().st_size > 0:
            return cached, _media_type(ext)
    try:
        font = TTFont(str(path), fontNumber=face, lazy=True)
        try:
            _sanitize_glyf(font)
            ext = ".otf" if "CFF " in font else ".ttf"
            out = base.with_suffix(ext)
            font.save(str(out))
            _prune_preview_cache(out)
            return out, _media_type(ext)
        finally:
            font.close()
    except Exception as exc:
        raise PreviewError(f"TTC 抽面失败: {exc}") from exc


def coverage(data: dict, face: int, texts: dict) -> dict:
    path = fonts.safe_font_path(data["rel_path"])
    if face < 0 or face >= _face_count(data):
        raise PreviewError("face 索引超出范围")
    collection = None
    font = None
    try:
        if path.suffix.lower() == ".ttc":
            collection = TTCollection(str(path), lazy=True)
            font = collection.fonts[face]
        else:
            font = TTFont(str(path), lazy=True)
        cmap = font.getBestCmap() or {}
        glyph_order = set(font.getGlyphOrder()) if cmap else set()
        results = {}
        for key, value in texts.items():
            text = str(value or "")[:2000]
            total = 0
            missing_total = 0
            missing = []
            seen = set()
            for ch in text:
                cp = ord(ch)
                if ch.isspace() or unicodedata.category(ch) in ("Cc", "Cf"):
                    continue
                if 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF:
                    continue
                total += 1
                glyph_name = cmap.get(cp)
                if not glyph_name or glyph_name == ".notdef" or glyph_name not in glyph_order:
                    missing_total += 1
                    if ch not in seen:
                        missing.append({"char": ch, "codepoint": f"U+{cp:04X}"})
                        seen.add(ch)
            results[key] = {
                "total": total,
                "missing_count": len(missing),
                "missing_occurrences": missing_total,
                "missing": missing,
                "coverage": round((total - missing_total) / total, 4) if total else 1.0,
            }
        return {"face": face, "no_cmap": not bool(cmap), "results": results}
    except PreviewError:
        raise
    except Exception as exc:
        raise PreviewError(f"缺字检测失败: {exc}") from exc
    finally:
        if collection is not None:
            collection.close()
        elif font is not None:
            font.close()
