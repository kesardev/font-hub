import math
import threading

from . import db, fonts

SPEED_BYTES_PER_SEC = 200 * 1024 * 1024
CONFIRM_BYTES = 2 * 1024 * 1024 * 1024
CONFIRM_SECONDS = 30


class HashState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.running = False
        self.total = 0
        self.done = 0
        self.total_bytes = 0
        self.done_bytes = 0
        self.errors = 0
        self.current = ""
        self.started_at = None
        self.finished_at = None
        self.error = None
        self.cancel_requested = False

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "running": self.running,
                "total": self.total,
                "done": self.done,
                "total_bytes": self.total_bytes,
                "done_bytes": self.done_bytes,
                "errors": self.errors,
                "current": self.current,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "error": self.error,
                "cancel_requested": self.cancel_requested,
            }

    def start(self) -> dict:
        if fonts.scan_state.snapshot()["running"]:
            raise RuntimeError("扫描进行中，请等扫描完成后再计算哈希")
        with self.lock:
            if self.running:
                return self.snapshot()
            self.running = True
            self.total = 0
            self.done = 0
            self.total_bytes = 0
            self.done_bytes = 0
            self.errors = 0
            self.current = ""
            self.started_at = fonts.now_iso()
            self.finished_at = None
            self.error = None
            self.cancel_requested = False
        thread = threading.Thread(target=self._run, name="font-hash", daemon=True)
        thread.start()
        return self.snapshot()

    def stop(self) -> dict:
        with self.lock:
            if self.running:
                self.cancel_requested = True
            return self.snapshot()

    def _run(self) -> None:
        try:
            self._hash_all()
        except Exception as exc:
            fonts.log.exception("hash job failed")
            with self.lock:
                self.error = f"{type(exc).__name__}: {exc}"[:500]
        finally:
            with self.lock:
                self.running = False
                self.finished_at = fonts.now_iso()
                self.current = ""

    def _hash_all(self) -> None:
        conn = db.connect()
        try:
            rows = conn.execute(
                "SELECT id, rel_path, size FROM fonts WHERE present=1 "
                "AND (sha256 IS NULL OR md5 IS NULL OR sha1 IS NULL) ORDER BY size"
            ).fetchall()
            total_bytes = sum(row["size"] or 0 for row in rows)
            with self.lock:
                self.total = len(rows)
                self.total_bytes = total_bytes
            for index, row in enumerate(rows, 1):
                with self.lock:
                    if self.cancel_requested:
                        break
                    self.current = row["rel_path"]
                try:
                    path = fonts.safe_font_path(row["rel_path"])
                    md5, sha1, sha256 = fonts.hash_file(path)
                    db.update_hashes(conn, row["id"], md5, sha1, sha256)
                except Exception:
                    fonts.log.exception("hash failed: %s", row["rel_path"])
                    with self.lock:
                        self.errors += 1
                with self.lock:
                    self.done = index
                    self.done_bytes += row["size"] or 0
                if index % 10 == 0:
                    conn.commit()
            conn.commit()
        finally:
            conn.close()


def estimate(conn) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS files, COALESCE(SUM(size), 0) AS bytes FROM fonts "
        "WHERE present=1 AND (sha256 IS NULL OR md5 IS NULL OR sha1 IS NULL)"
    ).fetchone()
    files = row["files"]
    total_bytes = row["bytes"]
    seconds = max(1, math.ceil(total_bytes / SPEED_BYTES_PER_SEC)) if total_bytes else 0
    return {
        "files": files,
        "bytes": total_bytes,
        "estimated_seconds": seconds,
        "needs_confirm": total_bytes >= CONFIRM_BYTES or seconds >= CONFIRM_SECONDS,
        "confirm_bytes": CONFIRM_BYTES,
        "confirm_seconds": CONFIRM_SECONDS,
    }


hash_state = HashState()
