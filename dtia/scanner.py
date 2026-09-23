from __future__ import annotations

import hashlib
import mimetypes
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image, ImageOps, ImageStat, UnidentifiedImageError

from .database import ArchiveDatabase, canonical_path


IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff",
    ".avif", ".heic", ".heif", ".jfif",
}

SKIP_DIRECTORIES = {
    "$RECYCLE.BIN", "System Volume Information", ".git", ".svn", "node_modules",
    "__pycache__", ".thumbnails", ".venv", "@eaDir", "Windows", "Program Files",
    "Program Files (x86)", "ProgramData", "Recovery",
}


def image_orientation(width: int, height: int) -> str:
    if not width or not height:
        return "unknown"
    ratio = width / height
    if 0.94 <= ratio <= 1.06:
        return "square"
    return "landscape" if width > height else "portrait"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def difference_hash(image: Image.Image) -> str:
    grayscale = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = grayscale.tobytes()
    value = 0
    for row in range(8):
        for column in range(8):
            value <<= 1
            left = pixels[row * 9 + column]
            right = pixels[row * 9 + column + 1]
            if left > right:
                value |= 1
    return f"{value:016x}"


def readable_exif(image: Image.Image) -> dict[str, str]:
    try:
        raw = image.getexif()
    except Exception:
        return {}
    selected = {
        "Make", "Model", "LensModel", "DateTime", "DateTimeOriginal", "Software",
        "ExposureTime", "FNumber", "ISOSpeedRatings", "PhotographicSensitivity",
        "FocalLength", "Flash", "Orientation", "PixelXDimension", "PixelYDimension",
        "Artist", "Copyright",
    }
    result: dict[str, str] = {}
    for key, value in raw.items():
        name = ExifTags.TAGS.get(key, str(key))
        if name not in selected:
            continue
        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8", errors="replace")
            except Exception:
                value = repr(value[:80])
        result[name] = str(value)
    return result


def dominant_hex(image: Image.Image) -> str:
    sample = ImageOps.exif_transpose(image).convert("RGB")
    sample.thumbnail((64, 64), Image.Resampling.BILINEAR)
    mean = ImageStat.Stat(sample).mean
    return "#" + "".join(f"{max(0, min(255, round(value))):02x}" for value in mean[:3])


