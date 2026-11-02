import json
import unittest

import skybet_prices as sk


def _catalog_html(markets, live):
    data = {"data": {"SportsbookMarket": markets, "SportsbookRunnerLiveData": live,
                     "SportsEvent": [{"eventId": 1, "name": "Oklahoma City Thunder @ Cleveland Cavaliers"}]}}
    return "<script>window.__TBD_PRELOADED_CATALOG__ = " + json.dumps(data) + ";</script>"


class Parse(unittest.TestCase):
    def test_preloaded_catalog(self):
        html = _catalog_html(
            [{"marketId": "930.1", "marketType": "TO_SCORE_20+_POINTS", "name": "To Score 20+ Points",
              "runners": [{"name": "Evan Mobley", "selectionId": 7, "handicap": 0}]}],
            [{"selectionId": 7, "market": "ppb:sbkMarket:930.1", "status": "ACTIVE", "trueOdds": {"decimal": 2.5}}])
        ls = sk.lines_of(html)
        self.assertEqual(len(ls), 1)
        self.assertEqual((ls[0]["player"], ls[0]["market"], ls[0]["line"], ls[0]["price"]),
                         ("Evan Mobley", "Points", 19.5, 2.5))

    def test_card_reply(self):
        reply = {"data": {"Cards": [{"full": {"edges": [{"node": {
            "markets": [{"market": {"urn": "ppb:sbkMarket:930.2", "marketType": "3+_MADE_THREES", "name": "3+ Made Threes",
                                    "liveData": {"runners": [{"__typename": "SportsbookRunnerLiveData",
                                                              "marketURN": "ppb:sbkMarket:930.2", "selectionId": 9,
                                                              "runnerStatus": "ACTIVE", "odds": {"decimal": 5.0}}]}}}],
            "runners": [{"displayName": {"name": "Sam Merrill"},
                         "runner": {"selectionId": 9, "marketURN": "ppb:sbkMarket:930.2"}}]}}]}}]}}
        import paddypower_prices as pp
        ls = pp.player_lines(sk.as_page(reply))
        self.assertEqual([(l["player"], l["market"], l["line"], l["price"]) for l in ls],
                         [("Sam Merrill", "Made Threes", 2.5, 5.0)])

    def test_suspended_and_unnamed_left_out(self):
        html = _catalog_html(
            [{"marketId": "930.1", "marketType": "TO_SCORE_20+_POINTS", "name": "x",
              "runners": [{"name": "A", "selectionId": 1}]}],
            [{"selectionId": 1, "market": "ppb:sbkMarket:930.1", "status": "SUSPENDED", "trueOdds": {"decimal": 2.0}},
             {"selectionId": 2, "market": "ppb:sbkMarket:930.1", "status": "ACTIVE", "trueOdds": {"decimal": 3.0}}])
        self.assertEqual(sk.lines_of(html), [])

    def test_no_catalogue_is_empty(self):
        self.assertEqual(sk.catalog("<html>Just a moment...</html>"), {})

    def test_url(self):
        self.assertEqual(sk.page_url(36262178, "Oklahoma City Thunder @ Cleveland Cavaliers", "points"),
                         "https://skybet.com/basketball/nba/oklahoma-city-thunder-cleveland-cavaliers/e-36262178?tab=points")


class FetchLayer(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._real = sk._flare_call

    def tearDown(self):
        sk._flare_call = self._real

    def _fake(self, solution=None, create_ok=True):
        def call(payload, timeout=90):
            self.calls.append(payload["cmd"])
            if payload["cmd"] == "sessions.create":
                return {"status": "ok", "session": "s1"} if create_ok else {"status": "error"}
            if payload["cmd"] == "request.get":
                self.assertEqual(payload["session"], "s1")
                return {"status": "ok", "solution": solution}
            return {"status": "ok"}
        sk._flare_call = call

    def test_one_session_reused_then_destroyed(self):
        page = _catalog_html([], [])
        self._fake({"status": 200, "response": page})
        with sk.Browser("http://fs") as b:
            self.assertEqual(b.mode, "FlareSolverr")
            b.get("https://skybet.com/a")
            b.get("https://skybet.com/b")
        self.assertEqual(self.calls, ["sessions.create", "request.get", "request.get", "sessions.destroy"])

    def test_http_error_is_refused(self):
        self._fake({"status": 403, "response": "nope"})
        with sk.Browser("http://fs") as b, self.assertRaises(sk.Refused):
            b.get("https://skybet.com/a")

    def test_challenge_page_is_refused(self):
        self._fake({"status": 200, "response": "<title>Just a moment...</title>"})
        with sk.Browser("http://fs") as b, self.assertRaises(sk.Refused):
            b.get("https://skybet.com/a")

    def test_flare_off_is_plain(self):
        with sk.Browser("") as b:
            self.assertEqual(b.mode, "plain")
        self.assertEqual(self.calls, [])

    def test_flare_unreachable_falls_back_to_plain(self):
        def boom(payload, timeout=90):
            raise ConnectionRefusedError
        sk._flare_call = boom
        with sk.Browser("http://fs") as b:
            self.assertEqual(b.mode, "plain")


class Pacing(unittest.TestCase):
    def test_points_first_then_every_other_tab_once(self):
        for _ in range(20):
            order = sk.tab_order()
            self.assertEqual(order[0], "points")
            self.assertEqual(sorted(order), sorted(sk.TABS))

    def test_gaps_inside_their_ranges(self):
        for _ in range(200):
            t, g = sk.human_gap("tab"), sk.human_gap("game")
            self.assertTrue(sk.TAB_GAP[0] <= t <= sk.TAB_GAP[1] + sk.BREAK[1])
            self.assertTrue(sk.GAME_GAP[0] <= g <= sk.GAME_GAP[1] + sk.BREAK[1])


if __name__ == "__main__":
    unittest.main()
