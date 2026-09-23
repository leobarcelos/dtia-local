from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_path(value: str | os.PathLike[str]) -> str:
    path = Path(value).expanduser()
    try:
        return str(path.resolve(strict=False))
    except OSError:
        return str(path.absolute())


class ArchiveDatabase:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "dtia-local.sqlite3"
        self._write_lock = threading.RLock()
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS roots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE,
                    label TEXT NOT NULL,
                    available INTEGER NOT NULL DEFAULT 1,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    image_count INTEGER NOT NULL DEFAULT 0,
                    added_at TEXT NOT NULL,
                    last_scan_at TEXT,
                    last_error TEXT
                );

                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    root_id INTEGER REFERENCES roots(id) ON DELETE SET NULL,
                    path TEXT NOT NULL UNIQUE,
                    relative_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    extension TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    byte_size INTEGER NOT NULL DEFAULT 0,
                    modified_ns INTEGER NOT NULL DEFAULT 0,
                    width INTEGER NOT NULL DEFAULT 0,
                    height INTEGER NOT NULL DEFAULT 0,
                    orientation TEXT NOT NULL DEFAULT 'unknown',
                    dominant_color TEXT NOT NULL DEFAULT '#292529',
                    content_hash TEXT,
                    perceptual_hash TEXT,
                    thumbnail_path TEXT,
                    date_taken TEXT,
                    camera TEXT,
                    lens TEXT,
                    exif_json TEXT NOT NULL DEFAULT '{}',
                    favorite INTEGER NOT NULL DEFAULT 0,
                    rating TEXT NOT NULL DEFAULT 'general'
                        CHECK (rating IN ('general', 'sensitive', 'adult')),
                    notes TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'online'
                        CHECK (status IN ('online', 'offline', 'missing', 'error')),
                    error_message TEXT,
                    search_blob TEXT NOT NULL DEFAULT '',
                    added_at TEXT NOT NULL,
                    indexed_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_images_root ON images(root_id);
                CREATE INDEX IF NOT EXISTS idx_images_status ON images(status);
                CREATE INDEX IF NOT EXISTS idx_images_favorite ON images(favorite);
                CREATE INDEX IF NOT EXISTS idx_images_rating ON images(rating);
                CREATE INDEX IF NOT EXISTS idx_images_orientation ON images(orientation);
                CREATE INDEX IF NOT EXISTS idx_images_extension ON images(extension);
                CREATE INDEX IF NOT EXISTS idx_images_hash ON images(content_hash);
                CREATE INDEX IF NOT EXISTS idx_images_phash ON images(perceptual_hash);
                CREATE INDEX IF NOT EXISTS idx_images_modified ON images(modified_ns DESC);

                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE
                );

                CREATE TABLE IF NOT EXISTS image_tags (
                    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    PRIMARY KEY (image_id, tag_id)
                );

                CREATE TABLE IF NOT EXISTS collections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS collection_images (
                    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
                    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (collection_id, image_id)
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            defaults = {
                "adult_visibility": "blur",
                "sensitive_visibility": "show",
                "theme": "dark",
                "thumbnail_quality": "82",
            }
            connection.executemany(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                defaults.items(),
            )

    def add_root(self, path: str, label: str | None = None) -> dict[str, Any]:
        normalized = canonical_path(path)
        if not Path(normalized).is_dir():
            raise ValueError("A pasta informada não existe ou não está acessível.")
        root_label = (label or Path(normalized).name or normalized).strip()
        now = utc_now()
        with self._write_lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO roots(path, label, available, enabled, added_at)
                VALUES (?, ?, 1, 1, ?)
                ON CONFLICT(path) DO UPDATE SET
                    label = excluded.label,
                    available = 1,
                    enabled = 1,
                    last_error = NULL
                """,
                (normalized, root_label, now),
            )
            row = connection.execute("SELECT * FROM roots WHERE path = ?", (normalized,)).fetchone()
            return dict(row)

    def list_roots(self, refresh: bool = True) -> list[dict[str, Any]]:
        with self._write_lock, self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM roots WHERE enabled = 1 ORDER BY label COLLATE NOCASE"
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                is_available = Path(item["path"]).is_dir()
                if refresh and bool(item["available"]) != is_available:
                    connection.execute(
                        "UPDATE roots SET available = ? WHERE id = ?",
                        (int(is_available), item["id"]),
                    )
                    if not is_available:
                        connection.execute(
                            "UPDATE images SET status = 'offline' WHERE root_id = ? AND status != 'missing'",
                            (item["id"],),
                        )
                    else:
                        connection.execute(
                            "UPDATE images SET status = 'online' WHERE root_id = ? AND status = 'offline'",
                            (item["id"],),
                        )
                    item["available"] = int(is_available)
                result.append(item)
            return result

    def get_root(self, root_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM roots WHERE id = ? AND enabled = 1", (root_id,)).fetchone()
            return dict(row) if row else None

    def disconnect_root(self, root_id: int) -> dict[str, Any]:
        with self._write_lock, self.connect() as connection:
            root = connection.execute("SELECT * FROM roots WHERE id = ?", (root_id,)).fetchone()
            if not root:
                raise KeyError("Fonte não encontrada.")
            image_count = connection.execute(
                "SELECT COUNT(*) FROM images WHERE root_id = ?", (root_id,)
            ).fetchone()[0]
            connection.execute("UPDATE roots SET enabled = 0 WHERE id = ?", (root_id,))
            connection.execute("UPDATE images SET status = 'offline' WHERE root_id = ?", (root_id,))
            return {
                "mode": "disconnect",
                "root_id": root_id,
                "label": root["label"],
                "image_count": int(image_count),
            }

    def remove_root_from_catalog(self, root_id: int) -> dict[str, Any]:
        with self._write_lock, self.connect() as connection:
            root = connection.execute("SELECT * FROM roots WHERE id = ?", (root_id,)).fetchone()
            if not root:
                raise KeyError("Fonte não encontrada.")
            rows = connection.execute(
                "SELECT thumbnail_path FROM images WHERE root_id = ? AND thumbnail_path IS NOT NULL",
                (root_id,),
            ).fetchall()
            thumbnail_paths = [row["thumbnail_path"] for row in rows]
            image_count = connection.execute(
                "SELECT COUNT(*) FROM images WHERE root_id = ?", (root_id,)
            ).fetchone()[0]
            connection.execute("DELETE FROM images WHERE root_id = ?", (root_id,))
            connection.execute("DELETE FROM roots WHERE id = ?", (root_id,))
            connection.execute(
                "DELETE FROM tags WHERE NOT EXISTS (SELECT 1 FROM image_tags WHERE image_tags.tag_id = tags.id)"
            )

        thumbnail_root = (self.data_dir / "thumbnails").resolve()
        removed_thumbnails = 0
        for raw_path in thumbnail_paths:
            try:
                thumbnail = Path(raw_path).resolve()
                if thumbnail.is_relative_to(thumbnail_root) and thumbnail.is_file():
                    thumbnail.unlink()
                    removed_thumbnails += 1
            except OSError:
                continue
        return {
            "mode": "catalog",
            "root_id": root_id,
            "label": root["label"],
            "image_count": int(image_count),
            "removed_thumbnails": removed_thumbnails,
        }

    def begin_scan(self, root_id: int) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "UPDATE roots SET available = 1, last_error = NULL WHERE id = ?", (root_id,)
            )
            connection.execute(
                "UPDATE images SET status = 'missing' WHERE root_id = ?", (root_id,)
            )

    def set_root_error(self, root_id: int, message: str) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "UPDATE roots SET available = 0, last_error = ? WHERE id = ?",
                (message[:1000], root_id),
            )
            connection.execute(
                "UPDATE images SET status = 'offline' WHERE root_id = ?", (root_id,)
            )

    def finish_scan(self, root_id: int) -> None:
        with self._write_lock, self.connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM images WHERE root_id = ? AND status = 'online'", (root_id,)
            ).fetchone()[0]
            connection.execute(
                """
                UPDATE roots
                SET image_count = ?, last_scan_at = ?, available = 1, last_error = NULL
                WHERE id = ?
                """,
                (count, utc_now(), root_id),
            )

    def image_is_current(self, path: str, byte_size: int, modified_ns: int) -> bool:
        normalized = canonical_path(path)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, thumbnail_path FROM images WHERE path = ? AND byte_size = ? AND modified_ns = ?",
                (normalized, byte_size, modified_ns),
            ).fetchone()
            if not row:
                return False
            thumbnail = row["thumbnail_path"]
            return bool(thumbnail and Path(thumbnail).is_file())

    def mark_seen(self, path: str, root_id: int, relative_path: str) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "UPDATE images SET status = 'online', root_id = ?, relative_path = ?, error_message = NULL WHERE path = ?",
                (root_id, relative_path, canonical_path(path)),
            )

    def upsert_image(self, metadata: dict[str, Any]) -> int:
        now = utc_now()
        path = canonical_path(metadata["path"])
        filename = metadata["filename"]
        title = metadata.get("title") or Path(filename).stem
        search_blob = " ".join(
            [title, filename, metadata.get("relative_path", ""), metadata.get("camera", "") or ""]
        ).lower()
        values = {
            **metadata,
            "path": path,
            "title": title,
            "search_blob": search_blob,
            "added_at": now,
            "indexed_at": now,
            "exif_json": json.dumps(metadata.get("exif", {}), ensure_ascii=False, default=str),
        }
        columns = (
            "root_id", "path", "relative_path", "filename", "title", "extension", "mime_type",
            "byte_size", "modified_ns", "width", "height", "orientation", "dominant_color",
            "content_hash", "perceptual_hash", "thumbnail_path", "date_taken", "camera", "lens",
            "exif_json", "status", "error_message", "search_blob", "added_at", "indexed_at"
        )
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(
            f"{column} = excluded.{column}"
            for column in columns
            if column not in {"path", "title", "search_blob", "added_at"}
        )
        with self._write_lock, self.connect() as connection:
            connection.execute(
                f"""
                INSERT INTO images({', '.join(columns)}) VALUES ({placeholders})
                ON CONFLICT(path) DO UPDATE SET {updates}
                """,
                tuple(values.get(column) for column in columns),
            )
            row = connection.execute("SELECT id FROM images WHERE path = ?", (path,)).fetchone()
            return int(row["id"])

    def counts(self) -> dict[str, int]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN favorite = 1 THEN 1 ELSE 0 END) AS favorites,
                    SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) AS online,
                    SUM(CASE WHEN status != 'online' THEN 1 ELSE 0 END) AS unavailable,
                    SUM(CASE WHEN rating = 'adult' THEN 1 ELSE 0 END) AS adult,
                    SUM(CASE WHEN content_hash IS NOT NULL AND content_hash IN (
                        SELECT content_hash FROM images WHERE content_hash IS NOT NULL
                        GROUP BY content_hash HAVING COUNT(*) > 1
                    ) THEN 1 ELSE 0 END) AS duplicate_files
                FROM images
                """
            ).fetchone()
            return {key: int(row[key] or 0) for key in row.keys()}

    def settings(self) -> dict[str, str]:
        with self.connect() as connection:
            rows = connection.execute("SELECT key, value FROM settings").fetchall()
            return {row["key"]: row["value"] for row in rows}

    def update_settings(self, changes: dict[str, Any]) -> dict[str, str]:
        allowed = {
            "adult_visibility": {"show", "blur", "hide"},
            "sensitive_visibility": {"show", "blur", "hide"},
        }
        with self._write_lock, self.connect() as connection:
            for key, choices in allowed.items():
                if key in changes and str(changes[key]) in choices:
                    connection.execute(
                        "INSERT INTO settings(key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, str(changes[key])),
                    )
        return self.settings()

    def list_tags(self, limit: int = 80) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT tags.id, tags.name, COUNT(image_tags.image_id) AS count
                FROM tags LEFT JOIN image_tags ON image_tags.tag_id = tags.id
                GROUP BY tags.id ORDER BY count DESC, tags.name COLLATE NOCASE LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_collections(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT collections.*, COUNT(collection_images.image_id) AS image_count
                FROM collections
                LEFT JOIN collection_images ON collection_images.collection_id = collections.id
                GROUP BY collections.id
                ORDER BY collections.created_at DESC, collections.name COLLATE NOCASE
                """
            ).fetchall()
            result = [dict(row) for row in rows]
            for item in result:
                covers = connection.execute(
                    """
                    SELECT images.id FROM collection_images
                    JOIN images ON images.id = collection_images.image_id
                    WHERE collection_images.collection_id = ?
                    ORDER BY collection_images.added_at DESC LIMIT 4
                    """,
                    (item["id"],),
                ).fetchall()
                item["cover_ids"] = [row["id"] for row in covers]
            return result

    def create_collection(self, name: str, description: str = "") -> dict[str, Any]:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Dê um nome à coleção.")
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO collections(name, description, created_at) VALUES (?, ?, ?)",
                (cleaned[:120], description.strip()[:1000], utc_now()),
            )
            row = connection.execute("SELECT * FROM collections WHERE id = ?", (cursor.lastrowid,)).fetchone()
            result = dict(row)
            result.update({"image_count": 0, "cover_ids": []})
            return result

    def delete_collection(self, collection_id: int) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute("DELETE FROM collections WHERE id = ?", (collection_id,))

    def _attach_tags(self, connection: sqlite3.Connection, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        ids = [int(item["id"]) for item in items]
        marks = ",".join("?" for _ in ids)
        rows = connection.execute(
            f"""
            SELECT image_tags.image_id, tags.name FROM image_tags
            JOIN tags ON tags.id = image_tags.tag_id
            WHERE image_tags.image_id IN ({marks}) ORDER BY tags.name COLLATE NOCASE
            """,
            ids,
        ).fetchall()
        mapped: dict[int, list[str]] = {image_id: [] for image_id in ids}
        for row in rows:
            mapped[int(row["image_id"])].append(row["name"])
        for item in items:
            item["tags"] = mapped[int(item["id"])]

    def query_images(self, filters: dict[str, Any]) -> dict[str, Any]:
        where: list[str] = ["1 = 1"]
        values: list[Any] = []
        query = str(filters.get("q", "")).strip().lower()
        if query:
            term = f"%{query}%"
            where.append(
                "(images.search_blob LIKE ? OR images.notes LIKE ? OR EXISTS ("
                "SELECT 1 FROM image_tags JOIN tags ON tags.id = image_tags.tag_id "
                "WHERE image_tags.image_id = images.id AND tags.name LIKE ?))"
            )
            values.extend([term, term, term])
        if filters.get("root_id"):
            where.append("images.root_id = ?")
            values.append(int(filters["root_id"]))
        if filters.get("collection_id"):
            where.append(
                "EXISTS (SELECT 1 FROM collection_images WHERE collection_images.image_id = images.id "
                "AND collection_images.collection_id = ?)"
            )
            values.append(int(filters["collection_id"]))
        if filters.get("favorite") in {True, "1", "true"}:
            where.append("images.favorite = 1")
        orientation = filters.get("orientation")
        if orientation in {"landscape", "portrait", "square"}:
            where.append("images.orientation = ?")
            values.append(orientation)
        extension = str(filters.get("format", "")).strip().lower().lstrip(".")
        if extension:
            where.append("images.extension = ?")
            values.append(extension)
        rating = filters.get("rating")
        if rating in {"general", "sensitive", "adult"}:
            where.append("images.rating = ?")
            values.append(rating)
        if filters.get("min_width"):
            where.append("images.width >= ?")
            values.append(max(0, int(filters["min_width"])))
        if filters.get("tag"):
            where.append(
                "EXISTS (SELECT 1 FROM image_tags JOIN tags ON tags.id = image_tags.tag_id "
                "WHERE image_tags.image_id = images.id AND tags.name = ? COLLATE NOCASE)"
            )
            values.append(str(filters["tag"]))
        view = filters.get("view")
        if view == "offline":
            where.append("images.status != 'online'")
        elif view == "duplicates":
            where.append(
                "images.content_hash IS NOT NULL AND images.content_hash IN ("
                "SELECT content_hash FROM images WHERE content_hash IS NOT NULL "
                "GROUP BY content_hash HAVING COUNT(*) > 1)"
            )
        else:
            where.append("images.status != 'missing'")
        privacy = self.settings()
        if privacy.get("adult_visibility") == "hide" and rating != "adult":
            where.append("images.rating != 'adult'")
        if privacy.get("sensitive_visibility") == "hide" and rating != "sensitive":
            where.append("images.rating != 'sensitive'")
        sort_map = {
            "oldest": "images.modified_ns ASC, images.id ASC",
            "name": "images.filename COLLATE NOCASE ASC, images.id ASC",
            "resolution": "(images.width * images.height) DESC, images.id DESC",
            "random": "RANDOM()",
        }
        order = sort_map.get(str(filters.get("sort")), "images.modified_ns DESC, images.id DESC")
        limit = min(240, max(1, int(filters.get("limit", 60))))
        offset = max(0, int(filters.get("offset", 0)))
        clause = " AND ".join(where)
        with self.connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM images WHERE {clause}", values
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT images.*, roots.label AS root_label, roots.available AS root_available
                FROM images LEFT JOIN roots ON roots.id = images.root_id
                WHERE {clause} ORDER BY {order} LIMIT ? OFFSET ?
                """,
                [*values, limit, offset],
            ).fetchall()
            items = [self._public_image(dict(row), include_path=False) for row in rows]
            self._attach_tags(connection, items)
        return {"items": items, "total": int(total), "offset": offset, "limit": limit}

    def _public_image(self, item: dict[str, Any], include_path: bool) -> dict[str, Any]:
        result = {key: item[key] for key in item.keys() if key not in {"exif_json", "thumbnail_path", "search_blob"}}
        if not include_path:
            result.pop("path", None)
        result["favorite"] = bool(result.get("favorite"))
        result["root_available"] = bool(result.get("root_available", True))
        result["thumbnail_url"] = f"/thumb/{item['id']}"
        result["original_url"] = f"/original/{item['id']}"
        return result

    def get_image(self, image_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT images.*, roots.label AS root_label, roots.available AS root_available
                FROM images LEFT JOIN roots ON roots.id = images.root_id WHERE images.id = ?
                """,
                (image_id,),
            ).fetchone()
            if not row:
                return None
            item = self._public_image(dict(row), include_path=True)
            try:
                item["exif"] = json.loads(row["exif_json"] or "{}")
            except json.JSONDecodeError:
                item["exif"] = {}
            self._attach_tags(connection, [item])
            collections = connection.execute(
                "SELECT collection_id FROM collection_images WHERE image_id = ?", (image_id,)
            ).fetchall()
            item["collection_ids"] = [int(value["collection_id"]) for value in collections]
            duplicate_rows = []
            if row["content_hash"]:
                duplicate_rows = connection.execute(
                    "SELECT id, filename, path, byte_size FROM images WHERE content_hash = ? AND id != ?",
                    (row["content_hash"], image_id),
                ).fetchall()
            item["duplicates"] = [dict(value) for value in duplicate_rows]
            return item

    def update_image(self, image_id: int, changes: dict[str, Any]) -> dict[str, Any]:
        assignments: list[str] = []
        values: list[Any] = []
        if "favorite" in changes:
            assignments.append("favorite = ?")
            values.append(int(bool(changes["favorite"])))
        if changes.get("rating") in {"general", "sensitive", "adult"}:
            assignments.append("rating = ?")
            values.append(changes["rating"])
        if "notes" in changes:
            assignments.append("notes = ?")
            values.append(str(changes["notes"])[:10000])
        if "title" in changes:
            assignments.append("title = ?")
            values.append(str(changes["title"]).strip()[:300])
        with self._write_lock, self.connect() as connection:
            if assignments:
                connection.execute(
                    f"UPDATE images SET {', '.join(assignments)} WHERE id = ?",
                    [*values, image_id],
                )
            if "tags" in changes:
                names = []
                seen = set()
                for raw in changes.get("tags") or []:
                    name = str(raw).strip().lower()[:60]
                    if name and name not in seen:
                        seen.add(name)
                        names.append(name)
                connection.execute("DELETE FROM image_tags WHERE image_id = ?", (image_id,))
                for name in names[:40]:
                    connection.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (name,))
                    tag = connection.execute("SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
                    connection.execute(
                        "INSERT OR IGNORE INTO image_tags(image_id, tag_id) VALUES (?, ?)",
                        (image_id, tag["id"]),
                    )
            if "collection_ids" in changes:
                collection_ids = {int(value) for value in changes.get("collection_ids") or []}
                connection.execute("DELETE FROM collection_images WHERE image_id = ?", (image_id,))
                for collection_id in collection_ids:
                    connection.execute(
                        "INSERT OR IGNORE INTO collection_images(collection_id, image_id, added_at) VALUES (?, ?, ?)",
                        (collection_id, image_id, utc_now()),
                    )
            row = connection.execute(
                "SELECT title, filename, relative_path, camera, notes FROM images WHERE id = ?", (image_id,)
            ).fetchone()
            if row:
                tags = connection.execute(
                    "SELECT tags.name FROM image_tags JOIN tags ON tags.id = image_tags.tag_id WHERE image_id = ?",
                    (image_id,),
                ).fetchall()
                blob = " ".join(
                    [row["title"], row["filename"], row["relative_path"], row["camera"] or "", row["notes"]]
                    + [tag["name"] for tag in tags]
                ).lower()
                connection.execute("UPDATE images SET search_blob = ? WHERE id = ?", (blob, image_id))
        item = self.get_image(image_id)
        if not item:
            raise KeyError("Imagem não encontrada.")
        return item

    def thumbnail_path(self, image_id: int) -> Path | None:
        with self.connect() as connection:
            row = connection.execute("SELECT thumbnail_path FROM images WHERE id = ?", (image_id,)).fetchone()
            return Path(row["thumbnail_path"]) if row and row["thumbnail_path"] else None

    def original_path(self, image_id: int) -> Path | None:
        with self.connect() as connection:
            row = connection.execute("SELECT path FROM images WHERE id = ?", (image_id,)).fetchone()
            return Path(row["path"]) if row else None
