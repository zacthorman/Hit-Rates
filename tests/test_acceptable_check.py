"""acceptable_check.py and the verdict change it made (ACCEPTABLE-CHECK.md).

Run from the repo root with the repo's own Python (node for the page check,
pandas and numpy for the replay):

    .venv/bin/python -m unittest tests.test_acceptable_check

Held here:
  * the replay prices a line exactly as pplog.snapshot does (model.appearances,
    price_player on the last ten, pplog._adjustment), skips a player who did not
    play and a stat the feed left out, and uses fmodel only out of its training
    years, on a small cache written in SofaScore's own shapes;
  * the scoring sums and the held-out adoption test: a change is adopted only
    when the lines it takes out still run high on the later months;
  * the page's verdictOf, lifted out of report.py and run in node, marks
    football fouls, fouled and tackles at 2+ a long shot, and agrees with
    rule_review.pp_verdict everywhere;
  * rule_review's acceptable scoreboard on a pplog record.
"""

from __future__ import annotations

import gzip
import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import numpy  # noqa: F401
    import pandas as pd
    HAVE_PD = True
except ImportError:
    HAVE_PD = False

import rule_review as R  # noqa: E402

NODE = shutil.which("node")


def ts(y, m, d):
    return int(datetime(y, m, d, 15, tzinfo=timezone.utc).timestamp())


# Seven matches between two clubs: five in June 2026, two in August.
DATES = [ts(2026, 6, 1), ts(2026, 6, 5), ts(2026, 6, 9), ts(2026, 6, 13), ts(2026, 6, 17),
         ts(2026, 8, 10), ts(2026, 8, 14)]
EIDS = [9001 + i for i in range(len(DATES))]
# Player A (club 1, starts every match): fouls and shots per match.
A_FOULS = [0, 2, 1, 3, 1, 2, 0]
A_SHOTS = [1, 0, 2, 1, 3, 1, 2]


def write_cache(folder: Path, drop_fouls_feed_at=None):
    events = []
    for i, (eid, t) in enumerate(zip(EIDS, DATES)):
        home, away = (1, 2) if i % 2 == 0 else (2, 1)
        events.append({"id": eid, "startTimestamp": t, "status": {"type": "finished"},
                       "homeTeam": {"id": home, "name": f"Club {home}", "sport": {"slug": "football"}},
                       "awayTeam": {"id": away, "name": f"Club {away}", "sport": {"slug": "football"}},
                       "homeScore": {"current": 1}, "awayScore": {"current": 0},
                       "tournament": {"name": "League", "slug": "league",
                                      "uniqueTournament": {"id": 17, "name": "League"}}})
        a_side = "home" if home == 1 else "away"
        b_side = "away" if a_side == "home" else "home"

        def player(pid, name, mins, fouls, shots, sub=False):
            st = {"minutesPlayed": mins, "fouls": fouls, "totalShots": shots} if mins else {}
            return {"player": {"id": pid, "name": name}, "position": "F", "substitute": sub, "statistics": st}

        lineups = {a_side: {"players": [player(11, "Player A", 90, A_FOULS[i], A_SHOTS[i]),
                                        player(12, "Player C", 0, 0, 0, sub=True)]},
                   b_side: {"players": [player(21, "Player B", 90, 1, 1)]}}
        (folder / f"event_{eid}_lineups.json").write_text(json.dumps(lineups))
        a_fouls = A_FOULS[i] if drop_fouls_feed_at != eid else 0
        team_fouls = {a_side: A_FOULS[i] if drop_fouls_feed_at != eid else 9, b_side: 1}
        team_shots = {a_side: A_SHOTS[i], b_side: 1}
        del a_fouls
        stats = {"statistics": [{"period": "ALL", "groups": [{"statisticsItems": [
            {"name": "Fouls", "homeValue": team_fouls["home"], "awayValue": team_fouls["away"]},
            {"name": "Total shots", "homeValue": team_shots["home"], "awayValue": team_shots["away"]},
        ]}]}]}
        if drop_fouls_feed_at == eid:
            # the feed has no fouls for club 1's players this match
            lu = json.loads((folder / f"event_{eid}_lineups.json").read_text())
            for p in lu[a_side]["players"]:
                p["statistics"].pop("fouls", None)
            (folder / f"event_{eid}_lineups.json").write_text(json.dumps(lu))
        (folder / f"event_{eid}_statistics.json").write_text(json.dumps(stats))
    for team in (1, 2):
        (folder / f"team_{team}_events_last_0.json").write_text(json.dumps({"events": events}))


