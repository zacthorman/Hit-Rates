"""nba_api.py: NBA.com box scores turned into SofaScore-shaped line-ups."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import nba_api as na  # noqa: E402

TIP = 1793840400  # 5 Nov 2026 01:00 UTC


def box(status=3):
    def p(name, starter, mins, **st):
        st["minutes"] = mins
        return {"personId": hash(name) % 10000, "name": name, "starter": starter,
                "played": "0" if mins == "PT00M00.00S" else "1", "statistics": st}
    return {"game": {"gameId": "0022600123", "gameStatus": status,
                     "homeTeam": {"teamName": "Thunder", "statistics": {"steals": 7, "reboundsTotal": 47},
                                  "players": [p("Shai Gilgeous-Alexander", "1", "PT35M02.00S", points=42,
                                                reboundsTotal=4, assists=8, steals=0),
                                              p("Josh Dix", "0", "PT00M00.00S")]},
                     "awayTeam": {"teamName": "Cavaliers", "statistics": {"steals": 5, "reboundsTotal": 45},
                                  "players": [p("James Harden", "1", "PT35M18.00S", points=19, reboundsTotal=9,
                                                assists=6, steals=1, threePointersMade=3, turnovers=3)]}}}


class Shaped(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._saved = na.ROOT, na.CACHE_DIR, na.SOFA_CACHE
        na.SOFA_CACHE, na.CACHE_DIR = self.tmp, self.tmp / "nba"
        na.CACHE_DIR.mkdir()
        na._memo.clear()
        na._state.update(stopped="no network in tests", last=0.0)
        (self.tmp / "event_99.json").write_text(json.dumps({"event": {
            "homeTeam": {"name": "Oklahoma City Thunder"}, "awayTeam": {"name": "Cleveland Cavaliers"},
            "startTimestamp": TIP, "status": {"type": "finished"},
            "tournament": {"uniqueTournament": {"name": "NBA"}}}}))
        (self.tmp / "event_99_lineups.json").write_text(json.dumps({"home": {"players": [
            {"player": {"name": "Shai Gilgeous-Alexander", "id": 111}, "teamId": 3418,
             "statistics": {"secondsPlayed": 2102, "points": 42, "rebounds": 4, "assists": 8, "steals": 0}}]},
            "away": {"players": [
                {"player": {"name": "James Harden", "id": 222}, "teamId": 3417,
                 "statistics": {"secondsPlayed": 2118, "points": 19, "rebounds": 9, "assists": 6, "steals": 0,
                                "threePointsMade": 3, "turnovers": 3}}]}}))
        (na.CACHE_DIR / na._cache_file(na.SCHEDULE).name).write_text(json.dumps({"leagueSchedule": {"gameDates": [
            {"games": [{"gameId": "0022600123", "gameDateTimeUTC": "2026-11-05T01:00:00Z",
                        "homeTeam": {"teamName": "Thunder"}, "awayTeam": {"teamName": "Cavaliers"}}]}]}}))
        (na.CACHE_DIR / na._cache_file(na.BOX.format(gid="0022600123")).name).write_text(json.dumps(box()))

    def tearDown(self):
        na.ROOT, na.CACHE_DIR, na.SOFA_CACHE = self._saved
        na._memo.clear()
        na._state.update(stopped=None, last=0.0)

    def test_lineups_carry_sofascore_ids_and_official_numbers(self):
        lu = na.event_lineups(99)
        harden = lu["away"]["players"][0]
        self.assertEqual(harden["player"]["id"], 222)
        self.assertEqual(harden["teamId"], 3417)
        self.assertEqual(harden["statistics"]["steals"], 1)
        self.assertEqual(harden["statistics"]["rebounds"], 9)
        self.assertFalse(harden["substitute"])
        self.assertEqual(harden["statistics"]["secondsPlayed"], 2118)

    def test_did_not_play_has_no_statistics(self):
        lu = na.event_lineups(99)
        dix = [p for p in lu["home"]["players"] if p["player"]["name"] == "Josh Dix"][0]
        self.assertEqual(dix["statistics"], {})

    def test_team_statistics_in_sofascore_shape(self):
        st = na.event_statistics(99)
        items = {i["key"]: i for i in st["statistics"][0]["groups"][0]["statisticsItems"]}
        self.assertEqual((items["steals"]["homeValue"], items["steals"]["awayValue"]), (7, 5))

    def test_compare_finds_the_harden_steal(self):
        r = na.compare(days=10 ** 6)
        self.assertEqual(r["games"], 1)
        self.assertIn(("James Harden", "steals", 0, 1), [(n, k, a, b) for _, n, k, a, b in r["rows"]])
        self.assertEqual(r["differences"], 1)

    def test_short_name_fallback(self):
        self.assertEqual(na._lookup({"ronald holland": 1}, "Ron Holland"), 1)
        self.assertIsNone(na._lookup({"jalen williams": 1, "jaylin williams": 2}, "J. Williams"))

    def test_names(self):
        self.assertEqual(na.norm("Nikola Jokić"), na.norm("Nikola Jokic"))
        self.assertEqual(na.norm("Jabari Smith Jr."), "jabari smith")


if __name__ == "__main__":
    unittest.main()
