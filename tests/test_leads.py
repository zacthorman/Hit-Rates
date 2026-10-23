"""Every logged lead can be settled, darts leads carry a chance, and nothing
but the publishing run writes learned.json.

    .venv/bin/python -B -m unittest tests.test_leads

21-22 Oct 2026: 15 of the 53 leads in lead_log.json had no leg in
best_bets.json, so nothing would ever settle them (the lead is picked on the
game-state chance, the fixture singles besttrack records on sort_value), and
all 13 darts leads were logged at 0%.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import besttrack  # noqa: E402
import learner  # noqa: E402
import tonight  # noqa: E402
import weekend  # noqa: E402

KICK = 1792609200


def lead(eid, team, stat, line, over=True, player=None, comp="UEFA Champions League", written=KICK - 60, **kw):
    return {"event_id": eid, "fixture": f"{team} v Other FC", "competition": comp, "kickoff": KICK,
            "selection": "x", "chance": 0.8, "fair": 1.25, "team": team, "player": player, "stat": stat,
            "period": "ALL", "line": line, "over": over, "written": written, **kw}


class TrackLeads(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = besttrack.STORE, besttrack.LEAD_LOG
        besttrack.STORE = self.tmp / "best_bets.json"
        besttrack.LEAD_LOG = self.tmp / "lead_log.json"

    def tearDown(self):
        besttrack.STORE, besttrack.LEAD_LOG = self.saved
        shutil.rmtree(self.tmp)

    def write_log(self, *rows):
        besttrack.LEAD_LOG.write_text(json.dumps({str(i): r for i, r in enumerate(rows)}))

    def test_the_two_untracked_leads_get_a_leg(self):
        # As logged on 21 Oct; best_bets.json held other lines on both games but not these.
        villa = lead(16938853, "Aston Villa", "Total shots", 13.5)
        lang = lead(16938889, "LASK", "Shots", 0.5, player="Christoph Lang")
        self.write_log(villa, lang)
        other = besttrack._leg({"team": "Aston Villa", "stat": "Total shots", "period": "2ND", "line": 5.5},
                               {"id": 16938853, "home": "Aston Villa", "away": "Viking FK", "kickoff": KICK},
                               "football")
        besttrack.save([{"category": "Fixture single", "sport": "football", "legs": [other], "result": None}])
        self.assertEqual(besttrack.leads(), 2)
        items = besttrack.load()
        got = {(l["team"], l["player"], l["stat"], l["line"], l["over"], l["period"], l["sport"])
               for i in items if i["category"] == "Lead" for l in i["legs"]}
        self.assertEqual(got, {("Aston Villa", None, "Total shots", 13.5, True, "ALL", "football"),
                               ("LASK", "Christoph Lang", "Shots", 0.5, True, "ALL", "football")})
        self.assertTrue(all(i["snapshot_at"] < i["legs"][0]["kickoff"] for i in items if i["category"] == "Lead"))
        # tonight.results_block finds every one of them now
        keys = {tonight._leg_key(l) for i in items for l in i["legs"]}
        self.assertTrue(all(tonight._leg_key(r) in keys for r in (villa, lang)))

    def test_idempotent_and_never_duplicates_a_tracked_leg(self):
        self.write_log(lead(1, "Home FC", "Corner kicks", 3.5))
        self.assertEqual(besttrack.leads(), 1)
        self.assertEqual(besttrack.leads(), 0)
        self.assertEqual(len(besttrack.load()), 1)

    def test_only_leads_written_before_kick_off(self):
        self.write_log(lead(2, "Home FC", "Corner kicks", 3.5, written=KICK + 10))
        self.assertEqual(besttrack.leads(), 0)

    def test_sport_comes_from_the_row_then_the_competition(self):
        self.write_log(lead(3, "Luke Littler", "Average 3 darts", 95.5, comp="European Darts Championship"),
                       lead(4, "Utah Jazz", "3 pointers", 13.5, over=False, comp="NBA"),
                       lead(5, "Bears", "Rushing yards", 70.5, comp="NFL", sport="american-football"))
        besttrack.leads()
        self.assertEqual({i["legs"][0]["event_id"]: i["sport"] for i in besttrack.load()},
                         {3: "darts", 4: "basketball", 5: "american-football"})

    def test_settle_tracks_leads_first(self):
        import contextlib
        import io
        import time
        soon = int(time.time()) + 86400  # not due yet, so settle fetches nothing
        self.write_log(dict(lead(6, "Home FC", "Corner kicks", 3.5), kickoff=soon, written=soon - 3600))
        besttrack.save([])
        with contextlib.redirect_stdout(io.StringIO()):
            besttrack.settle()
        self.assertEqual([i["category"] for i in besttrack.load()], ["Lead"])


class DartsChance(unittest.TestCase):
    leg = {"hits": 8, "total": 10, "fair": 1.25, "fixture": {"id": 1}}

    def test_darts_gets_the_shrunk_record(self):
        self.assertAlmostEqual(tonight.tonight_chance(dict(self.leg), "darts"), (8 + 2) / (10 + 4))
        self.assertAlmostEqual(tonight.tonight_chance(dict(self.leg), "darts"), weekend.chance(dict(self.leg)))

    def test_other_sports_unchanged(self):
        # A leg with no calibrated chance still ranks last outside darts, and
        # the game state still wins where it reaches.
        self.assertEqual(tonight.tonight_chance(dict(self.leg), "basketball"), 0)
        self.assertEqual(tonight.tonight_chance(dict(self.leg, gs={"chance": 0.61}), "darts"), 0.61)
        self.assertEqual(tonight.tonight_chance(dict(self.leg, pShrunk=0.7), "football"), 0.7)


class LearnedJson(unittest.TestCase):
    def test_pricing_a_leg_does_not_write_learned_json(self):
        path = ROOT / "learned.json"
        before = path.read_bytes() if path.exists() else None
        learner._MODEL = None
        learner.model()
        weekend.calibrate([{"hits": 8, "total": 10, "fair": 1.25, "line": 0.5, "over": True,
                            "stat": "Corner kicks", "fixture": {"id": 1}, "team": "A"}])
        self.assertEqual(path.read_bytes() if path.exists() else None, before)

    def test_save_writes_where_it_is_told(self):
        tmp = Path(tempfile.mkdtemp())
        saved = learner.OUT
        try:
            learner.OUT = tmp / "learned.json"
            learner.save({"groups": {}, "active": False, "legs": 0})
            self.assertEqual(json.loads(learner.OUT.read_text())["legs"], 0)
        finally:
            learner.OUT = saved
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
