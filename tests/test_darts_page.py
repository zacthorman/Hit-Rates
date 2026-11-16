"""The 14 Nov 2026 darts changes: exchange prices from the nightly Betfair
file, darts at a double kept beside the doubles hit, and the bookmaker
scraper's matching. No network, no cache: everything is built in the test."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import darts_books      # noqa: E402
import darts_market     # noqa: E402
import hitrates         # noqa: E402


def _event(name, pa, over=1.0, sport="darts", kind="MATCH_ODDS", swapped=False):
    a, b = name.split(" v ")
    return {"betfair": name, "start": "2026-11-14T13:15:00.000Z", "sport": sport, "swapped": swapped,
            "markets": [{"type": kind, "overround": over, "matched": 100.0,
                         "runners": [{"name": a, "price": round(1 / pa, 2), "p": pa},
                                     {"name": b, "price": round(1 / (1 - pa), 2), "p": round(1 - pa, 4)}]}]}


class MarketPricesFallback(unittest.TestCase):
    def _write(self, events, fetched):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = Path(d.name) / "market_prices.json"
        p.write_text(json.dumps({"fetched": fetched, "events": events}))
        return p

    def test_reads_darts_match_odds_only(self):
        now = time.time()
        p = self._write({"1": _event("Luke Woodhouse v Tom Sykes", 0.62),
                         "2": _event("Arsenal v Everton", 0.7, sport="football"),
                         "3": _event("Josh Rock v Tommy Morris", 0.54, kind="PLAYER_AVERAGE_A")}, now - 3600)
        got = darts_market.from_market_prices(p, now)
        self.assertEqual([m["event"] for m in got["matches"]], ["Luke Woodhouse v Tom Sykes"])
        self.assertEqual(got["source"], "market_prices.json")
        self.assertAlmostEqual(darts_market.market_chance(got, "Luke Woodhouse", "Sykes T."), 0.62)
        self.assertAlmostEqual(darts_market.market_chance(got, "Tom Sykes", "Luke Woodhouse"), 0.38)

    def test_too_old_is_not_used(self):
        now = time.time()
        p = self._write({"1": _event("Luke Woodhouse v Tom Sykes", 0.62)},
                        now - (darts_market.FALLBACK_HOURS + 1) * 3600)
        self.assertIsNone(darts_market.from_market_prices(p, now))

    def test_one_sided_book_is_dropped(self):
        # 1.02 v 1.45 is what a ladder with nobody on one side looks like: 167%.
        now = time.time()
        p = self._write({"1": _event("Jim McEwan v David Davies", 0.59, over=1.67)}, now)
        self.assertIsNone(darts_market.from_market_prices(p, now))

    def test_missing_file_is_none(self):
        self.assertIsNone(darts_market.from_market_prices(Path("/nonexistent/market_prices.json")))


class DartsAtDouble(unittest.TestCase):
    RAW = {"statistics": [{"period": "ALL", "groups": [{"groupName": "Attacking", "statisticsItems": [
        {"name": "Thrown 180", "home": "5", "away": "0", "homeValue": 5, "awayValue": 0},
        {"name": "Checkouts accuracy", "home": "6/26 (23%)", "away": "1/11 (9%)",
         "homeValue": 6, "awayValue": 1, "homeTotal": 26, "awayTotal": 11}]}]}]}

    def test_total_kept_beside_the_hits(self):
        got = hitrates.extract_match_stats(self.RAW)["ALL"]
        self.assertEqual(got["Checkouts accuracy"], (6.0, 1.0))
        self.assertEqual(got["Darts at double"], (26.0, 11.0))

    def test_not_a_market(self):
        import markets
        self.assertNotIn("Darts at double", markets.stats_for("darts"))

    def test_no_total_no_row(self):
        raw = json.loads(json.dumps(self.RAW))
        item = raw["statistics"][0]["groups"][0]["statisticsItems"][1]
        del item["homeTotal"], item["awayTotal"]
        self.assertNotIn("Darts at double", hitrates.extract_match_stats(raw)["ALL"])


class BooksMatching(unittest.TestCase):
    FIX = {"10": {"home": "Luke Littler", "away": "Beau Greaves", "kickoff": 0},
           "11": {"home": "Ross Smith", "away": "Rodriguez R.", "kickoff": 0},
           "12": {"home": "Stephen Bunting", "away": "Raymond Smith", "kickoff": 0}}

    def test_slug_matches_on_both_surnames_either_order(self):
        self.assertEqual(darts_books.match_slug("luke-littler-v-beau-greaves", self.FIX), "10")
        self.assertEqual(darts_books.match_slug("beau-greaves-v-luke-littler", self.FIX), "10")
        self.assertEqual(darts_books.match_slug("ross-smith-v-rowby-john-rodriguez", self.FIX), "11")
        self.assertEqual(darts_books.match_slug("raymond-smith-v-stephen-bunting", self.FIX), "12")

    def test_one_surname_is_not_enough(self):
        self.assertIsNone(darts_books.match_slug("ross-smith-v-michael-smith", self.FIX))
        self.assertIsNone(darts_books.match_slug("luke-littler-v-luke-humphries", self.FIX))

    def test_links_and_markets_read_off_a_page(self):
        html = ('<a href="/darts/grand-slam-of-darts/luke-littler-v-beau-greaves/winner">x</a>'
                '{"ocMarketId":123,"marketTypeName":"Winner"}{"ocMarketId":456,"marketTypeName":"First Leg Winner"}')
        self.assertEqual(darts_books.match_links(html, "darts"),
                         {"luke-littler-v-beau-greaves":
                          "https://www.oddschecker.com/darts/grand-slam-of-darts/luke-littler-v-beau-greaves/winner"})
        self.assertEqual(darts_books.wanted_markets(html), {"123": ("Match winner", "winner")})

    def test_best_price_skips_exchanges_and_suspended(self):
        market = {"bets": [{"betId": 1, "betName": "Luke Littler"}, {"betId": 2, "betName": "Beau Greaves"}],
                  "odds": [{"betId": 1, "bookmakerCode": "B3", "oddsDecimal": 1.25, "status": "ACTIVE"},
                           {"betId": 1, "bookmakerCode": "PP", "oddsDecimal": 1.29, "status": "ACTIVE"},
                           {"betId": 1, "bookmakerCode": "BF", "oddsDecimal": 1.40, "status": "ACTIVE"},
                           {"betId": 2, "bookmakerCode": "SK", "oddsDecimal": 4.0, "status": "ACTIVE"},
                           {"betId": 2, "bookmakerCode": "WH", "oddsDecimal": 4.5, "status": "SUSPENDED"}]}
        rows = {r["selection"]: r for r in darts_books.rows_for(market)}
        self.assertEqual((rows["Luke Littler"]["best"], rows["Luke Littler"]["book"], rows["Luke Littler"]["n"]), (1.29, "PP", 2))
        self.assertEqual((rows["Beau Greaves"]["best"], rows["Beau Greaves"]["bookName"]), (4.0, "Sky Bet"))


if __name__ == "__main__":
    unittest.main()
