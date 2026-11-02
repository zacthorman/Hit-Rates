"""Bet365's Sub On Play On (supersub.py BOOKS["b365"]), the Bet365 log
(b365log.py) and value_books.py's per-book chance. Synthetic data only."""
import json
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pplog  # noqa: E402
import supersub as ss  # noqa: E402


def inc_sub(out, inn, t):
    return {"incidentType": "substitution", "playerOut": {"name": out}, "playerIn": {"name": inn}, "time": t}


class Eligible(unittest.TestCase):
    def test_bet365_markets_lines_and_leagues(self):
        e = lambda stat, line, comp, book="b365": ss.eligible("football", stat, line, True, None, comp, book)
        self.assertTrue(e("Tackles", 1.5, "LaLiga"))            # tackles: Bet365 yes
        self.assertFalse(e("Tackles", 1.5, "Premier League", "pp"))   # Paddy Power no
        self.assertTrue(e("Shots", 9.5, "Serie A"))             # 10+ shots
        self.assertFalse(e("Shots", 9.5, "Serie A", "pp"))
        self.assertTrue(e("Fouled", 6.5, "Bundesliga"))         # 7+ fouled
        self.assertFalse(e("Fouled", 7.5, "Bundesliga"))
        self.assertTrue(e("Assists", 1.5, "Ligue 1"))
        self.assertFalse(e("Shots", 0.5, "Championship"))       # not on Bet365's list
        self.assertTrue(e("Shots", 0.5, "Championship", "pp"))  # but on Paddy Power's
        self.assertFalse(e("Shots", 0.5, "LaLiga", "sky"))      # an unknown book: never
        self.assertFalse(ss.eligible("football", "Shots", 0.5, False, None, "LaLiga", "b365"))  # under

    def test_row_book_decides(self):
        row = {"sport": "football", "stat": "Tackles", "line": 0.5, "over": True, "competition": "LaLiga"}
        self.assertFalse(ss.eligible_row(row))                  # no book: Paddy Power's row
        self.assertTrue(ss.eligible_row(dict(row, book="b365")))

    def test_bet365_tackles_settle_through_the_replacement(self):
        inc = [inc_sub("Iker Ruiz", "Pablo Mora", 60)]
        lu = {"home": {"players": [
            {"player": {"name": "Pablo Mora"}, "substitute": True, "statistics": {"minutesPlayed": 30, "totalTackle": 2}}]}}
        row = {"event_id": 1, "player": "Iker Ruiz", "stat": "Tackles", "sport": "football", "result": "lose",
               "line": 2.5, "over": True, "value": 1.0, "competition": "LaLiga", "book": "b365"}
        self.assertTrue(ss.settle_row(row, lambda e: inc, lambda e: lu))
        self.assertEqual((row["result"], row["supersub_value"]), ("win", 3.0))

    def test_tackles_rate_is_fitted(self):
        fit = json.loads((ROOT / "supersub_fit.json").read_text())
        for pos in ("D", "M", "F"):
            self.assertGreater(fit["rates"][pos]["Tackles"], 1.0)
            self.assertAlmostEqual(fit["rates"][pos]["Tackles"], ss.DEFAULT_RATES[pos]["Tackles"], delta=0.006)


class ReadLine(unittest.TestCase):
    def test_bet365_market_names(self):
        self.assertEqual(pplog.read_line({"market": "Player To Make 3 Or More Tackles"})[:3], ("Tackles", 2.5, True))
        self.assertEqual(pplog.read_line({"market": "Player To Have 1 Or More Assists"})[:3], ("Assists", 0.5, True))
        self.assertEqual(pplog.read_line({"market": "Player Shown a Card"})[:3], ("Card", 0.5, True))


class Untested(unittest.TestCase):
    def test_lines_beyond_paddy_power_are_never_value(self):
        saved = pplog.BOOK
        try:
            pplog.BOOK = "b365"
            self.assertTrue(pplog._untested("football", "Shots", 6.5))      # 7+ shots
            self.assertFalse(pplog._untested("football", "Shots", 5.5))     # 6+: Paddy has it
            self.assertTrue(pplog._untested("football", "Tackles", 0.5))    # Paddy has none
            self.assertTrue(pplog._untested("football", "Fouls", 3.5))
            pplog.BOOK = "pp"
            self.assertFalse(pplog._untested("football", "Shots", 6.5))     # Paddy's own log: unchanged
        finally:
            pplog.BOOK = saved
        snap = {"chance": 0.6, "edge": 0.2, "source": "fmodel"}
        row = {"sport": "football", "stat": "Shots", "first": snap, "n10": 10, "fresh": 1.0}
        self.assertTrue(pplog.is_value(row))
        self.assertFalse(pplog.is_value(dict(row, untested=True)))


