"""oddschecker_import.py on synthetic saved pages (tests/fixtures/oddschecker/).

    python -m pytest tests/test_oddschecker_import.py

Every team, player and price in the fixtures is made up. Nothing here makes a
request: fixture matching runs on a hand-built events dict.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import markets_sidecar  # noqa: E402
import oddschecker_import as oc  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "oddschecker"
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc).timestamp()


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


EVENTS = {
    "901": {"betfair": "Northbridge v Southfield", "start": _iso(NOW + 26 * 3600)},
    "902": {"betfair": "Eastwick v Westmoor", "start": _iso(NOW + 30 * 3600)},
    "903": {"betfair": "Northbridge v Southfield", "start": _iso(NOW - 3600)},   # started
}


class Prices(unittest.TestCase):
    def test_decimal_reads_fractions_decimals_and_evens(self):
        self.assertEqual(oc.decimal("6/5"), 2.2)
        self.assertEqual(oc.decimal("2.75"), 2.75)
        self.assertEqual(oc.decimal("EVS"), 2.0)
        self.assertIsNone(oc.decimal("15:00"))
        self.assertIsNone(oc.decimal("1"))           # not a price
        self.assertIsNone(oc.decimal("3/0"))

    def test_best_skips_exchanges(self):
        self.assertEqual(oc.best([("B3", 2.5), ("BF", 3.1), ("WH", 2.6)]), (2.6, "WH", 2))
        self.assertIsNone(oc.best([("BF", 3.1)]))
        self.assertEqual(oc.best([("", 2.0), ("", 2.2)]), (2.2, None, 2))


class Files(unittest.TestCase):
    def test_classic_table_takes_best_bookmaker_not_exchange(self):
        got = oc.read_file(FIX / "classic-table.html")
        self.assertEqual(got["layout"], "table")
        self.assertEqual((got["home"], got["away"], got["market"]),
                         ("northbridge", "southfield", "anytime-goalscorer"))
        by = {l["player"]: l for l in got["lines"]}
        # Betfair Exchange's 3.6 is higher but is not a bookmaker's price.
        self.assertEqual((by["Tomás Ferreira"]["price"], by["Tomás Ferreira"]["book"]), (3.0, "PP"))
        self.assertEqual(by["Tomás Ferreira"]["books"], 3)
        self.assertEqual(by["Tomás Ferreira"]["key"], "tomas ferreira")
        # Fractions only (no data-odig) still read.
        self.assertEqual((by["Kofi Mensah"]["price"], by["Kofi Mensah"]["book"]), (6.0, "WH"))
        self.assertEqual(by["Kofi Mensah"]["market"], "Anytime Goalscorer")
        self.assertNotIn("No Goalscorer", by)
        self.assertNotIn("Exchange Only", by)

    def test_json_lines_become_counts_and_unders_are_dropped(self):
        got = oc.read_file(FIX / "northbridge-v-southfield-player-shots-on-target.json")
        self.assertEqual(got["layout"], "json")
        lines = {(l["player"], l["market"]): l for l in got["lines"]}
        one = lines[("Tomas Ferreira", "Player To Have 1 Or More Shots On Target")]
        self.assertEqual((one["price"], one["book"]), (1.67, "SK"))
        two = lines[("Tomas Ferreira", "Player To Have 2 Or More Shots On Target")]
        self.assertEqual((two["price"], two["book"]), (3.75, "B3"))   # suspended 4.0 ignored
        self.assertEqual(lines[("Kofi Mensah", "Player To Have 1 Or More Shots On Target")]["price"], 2.5)
        self.assertEqual(len(got["lines"]), 3)

    def test_copied_text_reads_counts_and_needs_two_prices(self):
        got = oc.read_file(FIX / "northbridge-v-southfield-player-shots.txt")
        self.assertEqual(got["layout"], "text")
        lines = {(l["player"], l["market"]): l for l in got["lines"]}
        self.assertEqual(lines[("Tomás Ferreira", "Player To Have 2 Or More Shots")]["price"], 2.0)
        self.assertEqual(lines[("Tomás Ferreira", "Player To Have 3 Or More Shots")]["price"], 3.25)
        self.assertEqual(lines[("Kofi Mensah", "Player To Have 1 Or More Shots")]["price"], 1.333)
        self.assertTrue(all(l["book"] is None for l in got["lines"]))
        # "Kofi Mensah 2+ 6/4" has one price: not a row of odds.
        self.assertNotIn(("Kofi Mensah", "Player To Have 2 Or More Shots"), lines)
        self.assertEqual(len(got["lines"]), 3)

    def test_file_without_market_or_game_is_reported_not_read(self):
        self.assertIn("error", oc.read_file(FIX / "no-market-here.txt"))

    def test_market_from_address_or_file_name(self):
        self.assertEqual(oc.market_and_game(
            "https://www.oddschecker.com/football/english/premier-league/man-city-v-arsenal/player-shots-on-target"),
            ("player-shots-on-target", ("man city", "arsenal")))
        self.assertEqual(oc.market_and_game("man-city-v-arsenal-player-shots"),
                         ("player-shots", ("man city", "arsenal")))
        self.assertIsNone(oc.market_and_game("man-city-v-arsenal-match-result"))


class Build(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _drop(self, name, mtime, src=None, text=None):
        p = self.tmp / name
        p.write_text(text if text is not None else (FIX / src).read_text(encoding="utf-8"), encoding="utf-8")
        os.utime(p, (mtime, mtime))
        return p

    def test_matches_upcoming_game_either_way_round(self):
        self.assertEqual(oc.match_game("northbridge", "southfield", EVENTS, NOW)[0], "901")
        self.assertEqual(oc.match_game("southfield", "northbridge", EVENTS, NOW)[0], "901")
        self.assertEqual(oc.match_game("nowhere", "elsewhere", EVENTS, NOW), (None, None))
        # Only the started copy is left: nothing.
        only_started = {"903": EVENTS["903"]}
        self.assertEqual(oc.match_game("northbridge", "southfield", only_started, NOW), (None, None))

    def test_build_merges_markets_and_newest_file_wins(self):
        a = self._drop("classic-table.html", NOW - 7200, src="classic-table.html")
        b = self._drop("northbridge-v-southfield-player-shots.txt", NOW - 3600,
                       src="northbridge-v-southfield-player-shots.txt")
        newer = self._drop("northbridge-v-southfield-anytime-goalscorer.txt", NOW - 600,
                           text="Tomás Ferreira\t5/2\t11/4\n")
        out = oc.build([a, b, newer], EVENTS, NOW)
        ev = out["events"]["901"]
        self.assertEqual(set(out["events"]), {"901"})
        gs = [l for l in ev["lines"] if l["type"] == "anytime-goalscorer"]
        # The newer goalscorer file replaces the older one's market whole.
        self.assertEqual([(l["player"], l["price"]) for l in gs], [("Tomás Ferreira", 3.75)])
        self.assertEqual(sum(1 for l in ev["lines"] if l["type"] == "player-shots"), 3)
        self.assertEqual(ev["fetchedAt"], NOW - 600)

    def test_empty_folder_writes_nothing_new(self):
        old_drop, old_out = oc.DROP, oc.OUT
        try:
            oc.DROP, oc.OUT = self.tmp / "drop", self.tmp / "oddschecker.json"
            self.assertEqual(oc.run(), 0)
            self.assertFalse(oc.OUT.exists())
            oc.DROP.mkdir()
            self.assertEqual(oc.run(), 0)
            self.assertFalse(oc.OUT.exists())
        finally:
            oc.DROP, oc.OUT = old_drop, old_out


class Sidecar(unittest.TestCase):
    def test_sidecar_carries_best_price_and_bookmaker(self):
        tmp = Path(tempfile.mkdtemp())
        old = markets_sidecar.HERE
        try:
            (tmp / "reports").mkdir()
            data = oc.build([FIX / "classic-table.html"], EVENTS, NOW)
            (tmp / "reports" / "oddschecker.json").write_text(json.dumps(data))
            markets_sidecar.HERE = tmp
            out = markets_sidecar.build({"events": {}})
        finally:
            markets_sidecar.HERE = old
            shutil.rmtree(tmp)
        rows = out["events"]["901"]["oc"]["players"]["tomas ferreira"]
        self.assertEqual(rows, [{"m": "Anytime Goalscorer", "s": "", "o": None, "l": None,
                                 "p": 3.0, "b": "PP", "n": 3}])

    def test_sidecar_unchanged_without_imports(self):
        tmp = Path(tempfile.mkdtemp())
        old = markets_sidecar.HERE
        try:
            markets_sidecar.HERE = tmp
            self.assertEqual(markets_sidecar.build({"events": {}}), {"fetched": None, "events": {}})
        finally:
            markets_sidecar.HERE = old
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
