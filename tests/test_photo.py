"""photo.py를 로컬 가짜 Pexels 서버로 검증한다: python3 -m unittest discover tests"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


def fake_photo(base: str, photo_id: int, width: int = 4000, height: int = 2667) -> dict:
    return {
        "id": photo_id,
        "width": width,
        "height": height,
        "url": f"https://www.pexels.com/photo/{photo_id}/",
        "photographer": f"Author {photo_id}",
        "photographer_url": f"https://www.pexels.com/@author{photo_id}",
        "alt": f"Silicon wafer {photo_id}",
        "src": {"large2x": f"{base}/img/{photo_id}.jpeg"},
    }


class FakePexels(BaseHTTPRequestHandler):
    requests: list = []
    base = ""

    def do_GET(self):
        parts = urlsplit(self.path)
        FakePexels.requests.append({"path": parts.path, "query": parse_qs(parts.query), "auth": self.headers.get("Authorization")})
        if parts.path == "/v1/search":
            photos = [
                fake_photo(self.base, 100, width=1200, height=800),  # 너무 작다
                fake_photo(self.base, 101, width=2000, height=3000),  # 세로
                fake_photo(self.base, 102),
                fake_photo(self.base, 103),
                fake_photo(self.base, 104),
            ]
            body, content_type = json.dumps({"photos": photos}).encode(), "application/json"
        elif parts.path.startswith("/img/"):
            body, content_type = JPEG, "image/jpeg"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class PhotoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cards_dir = Path(self._tmp.name) / "cards"
        self.today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
        card_dir = self.cards_dir / self.today
        card_dir.mkdir(parents=True)
        self.card = card_dir / "381bbabb74.json"
        data = json.loads((FIXTURES / "card_sample.json").read_text(encoding="utf-8"))
        data["photo_query"] = "silicon wafer cleanroom"
        self.card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        FakePexels.requests = []
        self.server = HTTPServer(("127.0.0.1", 0), FakePexels)
        FakePexels.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self._tmp.cleanup()

    def run_photo(self, *extra, key="test-key", card=None):
        env = {**os.environ, "PEXELS_API_BASE": f"{FakePexels.base}/v1", "PEXELS_API_KEY": key}
        args = [sys.executable, str(ROOT / "scripts" / "photo.py"), "--cards-dir", str(self.cards_dir), *extra, str(card or self.card)]
        return subprocess.run(args, capture_output=True, text=True, env=env)

    def load(self, path=None):
        return json.loads((path or self.card).read_text(encoding="utf-8"))

    def test_picks_first_large_landscape_and_records_credit(self):
        result = self.run_photo()
        self.assertEqual(result.returncode, 0, result.stderr)
        search = FakePexels.requests[0]
        self.assertEqual(search["auth"], "test-key")
        self.assertEqual(search["query"]["query"], ["silicon wafer cleanroom"])
        photo = self.load()["photo"]
        self.assertEqual(photo["id"], "102")
        self.assertEqual(photo["file"], "381bbabb74.photo.jpg")
        self.assertEqual(photo["credit"], "Photo: Author 102 / Pexels")
        self.assertEqual(photo["license_url"], "https://www.pexels.com/license/")
        self.assertEqual(self.card.with_name("381bbabb74.photo.jpg").read_bytes(), JPEG)

    def test_existing_photo_is_kept_and_redownloaded(self):
        self.run_photo()
        self.card.with_name("381bbabb74.photo.jpg").unlink()
        FakePexels.requests = []
        result = self.run_photo()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([r["path"] for r in FakePexels.requests], ["/img/102.jpeg"])
        self.assertEqual(self.load()["photo"]["id"], "102")

    def test_exclude_picks_next(self):
        self.run_photo()
        result = self.run_photo("--exclude", "102")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.load()["photo"]["id"], "103")

    def test_skips_photo_used_by_recent_card(self):
        self.run_photo()
        other = self.card.with_name("aaaaaaaaaa.json")
        shutil.copy(self.card, other)
        data = self.load(other)
        data.pop("photo")
        other.write_text(json.dumps(data), encoding="utf-8")
        result = self.run_photo(card=other)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.load(other)["photo"]["id"], "103")

    def test_clear_removes_record_and_file(self):
        self.run_photo()
        result = self.run_photo("--clear", key="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("photo", self.load())
        self.assertFalse(self.card.with_name("381bbabb74.photo.jpg").exists())

    def test_missing_query_is_soft_failure(self):
        data = self.load()
        data.pop("photo_query")
        self.card.write_text(json.dumps(data), encoding="utf-8")
        result = self.run_photo()
        self.assertEqual(result.returncode, 3)
        self.assertIn("photo_query", result.stderr)

    def test_missing_key(self):
        result = self.run_photo(key="")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(FakePexels.requests, [])


if __name__ == "__main__":
    unittest.main()
