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
        words = [{"w": "1초에", "t0": 11.0}, {"w": "8,000번", "t0": 11.5}]
        clips = [{"t0": 14.2}]
        self.assertAlmostEqual(reel.resolve_at(0.5, 10.0, 13.0, words, clips), 10.5)
        self.assertAlmostEqual(reel.resolve_at("end", 10.0, 13.0, words, clips), 13.0)
        self.assertAlmostEqual(reel.resolve_at("end+0.3", 10.0, 13.0, words, clips), 13.3)
        self.assertAlmostEqual(reel.resolve_at("w:8,000", 10.0, 13.0, words, clips), 11.5)
        self.assertAlmostEqual(reel.resolve_at("w:0", 10.0, 13.0, words, clips), 11.0)
        self.assertAlmostEqual(reel.resolve_at("clip:0", 10.0, 13.0, words, clips), 14.2)
        with self.assertRaises(ValueError):
            reel.resolve_at("later", 10.0, 13.0, words, clips)

    def test_words_follow_pauses(self):
        # 쉼이 구 개수와 맞으면 구마다 실제 소리 구간에 맞춘다. 숫자 사이 쉼표(8,000)는 끊지 않는다
        w = reel.word_times("그대로 보내려면, 1초에 8,000번 재요.", "그대로 보내려면, 일초에 팔천번 재요.", 3.0, [(0.0, 1.0), (1.4, 3.0)])
        self.assertEqual([x["w"] for x in w], ["그대로", "보내려면,", "1초에", "8,000번", "재요."])
        self.assertAlmostEqual(w[2]["t0"], 1.4)
        self.assertAlmostEqual(w[1]["t1"], 1.0)
        self.assertAlmostEqual(w[-1]["t1"], 3.0)

    def test_words_fall_back_to_proportional(self):
        w = reel.word_times("하나, 둘 셋.", "하나, 둘 셋.", 2.0, [(0.0, 2.0)])
        self.assertAlmostEqual(w[0]["t0"], 0.0)
        self.assertAlmostEqual(w[-1]["t1"], 2.0)
        self.assertTrue(all(a["t1"] <= b["t0"] + 1e-9 for a, b in zip(w, w[1:])))

    def test_caption_groups(self):
        w = reel.word_times("그대로 보내려면, 이 떨림을 1초에 8,000번 재야 해요.", "", 3.0, [])
        groups = [[x["w"] for x in g] for g in reel.caption_groups(w)]
        self.assertEqual(groups[0], ["그대로", "보내려면,"])
        self.assertEqual(sum(groups, []), [x["w"] for x in w])
        self.assertTrue(all(sum(map(len, g)) <= reel.CAPTION_MAX + 4 for g in groups))

    def test_heard_ratio(self):
        # 문장부호·띄어쓰기는 보지 않고, 숫자는 say(한글)와 caption(아라비아 숫자) 중 가까운 쪽과 비교한다
        say, cap = "이 떨림을 일초에 팔천번 재야 해요.", "이 떨림을 1초에 8,000번 재야 해요."
        self.assertEqual(reel.heard_ratio("이 떨림을 1초에 8000번 재야 해요", say, cap), 1.0)
        self.assertEqual(reel.heard_ratio("이떨림을 일초에 팔천번 재야해요.", say, cap), 1.0)
        self.assertLess(reel.heard_ratio("이 을 1초에 8000번 제하해요.", say, cap), 0.9)
        self.assertEqual(reel.heard_ratio("아무 말", "", ""), 0.0)

    def test_example_episode_passes_check(self):
        self.assertEqual(reel.check(ROOT / "reels" / "episodes" / "vocoding"), [])


if __name__ == "__main__":
    unittest.main()
