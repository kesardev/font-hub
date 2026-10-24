import hashlib
import os
import shutil
import threading
import uuid
from pathlib import Path

from . import db, fonts
from .config import FONT_ROOT, SCAN_EXTENSIONS, STATE_DIR

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "1024"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
TMP_DIR = STATE_DIR / "upload-tmp"
_FINALIZE_LOCK = threading.Lock()


class UploadError(Exception):
    pass


class TooLarge(UploadError):
    pass


def normalize_rel(value: str) -> str:
    if "\x00" in value:
        raise UploadError("路径包含非法字符")
    value = value.replace("\\", "/").strip()
    parts = []
    for part in value.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise UploadError("路径不能包含 ..")
        if len(part) > 255:
            raise UploadError("路径片段过长")
        parts.append(part)
    return "/".join(parts)


def resolve_target(folder: str, name: str) -> tuple[str, Path]:
    base = normalize_rel(folder)
    rel = normalize_rel((base + "/" + name) if base else name)
    if not rel:
        raise UploadError("文件名为空")
    candidate = (FONT_ROOT / rel).resolve()
    try:
        candidate.relative_to(FONT_ROOT)
    except ValueError as exc:
        raise UploadError("目标路径越界") from exc
    if candidate == FONT_ROOT:
        raise UploadError("目标路径无效")
    return rel, candidate


def relative_name(folder: str, rel: str) -> str:
    base = normalize_rel(folder)
    if not base:
        return rel
    prefix = base + "/"
    return rel[len(prefix):] if rel.startswith(prefix) else rel


def suggest_name(
    conn,
    folder: str,
    name: str,
    reserved: set[str],
) -> tuple[str, Path]:
    rel, path = resolve_target(folder, name)
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for index in range(1, 1000):
        candidate = parent / f"{stem} ({index}){suffix}"
        candidate_rel = candidate.relative_to(FONT_ROOT).as_posix()
        if candidate_rel in reserved:
            continue
        exists = conn.execute(
            "SELECT 1 FROM fonts WHERE rel_path=? AND present=1", (candidate_rel,)
        ).fetchone()
        if exists is None and not candidate.exists():
            return candidate_rel, candidate
    raise UploadError("无法生成可用文件名")


def preflight(conn, folder: str, files: list[dict]) -> list[dict]:
    base = normalize_rel(folder)
    reserved: set[str] = set()
    results = []
    for item in files:
        name = str(item.get("name", ""))
        size = int(item.get("size", 0) or 0)
        entry = {
            "name": name,
            "size": size,
            "status": "ok",
            "target_path": None,
            "target_name": None,
            "suggested_path": None,
            "suggested_name": None,
            "existing": None,
            "error": None,
        }
        try:
            rel, path = resolve_target(base, name)
            entry["target_path"] = rel
            entry["target_name"] = relative_name(base, rel)
            if path.suffix.lower() not in SCAN_EXTENSIONS:
                raise UploadError("不支持的字体格式")
            if size <= 0:
                raise UploadError("空文件")
            existing = conn.execute(
                "SELECT id, rel_path, size, mtime_ns, md5, sha1, sha256 "
                "FROM fonts WHERE rel_path=? AND present=1",
                (rel,),
            ).fetchone()
            conflict = existing is not None or rel in reserved or path.exists()
            if conflict:
                suggested_rel, suggested_path = suggest_name(conn, base, name, reserved)
                entry["status"] = "conflict"
                entry["existing"] = dict(existing) if existing else None
                entry["suggested_path"] = suggested_rel
                entry["suggested_name"] = relative_name(base, suggested_rel)
                reserved.add(suggested_rel)
            else:
                reserved.add(rel)
        except UploadError as exc:
            entry["status"] = "invalid"
            entry["error"] = str(exc)
        results.append(entry)
    return results


