"""supersub.py, and Super Sub in pplog.py and the page, on synthetic data.

    python -m pytest tests/test_supersub.py

Players, matches and incidents are made up. Nothing here makes a request:
pplog.settle runs against stand-in sofascore_api and besttrack modules.
"""
import json
import math
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

    def test_settle_row_goals_needs_an_eligible_game(self):
        inc = [inc_sub("Tomás Ferreira", "Kofi Mensah", 62), inc_goal("Kofi Mensah", 80)]
        row = {"event_id": 1, "player": "Tomás Ferreira", "stat": "Goals", "market": "Anytime Goalscorer",
               "sport": "football", "result": "lose", "line": 0.5, "over": True, "value": 0.0,
               "competition": "Premier League"}
        self.assertTrue(ss.settle_row(row, lambda eid: inc))
        self.assertEqual((row["result"], row["supersub"], row["supersub_value"]), ("win", "Kofi Mensah", 1.0))
        self.assertFalse(ss.settle_row(dict(row, result="lose"), lambda eid: None))
        # LaLiga is not a Super Sub competition, and the page's own flag wins over the name.
        laliga = dict(row, result="lose", competition="LaLiga")
        laliga.pop("supersub")
        self.assertFalse(ss.settle_row(laliga, lambda eid: inc))
        self.assertTrue(ss.settle_row(dict(laliga, ss_ok=True), lambda eid: inc))
        self.assertFalse(ss.settle_row(dict(row, result="lose", ss_ok=False), lambda eid: inc))

    def test_settle_row_counts_carry_over_on_shots(self):
        # 1 shot of his own before going off at 62, his replacement 1 more: 2+ shots wins.
        inc = [inc_sub("Tomás Ferreira", "Kofi Mensah", 62)]
        lu = {"home": {"players": [
            {"player": {"name": "Tomás Ferreira"}, "statistics": {"minutesPlayed": 62, "totalShots": 1}},
            {"player": {"name": "Kofi Mensah"}, "substitute": True, "statistics": {"minutesPlayed": 28, "totalShots": 1}}]}}
        row = {"event_id": 1, "player": "Tomás Ferreira", "stat": "Shots", "sport": "football", "result": "lose",
               "line": 1.5, "over": True, "value": 1.0, "competition": "Championship"}
        self.assertTrue(ss.settle_row(row, lambda e: inc, lambda e: lu))
        self.assertEqual((row["result"], row["supersub_value"]), ("win", 2.0))
        three = dict(row, line=2.5, result="lose")
        for k in ("supersub", "supersub_value"):
            three.pop(k)
        self.assertFalse(ss.settle_row(three, lambda e: inc, lambda e: lu))
        self.assertEqual(three["result"], "lose")
        # No line-ups: cannot tell, so it stays as graded.
        self.assertFalse(ss.settle_row(dict(three, line=1.5), lambda e: inc, lambda e: None))
        # Tackles are not a Super Sub market.
        self.assertFalse(ss.settle_row(dict(three, stat="Tackles", line=0.5), lambda e: inc, lambda e: lu))

    def test_settle_row_follows_a_sub_of_a_sub(self):
        inc = [inc_sub("Tomás Ferreira", "Kofi Mensah", 55), inc_sub("Kofi Mensah", "Ana Silva", 80)]
        lu = {"away": {"players": [
            {"player": {"name": "Kofi Mensah"}, "substitute": True, "statistics": {"minutesPlayed": 25, "fouls": 1}},
            {"player": {"name": "Ana Silva"}, "substitute": True, "statistics": {"minutesPlayed": 10, "fouls": 1}}]}}
        row = {"event_id": 1, "player": "Tomás Ferreira", "stat": "Fouls", "sport": "football", "result": "lose",
               "line": 1.5, "over": True, "value": 0.0, "competition": "UEFA Europa League"}
        self.assertTrue(ss.settle_row(row, lambda e: inc, lambda e: lu))
        self.assertEqual(row["supersub_value"], 2.0)

    def test_settle_row_cards_from_incidents(self):
        inc = [inc_sub("Tomás Ferreira", "Kofi Mensah", 70),
               {"incidentType": "card", "player": {"name": "Kofi Mensah"}, "time": 85, "incidentClass": "yellow"}]
        row = {"event_id": 1, "player": "Tomás Ferreira", "stat": "Card", "sport": "football", "result": "lose",
               "line": 0.5, "over": True, "value": 0.0, "competition": "EFL Cup"}
        self.assertTrue(ss.settle_row(row, lambda e: inc))

    def test_chain(self):
        inc = [inc_sub("A", "B", 50), inc_sub("B", "C", 80)]
        self.assertEqual(ss.chain(inc, "A"), [("B", 50), ("C", 80)])
        self.assertEqual(ss.chain(inc, "Z"), [])
        self.assertIsNone(ss.chain(inc, "B"))            # came on himself


