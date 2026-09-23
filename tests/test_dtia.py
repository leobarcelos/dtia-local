from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from PIL import Image

from dtia.database import ArchiveDatabase
from dtia.scanner import ScanManager
from dtia.web import DTIAHTTPServer


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


class DTIATestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / "arquivo visual"
        self.source.mkdir()
        first = self.source / "cidade vermelha.jpg"
        Image.new("RGB", (640, 360), (174, 32, 52)).save(first, "JPEG", quality=91)
        shutil.copy2(first, self.source / "cópia com outro nome.jpg")
        Image.new("RGB", (320, 560), (38, 78, 108)).save(self.source / "retrato azul.png", "PNG")
        (self.source / "ignorar.txt").write_text("não é uma imagem", encoding="utf-8")
        self.original_hashes = {path.name: sha256(path) for path in self.source.glob("*.*")}
        self.database = ArchiveDatabase(self.base / "data")
        self.scanner = ScanManager(self.database, self.base / "data")
        self.root = self.database.add_root(str(self.source), "HD de teste")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def scan(self) -> dict:
        job = self.scanner.start(self.root["id"])
        deadline = time.time() + 15
        while time.time() < deadline:
            current = self.scanner.get(job["id"])
            if current["status"] not in {"queued", "running"}:
                self.assertEqual(current["status"], "completed", current)
                return current
            time.sleep(0.04)
        self.fail("A indexação não terminou dentro do prazo.")

    def test_scan_search_duplicates_and_metadata(self) -> None:
        first_job = self.scan()
        self.assertEqual(first_job["indexed"], 3)
        counts = self.database.counts()
        self.assertEqual(counts["total"], 3)
        self.assertEqual(counts["duplicate_files"], 2)

        portrait = self.database.query_images({"orientation": "portrait"})
        self.assertEqual(portrait["total"], 1)
        self.assertEqual(portrait["items"][0]["filename"], "retrato azul.png")
        search = self.database.query_images({"q": "vermelha"})
        self.assertEqual(search["total"], 1)

        image_id = portrait["items"][0]["id"]
        collection = self.database.create_collection("Referências", "Coleção de teste")
        updated = self.database.update_image(
            image_id,
            {
                "favorite": True,
                "rating": "adult",
                "title": "Retrato azul catalogado",
                "tags": ["Azul", "Retrato"],
                "notes": "Uma nota pesquisável",
                "collection_ids": [collection["id"]],
            },
        )
        self.assertTrue(updated["favorite"])
        self.assertEqual(updated["rating"], "adult")
        self.assertEqual(updated["tags"], ["azul", "retrato"])
        self.assertEqual(self.database.query_images({"q": "pesquisável"})["total"], 1)
        self.assertEqual(self.database.query_images({"collection_id": collection["id"]})["total"], 1)

        second_job = self.scan()
        self.assertEqual(second_job["unchanged"], 3)
        self.assertEqual(second_job["indexed"], 0)
        for path in self.source.glob("*.*"):
            self.assertEqual(self.original_hashes[path.name], sha256(path), path.name)

        Image.new("RGB", (360, 640), (31, 66, 96)).save(self.source / "retrato azul.png", "PNG")
        third_job = self.scan()
        self.assertEqual(third_job["indexed"], 1)
        refreshed = self.database.get_image(image_id)
        self.assertEqual(refreshed["title"], "Retrato azul catalogado")
        self.assertEqual(refreshed["rating"], "adult")
        self.assertTrue(refreshed["favorite"])

    def test_external_drive_offline_preserves_catalog(self) -> None:
        self.scan()
        disconnected = self.base / "desconectado"
        self.source.rename(disconnected)
        roots = self.database.list_roots(refresh=True)
        self.assertFalse(bool(roots[0]["available"]))
        self.assertEqual(self.database.counts()["total"], 3)
        self.assertEqual(self.database.query_images({"view": "offline"})["total"], 3)

    def test_disconnect_and_remove_source_preserve_originals(self) -> None:
        self.scan()
        thumbnails = list((self.base / "data" / "thumbnails").rglob("*.jpg"))
        self.assertEqual(len(thumbnails), 3)

        disconnected = self.database.disconnect_root(self.root["id"])
        self.assertEqual(disconnected["image_count"], 3)
        self.assertEqual(self.database.list_roots(), [])
        self.assertEqual(self.database.counts()["total"], 3)
        self.assertEqual(self.database.query_images({"view": "offline"})["total"], 3)

        restored = self.database.add_root(str(self.source), "HD de teste restaurado")
        self.assertEqual(restored["id"], self.root["id"])
        self.scan()
        portrait = self.database.query_images({"orientation": "portrait"})["items"][0]
        collection = self.database.create_collection("Temporária")
        self.database.update_image(
            portrait["id"],
            {"tags": ["temporária"], "collection_ids": [collection["id"]]},
        )

        removed = self.database.remove_root_from_catalog(self.root["id"])
        self.assertEqual(removed["image_count"], 3)
        self.assertEqual(removed["removed_thumbnails"], 3)
        self.assertEqual(self.database.list_roots(), [])
        self.assertEqual(self.database.counts()["total"], 0)
        self.assertEqual(self.database.list_tags(), [])
        self.assertEqual(self.database.list_collections()[0]["image_count"], 0)
        self.assertEqual(list((self.base / "data" / "thumbnails").rglob("*.jpg")), [])
        for path in self.source.glob("*.*"):
            self.assertEqual(self.original_hashes[path.name], sha256(path), path.name)

    def test_http_api_and_thumbnail(self) -> None:
        self.scan()
        server = DTIAHTTPServer(("127.0.0.1", 0), self.database, self.scanner)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            with urllib.request.urlopen(f"{base_url}/api/state") as response:
                state = json.loads(response.read().decode("utf-8"))
            self.assertEqual(state["counts"]["total"], 3)
            with urllib.request.urlopen(f"{base_url}/api/images?limit=1") as response:
                images = json.loads(response.read().decode("utf-8"))
            self.assertEqual(len(images["items"]), 1)
            image_id = images["items"][0]["id"]
            with urllib.request.urlopen(f"{base_url}/thumb/{image_id}") as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.headers["Content-Type"].startswith("image/"))
                self.assertGreater(len(response.read()), 100)
            request = urllib.request.Request(
                f"{base_url}/api/roots/{self.root['id']}?mode=catalog",
                method="DELETE",
            )
            with urllib.request.urlopen(request) as response:
                removed = json.loads(response.read().decode("utf-8"))
            self.assertTrue(removed["ok"])
            self.assertEqual(removed["image_count"], 3)
            self.assertEqual(self.database.counts()["total"], 0)
            self.assertTrue(all(path.exists() for path in self.source.glob("*.*")))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_windows_launchers_use_crlf(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        for filename in ("INSTALAR.bat", "INICIAR.bat", "ABRIR_DADOS.bat"):
            data = (project_root / filename).read_bytes()
            self.assertIn(b"\r\n", data, filename)
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""), filename)

    def test_source_management_controls_are_packaged(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        html = (project_root / "dtia" / "static" / "index.html").read_text(encoding="utf-8")
        javascript = (project_root / "dtia" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="sourceDialog"', html)
        self.assertIn('id="disconnectSource"', html)
        self.assertIn('id="removeSource"', html)
        self.assertIn('mode=${mode}', javascript)


if __name__ == "__main__":
    unittest.main()
