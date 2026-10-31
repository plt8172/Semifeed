"""contact_sheet.py가 이번 카드 사진과 최근 카드를 고르는지 검증한다: python3 -m unittest discover tests"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
try:
    import contact_sheet
except ImportError:  # playwright가 없는 환경
    contact_sheet = None

KST = timezone(timedelta(hours=9))


@unittest.skipIf(contact_sheet is None, "playwright not installed")
class ContactSheetTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cards = Path(self._tmp.name)
        self.now = datetime(2026, 10, 29, 20, 0, tzinfo=KST)

    def tearDown(self):
        self._tmp.cleanup()

    def card(self, day: str, card_id: str, photo_id: str | None, rendered: bool = True) -> Path:
        path = self.cards / day / f"{card_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"id": card_id, **({"photo": {"id": photo_id, "file": f"{card_id}.photo.jpg"}} if photo_id else {})}
        path.write_text(json.dumps(data), encoding="utf-8")
        if rendered:
            path.with_suffix(".jpg").write_bytes(b"\xff\xd8fake")
        return path

    def test_recent_cards_with_photo_only(self):
        new = self.card("2026-10-29", "new0000001", "9", rendered=False)
        self.card("2026-10-29", "today00001", "1")
        self.card("2026-10-28", "nophoto001", None)
        self.card("2026-10-27", "older00001", "2")
        self.card("2026-10-20", "tooold0001", "3")
        recent = contact_sheet.recent_cards(self.cards, self.now, 3, {new.resolve()})
        self.assertEqual([p.stem for p in recent], ["today00001", "older00001"])
        page = contact_sheet.build([new], recent, 3)
        self.assertIn("new0000001 · 9", page)
        self.assertIn("10-27 · 2", page)
        self.assertIn("사진 없음", page)  # 이번 카드 사진 파일이 아직 없다

    def test_candidate_rows_for_cards_without_photo(self):
        new = self.card("2026-10-29", "new0000002", None, rendered=False)
        folder = new.with_name("new0000002.candidates")
        folder.mkdir()
        (folder / "55.jpg").write_bytes(b"\xff\xd8fake")
        (folder / "list.json").write_text(json.dumps({"provider": "pixabay", "candidates": [
            {"id": "55", "label": "q1", "thumb": "55.jpg"}, {"id": "66", "label": "f2", "thumb": "66.jpg"}]}))
        page = contact_sheet.build([new], [], 3)
        self.assertIn("new0000002 후보", page)
        self.assertIn("55 · q1", page)
        self.assertIn("66 · f2", page)
        self.assertNotIn("new0000002 · -", page)  # 후보가 있는 카드는 윗줄에 다시 나오지 않는다
        self.assertEqual(page.count("data:image/jpeg"), 1)  # 썸네일이 있는 후보만 그림이 들어간다


if __name__ == "__main__":
    unittest.main()
