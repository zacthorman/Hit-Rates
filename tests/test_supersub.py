"""supersub.py, and Super Sub in pplog.py and the page, on synthetic data.

    python -m pytest tests/test_supersub.py

Players, matches and incidents are made up. Nothing here makes a request:
pplog.settle runs against stand-in sofascore_api and besttrack modules.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import supersub as ss  # noqa: E402

FIT = {"G": 0.0, "D": 0.024, "M": 0.052, "F": 0.080}


def starts(minutes, pos="F"):
    return [{"started": True, "minutes": m, "position": pos} for m in minutes]


class Chance(unittest.TestCase):
    def test_formula(self):
        # 30% on his own, off in 60% of starts, replacement scores 8%:
        # 0.30 + 0.70 x 0.60 x 0.08 = 0.3336
        self.assertAlmostEqual(ss.chance(0.30, 0.6, 0.08), 0.3336)
        self.assertEqual(ss.chance(0.30, 0.0, 0.08), 0.30)

    def test_sub_rate_counts_starts_only(self):
        rows = starts([90, 90, 70, 60, 84, 85]) + [{"started": False, "minutes": 20, "position": "F"}]
        self.assertAlmostEqual(ss.sub_rate(rows), 3 / 6)        # 70, 60, 84; 85 is not
        self.assertIsNone(ss.sub_rate(starts([60, 60, 60, 60])))  # four starts: too few

    def test_uplift_by_position(self):
        p, extra = ss.uplift(0.30, starts([90, 70, 60, 65, 90, 75]), FIT)   # off 4 of 6
        self.assertAlmostEqual(extra, 0.70 * (4 / 6) * 0.080)
        self.assertAlmostEqual(p, 0.30 + extra)
        self.assertEqual(ss.uplift(0.30, starts([60] * 6, pos="G"), FIT), (0.30, 0.0))
        self.assertEqual(ss.uplift(0.30, starts([60] * 3), FIT), (0.30, 0.0))

    def test_applies_to_paddy_power_goalscorer_only(self):
        self.assertTrue(ss.applies("Anytime Goalscorer"))
        self.assertTrue(ss.applies("Player To Score"))
        self.assertFalse(ss.applies("Player To Have 2 Or More Shots"))
        self.assertFalse(ss.applies("Anytime Goalscorer", "basketball"))

    def test_default_matches_committed_fit(self):
        fit = json.loads((ROOT / "supersub_fit.json").read_text())
        for pos, rep in ss.DEFAULT_REP.items():
            self.assertAlmostEqual(fit["positions"][pos]["rep_scores"], rep, delta=0.0006)


def inc_sub(out, inn, t):
    return {"incidentType": "substitution", "playerOut": {"name": out}, "playerIn": {"name": inn}, "time": t}


def inc_goal(who, t, cls="regular"):
    return {"incidentType": "goal", "player": {"name": who}, "time": t, "incidentClass": cls}


class Settling(unittest.TestCase):
    def test_replacement_scores_after_coming_on(self):
        inc = [inc_goal("Ana Silva", 10), inc_sub("Tomás Ferreira", "Kofi Mensah", 62), inc_goal("Kofi Mensah", 80)]
        self.assertEqual(ss.replacement_scored(inc, "Tomas Ferreira"), "Kofi Mensah")

    def test_no_transfer_cases(self):
        self.assertIsNone(ss.replacement_scored(
            [inc_sub("Tomás Ferreira", "Kofi Mensah", 62), inc_goal("Kofi Mensah", 80, "ownGoal")], "Tomás Ferreira"))
        self.assertIsNone(ss.replacement_scored(
            [inc_goal("Kofi Mensah", 80)], "Tomás Ferreira"))                 # never taken off
        self.assertIsNone(ss.replacement_scored(                               # someone else came on
            [inc_sub("Tomás Ferreira", "Kofi Mensah", 62), inc_goal("Ana Silva", 80)], "Tomás Ferreira"))
        # He came off the bench himself and was taken off again: not a starter.
        self.assertIsNone(ss.replacement_scored(
            [inc_sub("Ana Silva", "Tomás Ferreira", 46), inc_sub("Tomás Ferreira", "Kofi Mensah", 80),
             inc_goal("Kofi Mensah", 88)], "Tomás Ferreira"))

    def test_settle_row_flips_only_goalscorer_losses(self):
        inc = [inc_sub("Tomás Ferreira", "Kofi Mensah", 62), inc_goal("Kofi Mensah", 80)]
        row = {"event_id": 1, "player": "Tomás Ferreira", "stat": "Goals", "market": "Anytime Goalscorer",
               "sport": "football", "result": "lose"}
        self.assertTrue(ss.settle_row(row, lambda eid: inc))
        self.assertEqual((row["result"], row["supersub"]), ("win", "Kofi Mensah"))
        shots = dict(row, stat="Shots", market="Player To Have 2 Or More Shots", result="lose")
        shots.pop("supersub")
        self.assertFalse(ss.settle_row(shots, lambda eid: inc))
        self.assertEqual(shots["result"], "lose")
        self.assertFalse(ss.settle_row(dict(row, result="lose"), lambda eid: None))


def lineup_side(starters, subs):
    """starters/subs: [(id, pos, minutes, goals)]."""
    def p(i, pos, m, g, sub):
        st = {"minutesPlayed": m, "goals": g} if m else {}
        return {"player": {"id": i, "name": f"P{i}"}, "position": pos, "substitute": sub, "statistics": st}
    return {"players": [p(*x, False) for x in starters] + [p(*x, True) for x in subs]}


class Fit(unittest.TestCase):
    def test_pairs_first_off_with_longest_on(self):
        starters = [(i, "D", 92, 0) for i in range(1, 9)] + [(9, "M", 70, 0), (10, "F", 55, 0), (11, "G", 92, 0)]
        subs = [(20, "F", 38, 1), (21, "M", 23, 0), (22, "D", 0, 0)]
        rows = ss.match_rows({"home": lineup_side(starters, subs)})
        by = {r["id"]: r for r in rows}
        self.assertEqual(len(rows), 11)
        self.assertTrue(by[10]["off"] and by[10]["rep_scored"])     # off at 55, the 38-minute sub scored
        self.assertTrue(by[9]["off"] and not by[9]["rep_scored"])
        self.assertFalse(by[1]["off"])

    def test_fit_and_out_of_sample_check(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            events = []
            for k in range(20):
                starters = [(i, "D", 92, 0) for i in range(1, 10)] + [(10, "F", 60, 0), (11, "G", 92, 0)]
                subs = [(20, "F", 32, 1 if k % 4 == 0 else 0)]
                (tmp / f"event_{100 + k}_lineups.json").write_text(json.dumps({"home": lineup_side(starters, subs)}))
                events.append({"id": 100 + k, "startTimestamp": 1_700_000_000 + k * 86400})
            (tmp / "team_1_events_last_0.json").write_text(json.dumps({"events": events}))
            res = ss.fit(tmp)
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(res["matches"], 20)
        f = res["positions"]["F"]
        self.assertEqual((f["starts"], f["taken_off"], f["rep_scores"]), (20, 1.0, 0.25))
        self.assertEqual(res["positions"]["D"]["taken_off"], 0.0)
        # Last 30% (6 games), with the replacement rate fitted on the first
        # 14 only (scored in games 0, 4, 8 and 12: 4 of 14), times his
        # earlier starts (always taken off).
        band = res["check"]["6%+"]
        self.assertEqual(band["n"], 6)
        self.assertAlmostEqual(band["said"], 4 / 14, places=3)
        self.assertAlmostEqual(band["paid"], 1 / 6, places=3)     # game 16 of 14-19


class PplogSettle(unittest.TestCase):
    """pplog.settle grades a Super Sub win as a win, with stand-in modules."""

    def test_settle_uses_super_sub(self):
        import pplog
        tmp = Path(tempfile.mkdtemp())
        inc = [inc_sub("Tomás Ferreira", "Kofi Mensah", 62), inc_goal("Kofi Mensah", 80)]
        fake_api = types.ModuleType("sofascore_api")
        fake_api.get_json = lambda path, **kw: (
            {"incidents": inc} if path.endswith("/incidents") else {"event": {"status": {"type": "finished"}}})
        fake_bt = types.ModuleType("besttrack")
        fake_bt._player_value = lambda r, sport: 0.0
        base = {"event_id": 7, "fixture": "Northbridge v Southfield", "kickoff": 1_000_000, "sport": "football",
                "player": "Tomás Ferreira", "line": 0.5, "over": True, "result": None, "value": None,
                "first": {"price": 3.0, "chance": 0.3, "edge": -0.1}, "last": {"price": 3.0, "chance": 0.3, "edge": -0.1}}
        rows = [dict(base, stat="Goals", market="Anytime Goalscorer"),
                dict(base, stat="Shots", market="Player To Have 1 Or More Shots")]
        saved = {k: sys.modules.get(k) for k in ("sofascore_api", "besttrack")}
        old_dir = pplog.DIR
        try:
            sys.modules["sofascore_api"], sys.modules["besttrack"] = fake_api, fake_bt
            pplog.DIR = tmp
            (tmp / "1970-01.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
            pplog.settle()
            out = pplog._read(tmp / "1970-01.jsonl")
        finally:
            pplog.DIR = old_dir
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            shutil.rmtree(tmp)
        goals, shots = out
        self.assertEqual((goals["result"], goals["supersub"], goals["value"]), ("win", "Kofi Mensah", 0.0))
        self.assertEqual(shots["result"], "lose")
        self.assertNotIn("supersub", shots)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class PageMirror(unittest.TestCase):
    """The page's superSub() gives the same answer as supersub.uplift()."""

    def test_page_matches_python(self):
        import report
        js = report.JS
        rep = re.search(r"const SUPER_SUB_REP = \{[^}]*\};", js).group(0)
        fn = re.search(r"function superSub\(p, played\) \{.*?\n\}", js, re.S).group(0)
        cases = [(0.30, starts([90, 70, 60, 65, 90, 75])),
                 (0.12, starts([90, 80, 90, 90, 60], pos="M")),
                 (0.30, starts([60] * 6, pos="G")),
                 (0.30, starts([60] * 3))]
        prog = (f'const SPORT = "football";\n{rep}\n{fn}\n'
                f'const cases = {json.dumps(cases)};\n'
                'console.log(JSON.stringify(cases.map(([p, pl]) => superSub(p, pl).p)));\n')
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "t.js").write_text(prog)
            done = subprocess.run(["node", str(tmp / "t.js")], capture_output=True, text=True, timeout=30)
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(done.returncode, 0, done.stderr)
        page = json.loads(done.stdout)
        for (p, played), got in zip(cases, page):
            self.assertAlmostEqual(got, ss.uplift(p, played, ss.DEFAULT_REP)[0], places=9)


if __name__ == "__main__":
    unittest.main()
