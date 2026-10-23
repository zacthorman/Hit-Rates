"""hitrates.league_ratings: the divide by zero on a collapsing fit.

    .venv/bin/python -B -m unittest tests.test_league_ratings

The fixture is real: every Premier League record in the cache as of the
Wolverhampton v Newcastle kick-off (18 Jan 2026), cut down to the one stat
that broke, first-half red cards. Only 43 of 426 records carry a value, the
league average is 0.23, and inside the 25 passes a rating collapses until
base * rating rounds to 0.0 while the rating still tests > 0. Before the fix
this raised ZeroDivisionError on hitrates.py's d_vals line, the same crash
that kept La Liga out of the strength replay (USAGE.md, 14 October).
"""
import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hitrates  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "league_ratings_pl_red_cards_1st_2026-01-18.json"


def rec(opp, venue, mine, theirs, stat="Total shots"):
    return {"opponent_id": opp, "venue": venue, "stats": {"ALL": {stat: mine}},
            "against": {"ALL": {stat: theirs}}}


class CollapsingFit(unittest.TestCase):
    def setUp(self):
        d = json.loads(FIXTURE.read_text())
        self.period, self.stat = d["period"], d["stat"]
        self.teams = {int(k): v for k, v in d["teams"].items()}

    def test_does_not_divide_by_zero(self):
        r = hitrates.league_ratings(self.teams, {self.period: [self.stat]})
        self.assertEqual(r["teams"], 25)

    def test_every_rating_is_a_number(self):
        r = hitrates.league_ratings(self.teams, {self.period: [self.stat]})
        for kind in ("attack", "defence"):
            for per in r[kind].values():
                v = per.get(self.period, {}).get(self.stat)
                if v is not None:
                    self.assertTrue(math.isfinite(v) and v >= 0, (kind, v))


class OrdinaryFitUnchanged(unittest.TestCase):
    def test_recovers_known_multipliers(self):
        # Four sides, everyone plays everyone home and away, shots made as
        # league average 10 x attack x opponent defence. The fit should give
        # the multipliers back, as the docstring promises.
        att = {1: 1.4, 2: 1.0, 3: 0.8, 4: 0.8}
        dfn = {1: 0.7, 2: 1.0, 3: 1.2, 4: 1.1}
        a_mean = sum(att.values()) / 4
        d_mean = sum(dfn.values()) / 4
        att = {t: v / a_mean for t, v in att.items()}
        dfn = {t: v / d_mean for t, v in dfn.items()}
        teams = {t: [] for t in att}
        for h in att:
            for a in att:
                if h == a:
                    continue
                hs, as_ = 10 * att[h] * dfn[a], 10 * att[a] * dfn[h]
                teams[h].append(rec(a, "home", hs, as_))
                teams[a].append(rec(h, "away", as_, hs))
        r = hitrates.league_ratings(teams, {"ALL": ["Total shots"]}, min_matches=1)
        for t in att:
            self.assertAlmostEqual(r["attack"][str(t)]["ALL"]["Total shots"], att[t], places=4)
            self.assertAlmostEqual(r["defence"][str(t)]["ALL"]["Total shots"], dfn[t], places=4)


if __name__ == "__main__":
    unittest.main()