@unittest.skipUnless(HAVE_PD, "needs pandas and numpy")
class Build(unittest.TestCase):
    def setUp(self):
        import acceptable_check as AC
        self.AC = AC
        self.dir = Path(tempfile.mkdtemp())
        self.cache = self.dir / "cache"
        self.cache.mkdir()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def _build(self, fm=None, **kw):
        write_cache(self.cache, **kw)
        fm_path = None
        if fm is not None:
            fm_path = self.dir / "fm.pkl"
            pd.DataFrame(fm).to_pickle(fm_path)
        out = self.dir / "rows.json.gz"
        self.AC.build(self.cache, fm_path, out, log=lambda *a: None)
        with gzip.open(out, "rt") as fh:
            return json.load(fh)

    def test_prices_as_pplog_does(self):
        import hitrates
        import model
        rows = self._build()
        got = {(r["event_id"], r["stat"], r["line"]): r for r in rows if r["player"] == "Player A"}
        # Match 5 (index 4): four earlier appearances, adjustment 1 (no projection with two clubs).
        prior = [{"minutes": 90, "stats": {"Minutes": 90, "Fouls": float(f), "Shots": float(s),
                                           **{k: 0.0 for k in hitrates.PLAYER_ZERO_FILL if k not in ("Fouls", "Shots")}}}
                 for f, s in zip(A_FOULS[:4], A_SHOTS[:4])]
        apps = model.appearances(prior, "Fouls", hitrates.PLAYER_ZERO_FILL, 45)[-10:]
        want = model.price_player(apps, 1.5, True, 1.0, None, "football")["p"]
        r = got[(EIDS[4], "Fouls", 1.5)]
        self.assertAlmostEqual(r["p"], want, places=4)
        self.assertEqual((r["n10"], r["k10"], r["value"], r["won"]), (4, 2, 1.0, False))
        self.assertEqual(r["source"], "site")
        # Fewer than three earlier appearances: not priced.
        self.assertFalse(any(k[0] in EIDS[:3] for k in got))
        # A substitute who did not play is void: no line.
        self.assertFalse(any(r["player"] == "Player C" for r in rows))

    def test_a_stat_the_feed_left_out_is_not_settled(self):
        rows = self._build(drop_fouls_feed_at=EIDS[5])
        a6 = [r for r in rows if r["player"] == "Player A" and r["event_id"] == EIDS[5]]
        self.assertTrue(a6)
        self.assertFalse(any(r["stat"] == "Fouls" for r in a6))
        self.assertTrue(any(r["stat"] == "Shots" for r in a6))

    def test_fmodel_only_out_of_its_training_years(self):
        fm = {"match": [EIDS[4], EIDS[6]], "pid": [11, 11],
              **{c: [0.42, 0.42] for c in ("fm_goals_1", "fm_shots_1", "fm_shots_2", "fm_shots_3",
                                          "fm_sot_1", "fm_sot_2")}}
        rows = self._build(fm=fm)
        a = {(r["event_id"], r["stat"], r["line"]): r for r in rows if r["player"] == "Player A"}
        # June: fmodel would have priced shots 1+, in its training years, so the line is dropped.
        self.assertNotIn((EIDS[4], "Shots", 0.5), a)
        self.assertIn((EIDS[4], "Fouls", 0.5), a)               # not an fmodel line: site price
        # August: fmodel's chance is the one used.
        self.assertEqual(a[(EIDS[6], "Shots", 0.5)]["source"], "fmodel")
        self.assertAlmostEqual(a[(EIDS[6], "Shots", 0.5)]["p"], 0.42)

    def test_coverage(self):
        sides = [("home", 0, 1, [{"minutes": 90, "stats": {"Fouls": 3, "Fouled": 1}}]),
                 ("away", 1, 2, [{"minutes": 90, "stats": {"Fouls": 1, "Fouled": 3}}])]
        ms = {"Fouls": (3, 2), "Total shots": (0, 0)}
        c = self.AC.coverage(ms, sides, 0)
        self.assertTrue(c["Fouls"])          # 3 of 3
        self.assertFalse(c["Fouled"])        # being fouled is the other side's fouls: 1 of 2
        self.assertTrue(c["Shots"])          # nought and nought
        self.assertFalse(c["Tackles"])       # no team figure to check against
        self.assertTrue(self.AC.coverage(ms, sides, 1)["Fouled"])   # 3 of 3


