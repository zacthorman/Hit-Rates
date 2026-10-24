"""Main's 24 Oct value claims are off; their figures are still worked out.

Run from the repo root with the repo's own Python:

    .venv/bin/python -m unittest tests.test_value_claims_off

Three claims arrived with main's 24 Oct update, none with a settled record
whose interval is above zero (RELEASE-CHECK.md):

  sharp.py      "Paddy Power v Betfair": lines paying 2%+ over Betfair's fair
                price, with edges and a budget split. Nothing settled yet.
  ruletrack.py  "Rules on trial": the model-agrees short list "to bet from".
                No live results; the history is in sample.
  b365value.py  Bet365 lines against the player model, tagged BOTH as the
                strongest kind. No settled record.

Each is behind its own VALUE_SHOW flag, False. These tests hold that: off by
default, no bets, edges or stakes on the page while off, the inputs still
computed and the record still shown, and the old output when switched on.
"""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import b365value  # noqa: E402
import ruletrack  # noqa: E402
import sharp  # noqa: E402

ROW = {"player": "Bukayo Saka", "label": "1+", "stat": "Shots on target", "sport": "football",
       "fixture": "Arsenal v Spurs", "kickoff": 1792000000, "last": {"price": 2.1, "t": 1791990000},
       "event_id": 1, "over": True, "line": 0.5}
SHARP_BET = {"row": ROW, "edge": 0.06, "p": 0.505, "price": 2.1,
             "sig": {"lay": True, "model": True, "xi": True, "count": 3}, "kelly": 0.055}
SHARP_REC = {"all": {"n": 4, "w": 2, "profit": 0.4, "exp": 1.9}}


class Sharp(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(sharp.VALUE_SHOW)
        self.assertFalse(sharp.value_claimed())

    def test_off_lists_nothing_but_still_works_it_out(self):
        with mock.patch.object(sharp, "live", return_value=[SHARP_BET]) as lv, \
                mock.patch.object(sharp, "record", return_value=SHARP_REC) as rc:
            html = sharp.box(0, 1, False)
        lv.assert_called_once()
        rc.assert_called_once()
        self.assertIn("Value claims are switched off", html)
        self.assertIn("1 player lines", html)
        self.assertIn("4 settled, 2 won", html)
        for gone in ("sbudget", "data-k=", "Saka", "+6%"):
            self.assertNotIn(gone, html)

    def test_on_is_the_box_as_it_was(self):
        with mock.patch.object(sharp, "VALUE_SHOW", True), \
                mock.patch.object(sharp, "live", return_value=[SHARP_BET]), \
                mock.patch.object(sharp, "record", return_value=SHARP_REC):
            html = sharp.box(0, 1, False)
        for there in ("sbudget", "data-k=", "Bukayo Saka", "+6%"):
            self.assertIn(there, html)

    def test_stamping_is_untouched(self):
        # The Betfair check is still written into the logs for the record.
        self.assertTrue(callable(sharp.stamp))
        self.assertEqual(sharp.MIN_EDGE, 0.02)


def rule_bet(edge):
    return {**ROW, "stat": "Points", "label": "Under 20.5", "sport": "basketball", "over": False,
            "line": 20.5, "_model_edge": edge}


class Rules(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(ruletrack.VALUE_SHOW)

    def _box(self, on):
        q = {"nba_under_main": [rule_bet(0.1)] * 3, "nba_under_model": [rule_bet(0.4)]}
        with mock.patch.object(ruletrack, "VALUE_SHOW", on), \
                mock.patch.object(ruletrack, "tonight", return_value=q) as tn, \
                mock.patch.object(ruletrack, "qualifying", return_value={}), \
                mock.patch.object(ruletrack.pplog, "all_rows", return_value=[]):
            html = ruletrack.box(0, 1)
        tn.assert_called_once()
        return html

    def test_off_lists_no_bets(self):
        html = self._box(False)
        self.assertIn("No bets are listed until a rule's live record shows it making money", html)
        self.assertIn("3 qualify tonight, logged for the test", html)
        self.assertIn("1 qualify tonight, logged for the test", html)
        for gone in ("short list to bet from", "Small, equal stakes", "<table", "+40%"):
            self.assertNotIn(gone, html)

    def test_on_is_the_box_as_it_was(self):
        html = self._box(True)
        for there in ("short list to bet from", "Small, equal stakes", "<table", "+40%"):
            self.assertIn(there, html)


B365_ROW = {"mkt": 2.0, "mkt_n": 6, "vs_mkt": 0.05, "both": True, "fixture": "Arsenal v Spurs",
            "kickoff": 1792000000, "player": "Bukayo Saka", "stat": "Shots on target", "n": 1, "price": 2.1,
            "model": 0.52, "raw": 0.55, "edge": 0.092, "pp": 2.0, "xi": "predicted", "fetched": 1}


class Bet365(unittest.TestCase):
    def run_main(self, on):
        buf = io.StringIO()
        with mock.patch.object(b365value, "VALUE_SHOW", on), \
                mock.patch.object(b365value, "rows", return_value=[B365_ROW]) as rw, \
                mock.patch.object(sys, "argv", ["b365value.py"]), contextlib.redirect_stdout(buf):
            b365value.main()
        rw.assert_called_once()
        return buf.getvalue()

    def test_off_by_default(self):
        self.assertFalse(b365value.VALUE_SHOW)

    def test_off_prints_the_figures_without_calling_them_value(self):
        out = self.run_main(False)
        self.assertIn("Value claims are off", out)
        self.assertIn("+9%", out)                      # the figures are still printed
        self.assertIn("Bukayo Saka 1+ shots on target", out)
        self.assertNotIn("BOTH", out)

    def test_on_tags_both(self):
        out = self.run_main(True)
        self.assertIn("BOTH", out)
        self.assertNotIn("Value claims are off", out)


if __name__ == "__main__":
    unittest.main()
