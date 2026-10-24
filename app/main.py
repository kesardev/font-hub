import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import case_style, db, fonts, hashing, preview, preview_settings, project_settings, recycle, settings_store, upload
from .config import (
    AUTO_SCAN,
    FONT_ROOT,
    PAGE_SIZE_DEFAULT,
    PAGE_SIZE_MAX,
    STATIC_DIR,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("font-hub")

def _read_version() -> str:
    value = os.environ.get("APP_VERSION", "").strip()
    if value:
        return value
    try:
        return (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip() or "dev"
    except OSError:
        return "dev"


APP_VERSION = _read_version()
BUILD_COMMIT = os.environ.get("BUILD_COMMIT", "").strip()
BUILD_TIME = os.environ.get("BUILD_TIME", "").strip()


def _purge_recycle_once() -> None:
    conn = db.connect()
    try:
        recycle.purge_expired(conn)
    finally:
        conn.close()


async def _recycle_purge_loop() -> None:
    while True:
        await asyncio.sleep(6 * 3600)
        try:
            await run_in_threadpool(_purge_recycle_once)
        except Exception:
            log.exception("scheduled recycle purge failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db.init_db()
    except Exception:
        log.exception("database init failed")
    try:
        conn = db.connect()
        try:
            settings_store.load(conn)
        finally:
            conn.close()
    except Exception:
        log.exception("settings migration failed")
    try:
        await run_in_threadpool(_purge_recycle_once)
    except Exception:
        log.exception("recycle purge failed")
    purge_task = asyncio.create_task(_recycle_purge_loop())
    if AUTO_SCAN:
        fonts.start_scan()
    try:
        yield
    finally:
        purge_task.cancel()
        try:
            await purge_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="FontHub", version="0.2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    db_status = "ok"
    count = 0
    try:
        conn = db.connect()
        try:
            count = db.count_present(conn)
        finally:
            conn.close()
    except Exception as exc:
        db_status = f"{type(exc).__name__}: {exc}"
    ok = db_status == "ok" and FONT_ROOT.is_dir()
    return {
        "status": "ok" if ok else "degraded",
        "version": APP_VERSION,
        "font_root": str(FONT_ROOT),
        "font_root_exists": FONT_ROOT.is_dir(),
        "database": db_status,
        "fonts": count,
        "scan": fonts.scan_state.snapshot(),
        "hash": hashing.hash_state.snapshot(),
    }


@app.get("/api/version")
def version_info():
    return {
        "version": APP_VERSION,
        "commit": BUILD_COMMIT,
        "build_time": BUILD_TIME,
    }


@app.get("/api/stats")
def stats():
    conn = db.connect()
    try:
        return db.get_stats(conn)
    finally:
        conn.close()


@app.get("/api/tree")
def tree():
    conn = db.connect()
    try:
        return db.build_tree(conn)
    finally:
        conn.close()


@app.get("/api/fonts")
def list_fonts(
    path: str = "",
    q: str = "",
    sort: str = "rel_path",
    direction: str = "asc",
    page: int = Query(1, ge=1),
    page_size: int = Query(PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    duplicates: bool = False,
):
    conn = db.connect()
    try:
        return db.list_fonts(
            conn,
            path=path,
            q=q,
            sort=sort,
            direction=direction,
            page=page,
            page_size=page_size,
            duplicates=duplicates,
        )
    finally:
        conn.close()


@app.get("/api/fonts/{font_id}")
def font_detail(font_id: int):
    conn = db.connect()
    try:
        data = db.get_font(conn, font_id)
        if data is None:
            raise HTTPException(status_code=404, detail="字体不存在")
        hash_error = None
        if not data.get("md5") or not data.get("sha1") or not data.get("sha256"):
            try:
                path = fonts.safe_font_path(data["rel_path"])
                md5, sha1, sha256 = fonts.hash_file(path)
                db.update_hashes(conn, font_id, md5, sha1, sha256)
                conn.commit()
                data["md5"] = md5
                data["sha1"] = sha1
                data["sha256"] = sha256
            except Exception as exc:
                hash_error = f"{type(exc).__name__}: {exc}"
        data["hash_error"] = hash_error
        return data
    finally:
        conn.close()


@app.get('/api/fonts/{font_id}/download')
def download_font(font_id: int):
    conn = db.connect()
    try:
        data = db.get_font(conn, font_id)
        if data is None:
            raise HTTPException(status_code=404, detail='字体不存在')
        path = fonts.safe_font_path(data['rel_path'])
        if not path.is_file():
            raise HTTPException(status_code=404, detail='字体文件不存在')
        return FileResponse(
            path,
            media_type='application/octet-stream',
            filename=data['name'],
            headers={'Cache-Control': 'no-store'},
        )
    finally:
        conn.close()


class PreflightFile(BaseModel):
    name: str
    size: int = 0


class PreflightBody(BaseModel):
    path: str = ""
    files: list[PreflightFile]


@app.post("/api/upload/preflight")
def upload_preflight(body: PreflightBody):
    if fonts.scan_state.snapshot()["running"]:
        raise HTTPException(status_code=409, detail="扫描进行中，请稍后再上传")
    conn = db.connect()
    try:
        return {
            "files": upload.preflight(
                conn,
                body.path,
                [item.model_dump() for item in body.files],
            )
        }
    finally:
        conn.close()


@app.post("/api/upload")
async def upload_file(request: Request, path: str = "", name: str = ""):
    if fonts.scan_state.snapshot()["running"]:
        raise HTTPException(status_code=409, detail="扫描进行中，请稍后再上传")
    length = request.headers.get("content-length")
    if length and int(length) > upload.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"文件超过 {upload.MAX_UPLOAD_MB} MB 限制")
    tmp = None
    try:
        tmp, size, md5, sha1, sha256 = await upload.save_stream(request, path, name)
        return await run_in_threadpool(
            upload.finalize,
            tmp,
            path,
            name,
            size,
            md5,
            sha1,
            sha256,
        )
    except upload.TooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except upload.UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


@app.get("/api/hash/estimate")
def hash_estimate():
    conn = db.connect()
    try:
        return hashing.estimate(conn)
    finally:
        conn.close()


@app.post("/api/hash/start")
def hash_start():
    try:
        return hashing.hash_state.start()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/hash/status")
def hash_status():
    return hashing.hash_state.snapshot()


@app.post("/api/hash/stop")
def hash_stop():
    return hashing.hash_state.stop()


@app.post("/api/scan")
def scan():
    if hashing.hash_state.snapshot()["running"]:
        raise HTTPException(status_code=409, detail="哈希计算进行中，请稍后再扫描")
    return fonts.start_scan()


@app.get("/api/scan/status")
def scan_status():
    return fonts.scan_state.snapshot()


class PreviewSettingsBody(BaseModel):
    preview_cn: str = ""
    preview_en: str = ""
    preview_punct: str = ""
    preview_special: str = ""


class ProjectSettingsBody(BaseModel):
    recycle_days: int = 30


@app.get("/api/settings/project")
def get_project_settings():
    conn = db.connect()
    try:
        return project_settings.get_project_settings(conn)
    finally:
        conn.close()


@app.put("/api/settings/project")
def save_project_settings(body: ProjectSettingsBody):
    conn = db.connect()
    try:
        try:
            return project_settings.save_project_settings(conn, body.recycle_days)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@app.get("/api/settings/preview")
def get_preview_settings():
    conn = db.connect()
    try:
        return preview_settings.get_preview_settings(conn)
    finally:
        conn.close()


@app.put("/api/settings/preview")
def save_preview_settings(body: PreviewSettingsBody):
    conn = db.connect()
    try:
        return preview_settings.save_preview_settings(conn, body.model_dump())
    finally:
        conn.close()


@app.post("/api/settings/preview/reset")
def reset_preview_settings():
    conn = db.connect()
    try:
        return preview_settings.reset_preview_settings(conn)
    finally:
        conn.close()


class CoverageBody(BaseModel):
    face: int = 0
    texts: dict[str, str] = {}


def _ensure_mutation_allowed() -> None:
    if fonts.scan_state.snapshot()["running"]:
        raise HTTPException(status_code=409, detail="扫描进行中，请稍后再操作")
    if hashing.hash_state.snapshot()["running"]:
        raise HTTPException(status_code=409, detail="哈希计算进行中，请稍后再操作")


@app.delete("/api/fonts/{font_id}")
def delete_font(font_id: int, permanent: bool = False):
    _ensure_mutation_allowed()
    conn = db.connect()
    try:
        data = db.get_font(conn, font_id)
        if data is None:
            raise HTTPException(status_code=404, detail="字体不存在")
        try:
            return recycle.delete_font(conn, data, permanent)
        except recycle.RecycleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="字体文件不存在") from exc
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"文件操作失败: {exc}") from exc
    finally:
        conn.close()


class BatchDeleteBody(BaseModel):
    ids: list[int] = []
    permanent: bool = False


@app.post("/api/fonts/batch-delete")
def batch_delete_fonts(body: BatchDeleteBody):
    _ensure_mutation_allowed()
    ids = list(dict.fromkeys(int(item) for item in body.ids))
    if not ids:
        raise HTTPException(status_code=400, detail="没有选择字体")
    if len(ids) > 500:
        raise HTTPException(status_code=400, detail="单次最多处理 500 个字体")
    conn = db.connect()
    stats = {"recycled": 0, "deleted": 0, "failed": []}
    try:
        for font_id in ids:
            data = db.get_font(conn, font_id)
            if data is None:
                stats["failed"].append({"id": font_id, "error": "字体不存在"})
                continue
            try:
                result = recycle.delete_font(conn, data, body.permanent)
                if result["mode"] == "recycled":
                    stats["recycled"] += 1
                else:
                    stats["deleted"] += 1
            except FileNotFoundError:
                conn.rollback()
                stats["failed"].append({"id": font_id, "error": "字体文件不存在"})
            except Exception as exc:
                conn.rollback()
                stats["failed"].append({"id": font_id, "error": str(exc)})
        return {"permanent": body.permanent, **stats}
    finally:
        conn.close()


@app.get("/api/recycle")
def get_recycle():
    conn = db.connect()
    try:
        purged = []
        if not fonts.scan_state.snapshot()["running"]:
            purged = recycle.purge_expired(conn)
        data = recycle.list_items(conn)
        data["purged"] = len(purged)
        return data
    finally:
        conn.close()


@app.post("/api/recycle/{item_id}/restore")
def restore_recycle(item_id: int):
    _ensure_mutation_allowed()
    conn = db.connect()
    try:
        try:
            return recycle.restore_item(conn, item_id)
        except recycle.RecycleConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except recycle.RecycleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"文件操作失败: {exc}") from exc
    finally:
        conn.close()