@unittest.skipUnless(HAVE_PD, "needs pandas and numpy")
class Scoring(unittest.TestCase):
    def frame(self, rows):
        import acceptable_check as AC
        D = pd.DataFrame(rows)
        D["period"] = ["fit" if t < AC.CONFIRM_FROM else "confirm" for t in D["ts"]]
        return D

    def test_summary(self):
        import acceptable_check as AC
        D = self.frame([{"event_id": 1, "ts": 0, "p": 0.5, "won": True},
                        {"event_id": 1, "ts": 0, "p": 0.5, "won": False},
                        {"event_id": 2, "ts": 0, "p": 0.8, "won": True},
                        {"event_id": 3, "ts": 0, "p": 0.25, "won": False}])
        s = AC.summary(D, n_boot=200)
        self.assertEqual((s["n"], s["matches"]), (4, 3))
        self.assertAlmostEqual(s["said"], 0.5125)
        self.assertAlmostEqual(s["landed"], 0.5)
        # Backing each at its fair price: 2.0 + 1.25 returned on four units.
        self.assertAlmostEqual(s["roi"], (2.0 + 1.25) / 4 - 1)
        self.assertAlmostEqual(s["roi_lo5"], 0.95 * 3.25 / 4 - 1)
        self.assertLessEqual(s["gap_lo"], s["gap"])
        self.assertGreaterEqual(s["gap_hi"], s["gap"])

    def _held(self, high_in_confirm):
        import acceptable_check as AC
        rng = random.Random(3)
        rows = []
        for i in range(1200):
            fit = i < 800
            t = AC.CONFIRM_FROM - 86400 if fit else AC.CONFIRM_FROM + 86400
            for stat, line in (("Tackles", 0.5), ("Fouls", 1.5)):
                p = 0.6
                runs_high = stat == "Fouls" and (fit or high_in_confirm)
                land = 0.4 if runs_high else 0.65
                rows.append({"event_id": i, "ts": t, "p": p, "stat": stat, "line": line,
                             "won": rng.random() < land})
        return AC.held_out(self.frame(rows))

    def test_adopted_when_the_removed_lines_still_run_high(self):
        h = self._held(high_in_confirm=True)
        self.assertEqual(h["fitted"]["bad"], [("Fouls", 1.5)])
        self.assertEqual(h["adopt"], h["tried"])
        self.assertIn("stat-line", h["adopt"])

    def test_not_adopted_when_they_stop_running_high(self):
        h = self._held(high_in_confirm=False)
        self.assertEqual(h["fitted"]["bad"], [("Fouls", 1.5)])
        self.assertIsNone(h["adopt"])


def js_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    end = source.index("\n}\n", start) + 3
    return source[start:end]