async def save_stream(request, folder: str, name: str) -> tuple[Path, int, str, str, str]:
    rel, final = resolve_target(folder, name)
    if final.suffix.lower() not in SCAN_EXTENSIONS:
        raise UploadError("不支持的字体格式")
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = TMP_DIR / (uuid.uuid4().hex + ".part")
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    size = 0
    try:
        with tmp.open("wb") as handle:
            async for chunk in request.stream():
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise TooLarge(f"文件超过 {MAX_UPLOAD_MB} MB 限制")
                handle.write(chunk)
                md5.update(chunk)
                sha1.update(chunk)
                sha256.update(chunk)
        if size == 0:
            raise UploadError("空文件")
        return tmp, size, md5.hexdigest(), sha1.hexdigest(), sha256.hexdigest()
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _find_duplicate(conn, size: int, sha256: str, sha1: str) -> dict | None:
    row = conn.execute(
        "SELECT id, rel_path FROM fonts WHERE present=1 AND size=? AND "
        "((sha256 IS NOT NULL AND sha256=?) OR (sha256 IS NULL AND sha1=?)) LIMIT 1",
        (size, sha256, sha1),
    ).fetchone()
    if row is not None:
        return dict(row)
    rows = conn.execute(
        "SELECT id, rel_path FROM fonts WHERE present=1 AND size=? "
        "AND sha256 IS NULL AND sha1 IS NULL",
        (size,),
    ).fetchall()
    for candidate in rows:
        try:
            path = fonts.safe_font_path(candidate["rel_path"])
            md5c, sha1c, sha256c = fonts.hash_file(path)
            db.update_hashes(conn, candidate["id"], md5c, sha1c, sha256c)
            conn.commit()
            if sha256c == sha256:
                return dict(candidate)
        except Exception:
            fonts.log.warning("duplicate check failed: %s", candidate["rel_path"], exc_info=True)
    return None


def finalize(
    tmp: Path,
    folder: str,
    name: str,
    size: int,
    md5: str,
    sha1: str,
    sha256: str,
) -> dict:
    base = normalize_rel(folder)
    rel, final = resolve_target(base, name)
    with _FINALIZE_LOCK:
        conn = db.connect()
        try:
            duplicate = _find_duplicate(conn, size, sha256, sha1)
            if duplicate is not None:
                tmp.unlink(missing_ok=True)
                return {
                    "status": "skipped_duplicate",
                    "existing_id": duplicate["id"],
                    "existing_path": duplicate["rel_path"],
                    "name": name,
                    "size": size,
                    "sha256": sha256,
                }
            existing = conn.execute(
                "SELECT id, rel_path FROM fonts WHERE rel_path=? AND present=1", (rel,)
            ).fetchone()
            if existing is not None or final.exists():
                suggested_rel, suggested_path = suggest_name(conn, base, name, set())
                tmp.unlink(missing_ok=True)
                return {
                    "status": "conflict",
                    "existing_path": rel,
                    "suggested_path": suggested_rel,
                    "suggested_name": relative_name(base, suggested_rel),
                    "name": name,
                }
            final.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(tmp, final)
            except OSError:
                shutil.copyfile(tmp, final)
                tmp.unlink(missing_ok=True)
            try:
                os.chmod(final, 0o644)
            except OSError:
                pass
            stat = final.stat()
            meta = fonts.parse_font(final)
            font_id = db.upsert_font(
                conn,
                {
                    "rel_path": rel,
                    "name": final.name,
                    "ext": final.suffix.lower(),
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "family": meta.get("family"),
                    "subfamily": meta.get("subfamily"),
                    "full_name": meta.get("full_name"),
                    "version": meta.get("version"),
                    "postscript_name": meta.get("postscript_name"),
                    "face_count": meta.get("face_count", 1),
                    "glyph_count": meta.get("glyph_count"),
                    "units_per_em": meta.get("units_per_em"),
                    "md5": md5,
                    "sha1": sha1,
                    "sha256": sha256,
                    "parse_status": meta.get("status", "ok"),
                    "parse_error": meta.get("error"),
                },
                meta.get("faces", []),
            )
            conn.commit()
            return {
                "status": "uploaded",
                "id": font_id,
                "rel_path": rel,
                "name": final.name,
                "size": stat.st_size,
                "md5": md5,
                "sha1": sha1,
                "sha256": sha256,
            }
        finally:
            conn.close()
