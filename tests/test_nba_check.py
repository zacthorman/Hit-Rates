"""nba_check.py on synthetic data only: a made-up two-season NBA cache in
SofaScore's shape, a made-up pp-results.html, made-up best_bets legs and
pplog rows. Nothing is fetched and no tracked file is written.

    python -B -m unittest tests.test_nba_check
    python -m pytest tests/test_nba_check.py
"""
import json
import math
import random
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import nba_check as nc  # noqa: E402

DAY = 86400


def _ts(y, m, d):
    return int(datetime(y, m, d, 23, tzinfo=timezone.utc).timestamp())


def poisson(rng, lam):
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def write_cache(folder: Path, seed=3):
    """Two teams of six, a season of 30 games (Nov to Mar), then 10 of the next (from 21 Oct).

    Player 'Star' plays 36 minutes last season and 24 this season: stale minutes."""
    rng = random.Random(seed)
    teams = {"Northbridge": [(100 + i, f"N{i}", "GFC"[i % 3]) for i in range(6)],
             "Southfield": [(200 + i, f"S{i}", "GFC"[i % 3]) for i in range(6)]}
    teams["Northbridge"][0] = (100, "Star", "G")
    dates = [_ts(2025, 11, 1) + 4 * DAY * i for i in range(30)] + [_ts(2026, 10, 21) + 2 * DAY * i for i in range(10)]
    events = []
    for k, ts in enumerate(dates):
        eid = 9000 + k
        home, away = ("Northbridge", "Southfield") if k % 2 == 0 else ("Southfield", "Northbridge")
        events.append({"id": eid, "startTimestamp": ts, "status": {"type": "finished"},
                       "tournament": {"name": "NBA", "category": {"sport": {"slug": "basketball"}}},
                       "homeTeam": {"name": home}, "awayTeam": {"name": away}})
        lu = {}
        for side, team in (("home", home), ("away", away)):
            players = []
            for pid, name, pos in teams[team]:
                mins = 30.0
                if name == "Star":
                    mins = 36.0 if ts < _ts(2026, 8, 1) else 24.0
                rate = 0.6 if name == "Star" else 0.4
                players.append({"player": {"id": pid, "name": name, "position": pos}, "position": pos,
                                "substitute": False,
                                "statistics": {"secondsPlayed": int(mins * 60),
                                               "points": poisson(rng, rate * mins),
                                               "rebounds": poisson(rng, 0.2 * mins),
                                               "assists": poisson(rng, 0.12 * mins),
                                               "threePointsMade": poisson(rng, 0.05 * mins),
                                               "steals": poisson(rng, 0.03 * mins),
                                               "blocks": poisson(rng, 0.02 * mins),
                                               "turnovers": poisson(rng, 0.05 * mins)}})
            # an unused substitute: no seconds, never an appearance
            players.append({"player": {"id": 999, "name": "Bench", "position": "F"}, "position": "F",
                            "substitute": True, "statistics": {}})
            lu[side] = {"players": players}
        (folder / f"event_{eid}_lineups.json").write_text(json.dumps(lu))
    # a summer league game, left out
    events.append({"id": 8000, "startTimestamp": _ts(2026, 7, 10), "status": {"type": "finished"},
                   "tournament": {"name": "NBA Summer League", "category": {"sport": {"slug": "basketball"}}},
                   "homeTeam": {"name": "Northbridge"}, "awayTeam": {"name": "Southfield"}})
    (folder / "event_8000_lineups.json").write_text(json.dumps({"home": {"players": []}, "away": {"players": []}}))
    (folder / "team_1_events_last_0.json").write_text(json.dumps({"events": events}))


