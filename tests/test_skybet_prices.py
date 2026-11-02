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


if __name__ == "__main__":
    unittest.main()
