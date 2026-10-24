"""acca_corr.py: the multiples check.

    .venv/bin/python -B -m unittest tests.test_acca_corr

Synthetic data only, no cache needed. The pair sums are checked against
brute-force enumeration, because a closed-form sum that is off by one class
of pair would quietly measure the wrong correlation everywhere.
"""
import itertools
import json
import math
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import acca_corr as A  # noqa: E402


def ts(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()


def leg(event_id, result, fair, team="A", player=None, stat="Shots", line=1.5,
        kickoff=None, sport="football", over=True):
    return {"event_id": event_id, "team": team, "player": player, "stat": stat,
            "period": "ALL", "line": line, "over": over, "threshold": None,
            "fair": fair, "result": result, "sport": sport,
            "kickoff": kickoff or ts("2026-10-10 19:00")}


def item(category, legs, fair, result, snapshot=None):
    return {"category": category, "sport": "football", "fair": fair, "result": result,
            "legs": legs, "snapshot_at": snapshot or ts("2026-10-10 12:00")}


class Basics(unittest.TestCase):

    def test_night_runs_past_midnight(self):
        """A 1 a.m. tip-off belongs to the evening before it."""
        self.assertEqual(A.night_of(ts("2026-10-10 18:00")), "2026-10-10")
        self.assertEqual(A.night_of(ts("2026-10-11 00:30")), "2026-10-10")
        self.assertEqual(A.night_of(ts("2026-10-11 12:00")), "2026-10-11")

    def test_wilson(self):
        lo, hi = A.wilson(5, 10)
        self.assertAlmostEqual(lo, 0.2366, places=3)
        self.assertAlmostEqual(hi, 0.7634, places=3)
        self.assertEqual(A.wilson(0, 0), (0.0, 1.0))
        lo, hi = A.wilson(10, 10)
        self.assertEqual(hi, 1.0)
        self.assertGreater(lo, 0.6)

    def test_recal_recovers_a_known_curve(self):
        rng = np.random.default_rng(3)
        p = rng.uniform(0.2, 0.9, 40000)
        true = 1 / (1 + np.exp(-(0.3 + 0.7 * A._logit(p))))
        y = rng.random(len(p)) < true
        a, b = A.fit_recal(p, y)
        self.assertAlmostEqual(a, 0.3, delta=0.08)
        self.assertAlmostEqual(b, 0.7, delta=0.08)

    def test_recal_is_identity_when_thin(self):
        self.assertEqual(A.fit_recal([0.6] * 5, [1, 0, 1, 1, 0]), (0.0, 1.0))
        self.assertEqual(A.fit_recal([0.6] * 50, [1] * 50), (0.0, 1.0))

    def test_recalibrate_uses_training_rows_only(self):
        """Test rows whose outcomes flip must not move the fit."""
        rng = np.random.default_rng(5)
        n = 2000
        df = pd.DataFrame({"sport": "football", "kind": "team",
                           "p": rng.uniform(0.3, 0.8, n)})
        df["y"] = (rng.random(n) < df["p"]).astype(int)
        train = np.arange(n) < n // 2
        first = A.recalibrate(df, train)
        df.loc[~train, "y"] = 1 - df.loc[~train, "y"]
        second = A.recalibrate(df, train)
        self.assertTrue(np.allclose(first, second))

    def test_boot_ratio(self):
        num, den = np.array([1, 2, 3, 4.0]), np.array([2, 2, 2, 2.0])
        point, lo, hi = A.boot_ratio(num, den)
        self.assertAlmostEqual(point, 10 / 8)
        self.assertLessEqual(lo, point)
        self.assertGreaterEqual(hi, point)
        self.assertEqual(A.boot_ratio(num, den), A.boot_ratio(num, den))
        self.assertTrue(math.isnan(A.boot_ratio([], [])[0]))


class Pairs(unittest.TestCase):

    def frame(self):
        rng = np.random.default_rng(11)
        rows = []
        for night in ("n1", "n2"):
            for game in range(3):
                for side in ("H", "W"):
                    for who in ("TEAM", "p1", "p2"):
                        for stat in ("Shots", "Fouls"):
                            if rng.random() < 0.3:
                                continue
                            q = float(rng.uniform(0.3, 0.8))
                            rows.append({"night": night, "game": f"{night}g{game}",
                                         "side": f"{night}g{game}{side}", "who": who,
                                         "wstat": stat, "kind": "team" if who == "TEAM" else "player",
                                         "sport": "football", "p": q * 0.9, "q": q,
                                         "y": int(rng.random() < q)})
        return pd.DataFrame(rows)

    @staticmethod
    def brute(df):
        out = {name: np.zeros(6) for name, _, _ in A.CLASSES}
        recs = df.to_dict("records")
        for a, b in itertools.combinations(recs, 2):
            if a["night"] != b["night"]:
                continue
            if a["game"] != b["game"]:
                name = "cross game, same night"
            elif a["side"] != b["side"]:
                name = "same game, opposite sides"
            elif a["who"] != b["who"]:
                name = "same game, same side, different player or team leg"
            elif a["wstat"] != b["wstat"]:
                name = "same game, same team or player, different stat"
            else:
                continue
            ra, rb = a["y"] - a["q"], b["y"] - b["q"]
            sa, sb = math.sqrt(a["q"] * (1 - a["q"])), math.sqrt(b["q"] * (1 - b["q"]))
            out[name] += [1, a["y"] * b["y"], a["p"] * b["p"], a["q"] * b["q"], ra * rb, sa * sb]
        return out

    def test_pair_sums_match_enumeration(self):
        df = self.frame()
        got = A.pair_sums(df)
        want = self.brute(df)
        cols = ["pairs", "both", "said", "cal", "resid", "scale"]
        for name, _, _ in A.CLASSES:
            self.assertTrue(np.allclose(got[name][cols].sum().to_numpy(), want[name]), name)

    def test_kind_split_adds_up(self):
        df = self.frame()
        whole = A.pair_sums(df)
        parts = A.kind_pairs(df)
        for name, _, _ in A.CLASSES:
            total = sum(parts[k][name]["pairs"].sum() for k in parts if name in parts[k])
            self.assertAlmostEqual(total, whole[name]["pairs"].sum())

    def test_rho_finds_shared_game_and_not_across(self):
        """Legs sharing a latent game effect correlate inside the game only."""
        rng = np.random.default_rng(7)
        rows = []
        for night in range(60):
            for game in range(6):
                shock = rng.normal()
                for side in range(2):
                    for stat in range(3):
                        z = 0.2 + 0.9 * shock + rng.normal()
                        rows.append({"night": f"d{night}", "game": f"{night}-{game}",
                                     "side": f"{night}-{game}-{side}", "who": "TEAM",
                                     "wstat": str(stat), "p": 0.55, "y": int(z > 0)})
        df = pd.DataFrame(rows)
        df["q"] = df["y"].mean()
        s = A.pair_sums(df)
        same = A.summarise_pairs(s["same game, same team or player, different stat"])
        cross = A.summarise_pairs(s["cross game, same night"])
        self.assertGreater(same["rho"][1], 0.1)
        self.assertLess(abs(cross["rho"][0]), 0.05)

    def test_summarise_empty(self):
        self.assertEqual(A.summarise_pairs(None), {})


class Correction(unittest.TestCase):

    def test_no_correlation_is_the_product(self):
        self.assertAlmostEqual(A.corrected_joint([0.6, 0.7, 0.5], 0.0), 0.21)

    def test_positive_rho_raises_and_is_bounded(self):
        qs = [0.6, 0.7]
        lifted = A.corrected_joint(qs, 0.2)
        exact = 0.6 * 0.7 + 0.2 * math.sqrt(0.6 * 0.4 * 0.7 * 0.3)
        self.assertAlmostEqual(lifted, exact)
        self.assertLessEqual(A.corrected_joint(qs, 1.0), 0.6)
        self.assertGreaterEqual(A.corrected_joint(qs, -5.0), 0.0)

    def test_builder_fit_keeps_an_honest_joint_count(self):
        rng = np.random.default_rng(9)
        n = 20000
        said = rng.uniform(0.25, 0.6, n)
        df = pd.DataFrame({"said": said, "multiplied": said * rng.uniform(0.4, 0.9, n),
                           "won": (rng.random(n) < said).astype(int)})
        a, b, c = A.fit_builder(df)
        self.assertAlmostEqual(b, 1.0, delta=0.1)
        self.assertAlmostEqual(c, 0.0, delta=0.1)

    def test_builder_check_needs_both_sets(self):
        """A correction that helps the walk forward but hurts the record fails."""
        rng = np.random.default_rng(4)
        n = 6000
        said = rng.uniform(0.3, 0.6, n)
        walk = pd.DataFrame({"said": said, "multiplied": said * 0.5, "shown": True,
                             "won": (rng.random(n) < said * 0.7).astype(int),
                             "night": np.where(np.arange(n) < n // 2, "2025-01-01", "2026-06-01")})
        good = pd.DataFrame({"said": [0.5] * 400, "multiplied": [0.25] * 400,
                             "won": (rng.random(400) < 0.5).astype(int),
                             "night": [f"2026-10-{i % 28 + 1:02d}" for i in range(400)]})
        _, rows, holds = A.builder_check(walk, good, "2026-01-01")
        self.assertLess(rows[0]["ll_corrected"], rows[0]["ll_said"])
        self.assertGreater(rows[1]["ll_corrected"], rows[1]["ll_said"])
        self.assertFalse(holds)
        bad = good.assign(won=(rng.random(400) < 0.35).astype(int))
        _, _, holds = A.builder_check(walk, bad, "2026-01-01")
        self.assertTrue(holds)


class Record(unittest.TestCase):

    def items(self):
        k2 = ts("2026-10-10 20:00")
        return [
            item("Pick: acca", [leg(1, "win", 1.5), leg(2, "win", 2.0, team="B")], 3.0, "win"),
            item("Pick: acca", [leg(1, "win", 1.5), leg(3, "void", 2.0, team="C")], 3.0, "win"),
            item("Pick: builder", [leg(4, "win", 1.4, stat="Shots"), leg(4, "lose", 1.6, stat="Fouls"),
                                   leg(4, "win", 1.5, stat="Corners")], 2.2, "lose"),
            item("Pick: single", [leg(1, "win", 1.9)], 1.9, "win"),
            item("Fixture single", [leg(5, "lose", 1.8, kickoff=k2)], 1.8, "lose"),
            item("Pick: acca", [leg(6, None, 1.5), leg(7, None, 2.0)], 3.0, None),
        ]

    def test_multiples(self):
        m = A.multiples(self.items())
        self.assertEqual(len(m), 2)          # the void ticket and the open one are out
        acca = m[m["category"] == "acca"].iloc[0]
        self.assertEqual(acca["game"], "cross game")
        self.assertAlmostEqual(acca["said"], 1 / 3.0)
        self.assertAlmostEqual(acca["multiplied"], 1 / 3.0)
        b = m[m["category"] == "builder"].iloc[0]
        self.assertEqual(b["game"], "same game")
        self.assertAlmostEqual(b["said"], 1 / 2.2)
        self.assertAlmostEqual(b["multiplied"], 1 / (1.4 * 1.6 * 1.5))
        self.assertEqual(b["won"], 0)

    def test_settled_legs_once_each_at_first_price(self):
        items = self.items()
        later = item("Pick: single", [leg(1, "win", 1.2)], 1.2, "win",
                     snapshot=ts("2026-10-10 18:00"))
        legs = A.settled_legs(items + [later])
        ones = legs[(legs["game"] == 1) & (legs["stat"] == "Shots")]
        # fair 1.5 and 1.9 at 12:00 share a key; 1.2 at 18:00 is the same leg
        self.assertEqual(len(ones), 1)
        self.assertAlmostEqual(ones.iloc[0]["p"], 1 / 1.5)
        self.assertNotIn(3, set(legs["game"]))   # void
        self.assertNotIn(6, set(legs["game"]))   # open

    def test_lead_legs_settle_by_key(self):
        log = {"1": {"event_id": 1, "team": "A", "player": None, "stat": "Shots",
                     "period": "ALL", "line": 1.5, "over": True, "chance": 0.7,
                     "kickoff": ts("2026-10-10 19:00")},
               "9": {"event_id": 9, "team": "Z", "player": None, "stat": "Shots",
                     "period": "ALL", "line": 1.5, "over": True, "chance": 0.7,
                     "kickoff": ts("2026-10-10 19:00")}}
        leads = A.lead_legs(self.items(), log)
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads.iloc[0]["y"], 1)
        self.assertAlmostEqual(leads.iloc[0]["p"], 0.7)

    def test_report_without_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "best_bets.json"
            path.write_text(json.dumps(self.items()))
            old = A.BEST
            A.BEST = path
            try:
                text = A.report(use_cache=False)
            finally:
                A.BEST = old
        self.assertIn("## 1. Published multiples", text)
        self.assertIn("2 settled multiples", text)
        self.assertNotIn("\u2014", text)


class WalkForward(unittest.TestCase):

    def matches(self, n=30, spike_at=None):
        out = []
        for i in range(n):
            home, away = (1, 2) if i % 2 == 0 else (2, 1)
            shots = (9 + i % 5, 6 + i % 3)
            if spike_at is not None and i == spike_at:
                shots = (60, 60)
            out.append({"id": 100 + i, "ts": ts("2025-08-01 19:00") + i * 7 * 86400,
                        "sport": "football", "comp": "Premier League",
                        "home": home, "away": away, "home_name": str(home), "away_name": str(away),
                        "stats": {"Total shots": shots, "Corner kicks": (4 + i % 4, 3 + i % 2),
                                  "Yellow cards": (1 + i % 3, 2 + i % 2)}})
        return out

    def test_no_lookahead(self):
        """A match's own result must not reach the price of its own legs."""
        base, _ = A.team_legs(self.matches())
        spiked, _ = A.team_legs(self.matches(spike_at=25))
        key = lambda l: (l["game"], l["side"], l["stat"])  # noqa: E731
        a = {key(l): (l["line"], l["p"]) for l in base if l["game"] <= 125}
        b = {key(l): (l["line"], l["p"]) for l in spiked if l["game"] <= 125}
        self.assertEqual(a, b)
        self.assertTrue(a)

    def test_builder_joint_count(self):
        legs, builders = A.team_legs(self.matches())
        self.assertTrue(legs)
        for b in builders:
            self.assertGreaterEqual(b["said"], 0)
            self.assertLessEqual(b["said"], 1 / A.BUILDER_FLOOR + 1e-9)
            self.assertIn(b["won"], (0, 1))
        shown = [b for b in builders if b["shown"]]
        self.assertLessEqual(len(shown), len({(b["game"], b["side"]) for b in builders}))

    def test_synthetic_accas_one_leg_per_game(self):
        rows = [{"night": "n", "game": g, "p": 0.5, "q": 0.5, "y": 1} for g in range(5) for _ in range(2)]
        acc = A.synthetic_accas(pd.DataFrame(rows), sizes=(3,), per_night=5)
        self.assertEqual(len(acc), 5)
        self.assertTrue((acc["said"] == 0.125).all())
        self.assertTrue((acc["won"] == 1).all())


if __name__ == "__main__":
    unittest.main()
