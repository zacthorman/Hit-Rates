"""parlay_check.py: corrections, settlement and the published record.

    python -B -m unittest tests.test_parlay_check

Synthetic data only, no cache needed.
"""
import json
import math
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import parlay_check as P  # noqa: E402


def ticket(sides, won=1, night="2026-01-01"):
    """sides: list of (joint hits, joint total, [(leg hits, leg total), ...])."""
    legs, out_sides = [], []
    for t, (h, n, ls) in enumerate(sides):
        idx = []
        for lh, ln in ls:
            idx.append(len(legs))
            legs.append({"team": t, "player": f"p{len(legs)}", "stat": "Shots", "threshold": 1.0,
                         "hits": lh, "total": ln, "y": won})
        out_sides.append({"team": t, "hits": h, "total": n, "y": won, "legs": idx})
    said = math.prod(h / n for h, n, _ in sides)
    return {"night": night, "game": 1, "said": said, "fair": 1 / said, "legs": legs,
            "sides": out_sides, "won": won, "void": False}


class Corrections(unittest.TestCase):

    def test_shrink_zero_is_the_page(self):
        r = ticket([(6, 20, [(14, 20), (13, 20)]), (9, 18, [(12, 18), (13, 18)])])
        self.assertAlmostEqual(P.shrunk(r, 0), r["said"])

    def test_shrink_large_is_the_product_of_legs(self):
        r = ticket([(6, 20, [(14, 20), (13, 20)]), (9, 18, [(12, 18), (13, 18)])])
        self.assertAlmostEqual(P.shrunk(r, 1e9), P.multiplied(r), places=6)

    def test_shrink_sits_between(self):
        r = ticket([(12, 20, [(14, 20), (13, 20)])])
        lo, hi = sorted((r["said"], P.multiplied(r)))
        p = P.shrunk(r, 10)
        self.assertTrue(lo < p < hi)

    def test_recal_prior_is_identity(self):
        r = ticket([(7, 20, [(14, 20), (13, 20), (15, 20)])])
        self.assertAlmostEqual(P.recal(r, (0.0, 1.0, 0.0)), r["said"], places=9)

    def test_fit_k_finds_selection_optimism(self):
        """Independent legs, true chance the product; the shown side is the
        best joint count of twenty drawn on 15 matches. That joint count is
        lucky, so the fitted shrink must pull it back (k > 0)."""
        rnd = random.Random(1)
        rows = []
        for i in range(600):
            best = None
            for _ in range(20):
                qs = [rnd.uniform(0.6, 0.8) for _ in range(3)]
                n = 15
                joint = sum(all(rnd.random() < q for q in qs) for _ in range(n))
                if joint < 2:
                    continue
                legs = [(round(q * n), n) for q in qs]
                if best is None or joint > best[0]:
                    best = (joint, n, legs, qs)
            joint, n, legs, qs = best
            won = int(all(rnd.random() < q for q in qs))
            rows.append(ticket([(joint, n, legs)], won=won, night=f"n{i % 50}"))
        k = P.fit_k(rows)
        self.assertGreater(k, 0)
        ys = [r["won"] for r in rows]
        self.assertLess(P.log_loss([P.shrunk(r, k) for r in rows], ys),
                        P.log_loss([r["said"] for r in rows], ys))

    def test_fit_recal_on_calibrated_data_stays_near_identity(self):
        rnd = random.Random(2)
        rows = []
        for i in range(3000):
            h = rnd.randint(4, 14)
            r = ticket([(h, 20, [(15, 20), (15, 20)])], night=f"n{i % 60}")
            r["won"] = int(rnd.random() < r["said"])
            rows.append(r)
        a, b, c = P.fit_recal(rows)
        self.assertAlmostEqual(b, 1.0, delta=0.25)
        self.assertAlmostEqual(a + c * P._logit(P.multiplied(rows[0])), 0.0, delta=0.3)


class Intervals(unittest.TestCase):

    def test_boot_ratio_contains_point(self):
        rows = [{"night": f"n{i % 30}", "won": i % 3 == 0, "said": 0.33} for i in range(300)]
        r, lo, hi = P.boot_ratio(rows, lambda r: r["won"], lambda r: r["said"])
        self.assertTrue(lo <= r <= hi)
        self.assertAlmostEqual(r, 1.0, delta=0.05)

    def test_wilson(self):
        lo, hi = P.wilson(27, 86)
        self.assertTrue(lo < 27 / 86 < hi)