class Bet365Log(unittest.TestCase):
    def test_points_pplog_at_bet365_files(self):
        import b365log
        saved = (pplog.DIR, pplog.PP, pplog.PAGE, pplog.BOOK, pplog.BOOK_NAME)
        try:
            b365log.use_bet365()
            self.assertEqual(pplog.DIR, ROOT / "b365log")
            self.assertEqual(pplog.PP, ROOT / "reports" / "bet365.json")
            self.assertEqual((pplog.BOOK, pplog.BOOK_NAME), ("b365", "Bet365"))
            self.assertNotEqual(pplog.PAGE, ROOT / "pp-results.html")
        finally:
            pplog.DIR, pplog.PP, pplog.PAGE, pplog.BOOK, pplog.BOOK_NAME = saved

    def test_settle_grades_a_bet365_row_with_sub_on_play_on(self):
        import b365log
        tmp = Path(tempfile.mkdtemp())
        inc = [inc_sub("Iker Ruiz", "Pablo Mora", 60)]
        lu = {"home": {"players": [
            {"player": {"name": "Pablo Mora"}, "substitute": True, "statistics": {"minutesPlayed": 30, "totalTackle": 2}}]}}
        fake_api = types.ModuleType("sofascore_api")
        fake_api.get_json = lambda path, **kw: (
            {"incidents": inc} if path.endswith("/incidents") else lu if path.endswith("/lineups")
            else {"event": {"status": {"type": "finished"}}})
        fake_bt = types.ModuleType("besttrack")
        fake_bt._player_value = lambda r, sport: 1.0
        row = {"event_id": 9, "fixture": "Getafe v Sevilla", "kickoff": 1_000_000, "sport": "football",
               "player": "Iker Ruiz", "stat": "Tackles", "line": 2.5, "over": True, "result": None, "value": None,
               "competition": "LaLiga", "book": "b365",
               "first": {"price": 3.0, "chance": 0.3, "edge": -0.1}, "last": {"price": 3.0, "chance": 0.3, "edge": -0.1}}
        saved_mod = {k: sys.modules.get(k) for k in ("sofascore_api", "besttrack")}
        saved = (pplog.DIR, pplog.PP, pplog.PAGE, pplog.BOOK, pplog.BOOK_NAME)
        try:
            sys.modules["sofascore_api"], sys.modules["besttrack"] = fake_api, fake_bt
            b365log.use_bet365()
            pplog.DIR = tmp
            (tmp / "1970-01.jsonl").write_text(json.dumps(row) + "\n")
            pplog.settle()
            out = pplog._read(tmp / "1970-01.jsonl")[0]
        finally:
            pplog.DIR, pplog.PP, pplog.PAGE, pplog.BOOK, pplog.BOOK_NAME = saved
            for k, v in saved_mod.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            shutil.rmtree(tmp)
        self.assertEqual((out["result"], out["value"], out["supersub_value"]), ("win", 1.0, 3.0))


class ValueBooks(unittest.TestCase):
    def test_each_book_gets_its_own_cover(self):
        import value_books as vb
        played = [{"player": "Iker Ruiz", "started": True, "minutes": m, "position": "M", "date": f"2026-10-{10 + i:02d}"}
                  for i, m in enumerate([90, 60, 60, 60, 60, 60])]
        entry = {"players": [played, []]}
        ctx = ({"1": (entry, {"competition": "LaLiga"})}, {})
        r = {"fid": "1", "stat": "Shots", "line": 0.5, "over": True}
        q365, x365, info = vb.sub_chance(r, 0.5, "B3", "Iker Ruiz", ctx)
        qpp, xpp, _ = vb.sub_chance(r, 0.5, "PP", "Iker Ruiz", ctx)      # no Super Sub in LaLiga
        qsk, xsk, _ = vb.sub_chance(r, 0.5, "SK", "Iker Ruiz", ctx)      # Sky Bet: not modelled
        self.assertGreater(x365, 0)
        self.assertEqual((qpp, xpp), (0.5, 0.0))
        self.assertEqual((qsk, xsk), (0.5, 0.0))
        self.assertEqual((info["ss_book"], info["competition"]), ("b365", "LaLiga"))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Page(unittest.TestCase):
    def test_page_knows_each_books_cover(self):
        import re
        import report
        js = report.JS
        parts = [re.search(rf"const {n} = .*?;\n", js, re.S).group(0)
                 for n in ("SUPER_SUB_MAX", "SUPER_SUB_COMPS", "SUB_ON_MAX", "SUB_ON_COMPS")]
        fn = re.search(r"function superSubOn\(stat, line, over, book\) \{.*?\n\}", js, re.S).group(0)
        prog = ('const SPORT = "football"; let DATA = {fixture: {competition: "LaLiga"}};\n'
                'function fixtureMarket() { return null; }\n' + "\n".join(parts) + fn + "\n"
                'const a = [superSubOn("Tackles", 0.5, true, "b365"), superSubOn("Tackles", 0.5, true, "pp"),'
                ' superSubOn("Shots", 0.5, true, "pp")];\n'
                'DATA = {fixture: {competition: "Championship"}};\n'
                'a.push(superSubOn("Shots", 0.5, true, "b365"), superSubOn("Shots", 0.5, true, "pp"));\n'
                'console.log(JSON.stringify(a));\n')
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "t.js").write_text(prog)
            done = subprocess.run(["node", str(tmp / "t.js")], capture_output=True, text=True, timeout=30)
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), [True, False, False, False, True])


if __name__ == "__main__":
    unittest.main()