@app.delete("/api/recycle/{item_id}")
def delete_recycle(item_id: int):
    conn = db.connect()
    try:
        try:
            return recycle.permanent_delete_item(conn, item_id)
        except recycle.RecycleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@app.get("/api/fonts/{font_id}/preview")
def preview_font(font_id: int, face: int = 0):
    conn = db.connect()
    try:
        data = db.get_font(conn, font_id)
        if data is None:
            raise HTTPException(status_code=404, detail="字体不存在")
        try:
            path, media_type = preview.get_preview_font(data, face)
        except preview.PreviewError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return FileResponse(
            path,
            media_type=media_type,
            headers={"Cache-Control": "private, max-age=3600"},
        )
    finally:
        conn.close()


@app.post("/api/fonts/{font_id}/coverage")
def font_coverage(font_id: int, body: CoverageBody):
    conn = db.connect()
    try:
        data = db.get_font(conn, font_id)
        if data is None:
            raise HTTPException(status_code=404, detail="字体不存在")
        try:
            return preview.coverage(data, body.face, body.texts)
        except preview.PreviewError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@app.get("/api/fonts/{font_id}/case-style")
def font_case_style(font_id: int, face: int = 0):
    conn = db.connect()
    try:
        data = db.get_font(conn, font_id)
        if data is None:
            raise HTTPException(status_code=404, detail="字体不存在")
        try:
            return case_style.analyze(data, face)
        except case_style.CaseStyleError as exc:
            return {"face": face, "style": "unknown", "error": str(exc)}
    finally:
        conn.close()
