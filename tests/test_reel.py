"""reels/reel.py의 시간표 계산을 검증한다 (브라우저·TTS 없이): python3 -m unittest discover tests"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "reels"))

try:
    import reel
except ImportError:  # numpy/soundfile이 없는 환경
    reel = None


@unittest.skipIf(reel is None, "numpy/soundfile not installed")
class TimingTest(unittest.TestCase):
    def test_resolve_at(self):
        self.assertEqual(reel.resolve_at(1.5, 0.3, 4.0), 1.5)
        self.assertAlmostEqual(reel.resolve_at("vo:0.5", 0.3, 4.0), 2.3)
        self.assertAlmostEqual(reel.resolve_at("vo+0.5", 0.3, 4.0), 4.8)
        with self.assertRaises(ValueError):
            reel.resolve_at("later", 0.3, 4.0)

    def test_caption_chunks_keep_thousands(self):
        self.assertEqual(reel.caption_chunks("1초에 8,000번 재고, 8칸으로 적어요."),
                         ["1초에 8,000번 재고", "8칸으로 적어요"])

    def test_example_episode_passes_check(self):
        self.assertEqual(reel.check(ROOT / "reels" / "episodes" / "vocoding"), [])


if __name__ == "__main__":
    unittest.main()
