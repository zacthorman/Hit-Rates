"""strength.py and the strength-aware picks in weekend.py.

    .venv/bin/python -B -m unittest tests.test_strength

Synthetic events only, no cache needed, except the last test, which reads the
built reports if there are any and is skipped otherwise.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import learner   # noqa: E402
import strength  # noqa: E402
import weekend   # noqa: E402


def setUpModule():
    # weekend.calibrate refits learner's correction, which writes it to
    # learned.json. That file is committed, so a test run must not touch it.
    import tempfile
    global _scratch
    _scratch = tempfile.TemporaryDirectory()
    learner.OUT = Path(_scratch.name) / "learned.json"


def tearDownModule():
    _scratch.cleanup()


def ev(i, ts, home, away, hg, ag, tid=1, kind="league"):
    return {"id": i, "ts": ts, "home": home, "away": away, "home_name": str(home),
            "away_name": str(away), "hg": hg, "ag": ag, "tid": tid,
            "comp": f"comp{tid}", "kind": kind}


def season(start_id, start_ts, teams, tid):
    """Every pair once, home side winning 2-0 when it has the lower id."""
    out, i, ts = [], start_id, start_ts
    for a in teams:
        for b in teams:
            if a < b:
                out.append(ev(i, ts, a, b, 2, 0, tid))
                i += 1
                ts += 86400
    return out


class Ratings(unittest.TestCase):

    def test_no_lookahead(self):
        """A rating as of a match must not change when later results are added."""
        events = season(1, 1_000_000, [1, 2, 3, 4, 5], tid=1)
        early = strength.Ratings(events[:6])
        full = strength.Ratings(events)
        when = events[6]["ts"]
        for team in (1, 2, 3, 4, 5):
            a, b = early.rating_at(team, when), full.rating_at(team, when)
            if a is None:
                continue
            self.assertAlmostEqual(a, b, places=9)

    def test_promotion_keeps_strength(self):
        """Moving league must not move a club's strength on the day."""
        lower = season(1, 1_000_000, [11, 12, 13, 14, 15], tid=2)
        upper = season(100, 1_000_000, [1, 2, 3, 4, 5], tid=1)
        # A cross-league tie so the two offsets differ.
        cross = [ev(500, 3_000_000, 1, 11, 4, 0, tid=9, kind="cup")]
        promoted = [ev(600, 4_000_000, 11, 5, 1, 1, tid=1)]
        r = strength.Ratings(sorted(lower + upper + cross + promoted, key=lambda e: e["ts"]))
        before = r.rating_at(11, 3_999_999)
        at_kickoff = r.rating_at(11, 4_000_000)
        self.assertAlmostEqual(before, at_kickoff, places=6)

    def test_stronger_side_expected_to_win(self):
        events = season(1, 1_000_000, [1, 2, 3, 4, 5, 6], tid=1) * 1
        r = strength.Ratings(events)
        self.assertGreater(r.rating_at(1), r.rating_at(6))
        win, draw, loss = r.win_draw_loss(1, 6)
        self.assertGreater(win, loss)
        self.assertAlmostEqual(win + draw + loss, 1.0, places=6)


class LegChance(unittest.TestCase):

    def _side(self, shift=0.0):
        side = strength.Side.__new__(strength.Side)
        side.team, side.opp, side.gap = 1700.0, 1600.0, 100.0
        side.team_games = side.opp_games = 30
        side.weights = [1.0] * 20
        side.shift = shift
        side.win_draw_loss = (0.5, 0.25, 0.25)
        return side

    def test_bounds_and_direction(self):
        """A better record, with the match values behind it, means a higher
        chance. (Changing the hit count alone would not: the blend treats a
        record running ahead of its own numbers as luck, by design.)"""
        keep = [True] * 20

        def chance_for(k):
            values = [6.0] * k + [3.0] * (20 - k)
            price_fn = lambda exp: (k + 1) / 22
            return strength.leg_chance(self._side(), values, keep, k, 20, 4.5, True, None,
                                       price_fn, "ALL|Corner kicks")

        lo, hi = chance_for(12), chance_for(18)
        self.assertTrue(0 < lo["p"] < 1 and 0 < hi["p"] < 1)
        self.assertGreater(hi["p"], lo["p"])

    def test_tougher_opponent_lowers_expected_shots(self):
        values = [15.0] * 20
        keep = [True] * 20
        price_fn = lambda exp: 0.5
        easy = strength.leg_chance(self._side(+1.0), values, keep, 10, 20, 14.5, True, None,
                                   price_fn, "ALL|Total shots")
        hard = strength.leg_chance(self._side(-2.0), values, keep, 10, 20, 14.5, True, None,
                                   price_fn, "ALL|Total shots")
        if strength.slopes().get("ALL|Total shots", 0) > 0:
            self.assertGreater(easy["eloExpected"], hard["eloExpected"])


class Picks(unittest.TestCase):

    def _leg(self, **kw):
        leg = {"fixture": {"id": kw.pop("fid", 1), "sport": kw.pop("sport", "football")},
               "team": "A", "teamIndex": 0, "period": "ALL", "stat": "Corner kicks",
               "line": 4.5, "over": True, "venue": "home", "source": "x",
               "crossLeague": False}
        leg.update(kw)
        leg.setdefault("evidence", 0.5)
        leg.setdefault("need", leg["fair"])
        return leg

    def test_calibrate_is_idempotent_and_shrinks_players(self):
        leg = self._leg(player="P", hits=18, total=20, fair=1.11)
        weekend.calibrate([leg])
        first = leg["fair"]
        weekend.calibrate([leg])
        self.assertEqual(first, leg["fair"])
        self.assertLess(leg["pShrunk"], 18 / 20)
        self.assertGreaterEqual(leg["need"], leg["fair"])

    def test_other_sports_rank_as_before(self):
        """NFL and the rest keep the selection-adjusted record floor."""
        legs = [self._leg(sport="american-football", hits=14, total=20, fair=2.4, fid=1, stat="Rushing yards"),
                self._leg(sport="american-football", hits=36, total=60, fair=2.1, fid=2, stat="Receiving yards")]
        z = weekend.selection_z(weekend.group_count(legs))
        old = max([l for l in legs if l["fair"] >= weekend.ODDS_FLOOR],
                  key=lambda l: (__import__("model").wilson_low(l["hits"], l["total"], z=z), l["fair"]))
        new = weekend.best_single([dict(l) for l in legs])
        self.assertEqual(new["stat"], old["stat"])


class LiveReports(unittest.TestCase):

    def test_football_team_legs_carry_strength(self):
        import make_index
        reports = [p for p in (Path(__file__).resolve().parent.parent / "reports").glob("*.html")
                   if not p.name.startswith("pick-") and p.name in (
                       "premier-league.html", "uefa-champions-league.html")]
        if not reports:
            self.skipTest("no built reports")
        entry, meta = make_index.read_entries(reports[0])[0]
        legs = weekend.legs_for(entry, meta)
        priced = [l for l in legs if l.get("pStrength")]
        self.assertTrue(priced, "no team leg got a strength-aware chance")
        for l in priced:
            self.assertTrue(0 < l["pStrength"] < 1)
            self.assertAlmostEqual(l["fair"], 1 / l["pStrength"], places=9)
            self.assertGreaterEqual(l["need"], l["fair"])
            self.assertIn("team", l["strength"])


if __name__ == "__main__":
    unittest.main()
