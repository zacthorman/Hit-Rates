"""Competition names: every spelling of a league finds it, everywhere.

    .venv/bin/python -B -m unittest tests.test_league_names

The same bug kept coming back in a new file: a name compared as written.
"LaLiga" lowered to "laliga", the table held "la_liga", and the league was
skipped in silence: in run.py (fixed in tournament_id_for), then in
backtest.py and calib/strength_eval/strength_eval.py, which still looked the
name up with TOURNAMENTS.get. Brazil's feed names ("Campeonato Brasileiro
Série A", "Brasileirão Betano") and every stage name ("NFL, Regular Season")
resolved to nothing at all.
"""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import context  # noqa: E402
import markets  # noqa: E402
import sofascore_api as api  # noqa: E402


class TournamentIdFor(unittest.TestCase):
    def test_every_spelling_of_la_liga(self):
        for name in ("LaLiga", "La Liga", "la_liga", "la-liga", "LA LIGA", "laliga", "8"):
            self.assertEqual(api.tournament_id_for(name), 8, name)

    def test_the_feeds_own_names(self):
        # Every uniqueTournament and tournament name for a tracked league in the cache.
        cases = {"Campeonato Brasileiro Série A": 325, "Brasileirão Betano": 325, "Brasileirao": 325,
                 "NFL, Regular Season": 9464, "MLS, Playoffs": 242, "NBA, Playoffs": 132,
                 "UEFA Champions League, Knockout stage": 7, "UEFA Europa League, Qualification": 679,
                 "UEFA Nations League, League A, Gr. 3": 10783, "Championship, Promotion Playoffs": 18,
                 "Ligue 1, Relegation/Promotion Playoffs": 34, "Premier League": 17, "Serie A": 23,
                 "Bundesliga": 35}
        for name, tid in cases.items():
            self.assertEqual(api.tournament_id_for(name), tid, name)

    def test_italy_is_not_brazil(self):
        self.assertEqual(api.tournament_id_for("Serie A"), 23)
        self.assertEqual(api.tournament_id_for("Campeonato Brasileiro Série A"), 325)

    def test_unknown_is_none(self):
        self.assertIsNone(api.tournament_id_for("Eredivisie"))
        self.assertIsNone(api.tournament_id_for(""))

    def test_every_table_key_resolves_to_itself(self):
        for key, tid in api.TOURNAMENTS.items():
            self.assertEqual(api.tournament_id_for(key), tid, key)


class CompetitionTables(unittest.TestCase):
    def test_markets_match_any_spelling(self):
        deep = markets.stats_for_competition("football", "LaLiga")
        self.assertIn("Fouls", deep)
        for name in ("La Liga", "LALIGA", "la-liga", "LaLiga, Round 9"):
            self.assertEqual(markets.stats_for_competition("football", name), deep, name)
            self.assertEqual(markets.player_stats_for_competition("football", name),
                             markets.player_stats_for_competition("football", "LaLiga"), name)

    def test_short_names_survive_a_stage(self):
        self.assertEqual(context._short("UEFA Champions League, Knockout stage"), "UCL")
        self.assertEqual(context._short("La Liga"), "LaLiga")
        self.assertEqual(context._short("Premier League"), "PL")


class ReplayScripts(unittest.TestCase):
    """The two replays resolve names through tournament_id_for, and say so when they cannot."""

    def run_script(self, *args):
        return subprocess.run([sys.executable, "-B", *args], cwd=ROOT, capture_output=True,
                              text=True, timeout=120)

    def test_backtest_resolves_laliga(self):
        out = self.run_script("backtest.py", "--league", "LaLiga").stdout
        self.assertNotIn("unknown league 'LaLiga'", out)
        self.assertIn("unknown league 'NotALeague'",
                      self.run_script("backtest.py", "--league", "NotALeague").stdout)

    def test_strength_eval_refuses_an_unknown_league_out_loud(self):
        r = self.run_script("calib/strength_eval/strength_eval.py", str(ROOT), "/dev/null",
                            "2025-08-01", "NotALeague")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown league 'NotALeague'", r.stderr + r.stdout)

    def test_no_name_lookup_bypasses_tournament_id_for(self):
        for f in ("backtest.py", "calib/strength_eval/strength_eval.py", "run.py"):
            self.assertNotIn("TOURNAMENTS.get(", (ROOT / f).read_text(encoding="utf-8"), f)


if __name__ == "__main__":
    unittest.main()
