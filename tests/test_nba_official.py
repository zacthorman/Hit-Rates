"""nba_official.py: matching SofaScore games and players to NBA.com's box score."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import nba_official as no  # noqa: E402

TIP = 1793840400.0  # Cavaliers at Thunder, 5 Nov 2026 01:00 UTC


def schedule_json():
    return {"leagueSchedule": {"gameDates": [{"gameDate": "11/04/2026 00:00:00", "games": [
        {"gameId": "0022600123", "gameDateTimeUTC": "2026-11-05T01:00:00Z",
         "homeTeam": {"teamCity": "Oklahoma City", "teamName": "Thunder"},
         "awayTeam": {"teamCity": "Cleveland", "teamName": "Cavaliers"}},
        {"gameId": "0022600124", "gameDateTimeUTC": "2026-11-05T03:30:00Z",
         "homeTeam": {"teamCity": "LA", "teamName": "Clippers"},
         "awayTeam": {"teamCity": "Miami", "teamName": "Heat"}}]}]}}


def box_json(status=3):
    def p(name, mins, **st):
        st["minutes"] = mins
        return {"name": name, "played": "1" if mins != "PT00M00.00S" else "0", "statistics": st}
    return {"game": {"gameId": "0022600123", "gameStatus": status,
                     "homeTeam": {"teamName": "Thunder", "players": [
                         p("Shai Gilgeous-Alexander", "PT35M02.00S", points=42, reboundsTotal=4, assists=8,
                           steals=0, blocks=1, threePointersMade=2),
                         p("Josh Dix", "PT00M00.00S", points=0)]},
                     "awayTeam": {"teamName": "Cavaliers", "players": [
                         p("James Harden", "PT35M18.00S", points=19, reboundsTotal=9, assists=6, steals=1,
                           blocks=2, threePointersMade=3),
                         p("Tyrese Proctor", "PT22M00.00S", points=11, reboundsTotal=1, assists=0, steals=0,
                           blocks=0, threePointersMade=2)]}}}


class Matching(unittest.TestCase):
    def test_names_ignore_accents_and_suffixes(self):
        self.assertEqual(no.norm("Nikola Jokić"), no.norm("Nikola Jokic"))
        self.assertEqual(no.norm("Jabari Smith Jr."), no.norm("Jabari Smith"))
        self.assertEqual(no.norm("Robert Williams III"), no.norm("Robert Williams"))

    def test_teams_match_on_nickname(self):
        games = no.parse_schedule(schedule_json())
        self.assertEqual(no.find_game(games, "Los Angeles Clippers", "Miami Heat", TIP + 9000), "0022600124")
        self.assertEqual(no.find_game(games, "Oklahoma City Thunder", "Cleveland Cavaliers", TIP), "0022600123")

    def test_home_and_away_swapped_still_match(self):
        games = no.parse_schedule(schedule_json())
        self.assertEqual(no.find_game(games, "Cleveland Cavaliers", "Oklahoma City Thunder", TIP), "0022600123")

    def test_wrong_day_does_not_match(self):
        games = no.parse_schedule(schedule_json())
        self.assertIsNone(no.find_game(games, "Oklahoma City Thunder", "Cleveland Cavaliers", TIP + 86400))


class Values(unittest.TestCase):
    def test_harden_steal_is_read_from_the_official_box(self):
        st = no.players(box_json())[no.norm("James Harden")]
        self.assertEqual(no.stat_value(st, "Steals"), 1.0)
        self.assertEqual(no.stat_value(st, "Points rebounds and assists"), 34.0)
        self.assertEqual(no.stat_value(st, "Three pointers made"), 3.0)

    def test_player_who_did_not_play_is_left_out(self):
        self.assertNotIn(no.norm("Josh Dix"), no.players(box_json()))

    def test_minutes_parse(self):
        self.assertAlmostEqual(no.minutes("PT34M12.00S"), 34.2)


class OfficialValue(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._root, self._dir = no.ROOT, no.DIR
        no.ROOT, no.DIR = self.tmp, self.tmp / "cache" / "nba_official"
        no.DIR.mkdir(parents=True)
        (self.tmp / "cache" / "event_16824816.json").write_text(json.dumps(
            {"event": {"homeTeam": {"name": "Oklahoma City Thunder"}, "awayTeam": {"name": "Cleveland Cavaliers"}}}))
        (no.DIR / "schedule.json").write_text(json.dumps(schedule_json()))
        no._state.update(stopped="no network in tests", last=0.0)
        no._memo.clear()

    def tearDown(self):
        no.ROOT, no.DIR = self._root, self._dir
        no._state.update(stopped=None, last=0.0)
        no._memo.clear()

    def leg(self, **kw):
        base = {"event_id": 16824816, "kickoff": TIP, "player": "James Harden", "stat": "Steals",
                "line": 0.5, "over": True, "fixture": "Oklahoma City Thunder v Cleveland Cavaliers"}
        return {**base, **kw}

    def test_cached_final_box_gives_the_official_value(self):
        (no.DIR / "box_0022600123.json").write_text(json.dumps(box_json()))
        self.assertEqual(no.official_value(self.leg(), fetch=False), 1.0)
        self.assertEqual(no.official_value(self.leg(player="Tyrese Proctor"), fetch=False), 0.0)

    def test_box_that_is_not_final_is_ignored(self):
        (no.DIR / "box_0022600123.json").write_text(json.dumps(box_json(status=2)))
        self.assertIsNone(no.official_value(self.leg(), fetch=False))

    def test_no_box_and_no_network_gives_none(self):
        self.assertIsNone(no.official_value(self.leg(), fetch=True))

    def test_unknown_stat_gives_none(self):
        (no.DIR / "box_0022600123.json").write_text(json.dumps(box_json()))
        self.assertIsNone(no.official_value(self.leg(stat="Turnovers"), fetch=False))


if __name__ == "__main__":
    unittest.main()