class Eligible(unittest.TestCase):
    def test_markets_lines_and_competitions(self):
        self.assertTrue(ss.eligible("football", "Shots", 5.5, True, None, "Premier League"))    # 6+
        self.assertFalse(ss.eligible("football", "Shots", 6.5, True, None, "Premier League"))   # 7+ not listed
        self.assertTrue(ss.eligible("football", "Shots on target", 3.5, True, None, "Championship"))
        self.assertFalse(ss.eligible("football", "Shots on target", 4.5, True, None, "Championship"))
        self.assertTrue(ss.eligible("football", "Fouled", 2.5, True, None, "UEFA Champions League"))
        self.assertTrue(ss.eligible("football", "Goals", 1.5, True, None, "FA Cup"))
        self.assertFalse(ss.eligible("football", "Assists", 1.5, True, None, "Premier League"))
        self.assertFalse(ss.eligible("football", "Tackles", 0.5, True, None, "Premier League"))
        self.assertFalse(ss.eligible("football", "Shots", 0.5, False, None, "Premier League"))  # under
        self.assertFalse(ss.eligible("football", "Shots", 0.5, True, None, "Serie A"))
        self.assertTrue(ss.eligible("football", "Shots", 0.5, True, True, "Serie A"))           # page says yes
        self.assertFalse(ss.eligible("football", "Shots", 0.5, True, False, "Premier League"))  # page says no
        self.assertFalse(ss.eligible("basketball", "Shots", 0.5, True, True, "NBA"))


def played(minutes, stat=None, per_game=0.0, pos="F"):
    return [{"started": True, "minutes": m, "position": pos, "stats": {stat: per_game} if stat else {}}
            for m in minutes]


