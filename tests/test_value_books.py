"""The Oddschecker rework and the value section (30 Oct 2026)."""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bet365_prices as b3  # noqa: E402
import oddschecker_client as oc  # noqa: E402
import pinnacle_prices  # noqa: E402
import value_books as vb  # noqa: E402

MARKET_SHOTS = {
    "marketTypeName": "Player Shots",
    "bets": [{"betId": 1, "betName": "Callum Wilson Over", "line": "0.5"},
             {"betId": 2, "betName": "Callum Wilson Over", "line": "1.5"}],
    "odds": [{"betId": 1, "bookmakerCode": "B3", "oddsDecimal": 1.30, "status": "ACTIVE"},
             {"betId": 1, "bookmakerCode": "PP", "oddsDecimal": 1.36, "status": "ACTIVE"},
             {"betId": 1, "bookmakerCode": "SK", "oddsDecimal": 1.40, "status": "ACTIVE"},
             {"betId": 2, "bookmakerCode": "B3", "oddsDecimal": 2.10, "status": "FAILED"},
             {"betId": 2, "bookmakerCode": "WH", "oddsDecimal": 2.20, "status": "ACTIVE"}],
}
MARKET_CORNERS = {
    "marketTypeName": "Total Corners",
    "bets": [{"betId": 9, "betName": "Over", "line": "9.5"}, {"betId": 10, "betName": "Under", "line": "9.5"},
             {"betId": 11, "betName": "Over", "line": "10"}],
    "odds": [{"betId": 9, "bookmakerCode": "B3", "oddsDecimal": 1.90, "status": "ACTIVE"},
             {"betId": 10, "bookmakerCode": "PP", "oddsDecimal": 1.83, "status": "ACTIVE"},
             {"betId": 11, "bookmakerCode": "B3", "oddsDecimal": 2.0, "status": "ACTIVE"}],
}


class AllBooks(unittest.TestCase):
    def test_player_rows_keep_bet365_paddy_and_best(self):
        rows = b3.all_rows(MARKET_SHOTS)
        r = next(x for x in rows if x["line"] == 0.5)
        self.assertEqual((r["player"], r["stat"], r["over"]), ("Callum Wilson", "Shots", True))
        self.assertEqual(r["books"], {"B3": 1.3, "PP": 1.36})
        self.assertEqual((r["best"], r["bestBook"], r["n"]), (1.4, "SK", 3))
        r2 = next(x for x in rows if x["line"] == 1.5)
        self.assertEqual(r2["books"], {})          # Bet365 suspended: not kept, Hill is still the best price

    def test_team_rows_half_lines_only(self):
        rows = b3.all_rows(MARKET_CORNERS)
        self.assertEqual(sorted((r["over"], r["line"], r["scope"]) for r in rows),
                         [(False, 9.5, "match"), (True, 9.5, "match")])


class Discovery(unittest.TestCase):
    def test_both_page_layouts(self):
        links = '<a href="/football/spain/la-liga-primera/villarreal-v-espanyol/winner">x</a>'
        data = '<!--{"subevents":{"entities":{"1":{"urlMap":"brentford-v-nottingham-forest"}}}}-->'
        self.assertEqual(b3.match_slugs(links, "football/spain/la-liga-primera"), {"villarreal-v-espanyol"})
        self.assertEqual(b3.match_slugs(data, "football/english/premier-league"), {"brentford-v-nottingham-forest"})

    def test_page_file_is_the_add_name(self):
        f = b3.page_file("https://www.oddschecker.com/football/english/premier-league/brentford-v-nottingham-forest/winner")
        self.assertEqual(f.name, "football-english-premier-league-brentford-v-nottingham-forest-winner.html")


class Budget(unittest.TestCase):
    def client(self, budget):
        with mock.patch.object(oc.OddscheckerClient, "_load_state", lambda self: None):
            return oc.OddscheckerClient(budget=budget)

    def test_a_wait_that_does_not_fit_stops_the_run(self):
        c = self.client(20)
        with self.assertRaises(oc.BudgetExceeded):
            c._sleep(60, "backoff")

    def test_two_blocks_in_a_row_stop_the_run(self):
        c = self.client(300)
        c._note_block()
        with self.assertRaises(oc.BudgetExceeded):
            c._note_block()

    def test_spent_budget_stops_before_a_request(self):
        c = self.client(300)
        c.deadline = time.time() - 1
        with self.assertRaises(oc.BudgetExceeded):
            c._pace()


class PinnaclePause(unittest.TestCase):
    def test_connection_error_is_transient(self):
        import requests
        st = {"count": {}}
        with mock.patch.object(pinnacle_prices, "requests") as rq, mock.patch.object(pinnacle_prices, "HDR", {}, create=True), \
                mock.patch.object(pinnacle_prices, "MIN_GAP", 0), mock.patch.object(pinnacle_prices, "JITTER", 0):
            rq.RequestException = requests.RequestException
            rq.get.side_effect = requests.ConnectionError("boom")
            with self.assertRaises(pinnacle_prices.Transient):
                pinnacle_prices.get("/x", st)


class Rules(unittest.TestCase):
    def run_build(self, rows, model=(None, None), bf=None, pin=None, mt=None):
        with mock.patch.object(vb, "candidates", return_value=rows), \
                mock.patch.object(vb, "model_player", return_value=model), \
                mock.patch.object(vb, "betfair_player", return_value=bf), \
                mock.patch.object(vb, "pinnacle_team", return_value=pin), \
                mock.patch.object(vb, "model_team", return_value=mt), \
                mock.patch.object(vb, "_load", return_value={}), \
                mock.patch("sharp.index", return_value={}), mock.patch("teamlog._files", return_value=[]):
            return vb.build(time.time())

    def player(self, **books):
        return [{"fid": "1", "kickoff": time.time() + 3600, "game": "A v B", "player": "X Y", "key": "x y",
                 "stat": "Shots", "line": 0.5, "over": True, "books": books}]

    def team(self, **books):
        return [{"fid": "1", "kickoff": time.time() + 3600, "game": "A v B", "home": "A", "away": "B",
                 "stat": "Corner kicks", "scope": "match", "line": 9.5, "over": True, "books": books}]

    def test_player_takes_the_better_book_when_the_model_agrees(self):
        got = self.run_build(self.player(B3=1.60, PP=1.70), model=("X Y", 0.65))
        self.assertEqual((got[0]["book"], got[0]["price"]), ("PP", 1.70))      # 0.65 x 1.70 = 1.105

    def test_player_dropped_when_the_model_is_short_of_5pc(self):
        self.assertEqual(self.run_build(self.player(B3=1.60), model=("X Y", 0.65)), [])  # 1.04

    def test_player_dropped_when_betfair_says_short(self):
        self.assertEqual(self.run_build(self.player(B3=1.70), model=("X Y", 0.65), bf=0.55), [])  # 0.935

    def test_team_needs_pinnacle_and_the_model(self):
        self.assertEqual(len(self.run_build(self.team(B3=2.10), pin=0.50, mt=0.52)), 1)
        self.assertEqual(self.run_build(self.team(B3=2.10), pin=0.47, mt=0.60), [])   # Pinnacle: 0.987
        self.assertEqual(self.run_build(self.team(B3=2.10), pin=0.50, mt=0.45), [])   # model: 0.945
        self.assertEqual(self.run_build(self.team(B3=2.10), pin=None, mt=0.60), [])   # no Pinnacle price


if __name__ == "__main__":
    unittest.main()
