"""boostcheck's "Bookie value bets" box: the claim is off, the figures are not.

Run from the repo root with the repo's own Python:

    .venv/bin/python -m unittest tests.test_boostcheck_value

The box listed Paddy Power bets where the player model beat the price, with
Kelly stakes and a "proven" or "about break-even" banner, gated on each
market's own pplog record. Its only settled record in the repo (tonight.html,
23 Oct 2026) lost 32% over 108 bets, so the claim is off behind
boostcheck.VALUE_SHOW (RELEASE-CHECK.md). These tests hold that: off by
default, no bets or stakes shown while off, the bets and the record still
worked out and the record still printed, and the box as it was when on.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import boostcheck  # noqa: E402

BET = {"fixture": "Arsenal v Spurs", "kickoff": 1792000000, "player": "Bukayo Saka", "stat": "Shots",
       "label": "2+", "market": "Player To Have 2 Or More Shots", "price": 2.2, "p": 0.52, "site": 0.5,
       "kelly": 0.12, "fetched": 1791990000, "proven": False, "first_price": 2.3, "xi": "confirmed"}
SEG = {"Shots": {"n": 53, "w": 16, "profit": -19.0, "roi": -19.0 / 53, "pred": 20.0, "wins": [],
                 "robust_roi": -0.4, "shrink": 0.8, "ok": True, "proven": False}}


class ClaimOff(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(boostcheck.VALUE_SHOW)
        self.assertFalse(boostcheck.value_claimed())

    def test_off_lists_nothing_but_still_works_it_out(self):
        with mock.patch.object(boostcheck, "value_bets", return_value=([BET], SEG)) as vb:
            html = boostcheck.value_box(0, 1)
        vb.assert_called_once()                       # the figures are still computed
        self.assertNotIn("vbudget", html)             # no budget box
        self.assertNotIn("data-k=", html)             # no bet rows, no stakes
        self.assertNotIn("Proven", html)
        self.assertNotIn("Saka", html)
        self.assertIn("Value claims are switched off", html)
        self.assertIn("1 bet would have been listed tonight", html)
        self.assertIn("Shots: 53 bets, 16 won, -19.0 pts (-36%)", html)   # the record is still shown

    def test_on_is_the_box_as_it_was(self):
        with mock.patch.object(boostcheck, "VALUE_SHOW", True), \
                mock.patch.object(boostcheck, "value_bets", return_value=([BET], SEG)):
            html = boostcheck.value_box(0, 1)
        self.assertIn("vbudget", html)
        self.assertIn("data-k=", html)
        self.assertIn("Bukayo Saka 2+ shots", html)
        self.assertIn("Not proven yet", html)

    def test_off_with_nothing_tonight(self):
        with mock.patch.object(boostcheck, "value_bets", return_value=([], SEG)):
            html = boostcheck.value_box(0, 1)
        self.assertIn("Value claims are switched off", html)
        self.assertNotIn("would have been listed", html)


class Segments(unittest.TestCase):
    def test_record_sums(self):
        rows = []
        for i in range(25):
            won = i % 4 == 0
            rows.append({"sport": "football", "stat": "Goals", "result": "win" if won else "lose",
                         "last": {"source": "fmodel", "edge": 0.1, "price": 4.0, "chance": 0.3}})
        rows.append({"sport": "football", "stat": "Goals", "result": "win",       # too long a price
                     "last": {"source": "fmodel", "edge": 0.1, "price": 9.0, "chance": 0.15}})
        rows.append({"sport": "football", "stat": "Goals", "result": "lose",      # no edge
                     "last": {"source": "fmodel", "edge": -0.1, "price": 3.0, "chance": 0.3}})
        g = boostcheck._segments(rows)["Goals"]
        self.assertEqual((g["n"], g["w"]), (25, 7))
        self.assertAlmostEqual(g["profit"], 7 * 3.0 - 18)
        self.assertAlmostEqual(g["roi"], 3.0 / 25)
        self.assertTrue(g["ok"])
        self.assertAlmostEqual(g["robust_roi"], (3.0 - 6.0) / 25)
        self.assertFalse(g["proven"])


if __name__ == "__main__":
    unittest.main()
