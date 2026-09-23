from __future__ import annotations

import json
import mimetypes
import os
import platform
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .database import ArchiveDatabase
from .scanner import ScanManager


STATIC_DIR = Path(__file__).with_name("static")


def default_data_dir() -> Path:
    override = os.environ.get("DTIA_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "DTIA Local"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "DTIA Local"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "dtia-local"


def choose_directory() -> str | None:
    if sys.platform == "win32":
        script = r"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Escolha uma pasta para catalogar no DTIA Local'
$dialog.ShowNewFolderButton = $false
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  Write-Output $dialog.SelectedPath
}
"""
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
        selected = result.stdout.strip("\ufeff\r\n ")
        return selected or None
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(title="Escolha uma pasta para catalogar no DTIA Local")
        root.destroy()
        return selected or None
    except Exception:
        return None


def reveal_file(path: Path) -> None:
    if sys.platform == "win32":
        subprocess.Popen(["explorer.exe", f"/select,{path}"])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


class DTIAHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], database: ArchiveDatabase, scanner: ScanManager):
        self.database = database
        self.scanner = scanner
        super().__init__(server_address, DTIARequestHandler)


class DTIARequestHandler(BaseHTTPRequestHandler):
    server: DTIAHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        if self.path.startswith("/api/jobs/"):
            return
        super().log_message(format, *args)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store" if self.path.startswith("/api/") else "private, max-age=300")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        )
        super().end_headers()

    def _json(self, payload: Any, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status)

    def _body(self) -> dict[str, Any]:
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 2_000_000)
        except ValueError:
            length = 0
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("O corpo da solicitação não contém JSON válido.") from exc
        if not isinstance(value, dict):
            raise ValueError("O corpo da solicitação deve ser um objeto.")
        return value

    def _segments(self) -> list[str]:
        return [unquote(value) for value in urlparse(self.path).path.split("/") if value]

    def do_GET(self) -> None:
        try:
            self._handle_get()
        except BrokenPipeError:
            pass
        except Exception as exc:
            self._error(str(exc), 500)

    def _handle_get(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/ping":
            self._json({"app": "dtia-local", "version": __version__})
            return
        if path == "/api/state":
            self._json(
                {
                    "version": __version__,
                    "platform": platform.system(),
                    "roots": self.server.database.list_roots(),
                    "counts": self.server.database.counts(),
                    "collections": self.server.database.list_collections(),
                    "tags": self.server.database.list_tags(),
                    "settings": self.server.database.settings(),
                    "jobs": self.server.scanner.snapshot(),
                }
            )
            return
        if path == "/api/images":
            query = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
            self._json(self.server.database.query_images(query))
            return
        match = re.fullmatch(r"/api/images/(\d+)", path)
        if match:
            item = self.server.database.get_image(int(match.group(1)))
            if not item:
                self._error("Imagem não encontrada.", 404)
            else:
                self._json(item)
            return
        match = re.fullmatch(r"/api/jobs/([a-f0-9]+)", path)
        if match:
            job = self.server.scanner.get(match.group(1))
            if not job:
                self._error("Indexação não encontrada.", 404)
            else:
                self._json(job)
            return
        match = re.fullmatch(r"/(thumb|original)/(\d+)", path)
        if match:
            image_id = int(match.group(2))
            file_path = (
                self.server.database.thumbnail_path(image_id)
                if match.group(1) == "thumb"
                else self.server.database.original_path(image_id)
            )
            self._file(file_path, allow_range=match.group(1) == "original")
            return
        self._static(path)

    def do_POST(self) -> None:
        try:
            self._handle_post()
        except ValueError as exc:
            self._error(str(exc), 400)
        except KeyError as exc:
            self._error(str(exc), 404)
        except Exception as exc:
            self._error(str(exc), 500)

    def _handle_post(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/roots/pick":
            selected = choose_directory()
            if not selected:
                self._json({"cancelled": True})
                return
            root = self.server.database.add_root(selected)
            job = self.server.scanner.start(int(root["id"]))
            self._json({"root": root, "job": job}, 201)
            return
        if path == "/api/roots":
            body = self._body()
            root = self.server.database.add_root(str(body.get("path", "")), body.get("label"))
            job = self.server.scanner.start(int(root["id"]))
            self._json({"root": root, "job": job}, 201)
            return
        if path == "/api/scan":
            body = self._body()
            root_id = int(body["root_id"]) if body.get("root_id") else None
            self._json(self.server.scanner.start(root_id), 202)
            return
        if path == "/api/collections":
            body = self._body()
            item = self.server.database.create_collection(str(body.get("name", "")), str(body.get("description", "")))
            self._json(item, 201)
            return
        match = re.fullmatch(r"/api/images/(\d+)/reveal", path)
        if match:
            source = self.server.database.original_path(int(match.group(1)))
            if not source or not source.exists():
                raise ValueError("O arquivo original não está acessível.")
            reveal_file(source)
            self._json({"ok": True})
            return
        self._error("Rota não encontrada.", 404)

    def do_PATCH(self) -> None:
        try:
            path = urlparse(self.path).path
            body = self._body()
            if path == "/api/settings":
                self._json(self.server.database.update_settings(body))
                return
            match = re.fullmatch(r"/api/images/(\d+)", path)
            if match:
                self._json(self.server.database.update_image(int(match.group(1)), body))
                return
            self._error("Rota não encontrada.", 404)
        except ValueError as exc:
            self._error(str(exc), 400)
        except KeyError as exc:
            self._error(str(exc), 404)
        except Exception as exc:
            self._error(str(exc), 500)

    def do_DELETE(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            match = re.fullmatch(r"/api/roots/(\d+)", path)
            if match:
                root_id = int(match.group(1))
                if self.server.scanner.is_scanning_root(root_id):
                    self._error("Aguarde a indexação desta fonte terminar antes de removê-la.", 409)
                    return
                mode = parse_qs(parsed.query).get("mode", ["disconnect"])[-1]
                if mode == "disconnect":
                    result = self.server.database.disconnect_root(root_id)
                elif mode == "catalog":
                    result = self.server.database.remove_root_from_catalog(root_id)
                else:
                    raise ValueError("Modo de remoção inválido.")
                self._json({"ok": True, **result})
                return
            match = re.fullmatch(r"/api/collections/(\d+)", path)
            if match:
                self.server.database.delete_collection(int(match.group(1)))
                self._json({"ok": True})
                return
            self._error("Rota não encontrada.", 404)
        except ValueError as exc:
            self._error(str(exc), 400)
        except KeyError as exc:
            self._error(str(exc).strip("'"), 404)
        except Exception as exc:
            self._error(str(exc), 500)

    def _static(self, request_path: str) -> None:
        mapping = {
            "/": "index.html",
            "/index.html": "index.html",
            "/app.js": "app.js",
            "/style.css": "style.css",
            "/favicon.svg": "favicon.svg",
        }
        filename = mapping.get(request_path)
        if not filename:
            self._error("Arquivo não encontrado.", 404)
            return
        path = STATIC_DIR / filename
        if not path.is_file():
            self._error("Interface não instalada corretamente.", 500)
            return
        data = path.read_bytes()
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "image/svg+xml"}:
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path: Path | None, allow_range: bool = False) -> None:
        if not path or not path.is_file():
            self._error("O arquivo não está acessível. Verifique se o HD está conectado.", 404)
            return
        size = path.stat().st_size
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        start, end = 0, size - 1
        status = 200
        range_header = self.headers.get("Range") if allow_range else None
        if range_header:
            match = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if match:
                if match.group(1):
                    start = int(match.group(1))
                if match.group(2):
                    end = min(size - 1, int(match.group(2)))
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as source:
            source.seek(start)
            remaining = length
            while remaining > 0:
                block = source.read(min(1024 * 1024, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)


def existing_server(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=0.5) as response:
            value = json.loads(response.read().decode("utf-8"))
            return value.get("app") == "dtia-local"
    except Exception:
        return False


def find_port(preferred: int) -> tuple[int, bool]:
    if existing_server(preferred):
        return preferred, True
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
                return port, False
            except OSError:
                if existing_server(port):
                    return port, True
    raise RuntimeError("Não foi possível encontrar uma porta local disponível.")


def run(data_dir: Path | None = None, preferred_port: int = 8148, open_browser: bool = True) -> None:
    port, already_running = find_port(preferred_port)
    url = f"http://127.0.0.1:{port}"
    if already_running:
        if open_browser:
            webbrowser.open(url)
        print(f"O DTIA Local já está em execução: {url}")
        return
    archive_dir = (data_dir or default_data_dir()).expanduser().resolve()
    database = ArchiveDatabase(archive_dir)
    scanner = ScanManager(database, archive_dir)
    server = DTIAHTTPServer(("127.0.0.1", port), database, scanner)
    if open_browser:
        threading.Timer(0.65, lambda: webbrowser.open(url)).start()
    print("\nDTIA LOCAL")
    print(f"Interface: {url}")
    print(f"Dados locais: {archive_dir}")
    print("Esta janela pode ser minimizada. Pressione Ctrl+C para encerrar.\n")
    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
