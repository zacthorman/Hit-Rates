"""context.shape / overload / ball_side: the game state's midfield and
possession claims can never be made for both sides of one game (2 Nov 2026,
Newcastle v Everton: both double pivots were called "outnumbered")."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import context  # noqa: E402


def lineup(formation):
    sizes = [int(x) for x in formation.split("-")]
    xi = [{"name": f"P{i}", "pos": "D"} for i in range(sum(sizes))]
    return {"formation": formation, "xi": xi}


def shp(formation):
    return context.shape({"lineups": {"confirmed": {"home": lineup(formation)}}}, "home")


class Shape(unittest.TestCase):
    def test_only_the_number_ten_is_between_the_lines_in_a_4231(self):
        s = shp("4-2-3-1")      # P0-P3 back four, P4 P5 pivot, P6 P7 P8 the three, P9 striker
        self.assertEqual(s["pivot"], ["P4", "P5"])
        self.assertEqual(s["between"], ["P7"])          # not the two wingers

    def test_other_shapes(self):
        self.assertEqual(shp("4-3-3")["pivot"], ["P5"])
        self.assertEqual(shp("4-3-3")["between"], ["P4", "P6"])          # the two eights
        self.assertEqual(shp("3-4-2-1")["between"], ["P7", "P8"])        # two tens
        self.assertEqual(shp("3-5-2")["pivot"], ["P5"])
        self.assertEqual(shp("3-5-2")["between"], ["P4", "P6"])
        self.assertEqual(shp("4-1-4-1")["between"], ["P6", "P7"])
        self.assertEqual(shp("4-4-2")["pivot"], [])                       # flat four: nothing claimed


class Overload(unittest.TestCase):
    FORMATIONS = ["4-2-3-1", "4-3-3", "3-4-2-1", "3-5-2", "4-1-4-1", "4-4-2", "4-2-2-2", "5-3-2"]

    def test_never_both_sides(self):
        for a in self.FORMATIONS:
            for b in self.FORMATIONS:
                x, y = shp(a), shp(b)
                one, two = context.overload(x, y), context.overload(y, x)
                stretched = [v for v in (one, two) if v in ("double", "single")]
                self.assertLessEqual(len(stretched), 1, f"{a} v {b}: {one}, {two}")
                if "even" in (one, two):
                    self.assertEqual(one, two, f"{a} v {b}")

    def test_mirror_is_even(self):
        self.assertEqual(context.overload(shp("4-2-3-1"), shp("4-2-3-1")), "even")

    def test_single_pivot_against_two_tens(self):
        self.assertEqual(context.overload(shp("4-3-3"), shp("3-4-2-1")), "single")
        self.assertIsNone(context.overload(shp("3-4-2-1"), shp("4-3-3")))

    def test_unknown_shape_says_nothing(self):
        self.assertIsNone(context.overload(None, shp("4-2-3-1")))
        self.assertIsNone(context.overload(shp("4-2-3-1"), {}))


class BallSide(unittest.TestCase):
    def test_game_state_projection_decides(self):
        gs = {"poss": [58.0, 42.0]}
        self.assertEqual(context.ball_side(gs, {}, {}, 0), 0)
        self.assertEqual(context.ball_side(gs, {}, {}, 1), 0)    # the same answer from either side

    def test_usual_possession_otherwise_and_only_one_side(self):
        a, b = {"possession": 61.0}, {"possession": 55.0}
        self.assertEqual(context.ball_side(None, a, b, 0), 0)     # side 0 asking: itself
        self.assertEqual(context.ball_side(None, b, a, 1), 0)     # side 1 asking: the other one
        self.assertIsNone(context.ball_side(None, a, dict(a), 0))


if __name__ == "__main__":
    unittest.main()
