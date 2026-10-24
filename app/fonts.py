import hashlib
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont

from . import db
from .config import FONT_ROOT, SCAN_EXTENSIONS

log = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pick_name(name_table, ids: list[int]) -> str | None:
    if name_table is None:
        return None
    best = None
    best_score = -1
    for record in name_table.names:
        if record.nameID not in ids:
            continue
        try:
            value = record.toUnicode()
        except Exception:
            continue
        if not value:
            continue
        value = value.strip()
        if not value:
            continue
        score = 0
        if record.nameID == ids[0]:
            score += 100
        if record.platformID == 3:
            score += 20
        if record.langID in (0x409, 0x804):
            score += 10
        if record.platformID == 0:
            score += 5
        if score > best_score:
            best_score = score
            best = value
    return best


def _face_metadata(font, face_index: int) -> dict:
    name_table = font.get("name")
    head = font.get("head")
    family = _pick_name(name_table, [16, 1])
    subfamily = _pick_name(name_table, [17, 2])
    full_name = _pick_name(name_table, [4])
    version = _pick_name(name_table, [5])
    postscript_name = _pick_name(name_table, [6])
    if not version and head is not None:
        revision = getattr(head, "fontRevision", None)
        if revision is not None:
            version = f"{revision:g}" if isinstance(revision, (int, float)) else str(revision)
    glyph_count = None
    try:
        glyph_count = len(font.getGlyphOrder())
    except Exception:
        pass
    units_per_em = None
    if head is not None:
        units_per_em = getattr(head, "unitsPerEm", None)
    return {
        "face_index": face_index,
        "family": family,
        "subfamily": subfamily,
        "full_name": full_name,
        "version": version,
        "postscript_name": postscript_name,
        "glyph_count": glyph_count,
        "units_per_em": units_per_em,
    }


def parse_font(path: Path) -> dict:
    faces: list[dict] = []
    try:
        if path.suffix.lower() == ".ttc":
            collection = TTCollection(str(path), lazy=True)
            try:
                for index, font in enumerate(collection.fonts):
                    faces.append(_face_metadata(font, index))
            finally:
                collection.close()
        else:
            font = TTFont(str(path), lazy=True)
            try:
                faces.append(_face_metadata(font, 0))
            finally:
                font.close()
    except Exception as exc:
        log.warning("font parse failed: %s: %s", path, exc)
        return {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}"[:500],
            "faces": [],
        }
    if not faces:
        return {"status": "error", "error": "字体没有可读取的 face", "faces": []}
    first = faces[0]
    return {
        "status": "ok",
        "error": None,
        "family": first.get("family"),
        "subfamily": first.get("subfamily"),
        "full_name": first.get("full_name"),
        "version": first.get("version"),
        "postscript_name": first.get("postscript_name"),
        "face_count": len(faces),
        "glyph_count": first.get("glyph_count"),
        "units_per_em": first.get("units_per_em"),
        "faces": faces,
    }


def _walk(root: Path):
    try:
        entries = list(os.scandir(root))
    except OSError as exc:
        log.warning("cannot scan %s: %s", root, exc)
        return
    for entry in entries:
        try:
            if entry.is_symlink():
                continue
            if entry.name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=False):
                yield from _walk(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                if Path(entry.name).suffix.lower() in SCAN_EXTENSIONS:
                    yield Path(entry.path)
        except OSError:
            continue


def hash_file(path: Path) -> tuple[str, str, str]:
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            md5.update(chunk)
            sha1.update(chunk)
            sha256.update(chunk)
    return md5.hexdigest(), sha1.hexdigest(), sha256.hexdigest()


def safe_font_path(rel_path: str) -> Path:
    candidate = (FONT_ROOT / rel_path).resolve()
    candidate.relative_to(FONT_ROOT)
    if not candidate.is_file():
        raise FileNotFoundError(rel_path)
    return candidate


class ScanState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.running = False
        self.total = 0
        self.done = 0
        self.errors = 0
        self.current = ""
        self.started_at = None
        self.finished_at = None
        self.error = None

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "running": self.running,
                "total": self.total,
                "done": self.done,
                "errors": self.errors,
                "current": self.current,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "error": self.error,
            }

    def start(self) -> dict:
        with self.lock:
            if self.running:
                return self.snapshot()
            self.running = True
            self.total = 0
            self.done = 0
            self.errors = 0
            self.current = ""
            self.started_at = now_iso()
            self.finished_at = None
            self.error = None
        thread = threading.Thread(target=self._run, name="font-scan", daemon=True)
        thread.start()
        return self.snapshot()

    def _run(self) -> None:
        try:
            self._scan()
        except Exception as exc:
            log.exception("scan failed")
            with self.lock:
                self.error = f"{type(exc).__name__}: {exc}"[:500]
        finally:
            with self.lock:
                self.running = False
                self.finished_at = now_iso()
                self.current = ""


    def _scan(self) -> None:
        if not FONT_ROOT.is_dir():
            raise RuntimeError("字体目录不存在: " + str(FONT_ROOT))
        paths = list(_walk(FONT_ROOT))
        paths.sort(key=lambda item: item.as_posix().lower())
        with self.lock:
            self.total = len(paths)
            self.done = 0
            self.errors = 0
        conn = db.connect()
        try:
            db.reset_present(conn)
            conn.commit()
            for index, path in enumerate(paths, 1):
                rel = path.relative_to(FONT_ROOT).as_posix()
                try:
                    stat = path.stat()
                    existing = conn.execute(
                        "SELECT id, size, mtime_ns, parse_status FROM fonts WHERE rel_path=?",
                        (rel,),
                    ).fetchone()
                    if (
                        existing is not None
                        and existing["size"] == stat.st_size
                        and existing["mtime_ns"] == stat.st_mtime_ns
                        and existing["parse_status"] in ("ok", "error")
                    ):
                        db.mark_seen(conn, int(existing["id"]))
                    else:
                        meta = parse_font(path)
                        if meta.get("status") == "error":
                            with self.lock:
                                self.errors += 1
                        db.upsert_font(
                            conn,
                            {
                                "rel_path": rel,
                                "name": path.name,
                                "ext": path.suffix.lower(),
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
                                "parse_status": meta.get("status", "ok"),
                                "parse_error": meta.get("error"),
                            },
                            meta.get("faces", []),
                        )
                except Exception as exc:
                    log.exception("failed to index %s", rel)
                    with self.lock:
                        self.errors += 1
                    try:
                        stat = path.stat()
                        db.upsert_font(
                            conn,
                            {
                                "rel_path": rel,
                                "name": path.name,
                                "ext": path.suffix.lower(),
                                "size": stat.st_size,
                                "mtime_ns": stat.st_mtime_ns,
                                "parse_status": "error",
                                "parse_error": f"{type(exc).__name__}: {exc}"[:500],
                            },
                            [],
                        )
                    except Exception:
                        pass
                if index % 10 == 0:
                    conn.commit()
                with self.lock:
                    self.done = index
                    self.current = rel
            conn.commit()
        finally:
            conn.close()


scan_state = ScanState()


def start_scan() -> dict:
    return scan_state.start()
