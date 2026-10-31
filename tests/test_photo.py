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


def fake_hit(base: str, photo_id: int, width: int = 5000, height: int = 3333, fresh: bool = False,
             tags: str = "chip, wafer") -> dict:
    return {
        "id": photo_id,
        "imageWidth": width,
        "imageHeight": height,
        "pageURL": f"https://pixabay.com/photos/chip-{photo_id}/",
        "user": "maker",
        "user_id": 77,
        "tags": tags,
        "largeImageURL": f"{base}/img/px{photo_id}{'-fresh' if fresh else ''}.jpg",
        "webformatURL": f"{base}/img/thumb{photo_id}.jpg",
    }


class FakePexels(BaseHTTPRequestHandler):
    requests: list = []
    base = ""
    empty_queries: set = set()  # 결과가 없는 검색어

    def do_GET(self):
        parts = urlsplit(self.path)
        FakePexels.requests.append({"path": parts.path, "query": parse_qs(parts.query), "auth": self.headers.get("Authorization")})
        if parts.path == "/api/":
            q = parse_qs(parts.query)
            hits = [fake_hit(self.base, 200, width=1000, height=700), fake_hit(self.base, 201), fake_hit(self.base, 202),
                    fake_hit(self.base, 203, tags="cupcakes, dessert, food"),  # 'wafer'가 과자로 나오던 사례
                    fake_hit(self.base, 204, tags="worker, beautiful girl, chip")]
            if q.get("category") == ["science"]:
                hits = [fake_hit(self.base, 201), fake_hit(self.base, 205), fake_hit(self.base, 206)]
            if "id" in q:
                hits = [fake_hit(self.base, int(q["id"][0]), fresh=True)]
            body, content_type = json.dumps({"hits": hits}).encode(), "application/json"
        elif parts.path == "/v1/search":
            photos = [
                fake_photo(self.base, 100, width=1200, height=800),  # 너무 작다
                fake_photo(self.base, 101, width=2000, height=3000),  # 세로
                fake_photo(self.base, 102),
                fake_photo(self.base, 103),
                fake_photo(self.base, 104),
            ]
            q = parse_qs(parts.query)
            if q["query"][0] in self.empty_queries or q.get("page") != ["1"]:
                photos = []
            elif q["query"][0] == "second query":
                photos = [fake_photo(self.base, 300)]
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
        FakePexels.empty_queries = set()
        self.server = HTTPServer(("127.0.0.1", 0), FakePexels)
        FakePexels.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self._tmp.cleanup()

    def run_photo(self, *extra, key="test-key", card=None, provider="pexels"):
        env = {**os.environ, "PEXELS_API_BASE": f"{FakePexels.base}/v1", "PIXABAY_API_BASE": f"{FakePexels.base}/api",
               "PEXELS_API_KEY": key, "PIXABAY_API_KEY": key}
        args = [sys.executable, str(ROOT / "scripts" / "photo.py"), "--cards-dir", str(self.cards_dir),
                "--provider", provider, *extra, str(card or self.card)]
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

    def make_other_card(self, **fields):
        other = self.card.with_name("aaaaaaaaaa.json")
        data = self.load()
        data.pop("photo", None)
        data.update(fields)
        other.write_text(json.dumps(data), encoding="utf-8")
        return other

    def test_skips_photographer_used_by_recent_card(self):
        self.run_photo()
        card = self.load()
        card["photo"]["photographer_url"] = "https://www.pexels.com/@author103"  # 103의 작가가 쓴 것으로
        self.card.write_text(json.dumps(card), encoding="utf-8")
        other = self.make_other_card()
        result = self.run_photo(card=other)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.load(other)["photo"]["id"], "104")

    def test_falls_back_to_next_query(self):
        FakePexels.empty_queries = {"first query"}
        other = self.make_other_card(photo_queries=["first query", "second query"])
        result = self.run_photo(card=other)
        self.assertEqual(result.returncode, 0, result.stderr)
        photo = self.load(other)["photo"]
        self.assertEqual((photo["id"], photo["query"]), ("300", "second query"))
        searched = [r["query"]["query"][0] for r in FakePexels.requests if r["path"] == "/v1/search"]
        self.assertEqual(searched, ["first query", "second query"])

    def test_no_result_for_any_query_is_soft_failure(self):
        FakePexels.empty_queries = {"first query", "other query"}
        other = self.make_other_card(photo_queries=["first query", "other query"])
        result = self.run_photo(card=other)
        self.assertEqual(result.returncode, 3)
        self.assertIn("0 results", result.stderr)

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
        self.assertIn("photo_queries", result.stderr)

    def test_pixabay_picks_and_refreshes_by_id(self):
        result = self.run_photo(provider="pixabay")
        self.assertEqual(result.returncode, 0, result.stderr)
        search = FakePexels.requests[0]
        self.assertEqual(search["query"]["key"], ["test-key"])
        self.assertEqual(search["query"]["q"], ["silicon wafer cleanroom"])
        photo = self.load()["photo"]
        self.assertEqual((photo["provider"], photo["id"]), ("pixabay", "201"))
        self.assertEqual(photo["credit"], "Photo: maker / Pixabay")
        self.assertEqual(photo["photographer_url"], "https://pixabay.com/users/maker-77/")
        self.assertNotIn("test-key", json.dumps(photo))
        # 임시 이미지 주소 대신 id로 새 주소를 받아 다시 내려받는다.
        self.card.with_name("381bbabb74.photo.jpg").unlink()
        FakePexels.requests = []
        result = self.run_photo(provider="pixabay")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([r["path"] for r in FakePexels.requests], ["/api/", "/img/px201-fresh.jpg"])

    def run_candidates(self, *extra):
        config = Path(self._tmp.name) / "config.json"
        config.write_text(json.dumps({"photo_fallback_queries": [{"query": "semiconductor", "category": "science"}]}))
        return self.run_photo("--config", str(config), *extra, provider="pixabay")

    def test_candidates_collects_card_and_fallback_queries(self):
        result = self.run_candidates("--candidates")
        self.assertEqual(result.returncode, 0, result.stderr)
        folder = self.card.with_name("381bbabb74.candidates")
        listing = json.loads((folder / "list.json").read_text())
        # 200은 작고, 203·204는 태그로 빠진다. 201은 카드 검색어에서 이미 나와 일반 검색어 쪽에서는 205가 들어간다.
        self.assertEqual([(c["id"], c["label"]) for c in listing["candidates"]], [("201", "q1"), ("202", "q1"), ("205", "f1")])
        self.assertTrue((folder / "205.jpg").is_file())
        searches = [r["query"] for r in FakePexels.requests if r["path"] == "/api/"]
        self.assertEqual([s.get("category") for s in searches], [None, ["science"]])
        self.assertNotIn("photo", self.load())  # 후보 모드는 고르지 않는다

    def test_pick_attaches_candidate(self):
        self.run_candidates("--candidates")
        result = self.run_candidates("--pick", "205")
        self.assertEqual(result.returncode, 0, result.stderr)
        photo = self.load()["photo"]
        self.assertEqual((photo["id"], photo["query"], photo["category"]), ("205", "semiconductor", "science"))
        self.assertEqual(self.card.with_name("381bbabb74.photo.jpg").read_bytes(), JPEG)
        # 이미 사진이 있는 카드는 후보를 다시 모으지 않는다
        result = self.run_candidates("--candidates")
        self.assertIn("already has photo 205", result.stderr)

    def test_pick_rejects_non_candidate_and_photo_used_elsewhere(self):
        self.run_candidates("--candidates")
        self.assertEqual(self.run_candidates("--pick", "999").returncode, 3)
        other = self.make_other_card(photo={"provider": "pixabay", "id": "202"})
        result = self.run_candidates("--pick", "202")
        self.assertEqual(result.returncode, 3)
        self.assertIn("already used", result.stderr)
        other.unlink()

    def test_missing_key(self):
        result = self.run_photo(key="")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(FakePexels.requests, [])


if __name__ == "__main__":
    unittest.main()
