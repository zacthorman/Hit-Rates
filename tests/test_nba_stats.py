"""nba_stats.py on fixtures and made-up data only. Nothing is fetched.

The fixtures in tests/fixtures/nba_stats/ were built by hand in the shape
stats.nba.com documents (resultSets of headers and rowSet, and v3's nested
boxScoreTraditional), because stats.nba.com does not answer from the machine
these tests were written on. They test the parsing and the maths, not that
NBA.com still answers in this shape: that is the first live run's job.

    python -B -m unittest tests.test_nba_stats
"""
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import nba_stats as ns  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "nba_stats"
NYK, CLE, BOS, PHI = 1610612752, 1610612739, 1610612738, 1610612755


def fixture(name):
    return json.loads((FIX / name).read_text())


class FakeResponse:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data

    def json(self):
        if self._data is None:
            raise ValueError("not JSON")
        return self._data


class FakeSession:
    """Answers by endpoint from a dict; records every call."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        endpoint = url.rsplit("/", 1)[-1]
        self.calls.append((endpoint, dict(params or {}), headers, timeout))
        a = self.answers[endpoint]
        a = a(params) if callable(a) else a
        if isinstance(a, Exception):
            raise a
        return a


def ok(data):
    return FakeResponse(200, data)


class TempCache(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="nba-stats-test-"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def client(self, session, max_requests=50):
        self.slept = []
        return ns.Client(cache=self.dir, session=session, max_requests=max_requests,
                         sleep=self.slept.append, verbose=False)


class Parsing(unittest.TestCase):
    def test_result_set_rows_become_dicts(self):
        rows = ns.result_set(fixture("leaguegamelog_T.json"), "LeagueGameLog")
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["TEAM_ABBREVIATION"], "NYK")
        self.assertEqual(rows[0]["GAME_ID"], "0022500001")
        with self.assertRaises(KeyError):
            ns.result_set(fixture("leaguegamelog_T.json"), "Nope")

    def test_single_result_set_dict_is_read(self):
        data = {"resultSet": {"name": "X", "headers": ["A", "B"], "rowSet": [[1, 2]]}}
        self.assertEqual(ns.result_set(data), [{"A": 1, "B": 2}])

    def test_minutes_in_every_shape(self):
        self.assertAlmostEqual(ns.parse_minutes("34:12"), 34.2)
        self.assertAlmostEqual(ns.parse_minutes("37.000000:41"), 37 + 41 / 60)
        self.assertAlmostEqual(ns.parse_minutes("PT34M12.00S"), 34.2)
        self.assertEqual(ns.parse_minutes(27.5), 27.5)
        self.assertEqual(ns.parse_minutes(""), 0.0)
        self.assertEqual(ns.parse_minutes(None), 0.0)

    def test_team_log_pairs_opponents(self):
        games = ns.parse_team_log(fixture("leaguegamelog_T.json"))
        nyk = next(g for g in games if g["team_id"] == NYK)
        self.assertEqual((nyk["opp_id"], nyk["opp"], nyk["date"]), (CLE, "CLE", "2025-10-21"))
        self.assertEqual(len(games), 4)

    def test_box_v3_starters_and_dnp(self):
        box = ns.parse_box(fixture("boxscoretraditionalv3_0022500001.json"))
        self.assertEqual(box["game_id"], "0022500001")
        by = {p["name"]: p for p in box["players"]}
        self.assertTrue(by["Karl-Anthony Towns"]["starter"])
        self.assertFalse(by["Mitchell Robinson"]["starter"])
        self.assertAlmostEqual(by["Mitchell Robinson"]["min"], 18.5)
        self.assertEqual(by["Mitchell Robinson"]["reb"], 9)
        self.assertEqual(by["OG Anunoby"]["min"], 0.0)
        self.assertTrue(by["OG Anunoby"]["comment"].startswith("DNP"))
        self.assertEqual(by["Evan Mobley"]["team_id"], CLE)

    def test_box_v2_reads_the_same(self):
        box = ns.parse_box(fixture("boxscoretraditionalv2_0022400061.json"))
        by = {p["name"]: p for p in box["players"]}
        self.assertTrue(by["Karl-Anthony Towns"]["starter"])
        self.assertAlmostEqual(by["Karl-Anthony Towns"]["min"], 37 + 41 / 60)
        self.assertFalse(by["Mitchell Robinson"]["starter"])
        self.assertEqual(by["OG Anunoby"]["min"], 0.0)
        self.assertEqual(by["OG Anunoby"]["pts"], 0)

    def test_lineups_group_id_split(self):
        rows = ns.parse_lineups(fixture("leaguedashlineups_2025-10-21.json"))
        self.assertEqual(rows[0]["ids"], (1626157, 1628973, 1628384, 1628969, 1629011))
        self.assertEqual(rows[1]["min"], 27.5)

    def test_positions_and_big(self):
        pos = ns.parse_positions(fixture("playerindex.json"))
        self.assertEqual(pos[1626157]["position"], "C-F")      # Towns: big here, F on SofaScore
        self.assertTrue(ns.is_big(pos[1626157]["position"]))
        self.assertTrue(ns.is_big(pos[1630596]["position"]))   # F-C
        self.assertFalse(ns.is_big(pos[1628384]["position"]))  # F
        self.assertFalse(ns.is_big(""))


def _answers():
    return {
        "leaguegamelog": lambda p: ok(fixture(f"leaguegamelog_{p['PlayerOrTeam']}.json")),
        "playerindex": ok(fixture("playerindex.json")),
        "boxscoretraditionalv3": lambda p: ok(fixture("boxscoretraditionalv3_0022500001.json")
                                              if p["GameID"] == "0022500001"
                                              else {"boxScoreTraditional": {"gameId": p["GameID"]}}),
        "leaguedashlineups": ok(fixture("leaguedashlineups_2025-10-21.json")),
    }


class Fetching(TempCache):
    def test_fetch_fills_cache_and_rerun_asks_only_for_what_is_missing(self):
        s = FakeSession(_answers())
        done = ns.fetch(self.client(s), "2025-26", "Regular Season", today=date(2025, 10, 28))
        endpoints = [c[0] for c in s.calls]
        self.assertEqual(endpoints.count("leaguegamelog"), 2)
        self.assertEqual(endpoints.count("boxscoretraditionalv3"), 2)
        self.assertEqual(endpoints.count("leaguedashlineups"), 1)
        # every request carries the site's headers and a timeout
        for _, _, headers, timeout in s.calls:
            self.assertEqual(headers["Referer"], "https://www.nba.com/")
            self.assertEqual(headers["Origin"], "https://www.nba.com")
            self.assertIn("Mozilla", headers["User-Agent"])
            self.assertEqual(timeout, ns.TIMEOUT)
        # paced: a wait before every request but the first, at least MIN_GAP
        self.assertEqual(len(self.slept), len(s.calls) - 1)
        self.assertTrue(all(w >= ns.MIN_GAP - 0.05 for w in self.slept))
        self.assertTrue((self.dir / "box_0022500001.json").exists())
        # the empty box (game 2, not filled yet) is not cached as final
        self.assertFalse((self.dir / "box_0022500002.json").exists())
        self.assertEqual(done["lineups"], 1)

        s2 = FakeSession(_answers())
        ns.fetch(self.client(s2), "2025-26", "Regular Season", today=date(2025, 10, 28))
        self.assertEqual([c[0] for c in s2.calls], ["boxscoretraditionalv3"])
        self.assertEqual(s2.calls[0][1]["GameID"], "0022500002")

    def test_cached_game_is_never_requested(self):
        self.dir.mkdir(exist_ok=True)
        (self.dir / "box_0022500001.json").write_text(
            json.dumps(fixture("boxscoretraditionalv3_0022500001.json")))
        s = FakeSession({})
        data = self.client(s).fetch("boxscoretraditionalv3", ns.box_params("0022500001"),
                                    "box_0022500001")
        self.assertEqual(s.calls, [])
        self.assertEqual(data["boxScoreTraditional"]["gameId"], "0022500001")

    def test_lineup_day_not_fetched_until_over(self):
        s = FakeSession(_answers())
        ns.fetch(self.client(s), "2025-26", "Regular Season", today=date(2025, 10, 22))
        self.assertNotIn("leaguedashlineups", [c[0] for c in s.calls])

    def test_lineup_params_are_one_day_of_five_man_groups(self):
        p = ns.lineup_params("2025-26", "Regular Season", "2025-10-21")
        self.assertEqual((p["DateFrom"], p["DateTo"]), ("10/21/2025", "10/21/2025"))
        self.assertEqual((p["GroupQuantity"], p["LeagueID"], p["PerMode"]), (5, "00", "Totals"))

    def test_cap_stops_quietly(self):
        s = FakeSession(_answers())
        done = ns.fetch(self.client(s, max_requests=3), "2025-26", "Regular Season",
                        today=date(2025, 10, 28))
        self.assertEqual(len(s.calls), 3)
        self.assertTrue(done["capped"])


class StopOnRefusal(TempCache):
    def _run(self, box_answer):
        answers = _answers()
        answers["boxscoretraditionalv3"] = box_answer
        s = FakeSession(answers)
        with self.assertRaises(ns.Stopped):
            ns.fetch(self.client(s), "2025-26", "Regular Season", today=date(2025, 10, 28))
        return s

    def test_403_stops_at_once(self):
        s = self._run(FakeResponse(403, {}))
        # three log/index requests, then exactly one box request: no retry, no next game
        self.assertEqual([c[0] for c in s.calls].count("boxscoretraditionalv3"), 1)
        self.assertNotIn("leaguedashlineups", [c[0] for c in s.calls])
        self.assertFalse((self.dir / "box_0022500001.json").exists())
        self.assertTrue((self.dir / "gamelog_T_2025-26_rs.json").exists())   # earlier work kept

    def test_429_and_timeout_and_non_json_stop(self):
        for answer in (FakeResponse(429, {}), TimeoutError("read timed out"),
                       FakeResponse(200, None), FakeResponse(500, {})):
            shutil.rmtree(self.dir, ignore_errors=True)
            s = self._run(answer)
            self.assertEqual([c[0] for c in s.calls].count("boxscoretraditionalv3"), 1)

    def test_main_returns_2_on_stop(self):
        orig = ns.Client

        class Fake(ns.Client):
            def __init__(inner, **kw):
                orig.__init__(inner, cache=self.dir, sleep=lambda w: None, verbose=False,
                              session=FakeSession({"leaguegamelog": FakeResponse(403, {})}))
        ns.Client = Fake
        try:
            self.assertEqual(ns.main(["fetch", "--season", "2025-26"]), 2)
        finally:
            ns.Client = orig


# ------------------------------------------------------------------ analysis

def _pg(gid, day, pid, name, team, mins, pts=0, reb=0, ast=0):
    return {"game_id": gid, "date": day, "player_id": pid, "name": name, "team_id": team,
            "min": mins, "pts": pts, "reb": reb, "ast": ast}


class WithWithout(unittest.TestCase):
    def league(self):
        # Star (1) and Mate (2) on team 10. Mate plays games 0-5, misses 6-9.
        # Star scores 20 with him and 28 without; 30 minutes with, 36 without.
        pg = []
        for g in range(10):
            day = f"2025-11-{g + 1:02d}"
            gid = f"G{g}"
            out = g >= 6
            pg.append(_pg(gid, day, 1, "Star Player", 10, 36 if out else 30, 28 if out else 20,
                          5, 4))
            if not out:
                pg.append(_pg(gid, day, 2, "Mate Man", 10, 32, 15, 6, 2))
        # a player on another team with the same games, to be ignored
        pg.append(_pg("G0", "2025-11-01", 3, "Other Guy", 11, 30, 10, 3, 3))
        return ns.League([], pg, {}, {}, {})

    def test_split_and_difference(self):
        res = ns.with_without(self.league(), 1, 2)
        self.assertEqual((res["with"], res["without"]), (6, 4))
        r = res["rows"]
        self.assertEqual((r["min"]["with"], r["min"]["without"]), (30, 36))
        est, lo, hi = r["pts"]["diff"]
        self.assertEqual(est, 8)
        self.assertEqual((lo, hi), (8, 8))      # no spread inside either side
        self.assertEqual(r["reb"]["diff"][0], 0)

    def test_range_brackets_estimate_when_noisy(self):
        lg = self.league()
        for i, p in enumerate(p for p in lg.player_games if p["player_id"] == 1):
            p["pts"] += (i % 3) * 3
        est, lo, hi = ns.with_without(lg, 1, 2)["rows"]["pts"]["diff"]
        self.assertLessEqual(lo, est)
        self.assertLessEqual(est, hi)
        self.assertLess(lo, hi)

    def test_since_joined_drops_games_before_he_arrived(self):
        lg = self.league()
        lg.player_games = [p for p in lg.player_games
                           if not (p["player_id"] == 2 and p["game_id"] in ("G0", "G1"))]
        self.assertEqual(ns.with_without(lg, 1, 2)["without"], 6)
        self.assertEqual(ns.with_without(lg, 1, 2, since_joined=True)["without"], 4)

    def test_find_player_ignores_accents_and_rejects_ambiguity(self):
        lg = ns.League([], [_pg("G", "d", 7, "Nikola Jokić", 1, 30),
                            _pg("G", "d", 8, "Nikola Vučević", 2, 30)], {}, {}, {})
        self.assertEqual(ns.find_player(lg, "nikola jokic"), (7, "Nikola Jokić"))
        self.assertEqual(ns.find_player(lg, "Vucevic")[0], 8)
        with self.assertRaises(SystemExit):
            ns.find_player(lg, "Nikola")


class SmallBall(unittest.TestCase):
    """A tiny league: team A (backup big B, a starting big S) plays teams Small and Tall.

    Small plays 40 of 48 minutes with one big or fewer; Tall plays 8 of 48.
    B plays 10 minutes against Small and 20 against Tall, with points and
    rebounds proportional to minutes.
    """

    POS = {1: "C", 2: "C", 3: "G", 4: "G", 5: "F",                    # team A
           11: "F", 12: "G", 13: "G", 14: "F", 15: "C", 16: "C",      # team Small
           21: "C", 22: "C-F", 23: "G", 24: "F", 25: "F-C"}           # team Tall

    def league(self):
        positions = {i: {"name": str(i), "position": p, "height": ""} for i, p in self.POS.items()}
        team_games, boxes, lineups = [], {}, {}
        for g in range(12):
            day = f"2025-11-{g + 1:02d}"
            gid = f"G{g}"
            opp = 100 if g % 2 == 0 else 200          # Small on even days, Tall on odd
            team_games += [{"game_id": gid, "date": day, "team_id": 1, "team": "A", "opp_id": opp,
                            "opp": "x"},
                           {"game_id": gid, "date": day, "team_id": opp, "team": "x", "opp_id": 1,
                            "opp": "A"}]
            b_min = 10 if opp == 100 else 20
            boxes[gid] = {"game_id": gid, "players": [
                {"player_id": 1, "name": "Backup Big", "team_id": 1, "starter": False,
                 "min": b_min, "pts": b_min // 2, "reb": b_min // 3, "ast": 0, "comment": ""},
                {"player_id": 2, "name": "Starting Big", "team_id": 1, "starter": True,
                 "min": 30, "pts": 15, "reb": 10, "ast": 1, "comment": ""},
                {"player_id": 3, "name": "Guard", "team_id": 1, "starter": True,
                 "min": 34, "pts": 20, "reb": 3, "ast": 6, "comment": ""},
            ]}
            if opp == 100:
                opp_lu = [{"team_id": 100, "ids": (11, 12, 13, 14, 15), "min": 40.0},   # one big
                          {"team_id": 100, "ids": (11, 12, 13, 15, 16), "min": 8.0}]    # two
            else:
                opp_lu = [{"team_id": 200, "ids": (21, 22, 23, 24, 25), "min": 40.0},   # three
                          {"team_id": 200, "ids": (21, 23, 24, 12, 13), "min": 8.0}]    # one
            lineups[day] = opp_lu + [{"team_id": 1, "ids": (1, 2, 3, 4, 5), "min": 48.0}]
        return ns.League(team_games, [], positions, boxes, lineups)

    def test_small_share_counts_bigs_by_listed_position(self):
        share = ns.small_share(self.league())
        self.assertAlmostEqual(share[("2025-11-01", 100)], 40 / 48)
        self.assertAlmostEqual(share[("2025-11-02", 200)], 8 / 48)
        self.assertAlmostEqual(share[("2025-11-01", 1)], 0.0)     # two Cs in every A line-up

    def test_backup_big_loses_minutes_against_small(self):
        res = ns.smallball(self.league(), "backup-bigs", cut=0.5)
        self.assertEqual([r["name"] for r in res["players"]], ["Backup Big"])
        r = res["players"][0]
        self.assertEqual((r["n_small"], r["n_big"]), (6, 6))
        self.assertEqual(r["min"][0], -10)
        self.assertEqual(r["pts"][0], -5)
        self.assertAlmostEqual(r["reb36"], 36 * 3 / 10 - 36 * 6 / 20)
        self.assertEqual(res["pooled"]["min"][0], -10)

    def test_who_filters(self):
        lg = self.league()
        names = {r["name"] for r in ns.smallball(lg, "bigs", cut=0.5)["players"]}
        self.assertEqual(names, {"Backup Big", "Starting Big"})
        names = {r["name"] for r in ns.smallball(lg, "all", cut=0.5)["players"]}
        self.assertEqual(names, {"Backup Big", "Starting Big", "Guard"})

    def test_too_few_games_each_side_left_out(self):
        self.assertEqual(ns.smallball(self.league(), "all", cut=0.5, min_games=7)["players"], [])

    def test_no_lineups_says_so(self):
        lg = self.league()
        lg.lineups = {}
        self.assertIsNone(ns.smallball(lg)["cut"])


class FromCache(TempCache):
    def test_league_reads_what_fetch_wrote(self):
        ns.fetch(self.client(FakeSession(_answers())), "2025-26", "Regular Season",
                 today=date(2025, 10, 28))
        lg = ns.League.from_cache("2025-26", "Regular Season", self.dir)
        self.assertEqual(len(lg.team_games), 4)
        self.assertEqual(set(lg.boxes), {"0022500001"})
        share = ns.small_share(lg)
        self.assertAlmostEqual(share[("2025-10-21", NYK)], 27.5 / 48)   # Towns alone is one big
        self.assertAlmostEqual(share[("2025-10-21", CLE)], 1.0)          # Allen not in the index


if __name__ == "__main__":
    unittest.main()
