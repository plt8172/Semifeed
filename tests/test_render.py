"""render.py의 레이아웃 선택을 검증한다 (브라우저 없이): python3 -m unittest discover tests"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    import render
except ImportError:  # playwright가 없는 환경
    render = None


@unittest.skipIf(render is None, "playwright not installed")
class LayoutTest(unittest.TestCase):
    def test_layouts_exist(self):
        self.assertIn("photo", render.layout_names())
        self.assertIn("classic", render.layout_names())

    def test_priority(self):
        config = {"card_layout": "classic"}
        self.assertEqual(render.choose_layout({}, None, {}), "photo")
        self.assertEqual(render.choose_layout({}, None, config), "classic")
        self.assertEqual(render.choose_layout({"layout": "photo"}, None, config), "photo")
        self.assertEqual(render.choose_layout({"layout": "photo"}, "classic", config), "classic")


if __name__ == "__main__":
    unittest.main()