class Pricing(unittest.TestCase):
    RATES = {"F": {"Shots": 2.7, "Card": 0.3, "_off_minutes": 67}}

    def test_tail(self):
        self.assertAlmostEqual(ss._tail(1.0, 1), 1 - math.exp(-1))
        self.assertAlmostEqual(ss._tail(1.0, 2), 1 - 2 * math.exp(-1))
        self.assertEqual(ss._tail(0.0, 1), 0.0)
        self.assertEqual(ss._tail(3.0, 0), 1.0)

    def test_two_plus_shots_formula(self):
        # Off at 60 in 4 of 6 starts (90, 90, 60 x 4); our chance of 2+ is 40%.
        pl = played([90, 90, 60, 60, 60, 60], "Shots", 1.0)
        s, m_off = 4 / 6, 60
        lam = ss.rate_from_chance(0.40, 2, (1 - s) * 90 + s * m_off)
        self.assertAlmostEqual(ss._tail(lam * 70 / 90, 2), 0.40, places=9)
        a, b = lam * 60 / 90, 2.7 * 30 / 90
        want = s * (ss._tail(a + b, 2) - ss._tail(a, 2))
        p, extra = ss.extra_for(0.40, "Shots", 2, pl, self.RATES)
        self.assertAlmostEqual(extra, want)
        self.assertAlmostEqual(p, 0.40 + want)

    def test_thin_record_does_not_override_the_model(self):
        # No shots in his record, but the model says 53%: the extra follows the model.
        pl = played([71, 77, 50, 90, 90, 60], "Shots", 0.0, pos="M")
        p, extra = ss.extra_for(0.53, "Shots", 1, pl, {"M": {"Shots": 2.0}})
        self.assertLess(extra, 0.15)

    def test_more_for_two_plus_than_three_plus_at_this_rate_and_never_negative(self):
        pl = played([90, 60, 60, 60, 60, 60], "Shots", 1.0)
        e1 = ss.extra_for(0.6, "Shots", 1, pl, self.RATES)[1]
        e2 = ss.extra_for(0.3, "Shots", 2, pl, self.RATES)[1]
        e6 = ss.extra_for(0.01, "Shots", 6, pl, self.RATES)[1]
        self.assertTrue(e1 > 0 and e2 > 0 and e6 >= 0)

    def test_no_extra_without_a_record(self):
        self.assertEqual(ss.extra_for(0.4, "Shots", 2, played([60] * 3, "Shots", 1.0), self.RATES), (0.4, 0.0))
        self.assertEqual(ss.extra_for(0.4, "Shots", 2, played([90] * 6, "Shots", 1.0), self.RATES), (0.4, 0.0))
        self.assertEqual(ss.extra_for(0.4, "Shots", 2, played([60] * 6, "Shots", 1.0, pos="G"), self.RATES), (0.4, 0.0))

    def test_rotation_player_gets_only_his_start_share(self):
        pl = played([90, 60, 60, 60, 60, 60], "Shots", 1.0)
        full = ss.extra_for(0.3, "Shots", 2, pl, self.RATES)[1]
        for i, g in enumerate(pl):
            g["date"] = f"2026-10-{10 + i:02d}"
        bench = [{"started": False, "minutes": 20, "position": "F", "date": f"2026-10-{20 + i:02d}",
                  "stats": {"Shots": 1}} for i in range(4)]
        half = ss.extra_for(0.3, "Shots", 2, pl + bench, self.RATES)[1]
        self.assertAlmostEqual(ss.start_share(pl + bench), 0.6)
        self.assertLess(half, full)

    def test_off_minute_needs_three_early_starts_and_is_held_in_range(self):
        self.assertIsNone(ss.off_minutes(played([90, 90, 90, 60, 60])))
        self.assertEqual(ss.off_minutes(played([10, 20, 15, 90, 90])), 45)
        self.assertEqual(ss.off_minutes(played([60, 70, 80, 90])), 70)

    def test_card_backs_out_his_own_rate(self):
        p, extra = ss.extra_for(0.20, "Card", 1, played([90, 60, 60, 60, 60, 60]), self.RATES)
        self.assertTrue(0 < extra < 0.1)
        self.assertAlmostEqual(p, 0.20 + extra)

    def test_goals_one_plus_keeps_the_checked_formula(self):
        pl = [{"started": True, "minutes": m, "position": "F"} for m in [90, 70, 60, 65, 90, 75]]
        self.assertEqual(ss.extra_for(0.30, "Goals", 1, pl, self.RATES, FIT), ss.uplift(0.30, pl, FIT))

    def test_committed_fit_has_rates(self):
        fit = json.loads((ROOT / "supersub_fit.json").read_text())
        for pos in ("D", "M", "F"):
            for stat in ("Shots", "Shots on target", "Fouls", "Fouled", "Goals", "Assists", "Card"):
                self.assertGreater(fit["rates"][pos][stat], 0)
                self.assertAlmostEqual(fit["rates"][pos][stat], ss.DEFAULT_RATES[pos][stat], delta=0.006)


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
        lu = {"home": {"players": [
            {"player": {"name": "Kofi Mensah"}, "substitute": True, "statistics": {"minutesPlayed": 28, "totalShots": 1}}]}}
        fake_api.get_json = lambda path, **kw: (
            {"incidents": inc} if path.endswith("/incidents") else lu if path.endswith("/lineups")
            else {"event": {"status": {"type": "finished"}}})
        fake_bt = types.ModuleType("besttrack")
        fake_bt._player_value = lambda r, sport: 0.0
        base = {"event_id": 7, "fixture": "Northbridge v Southfield", "kickoff": 1_000_000, "sport": "football",
                "player": "Tomás Ferreira", "line": 0.5, "over": True, "result": None, "value": None,
                "competition": "Premier League",
                "first": {"price": 3.0, "chance": 0.3, "edge": -0.1}, "last": {"price": 3.0, "chance": 0.3, "edge": -0.1}}
        rows = [dict(base, stat="Goals", market="Anytime Goalscorer"),
                dict(base, stat="Shots", market="Player To Have 1 Or More Shots"),
                dict(base, stat="Shots", market="Player To Have 2 Or More Shots", line=1.5),
                dict(base, stat="Goals", market="Anytime Goalscorer", competition="LaLiga")]
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
        goals, shots1, shots2, laliga = out
        self.assertEqual((goals["result"], goals["supersub"], goals["value"]), ("win", "Kofi Mensah", 0.0))
        self.assertEqual((shots1["result"], shots1["supersub_value"]), ("win", 1.0))
        self.assertEqual(shots2["result"], "lose")
        self.assertNotIn("supersub", shots2)
        self.assertEqual(laliga["result"], "lose")         # no Super Sub in LaLiga


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class PageMirror(unittest.TestCase):
    """The page's superSub() gives the same answer as supersub.uplift()."""

    def test_page_matches_python(self):
        import report
        js = report.JS
        consts = "\n".join(re.search(rf"const {n} = .*?;\n", js, re.S).group(0)
                           for n in ("SUPER_SUB_REP", "SUPER_SUB_RATES", "SUPER_SUB_MAX"))
        tail = re.search(r"function poissonTail\(lam, k\) \{.*?\n\}", js, re.S).group(0) + "\n" + \
            re.search(r"function rateFromChance\(p, k, minutes\) \{.*?\n\}", js, re.S).group(0)
        fn = re.search(r"function superSub\(p, played, stat, k\) \{.*?\n\}", js, re.S).group(0)
        rates = ss.load_rates()
        sh = played([90, 60, 70, 60, 75, 60], "Shots", 1.0, pos="M")
        fl = played([90, 90, 60, 60, 80, 60], "Fouled", 2.0, pos="D")
        cases = [(0.30, starts([90, 70, 60, 65, 90, 75]), None, None),
                 (0.12, starts([90, 80, 90, 90, 60], pos="M"), None, None),
                 (0.30, starts([60] * 6, pos="G"), None, None),
                 (0.30, starts([60] * 3), None, None),
                 (0.55, sh, "Shots", 1), (0.25, sh, "Shots", 2), (0.05, sh, "Shots", 4),
                 (0.40, fl, "Fouled", 2), (0.20, fl, "Card", 1), (0.08, sh, "Goals", 2)]
        prog = (f'const SPORT = "football";\n{consts}\n{tail}\n{fn}\n'
                f'const cases = {json.dumps(cases)};\n'
                'console.log(JSON.stringify(cases.map(([p, pl, st, k]) => superSub(p, pl, st, k).p)));\n')
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "t.js").write_text(prog)
            done = subprocess.run(["node", str(tmp / "t.js")], capture_output=True, text=True, timeout=30)
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(done.returncode, 0, done.stderr)
        page = json.loads(done.stdout)
        for (p, pl, st, k), got in zip(cases, page):
            want = (ss.uplift(p, pl, ss.DEFAULT_REP)[0] if st is None
                    else ss.extra_for(p, st, k, pl, rates, ss.DEFAULT_REP)[0])
            self.assertAlmostEqual(got, want, places=9, msg=f"{st} {k}")


if __name__ == "__main__":
    unittest.main()