class Verdict(unittest.TestCase):
    def test_python_mirror(self):
        V = R.pp_verdict
        self.assertEqual(V(0.56, 1.80, stat="Fouls", line=1.5), "long")          # +0.8%, runs high
        self.assertEqual(V(0.56, 1.80, stat="Fouls", line=0.5), "ok")
        self.assertEqual(V(0.56, 1.80, stat="Tackles", line=1.5), "long")
        self.assertEqual(V(0.56, 1.80, stat="Fouled", line=2.5), "long")
        self.assertEqual(V(0.56, 1.80, stat="Shots", line=1.5), "ok")
        self.assertEqual(V(0.56, 1.80, stat="Fouls", line=1.5, sport="basketball"), "ok")
        self.assertEqual(V(0.56, 1.80, stat="Fouls", line=1.5, over=False), "ok")
        self.assertEqual(V(0.56, 1.60, stat="Fouls", line=1.5), "avoid")         # -10%
        self.assertEqual(V(0.56, 2.00, stat="Fouls", line=1.5), "avoid")         # +12%
        self.assertEqual(V(0.56, 1.80), "ok")                                    # no stat given

    @unittest.skipUnless(NODE, "node not installed")
    def test_page_agrees(self):
        src = (ROOT / "report.py").read_text()
        fns = js_function(src, "verdictOf") + js_function(src, "RUNS_HIGH")
        consts = 'const RUNS_HIGH_STATS = new Set(["Fouls", "Fouled", "Tackles"]);\n'
        self.assertIn(consts.strip(), src)
        rng = random.Random(7)
        grid = []
        for _ in range(3000):
            grid.append([round(rng.uniform(0.3, 0.95), 3), round(rng.uniform(1.05, 4), 2),
                         rng.choice(["Fouls", "Fouled", "Tackles", "Shots", "Goals", None]),
                         rng.choice([0.5, 1.5, 2.5]), rng.choice(["football", "basketball"]),
                         rng.random() < 0.85])
        script = Path(tempfile.mkdtemp()) / "verdict.js"
        script.write_text(consts + fns + f"""
globalThis.DATA = {{ fixture: {{ staleDays: 0 }} }};
const grid = {json.dumps(grid)};
console.log(JSON.stringify(grid.map(([p, price, stat, line, sport, over]) => {{
  globalThis.SPORT = sport;
  return verdictOf({{ p, price, n: 5, stat, line, over }});
}})));
""")
        try:
            out = subprocess.run([NODE, str(script)], capture_output=True, text=True, check=True)
        finally:
            shutil.rmtree(script.parent)
        got = json.loads(out.stdout)
        for (p, price, stat, line, sport, over), v in zip(grid, got):
            self.assertEqual(v, R.pp_verdict(p, price, 5, False, stat, line, sport, over),
                             (p, price, stat, line, sport, over))
        self.assertIn("long", got)
        self.assertNotIn("take", got)


class Scoreboard(unittest.TestCase):
    def rows(self):
        out = []
        for i in range(40):
            ko = 1792000000 + i * 86400
            out.append({"event_id": i, "kickoff": ko, "sport": "football", "stat": "Shots", "line": 0.5,
                        "over": True, "n10": 10, "result": "win" if i % 3 else "lose",
                        "first": {"t": ko - 7200, "price": 1.70, "chance": 0.60},
                        "last": {"t": ko - 600, "price": 1.65, "chance": 0.61}})
            out.append({"event_id": i, "kickoff": ko, "sport": "football", "stat": "Fouls", "line": 1.5,
                        "over": True, "n10": 10, "result": "lose",
                        "first": {"t": ko - 7200, "price": 1.80, "chance": 0.56},
                        "last": {"t": ko - 7200, "price": 1.80, "chance": 0.56}})
        out.append({"event_id": 99, "kickoff": 1792000000, "sport": "basketball", "stat": "Points",
                    "line": 19.5, "over": False, "n10": 10, "result": None,
                    "first": {"t": 1, "price": 1.9, "chance": 0.6}})
        return out

    def test_verdicts_and_sums(self):
        a = R.acceptable_rows(self.rows())
        self.assertEqual(len(a), 80)                                  # the open line is left out
        self.assertEqual({r["verdict"] for r in a if r["stat"] == "Shots"}, {"ok"})
        self.assertEqual({r["verdict"] for r in a if r["stat"] == "Fouls"}, {"long"})
        b = R.acceptable_block([r for r in a if r["verdict"] == "ok"])
        self.assertEqual((b["n"], b["won"]), (40, 26))
        self.assertAlmostEqual(b["roi"], (26 * 0.70 - 14) / 40)
        self.assertEqual(b["shortened"], 1.0)

    def test_command(self):
        d = Path(tempfile.mkdtemp())
        try:
            (d / "2026-10.jsonl").write_text("\n".join(json.dumps(r) for r in self.rows()))
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                R.main(["acceptable", "--pplog", str(d)])
            text = buf.getvalue()
            self.assertIn("80 settled Paddy Power lines", text)
            self.assertIn("| acceptable | all | 40 | 26 |", text)
            self.assertIn("| long shot | all | 40 | 0 |", text)
            self.assertIn("Acceptable by stat:", text)
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
