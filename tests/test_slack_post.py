"""slack_post.py를 로컬 가짜 Slack 서버로 검증한다: python3 -m unittest discover tests"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


class FakeSlack(BaseHTTPRequestHandler):
    requests: list = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        FakeSlack.requests.append({"path": self.path, "auth": self.headers["Authorization"], "body": json.loads(body)})
        payload = json.dumps({"ok": True, "ts": "1760000000.000100"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class SlackPostTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        card_dir = Path(self._tmp.name) / "2026-10-19"
        card_dir.mkdir()
        self.card = card_dir / "381bbabb74.json"
        shutil.copy(FIXTURES / "card_sample.json", self.card)
        (card_dir / "381bbabb74.jpg").write_bytes(b"\xff\xd8fake")
        FakeSlack.requests = []
        self.server = HTTPServer(("127.0.0.1", 0), FakeSlack)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self._tmp.cleanup()

    def run_post(self, *extra, token="xoxb-test"):
        env = {**os.environ, "SLACK_API_BASE": f"http://127.0.0.1:{self.server.server_port}", "SLACK_BOT_TOKEN": token}
        args = [sys.executable, str(ROOT / "scripts" / "slack_post.py"), "--skip-url-check", *extra, str(self.card)]
        return subprocess.run(args, capture_output=True, text=True, env=env)

    def test_posts_image_and_buttons(self):
        result = self.run_post()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(FakeSlack.requests), 1)
        sent = FakeSlack.requests[0]
        self.assertEqual(sent["path"], "/chat.postMessage")
        self.assertEqual(sent["auth"], "Bearer xoxb-test")
        blocks = sent["body"]["blocks"]
        self.assertEqual(blocks[0]["image_url"], "https://raw.githubusercontent.com/plt8172/Semifeed/main/cards/2026-10-19/381bbabb74.jpg")
        buttons = blocks[-1]["elements"]
        self.assertEqual([b["action_id"] for b in buttons], ["approve", "reject"])
        self.assertTrue(all(b["value"] == "2026-10-19/381bbabb74" for b in buttons))

    def test_missing_image_is_rejected(self):
        self.card.with_suffix(".jpg").unlink()
        result = self.run_post()
        self.assertEqual(result.returncode, 1)
        self.assertIn("image not rendered", result.stderr)
        self.assertEqual(FakeSlack.requests, [])

    def test_long_caption_is_rejected(self):
        card = json.loads(self.card.read_text(encoding="utf-8"))
        card["caption"] = "가" * 2201
        self.card.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
        result = self.run_post()
        self.assertEqual(result.returncode, 1)
        self.assertIn("caption", result.stderr)

    def test_missing_token(self):
        result = self.run_post(token="")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(FakeSlack.requests, [])


if __name__ == "__main__":
    unittest.main()