class ScanManager:
    def __init__(self, database: ArchiveDatabase, data_dir: Path):
        self.database = database
        self.thumbnail_dir = data_dir / "thumbnails"
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(job) for job in sorted(self.jobs.values(), key=lambda item: item["created_at"], reverse=True)[:10]]

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def is_scanning_root(self, root_id: int) -> bool:
        with self.lock:
            return any(
                job["status"] in {"queued", "running"}
                and root_id in {int(value) for value in job.get("root_ids", [])}
                for job in self.jobs.values()
            )

    def start(self, root_id: int | None = None) -> dict[str, Any]:
        roots = [self.database.get_root(root_id)] if root_id else self.database.list_roots()
        roots = [root for root in roots if root]
        if not roots:
            raise ValueError("Adicione ao menos uma pasta antes de indexar.")
        requested_ids = {int(root["id"]) for root in roots}
        with self.lock:
            active_ids = {
                int(active_root_id)
                for job in self.jobs.values()
                if job["status"] in {"queued", "running"}
                for active_root_id in job.get("root_ids", [])
            }
        if requested_ids & active_ids:
            raise ValueError("Essa fonte já está sendo indexada. Aguarde a conclusão.")
        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "status": "queued",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "root_count": len(roots),
            "root_ids": sorted(requested_ids),
            "root_index": 0,
            "root_label": "",
            "discovered": 0,
            "processed": 0,
            "indexed": 0,
            "unchanged": 0,
            "errors": 0,
            "current": "",
            "message": "Preparando a indexação…",
        }
        with self.lock:
            self.jobs[job_id] = job
        thread = threading.Thread(target=self._run, args=(job_id, roots), daemon=True, name=f"dtia-scan-{job_id}")
        thread.start()
        return dict(job)

    def _update(self, job_id: str, **changes: Any) -> None:
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].update(changes)

    def _increment(self, job_id: str, key: str, amount: int = 1) -> None:
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id][key] = int(self.jobs[job_id].get(key, 0)) + amount

    def _run(self, job_id: str, roots: list[dict[str, Any]]) -> None:
        self._update(job_id, status="running", message="Lendo as pastas…")
        try:
            for position, root in enumerate(roots, start=1):
                self._update(
                    job_id,
                    root_index=position,
                    root_label=root["label"],
                    message=f"Indexando {root['label']}",
                )
                self._scan_root(job_id, root)
            self._update(job_id, status="completed", current="", message="Indexação concluída.")
        except Exception as exc:
            self._update(job_id, status="failed", current="", message=str(exc))

    def _scan_root(self, job_id: str, root: dict[str, Any]) -> None:
        root_path = Path(root["path"])
        if not root_path.is_dir():
            self.database.set_root_error(root["id"], "A unidade ou pasta não está conectada.")
            self._increment(job_id, "errors")
            return
        self.database.begin_scan(root["id"])
        try:
            for directory, dirnames, filenames in os.walk(root_path):
                directory_path = Path(directory)
                data_path = self.database.data_dir.resolve()
                dirnames[:] = [
                    name for name in dirnames
                    if name not in SKIP_DIRECTORIES
                    and not name.startswith(".")
                    and (directory_path / name).resolve() != data_path
                ]
                for filename in filenames:
                    path = directory_path / filename
                    if path.suffix.lower() not in IMAGE_EXTENSIONS:
                        continue
                    self._increment(job_id, "discovered")
                    self._update(job_id, current=str(path.relative_to(root_path)))
                    try:
                        stat = path.stat()
                        relative = str(path.relative_to(root_path))
                        if self.database.image_is_current(str(path), stat.st_size, stat.st_mtime_ns):
                            self.database.mark_seen(str(path), root["id"], relative)
                            self._increment(job_id, "unchanged")
                        else:
                            metadata = self._analyze(path, root["id"], relative, stat)
                            self.database.upsert_image(metadata)
                            self._increment(job_id, "indexed")
                    except (OSError, UnidentifiedImageError, ValueError) as exc:
                        self._record_error(path, root["id"], root_path, exc)
                        self._increment(job_id, "errors")
                    except Exception as exc:
                        self._record_error(path, root["id"], root_path, exc)
                        self._increment(job_id, "errors")
                    finally:
                        self._increment(job_id, "processed")
            self.database.finish_scan(root["id"])
        except OSError as exc:
            self.database.set_root_error(root["id"], str(exc))
            self._increment(job_id, "errors")

    def _thumbnail_path(self, source: Path) -> Path:
        digest = hashlib.sha1(canonical_path(source).encode("utf-8", errors="surrogatepass")).hexdigest()
        folder = self.thumbnail_dir / digest[:2]
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{digest}.jpg"

    def _analyze(self, path: Path, root_id: int, relative: str, stat: os.stat_result) -> dict[str, Any]:
        thumb_path = self._thumbnail_path(path)
        with Image.open(path) as source:
            source.seek(0)
            exif = readable_exif(source)
            oriented = ImageOps.exif_transpose(source)
            width, height = oriented.size
            color = dominant_hex(oriented)
            phash = difference_hash(oriented)
            thumbnail = oriented.convert("RGB")
            thumbnail.thumbnail((720, 720), Image.Resampling.LANCZOS)
            thumbnail.save(thumb_path, "JPEG", quality=82, optimize=True, progressive=True)
        camera = " ".join(value for value in [exif.get("Make", "").strip(), exif.get("Model", "").strip()] if value).strip()
        date_taken = exif.get("DateTimeOriginal") or exif.get("DateTime")
        return {
            "root_id": root_id,
            "path": str(path),
            "relative_path": relative,
            "filename": path.name,
            "extension": path.suffix.lower().lstrip("."),
            "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "byte_size": stat.st_size,
            "modified_ns": stat.st_mtime_ns,
            "width": width,
            "height": height,
            "orientation": image_orientation(width, height),
            "dominant_color": color,
            "content_hash": file_sha256(path),
            "perceptual_hash": phash,
            "thumbnail_path": str(thumb_path),
            "date_taken": date_taken,
            "camera": camera or None,
            "lens": exif.get("LensModel"),
            "exif": exif,
            "status": "online",
            "error_message": None,
        }

    def _record_error(self, path: Path, root_id: int, root_path: Path, error: Exception) -> None:
        try:
            stat = path.stat()
            byte_size, modified_ns = stat.st_size, stat.st_mtime_ns
        except OSError:
            byte_size, modified_ns = 0, 0
        self.database.upsert_image(
            {
                "root_id": root_id,
                "path": str(path),
                "relative_path": str(path.relative_to(root_path)),
                "filename": path.name,
                "extension": path.suffix.lower().lstrip("."),
                "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "byte_size": byte_size,
                "modified_ns": modified_ns,
                "width": 0,
                "height": 0,
                "orientation": "unknown",
                "dominant_color": "#292529",
                "content_hash": None,
                "perceptual_hash": None,
                "thumbnail_path": None,
                "date_taken": None,
                "camera": None,
                "lens": None,
                "exif": {},
                "status": "error",
                "error_message": str(error)[:1000],
            }
        )