class Intervals(unittest.TestCase):
    def test_wilson_and_calib(self):
        lo, hi = nc.wilson(7, 10)
        self.assertAlmostEqual(lo, 0.3968, places=3)
        self.assertAlmostEqual(hi, 0.8922, places=3)
        rows = [{"game": g, "p": 0.6, "y": int(g % 2 == 0)} for g in range(20)]
        s = nc.calib(rows)
        self.assertEqual((s["n"], s["games"]), (20, 20))
        self.assertAlmostEqual(s["gap"], -0.1)
        self.assertLess(s["gap_ci"][0], -0.1)
        self.assertIsNone(nc.calib_row("empty", nc.calib([])))

    def test_logit_shrink(self):
        self.assertAlmostEqual(nc.apply_logit(0.8, 1.0, 0.5), 0.8)
        self.assertAlmostEqual(nc.apply_logit(0.8, 0.0, 0.4), 0.4)
        # overconfident rows: said 80%, landed 50%: the fit pulls in
        rows = [{"p": 0.8, "y": i % 2} for i in range(200)]
        b, base = nc.shrink_fit(rows)
        self.assertLess(b, 0.2)
        self.assertAlmostEqual(base, 0.5)

    def test_loss_diff_sign(self):
        rows = [{"game": i, "a": 0.9, "b": 0.6, "y": i % 2} for i in range(40)]
        d = nc.loss_diff(rows, "a", "b")
        self.assertLess(d["diff"], 0)
        self.assertLess(d["ci"][1], 0)