class Settlement(unittest.TestCase):

    def lineup(self, stats, sub=False):
        return {"home": {"players": [{"player": {"name": "A"}, "substitute": sub, "statistics": stats}]},
                "away": {"players": []}}

    def test_no_statistics_is_void(self):
        self.assertIsNone(P.settle(self.lineup({}), 0, "A", "Shots", 1.0, "football"))

    def test_unused_sub_is_void(self):
        lu = self.lineup({"minutesPlayed": 0, "totalShots": 0}, sub=True)
        self.assertIsNone(P.settle(lu, 0, "A", "Shots", 1.0, "football"))

    def test_absent_is_void(self):
        self.assertIsNone(P.settle(self.lineup({"minutesPlayed": 90}), 0, "B", "Shots", 1.0, "football"))

    def test_short_appearance_counts_and_zero_fills(self):
        lu = self.lineup({"minutesPlayed": 12})
        self.assertEqual(P.settle(lu, 0, "A", "Shots", 1.0, "football"), 0)

    def test_over_threshold_lands(self):
        lu = self.lineup({"minutesPlayed": 90, "totalShots": 3})
        self.assertEqual(P.settle(lu, 0, "A", "Shots", 3.0, "football"), 1)
        self.assertEqual(P.settle(lu, 0, "A", "Shots", 4.0, "football"), 0)


class Squad(unittest.TestCase):

    def test_recent_squad_drops_players_gone_from_the_last_matches(self):
        recs = []
        for m in range(10):
            recs.append({"player": "stays", "match_id": m, "date": f"2026-01-{m + 1:02d}"})
            if m < 6:
                recs.append({"player": "left", "match_id": m, "date": f"2026-01-{m + 1:02d}"})
        kept = P.recent_squad(recs, last=3)
        self.assertEqual({r["player"] for r in kept}, {"stays"})
        self.assertEqual(len(kept), 10)


class Published(unittest.TestCase):

    def test_published_dedupes_and_skips_voids(self):
        leg = {"event_id": 5, "kickoff": 1_790_000_000, "team": "X", "player": "A", "stat": "Shots",
               "threshold": 1.0, "hits": 14, "total": 20, "result": "win"}
        items = [
            {"category": "Pick: parlay", "sport": "football", "fair": 4.0, "result": "win",
             "legs": [dict(leg), dict(leg, player="B", team="Y")]},
            {"category": "Pick: parlay", "sport": "football", "fair": 4.0, "result": "win",
             "legs": [dict(leg), dict(leg, player="B", team="Y")]},
            {"category": "Pick: parlay", "sport": "football", "fair": 4.0, "result": "lose",
             "legs": [dict(leg, player="C"), dict(leg, player="D", result="void")]},
            {"category": "Pick: acca", "sport": "football", "fair": 4.0, "result": "win", "legs": [leg]},
        ]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "best.json"
            path.write_text(json.dumps(items))
            pub = P.published(path)
        self.assertEqual(len(pub), 1)
        self.assertEqual([l["team"] for l in pub[0]["legs"]], [0, 1])
        self.assertAlmostEqual(pub[0]["said"], 0.25)

    def test_attach_sides_needs_the_same_price(self):
        pub = [{"game": 1, "said": 0.25, "keys": [["A", "Shots", 1.0]],
                "legs": [{"player": "A", "stat": "Shots", "threshold": 1.0, "y": 1}], "sides": None}]
        walk = [{"game": 1, "said": 0.25, "keys": [["A", "Shots", 1.0]],
                 "legs": [{"player": "A", "stat": "Shots", "threshold": 1.0, "team": 0, "hits": 5,
                           "total": 20, "y": 0}],
                 "sides": [{"team": 0, "hits": 5, "total": 20, "legs": [0]}]}]
        self.assertEqual(P.attach_sides(pub, walk), 1)
        self.assertEqual(pub[0]["legs"][0]["y"], 1)     # the published result, not the rebuild's
        pub[0]["sides"] = None
        walk[0]["said"] = 0.3
        self.assertEqual(P.attach_sides(pub, walk), 0)


if __name__ == "__main__":
    unittest.main()
