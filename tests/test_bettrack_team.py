"""bettrack.py log --team: a team leg recorded exactly as settle reads it.

Run from the repo root with the repo's own Python:

    .venv/bin/python -m unittest discover -s tests

Every test points bettrack at a temporary bets.json and reports/ folder, so the
real files are never written.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bettrack  # noqa: E402

EVENT = 999001
KICKOFF = int(time.time()) + 3 * 86400


def _record(day: int, shots: float, corners_1st: float, cards_2nd: float | None,
            goals: float, opp_corners: float = 4.0) -> dict:
    second = {"Total shots": shots / 2}
    if cards_2nd is not None:
        second["Yellow cards"] = cards_2nd
    return {
        "id": day, "date": f"2026-09-{day:02d}", "opponent": f"Opp {day}",
        "venue": "home", "goals_for": goals, "goals_against": 1,
        "stats": {"ALL": {"Total shots": shots, "Corner kicks": 5.0, "Goals": goals},
                  "1ST": {"Corner kicks": corners_1st}, "2ND": second},
        "against": {"ALL": {"Corner kicks": opp_corners, "Goals": 1.0},
                    "1ST": {}, "2ND": {}},
    }


def _fixture(kickoff: int = KICKOFF) -> dict:
    # Twelve games for the home side, oldest first, so "last 10" drops two.
    home = [_record(d, shots=10 + d, corners_1st=d % 3, cards_2nd=(None if d % 4 == 0 else 1.0),
                    goals=d % 3) for d in range(1, 13)]
    away = [_record(d, shots=8, corners_1st=1, cards_2nd=0.0, goals=1) for d in range(1, 11)]
    player_rows = [{"player": "Ann Striker", "player_id": 77, "date": f"2026-09-{d:02d}",
                    "stats": {"Total shots": float(d % 4)}} for d in range(1, 13)]
    return {
        "fixture": {"id": EVENT, "home": "Home FC", "away": "Away FC", "kickoff": kickoff},
        "teams": [{"name": "Home FC", "id": 1, "side": "home"},
                  {"name": "Away FC", "id": 2, "side": "away"}],
        "records": [home, away],
        "players": [player_rows, []],
    }


class TeamLegTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.reports = self.tmp / "reports"
        self.reports.mkdir()
        self._write_report(_fixture())
        self.saved = {k: getattr(bettrack, k) for k in ("BETS", "REPORTS", "CALIB", "LESSONS")}
        bettrack.BETS = self.tmp / "bets.json"
        bettrack.REPORTS = self.reports
        bettrack.CALIB = self.tmp / "calibration.json"
        bettrack.LESSONS = self.tmp / "LESSONS.md"

    def tearDown(self) -> None:
        for k, v in self.saved.items():
            setattr(bettrack, k, v)
        shutil.rmtree(self.tmp)

    def _write_report(self, fx: dict) -> None:
        body = json.dumps({"fixtures": [fx]})
        (self.reports / "test-league.html").write_text(
            f"<script>\nconst ALL = {body};\n</script>", encoding="utf-8")

    def run_cli(self, *argv: str) -> str:
        args = bettrack.parser().parse_args(list(argv))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            {"log": bettrack.log}[args.cmd](args)
        return out.getvalue()

    def only_leg(self) -> tuple[dict, dict]:
        bets = bettrack.load()
        self.assertEqual(len(bets), 1)
        self.assertEqual(len(bets[0]["legs"]), 1)
        return bets[0], bets[0]["legs"][0]

    # ------------------------------------------------------------- the leg

    def test_team_over_full_match_is_recorded_as_settle_reads_it(self) -> None:
        self.run_cli("log", "--event", str(EVENT), "--team", "Home FC", "--stat", "Total shots",
                     "--line", "15.5", "--side", "over", "--period", "ALL",
                     "--price", "1.40", "--stake", "2", "--suggested", "--group", "g1")
        bet, leg = self.only_leg()
        # Last 10 of 12 games: shots 13..22, over 15.5 is 16..22, 7 of 10.
        self.assertEqual((leg["model_k"], leg["model_n"]), (7, 10))
        self.assertEqual(leg["model_p"], round(bettrack.adjusted(7, 10), 3))
        for key, want in {"team_leg": True, "team": "Home FC", "player": "Home FC",
                          "player_id": None, "stat": "Total shots", "period": "ALL",
                          "line": 15.5, "over": True, "event_id": EVENT,
                          "fixture": "Home FC v Away FC", "kickoff": KICKOFF,
                          "source": "test-league.html", "value": None,
                          "result": None}.items():
            self.assertEqual(leg[key], want, key)
        self.assertEqual(bet["group"], "g1")
        self.assertFalse(bet["placed"])
        self.assertEqual((bet["price"], bet["stake"], bet["kind"]), (1.40, 2.0, "single"))

    def test_under_counts_values_below_the_line(self) -> None:
        self.run_cli("log", "--event", str(EVENT), "--team", "Home FC", "--stat", "Total shots",
                     "--line", "15.5", "--side", "under", "--suggested")
        _, leg = self.only_leg()
        self.assertEqual((leg["model_k"], leg["model_n"], leg["over"]), (3, 10, False))

    def test_a_half_reads_that_half(self) -> None:
        self.run_cli("log", "--event", str(EVENT), "--team", "Home FC", "--stat", "Corner kicks",
                     "--line", "0.5", "--period", "1ST", "--suggested")
        _, leg = self.only_leg()
        # Days 3..12, corners d % 3: zero on 3, 6, 9, 12, so 6 of 10 over 0.5.
        self.assertEqual((leg["model_k"], leg["model_n"], leg["period"]), (6, 10, "1ST"))

    def test_a_missing_card_row_in_a_half_is_no_cards(self) -> None:
        # The feed leaves a card row out when nobody was booked, as settle assumes.
        self.run_cli("log", "--event", str(EVENT), "--team", "Home FC", "--stat", "Yellow cards",
                     "--line", "0.5", "--period", "2ND", "--suggested")
        _, leg = self.only_leg()
        # Days 3..12: no row on 4, 8, 12, so 7 of 10 over 0.5.
        self.assertEqual((leg["model_k"], leg["model_n"]), (7, 10))

    def test_a_match_market_missing_from_an_old_report_is_derived(self) -> None:
        self.run_cli("log", "--event", str(EVENT), "--team", "Home FC", "--stat", "Match corners",
                     "--line", "8.5", "--suggested")
        _, leg = self.only_leg()
        # 5 + 4 = 9 corners every game.
        self.assertEqual((leg["model_k"], leg["model_n"]), (10, 10))

    def test_default_group_names_the_side_and_period(self) -> None:
        self.run_cli("log", "--event", str(EVENT), "--team", "Away FC", "--stat", "Total shots",
                     "--line", "9.5", "--side", "under", "--period", "ALL", "--suggested")
        bet, leg = self.only_leg()
        self.assertEqual(bet["group"], "Away FC-Total shots-under-9.5-ALL")
        self.assertEqual((leg["model_k"], leg["model_n"]), (10, 10))

    # ------------------------------------------------------------ refusals

    def test_unknown_team_is_refused(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            self.run_cli("log", "--event", str(EVENT), "--team", "Nobody", "--stat",
                         "Total shots", "--line", "9.5", "--suggested")
        self.assertIn("Home FC", str(caught.exception))
        self.assertEqual(bettrack.load(), [])

    def test_a_stat_with_no_record_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            self.run_cli("log", "--event", str(EVENT), "--team", "Home FC", "--stat",
                         "Throw-ins", "--line", "9.5", "--suggested")
        self.assertEqual(bettrack.load(), [])

    def test_after_kick_off_is_refused_without_backfill(self) -> None:
        self._write_report(_fixture(kickoff=int(time.time()) - 60))
        with self.assertRaises(SystemExit):
            self.run_cli("log", "--event", str(EVENT), "--team", "Home FC", "--stat",
                         "Total shots", "--line", "9.5", "--suggested")
        self.assertEqual(bettrack.load(), [])

    def test_player_and_team_together_is_refused(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_cli("log", "--event", str(EVENT), "--team", "Home FC", "--player",
                         "Ann Striker", "--stat", "Total shots", "--line", "2")

    def test_a_player_leg_takes_no_side_or_period(self) -> None:
        for extra in (["--side", "under"], ["--period", "1ST"], ["--side", "over"]):
            with self.assertRaises(SystemExit):
                self.run_cli("log", "--event", str(EVENT), "--player", "Ann Striker",
                             "--stat", "Total shots", "--line", "2", "--suggested", *extra)
        self.assertEqual(bettrack.load(), [])

    def test_side_and_period_are_checked(self) -> None:
        for extra in (["--side", "both"], ["--period", "3RD"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.run_cli("log", "--event", str(EVENT), "--team", "Home FC", "--stat",
                             "Total shots", "--line", "9.5", *extra)

    # ------------------------------------------------- player legs unchanged

    def test_player_leg_is_exactly_as_before(self) -> None:
        self.run_cli("log", "--event", str(EVENT), "--player", "Ann Striker", "--stat",
                     "Total shots", "--line", "2", "--price", "1.8", "--suggested")
        bet, leg = self.only_leg()
        # The keys and values the old code wrote, nothing added.
        vals = [float(d % 4) for d in range(3, 13)]
        k = sum(v >= 2 for v in vals)
        self.assertEqual(leg, {
            "event_id": EVENT, "fixture": "Home FC v Away FC", "kickoff": KICKOFF,
            "player": "Ann Striker", "player_id": 77, "team": "Home FC",
            "stat": "Total shots", "line": 2.0, "model_k": k, "model_n": 10,
            "model_p": round(bettrack.adjusted(k, 10), 3), "source": "test-league.html",
            "value": None, "result": None})
        self.assertEqual(bet["group"], "Ann Striker-Total shots-2.0")

    # ------------------------------------------------------------- settle

    def test_settle_reads_a_logged_team_leg(self) -> None:
        import besttrack  # noqa: F401  (settle imports it for team legs)
        import hitrates
        import sofascore_api as api

        self._write_report(_fixture(kickoff=int(time.time()) + 3600))
        self.run_cli("log", "--event", str(EVENT), "--team", "Away FC", "--stat",
                     "Yellow cards", "--line", "0.5", "--period", "2ND", "--side", "under",
                     "--price", "1.30", "--stake", "2", "--suggested", "--group", "g2")
        bets = bettrack.load()
        bets[0]["legs"][0]["kickoff"] = int(time.time()) - 7200
        bettrack.save(bets)
        event = {"event": {"status": {"type": "finished"},
                           "homeTeam": {"name": "Home FC"}, "awayTeam": {"name": "Away FC"},
                           "homeScore": {"current": 1}, "awayScore": {"current": 0}}}
        stats = {"ALL": {"Yellow cards": [2.0, 1.0]}, "2ND": {"Yellow cards": [1.0, 0.0]}}
        saved = (api.get_json, api.event_statistics, hitrates.extract_match_stats)
        api.get_json = lambda *a, **k: event
        api.event_statistics = lambda *a, **k: {}
        hitrates.extract_match_stats = lambda *a, **k: stats
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                bettrack.settle(None)
        finally:
            api.get_json, api.event_statistics, hitrates.extract_match_stats = saved
        bet = bettrack.load()[0]
        self.assertEqual(bet["legs"][0]["value"], 0.0)
        self.assertEqual(bet["legs"][0]["result"], "win")
        self.assertEqual(bet["result"], "win")
        self.assertEqual(bet["profit"], round(2 * 0.30, 2))


class OldBetsTest(unittest.TestCase):
    """bets.json written by the old code still loads, and a team leg added to it
    leaves every old bet exactly as it was."""

    def test_the_real_bets_json_still_loads_and_round_trips(self) -> None:
        real = ROOT / "bets.json"
        if not real.exists():
            self.skipTest("no bets.json in this checkout")
        tmp = Path(tempfile.mkdtemp())
        saved = bettrack.BETS
        try:
            copy = tmp / "bets.json"
            shutil.copy(real, copy)
            bettrack.BETS = copy
            before = bettrack.load()
            self.assertIsInstance(before, list)
            for b in before:
                for leg in b["legs"]:
                    self.assertIn("model_k", leg)
                    self.assertIn("line", leg)
            bettrack.save(before)
            self.assertEqual(bettrack.load(), before)
            # Calibration reads every settled leg, player and team alike.
            legs = bettrack._legs(include_site=False)
            self.assertTrue(all(l["result"] in ("win", "lose") for l in legs))
        finally:
            bettrack.BETS = saved
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
