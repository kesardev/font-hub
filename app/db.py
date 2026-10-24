import sqlite3

from .config import DB_PATH, STATE_DIR


SCHEMA = """
CREATE TABLE IF NOT EXISTS fonts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rel_path TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    ext TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    created_ns INTEGER,
    family TEXT,
    subfamily TEXT,
    full_name TEXT,
    version TEXT,
    postscript_name TEXT,
    face_count INTEGER NOT NULL DEFAULT 1,
    glyph_count INTEGER,
    units_per_em INTEGER,
    md5 TEXT,
    sha1 TEXT,
    sha256 TEXT,
    parse_status TEXT NOT NULL DEFAULT 'pending',
    parse_error TEXT,
    present INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS faces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    font_id INTEGER NOT NULL REFERENCES fonts(id) ON DELETE CASCADE,
    face_index INTEGER NOT NULL,
    family TEXT,
    subfamily TEXT,
    full_name TEXT,
    version TEXT,
    postscript_name TEXT,
    glyph_count INTEGER,
    UNIQUE(font_id, face_index)
);

CREATE INDEX IF NOT EXISTS idx_fonts_present ON fonts(present);
CREATE INDEX IF NOT EXISTS idx_fonts_family ON fonts(family);
CREATE INDEX IF NOT EXISTS idx_faces_font ON faces(font_id, face_index);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recycle_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    font_id INTEGER NOT NULL,
    rel_path TEXT NOT NULL,
    name TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha1 TEXT,
    storage_key TEXT NOT NULL UNIQUE,
    deleted_at TEXT NOT NULL,
    expires_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_recycle_expires ON recycle_items(expires_at);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma journal_mode=wal")
    conn.execute("pragma foreign_keys=on")
    conn.execute("pragma busy_timeout=30000")
    return conn


def init_db() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        columns = {row["name"] for row in conn.execute("pragma table_info(fonts)")}
        if "sha256" not in columns:
            conn.execute("alter table fonts add column sha256 text")
        conn.execute("create index if not exists idx_fonts_sha256 on fonts(sha256)")
        if "created_ns" not in columns:
            conn.execute("alter table fonts add column created_ns integer")


def reset_present(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE fonts SET present=0")


def mark_seen(conn: sqlite3.Connection, font_id: int) -> None:
    conn.execute(
        "UPDATE fonts SET present=1, last_seen=CURRENT_TIMESTAMP WHERE id=?",
        (font_id,),
    )


def set_created(conn: sqlite3.Connection, font_id: int, created_ns: int | None) -> None:
    conn.execute('UPDATE fonts SET created_ns=? WHERE id=?', (created_ns, font_id))


def upsert_font(conn: sqlite3.Connection, data: dict, faces: list[dict]) -> int:
    row = conn.execute(
        """
        INSERT INTO fonts (
            rel_path, name, ext, size, mtime_ns, created_ns, family, subfamily, full_name,
            version, postscript_name, face_count, glyph_count, units_per_em,
            md5, sha1, sha256, parse_status, parse_error,
            present, last_seen, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(rel_path) DO UPDATE SET
            name=excluded.name,
            ext=excluded.ext,
            size=excluded.size,
            mtime_ns=excluded.mtime_ns,
            created_ns=excluded.created_ns,
            family=excluded.family,
            subfamily=excluded.subfamily,
            full_name=excluded.full_name,
            version=excluded.version,
            postscript_name=excluded.postscript_name,
            face_count=excluded.face_count,
            glyph_count=excluded.glyph_count,
            units_per_em=excluded.units_per_em,
            md5=excluded.md5,
            sha1=excluded.sha1,
            sha256=excluded.sha256,
            parse_status=excluded.parse_status,
            parse_error=excluded.parse_error,
            present=1,
            last_seen=CURRENT_TIMESTAMP,
            updated_at=CURRENT_TIMESTAMP
        RETURNING id
        """,
        (
            data["rel_path"], data["name"], data["ext"], data["size"], data["mtime_ns"],
            data.get("created_ns"),
            data.get("family"), data.get("subfamily"), data.get("full_name"),
            data.get("version"), data.get("postscript_name"), data.get("face_count", 1),
            data.get("glyph_count"), data.get("units_per_em"),
            data.get("md5"), data.get("sha1"), data.get("sha256"),
            data.get("parse_status", "ok"), data.get("parse_error"),
        ),
    ).fetchone()
    font_id = int(row["id"])
    conn.execute("DELETE FROM faces WHERE font_id=?", (font_id,))
    for face in faces:
        conn.execute(
            """
            INSERT INTO faces (
                font_id, face_index, family, subfamily, full_name, version,
                postscript_name, glyph_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                font_id, face.get("face_index", 0), face.get("family"),
                face.get("subfamily"), face.get("full_name"), face.get("version"),
                face.get("postscript_name"), face.get("glyph_count"),
            ),
        )
    return font_id