class Cache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        write_cache(cls.tmp)
        cls.games = nc.load_games(cls.tmp)
        cls.rows = nc.priced_lines(cls.games, stats=("Points", "Rebounds"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_games_and_seasons(self):
        self.assertEqual(len(self.games), 40)                       # summer league left out
        self.assertEqual({g["season"] for g in self.games}, {2025, 2026})
        self.assertTrue(all(len(g["players"]) == 12 for g in self.games))   # the bench player never appears
        first26 = min(g["ts"] for g in self.games if g["season"] == 2026)
        self.assertTrue(all(g["start"] == first26 for g in self.games if g["season"] == 2026))

    def test_lines_use_earlier_games_only(self):
        first = self.games[0]["ts"]
        # no line before a player has three earlier appearances
        self.assertTrue(all(r["ts"] > first + 2 * 4 * DAY for r in self.rows))
        r = next(r for r in self.rows if r["season"] == 2026)
        self.assertTrue(r["early"])
        self.assertEqual(r["group"], "0-2 this season")
        self.assertGreater(r["rest"], 60)            # the summer gap
        self.assertTrue(all(0 < r["p"] < 1 for r in self.rows))

    def test_stale_minutes_show_as_overconfidence(self):
        star = [r for r in self.rows if r["season"] == 2026 and r["stat"] == "Points"
                and r["med_min"] >= 33 and r["group"] in ("0-2 this season", "3-5 this season")]
        self.assertTrue(star)
        s = nc.calib(star)
        self.assertLess(s["gap"], -0.15)            # 36-minute records, 24-minute games

    def test_fit_score_decide(self):
        train = [r for r in self.rows if r["season"] == 2025]
        test = [r for r in self.rows if r["season"] == 2026]
        fit = nc.fit_shrinks(train)
        self.assertIn(fit["K"], nc.K_GRID)
        self.assertEqual(set(fit["b"]), set(nc.GROUPS))
        scored = nc.score_shrinks(test, fit)
        self.assertTrue(all(0 < r["rate"] < 1 and 0 < r["logit"] < 1 for r in scored))
        res = nc.decide(scored)
        self.assertEqual(set(res), {"rate", "logit"})
        for r in res.values():
            self.assertIn("holds", r)
            self.assertEqual(r["holds"], r["all"]["ci"][1] < 0 and r["early"]["ci"][1] < 0 and not r["worse_groups"])

    def test_cache_report_writes_only_to_the_cache_folder(self):
        old = nc.OUT
        try:
            nc.OUT = self.tmp / "nba_check.json"
            text = nc.render(nc.cache_report(self.tmp, None))
        finally:
            nc.OUT = old
        self.assertIn("Verdict under the fixed rule", text)
        self.assertTrue((self.tmp / "nba_check.json").exists())
        self.assertIn("first 21 days of the season", text)

    def test_empty_cache(self):
        empty = Path(tempfile.mkdtemp())
        try:
            self.assertIn("No NBA games", nc.render(nc.cache_report(empty, None)))
        finally:
            shutil.rmtree(empty)


PP_HTML = """<html><body><main>
<h2>Value bets by market</h2><table><tbody>
<tr><td>basketball · Points over</td><td>26</td><td>12%</td><td>65%</td><td class='neg'>-18.3u</td><td>-71%</td></tr>
<tr><td>football · Shots over</td><td>40</td><td>60%</td><td>62%</td><td>+1.0u</td><td>+2%</td></tr>
</tbody></table>
<h2>Recent value bets</h2><table><tbody>
<tr><td>Wed 21 Oct 02:30</td><td><b>A Guard</b><br><small>Northbridge v Southfield</small></td><td>Points Over 18.5</td>
<td>4/5 &middot; 7/10</td><td>70%</td><td>1.83</td><td class='pos'>+28%</td><td class='res lose'>lose (11)</td></tr>
<tr><td>Wed 21 Oct 02:30</td><td><b>B Forward</b><br><small>Northbridge v Southfield</small></td><td>Rebounds Over 4.5</td>
<td>2/5 &middot; 6/10</td><td>60%</td><td>2.10</td><td class='pos'>+26%</td><td class='res win'>win (7)</td></tr>
<tr><td>Wed 21 Oct 02:30</td><td><b>C Striker</b><br><small>Rovers v United</small></td><td>Shots 2+</td>
<td>4/5 &middot; 7/10</td><td>70%</td><td>1.83</td><td class='pos'>+28%</td><td class='res win'>win (3)</td></tr>
</tbody></table>
<p>Updated Wed 21 Oct 23:31.</p>
</main></body></html>"""


class Committed(unittest.TestCase):
    def test_pp_results_parser(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "pp.html").write_text(PP_HTML, encoding="utf-8")
            got = nc.pp_results(tmp / "pp.html")
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(got["by_market"], [{"market": "Points over", "n": 26, "won": 3, "said": 0.65, "profit": -18.3}])
        self.assertEqual([(r["stat"], r["line"], r["y"], r["k5"]) for r in got["recent"]],
                         [("Points", 18.5, 0, (4, 5)), ("Rebounds", 4.5, 1, (2, 5))])
        self.assertEqual(got["updated"], "Wed 21 Oct 23:31")

    def test_best_bets_rows(self):
        leg = {"event_id": 1, "kickoff": _ts(2026, 10, 21), "sport": "basketball", "player": "A Guard",
               "stat": "Points", "line": 14.5, "over": True, "alt": True, "fair": 1.4, "chance": None,
               "hits": 15, "total": 20, "result": "win"}
        bets = [{"category": "Player line", "legs": [leg]},
                {"category": "Pick: parlay", "legs": [dict(leg), dict(leg, event_id=2, result="lose", chance=0.66)]},
                {"category": "Player line", "legs": [dict(leg, event_id=3, result="void")]},
                {"category": "Player line", "legs": [dict(leg, event_id=4, player=None)]}]
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "b.json").write_text(json.dumps(bets))
            rows = nc.best_bets_rows(tmp / "b.json")
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(sorted((r["game"], r["y"], round(r["p"], 4)) for r in rows), [(1, 1, round(1 / 1.4, 4)), (2, 0, 0.66)])

    def test_committed_report_runs_on_the_repo(self):
        text = nc.render(nc.committed_report())
        self.assertIn("Published basketball player legs", text)


class Pplog(unittest.TestCase):
    def rows(self):
        out = []
        for i in range(60):
            out.append({"sport": "basketball", "event_id": i // 6, "kickoff": _ts(2026, 10, 21) + (i // 20) * 7 * DAY,
                        "stat": "Points" if i % 2 else "Rebounds", "line": 10.5, "over": i % 3 != 0,
                        "first": {"chance": 0.65, "price": 1.9, "edge": 0.235}, "result": "win" if i % 2 else "lose",
                        "n10": 10, "k10": 7, "player": f"P{i}"})
        out.append({"sport": "football", "event_id": 99, "kickoff": 0, "stat": "Shots", "line": 1.5, "over": True,
                    "first": {"chance": 0.6, "price": 1.8}, "result": "win", "n10": 10})
        return out

    def test_rows_and_report(self):
        rows = nc.pplog_rows(self.rows())
        self.assertEqual(len(rows), 60)
        old = nc.OUT
        try:
            nc.OUT = Path(tempfile.mkdtemp()) / "missing.json"
            text = nc.render(nc.pplog_report(self.rows()))
        finally:
            nc.OUT = old
        self.assertIn("60 settled Paddy Power basketball lines", text)
        self.assertIn("week 3 of the log", text)
        self.assertIn("| Points |", text)

    def test_no_rows(self):
        self.assertIn("No settled", nc.render(nc.pplog_report([])))


if __name__ == "__main__":
    unittest.main()
