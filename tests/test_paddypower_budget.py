"""2 Nov 2026: Paddy Power's daily cap keeps a reserve for NBA / NFL tip-offs."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paddypower_prices as pp  # noqa: E402

NOW = 1_800_000_000.0


def c(hours, us, fid):
    return (NOW + hours * 3600, fid, "x", "A @ B" if us else "A v B")


class Budget(unittest.TestCase):
    def setUp(self):
        self.was = pp.now
        pp.now = lambda: NOW

    def tearDown(self):
        pp.now = self.was

    def test_us_tipoffs_first_and_reserve_held_back_from_football(self):
        todo = [c(1, False, "f1"), c(2, True, "u1"), c(10, False, "f2")]
        got = pp.choose(todo, left=22, by_hand=False, held={}, us_ahead=10)
        self.assertEqual(got[0][1], "u1")
        self.assertIn("f1", [x[1] for x in got])      # 22 left - 10 held still leaves room
        self.assertNotIn("f2", [x[1] for x in got])   # far football waits behind the reserves

    def test_reserve_blocks_football_when_tight(self):
        todo = [c(1, False, "f1"), c(2, True, "u1")]
        got = pp.choose(todo, left=5, by_hand=False, held={}, us_ahead=10)
        self.assertEqual([x[1] for x in got], ["u1"])

    def test_far_us_game_fetched_once(self):
        todo = [c(10, True, "u2"), c(11, True, "u3")]
        got = pp.choose(todo, left=60, by_hand=False, held={"u2": {"fetchedAt": NOW - 9 * 3600}}, us_ahead=0)
        self.assertEqual([x[1] for x in got], ["u3"])

    def test_by_hand_ignores_reserves(self):
        todo = [c(1, False, "f1"), c(10, False, "f2")]
        got = pp.choose(todo, left=3, by_hand=True, held={}, us_ahead=10)
        self.assertEqual([x[1] for x in got], ["f1", "f2"])


if __name__ == "__main__":
    unittest.main()