def get_font(conn: sqlite3.Connection, font_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM fonts WHERE id=? AND present=1", (font_id,)
    ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["faces"] = [
        dict(face)
        for face in conn.execute(
            """
            SELECT face_index, family, subfamily, full_name, version,
                   postscript_name, glyph_count
            FROM faces WHERE font_id=? ORDER BY face_index
            """,
            (font_id,),
        )
    ]
    return data


def _like(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


SORT_COLUMNS = {
    "name": "f.name COLLATE NOCASE",
    "rel_path": "f.rel_path COLLATE NOCASE",
    "size": "f.size",
    "family": "COALESCE(f.family, '') COLLATE NOCASE",
    "version": "COALESCE(f.version, '') COLLATE NOCASE",
    "mtime_ns": "f.mtime_ns",
    "created_ns": "f.created_ns",
    "ext": "f.ext COLLATE NOCASE",
    "face_count": "f.face_count",
}


def list_fonts(
    conn: sqlite3.Connection,
    path: str = "",
    q: str = "",
    sort: str = "rel_path",
    direction: str = "asc",
    page: int = 1,
    page_size: int = 100,
    duplicates: bool = False,
) -> dict:
    where = ["f.present=1"]
    params: list = []
    if path:
        where.append("f.rel_path LIKE ? ESCAPE '!'")
        params.append(_like(path) + "/%")
    if q:
        needle = "%" + _like(q) + "%"
        where.append(
            "(f.name LIKE ? ESCAPE '!' OR f.rel_path LIKE ? ESCAPE '!' OR "
            "COALESCE(f.family, '') LIKE ? ESCAPE '!' OR "
            "COALESCE(f.full_name, '') LIKE ? ESCAPE '!' OR "
            "COALESCE(f.version, '') LIKE ? ESCAPE '!')"
        )
        params.extend([needle] * 5)
    if duplicates:
        where.append("COALESCE(f.sha256, f.sha1) IS NOT NULL")
        where.append(
            "EXISTS (SELECT 1 FROM fonts f2 WHERE f2.present=1 "
            "AND f2.size=f.size AND COALESCE(f2.sha256,f2.sha1)=COALESCE(f.sha256,f.sha1) "
            "AND f2.id<>f.id)"
        )
    where_sql = " AND ".join(where)
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM fonts f WHERE " + where_sql, params
    ).fetchone()["n"]
    page = max(1, int(page))
    page_size = max(1, min(500, int(page_size)))
    offset = (page - 1) * page_size
    if duplicates:
        order_sql = "f.size ASC, COALESCE(f.sha256, f.sha1) ASC, f.rel_path COLLATE NOCASE ASC"
    else:
        order = SORT_COLUMNS.get(sort, SORT_COLUMNS["rel_path"])
        direction_sql = "DESC" if str(direction).lower() == "desc" else "ASC"
        order_sql = order + " " + direction_sql + ", f.rel_path COLLATE NOCASE ASC"
    rows = conn.execute(
        "SELECT f.id, f.rel_path, f.name, f.ext, f.size, f.mtime_ns, f.created_ns, f.family, f.subfamily, "
        "f.version, f.face_count, f.glyph_count, f.parse_status, f.parse_error, "
        "CASE WHEN COALESCE(f.sha256, f.sha1) IS NULL THEN 1 ELSE "
        "(SELECT COUNT(*) FROM fonts f2 WHERE f2.present=1 AND f2.size=f.size "
        "AND COALESCE(f2.sha256,f2.sha1)=COALESCE(f.sha256,f.sha1)) END AS duplicate_count, "
        "CASE WHEN COALESCE(f.sha256, f.sha1) IS NULL THEN 0 ELSE "
        "ROW_NUMBER() OVER (PARTITION BY f.size, COALESCE(f.sha256,f.sha1) "
        "ORDER BY f.rel_path COLLATE NOCASE ASC) - 1 END AS duplicate_index "
        "FROM fonts f WHERE " + where_sql + " ORDER BY " + order_sql + " LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ).fetchall()
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "duplicates": duplicates,
    }


def build_tree(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT rel_path, size FROM fonts WHERE present=1").fetchall()
    root = {"name": "全部", "path": "", "count": 0, "size": 0, "children": {}}
    for row in rows:
        rel = row["rel_path"]
        size = row["size"] or 0
        root["count"] += 1
        root["size"] += size
        node = root
        for part in rel.split("/")[:-1]:
            child = node["children"].setdefault(
                part,
                {"name": part, "path": "", "count": 0, "size": 0, "children": {}},
            )
            child["count"] += 1
            child["size"] += size
            node = child

    def finalize(node: dict, parent_path: str | None) -> dict:
        if parent_path is None:
            node["path"] = ""
        elif parent_path:
            node["path"] = parent_path + "/" + node["name"]
        else:
            node["path"] = node["name"]
        children = sorted(node["children"].values(), key=lambda item: item["name"].lower())
        node["children"] = [finalize(child, node["path"]) for child in children]
        return node

    return finalize(root, None)


def count_nodes(node: dict) -> int:
    return 1 + sum(count_nodes(child) for child in node["children"])


def get_stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS count, COALESCE(SUM(size), 0) AS size, "
        "SUM(CASE WHEN parse_status='error' THEN 1 ELSE 0 END) AS errors "
        "FROM fonts WHERE present=1"
    ).fetchone()
    duplicate = conn.execute(
        "SELECT COUNT(*) AS groups, COALESCE(SUM(c), 0) AS files, "
        "COALESCE(SUM(size * (c - 1)), 0) AS wasted FROM ("
        "SELECT size, COALESCE(sha256, sha1) AS digest, COUNT(*) AS c "
        "FROM fonts WHERE present=1 AND COALESCE(sha256, sha1) IS NOT NULL "
        "GROUP BY size, digest HAVING c > 1)"
    ).fetchone()
    extensions = [
        dict(item)
        for item in conn.execute(
            "SELECT ext, COUNT(*) AS count, COALESCE(SUM(size), 0) AS size "
            "FROM fonts WHERE present=1 GROUP BY ext ORDER BY count DESC"
        )
    ]
    tree = build_tree(conn)
    return {
        "count": row["count"],
        "size": row["size"],
        "errors": row["errors"] or 0,
        "folders": count_nodes(tree) - 1,
        "extensions": extensions,
        "duplicate_groups": duplicate["groups"],
        "duplicate_files": duplicate["files"],
        "wasted_size": duplicate["wasted"],
    }


def update_hashes(
    conn: sqlite3.Connection,
    font_id: int,
    md5: str,
    sha1: str,
    sha256: str,
) -> None:
    conn.execute(
        "UPDATE fonts SET md5=?, sha1=?, sha256=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (md5, sha1, sha256, font_id),
    )


def count_present(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM fonts WHERE present=1"
    ).fetchone()["n"]

def set_present(conn: sqlite3.Connection, font_id: int, present: bool) -> None:
    conn.execute(
        "UPDATE fonts SET present=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (1 if present else 0, font_id),
    )


def delete_font_row(conn: sqlite3.Connection, font_id: int) -> None:
    conn.execute("DELETE FROM fonts WHERE id=?", (font_id,))


def insert_recycle_item(conn: sqlite3.Connection, data: dict) -> int:
    row = conn.execute(
        """
        INSERT INTO recycle_items (
            font_id, rel_path, name, size, sha1, storage_key, deleted_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            data["font_id"], data["rel_path"], data["name"], data["size"],
            data.get("sha1"), data["storage_key"], data["deleted_at"],
            data.get("expires_at"),
        ),
    ).fetchone()
    return int(row["id"])


def list_recycle_items(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, font_id, rel_path, name, size, sha1, storage_key, deleted_at, expires_at "
        "FROM recycle_items ORDER BY deleted_at DESC, id DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def get_recycle_item(conn: sqlite3.Connection, item_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, font_id, rel_path, name, size, sha1, storage_key, deleted_at, expires_at "
        "FROM recycle_items WHERE id=?",
        (item_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def delete_recycle_item(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM recycle_items WHERE id=?", (item_id,))


def list_expired_recycle_items(conn: sqlite3.Connection, now: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, font_id, rel_path, name, size, sha1, storage_key, deleted_at, expires_at "
        "FROM recycle_items WHERE expires_at IS NOT NULL AND expires_at <= ? "
        "ORDER BY expires_at ASC",
        (now,),
    ).fetchall()
    return [dict(row) for row in rows]
