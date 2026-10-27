"""fetch.py를 로컬 피드 파일로 검증한다: python3 -m unittest discover tests"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "scripts"))
from common import card_id, normalize_link  # noqa: E402


def run_fetch(tmp: Path, *feeds: str, seen: dict | None = None) -> tuple[int, dict]:
    seen_path = tmp / "seen.json"
    seen_path.write_text(json.dumps({"links": seen or {}}), encoding="utf-8")
    out = tmp / "candidates.json"
    args = [sys.executable, str(ROOT / "scripts" / "fetch.py"), "--seen", str(seen_path), "--out", str(out), "--now", "2026-10-19T12:00:00+09:00"]
    for feed in feeds:
        args += ["--feed", str(FIXTURES / feed)]
    result = subprocess.run(args, capture_output=True, text=True)
    return result.returncode, json.loads(out.read_text(encoding="utf-8"))


class FetchTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def titles(self, data):
        return {c["title"] for c in data["candidates"]}

    def test_window_and_duplicate_links(self):
        code, data = run_fetch(self.tmp, "rss2.xml")
        self.assertEqual(code, 0)
        # 72시간 밖 기사와 추적 파라미터만 다른 중복 기사는 빠진다.
        self.assertEqual(self.titles(data), {"TSMC raises 2nm capacity plan", "Already processed HBM4 story"})

    def test_seen_links_are_skipped(self):
        seen = {normalize_link("https://example-semi.com/news/hbm4-ramp"): "2026-10-18T20:00:00+09:00"}
        _, data = run_fetch(self.tmp, "rss2.xml", seen=seen)
        self.assertNotIn("Already processed HBM4 story", self.titles(data))

    def test_atom_and_euckr(self):
        _, data = run_fetch(self.tmp, "atom.xml", "euckr.xml")
        self.assertEqual(self.titles(data), {"Intel ships 18A test chips", "삼성전자, HBM4 12단 양산 돌입"})
        atom = next(c for c in data["candidates"] if c["source"] == "atom.example.org")
        self.assertEqual(atom["summary"], "Foundry Intel says 18A yields improve.")
        self.assertEqual(atom["published_at"], "2026-10-19T06:15+09:00")

    def test_broken_feed_does_not_stop_others(self):
        code, data = run_fetch(self.tmp, "broken.xml", "atom.xml")
        self.assertEqual(code, 0)
        self.assertFalse(data["feeds"][0]["ok"])
        self.assertEqual(len(data["candidates"]), 1)

    def test_all_feeds_failing_exits_nonzero(self):
        code, _ = run_fetch(self.tmp, "broken.xml")
        self.assertEqual(code, 1)

    def test_source_name_from_config(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from fetch import source_name
        names = {"etnews.com": "전자신문"}
        self.assertEqual(source_name("rss.etnews.com", names), "전자신문")
        self.assertEqual(source_name("etnews.com", names), "전자신문")
        self.assertEqual(source_name("notetnews.com", names), "notetnews.com")

    def test_card_id_is_stable_across_tracking_params(self):
        self.assertEqual(
            card_id("https://www.example-semi.com/news/tsmc-2nm?utm_source=rss"),
            card_id("https://example-semi.com/news/tsmc-2nm/"),
        )


if __name__ == "__main__":
    unittest.main()
