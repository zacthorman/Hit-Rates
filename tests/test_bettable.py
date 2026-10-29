"""bettable.py: tonight's page lists only what Paddy Power sells (28 Oct 2026)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bettable  # noqa: E402

PP = {"events": {"9": {"ppHome": "Venezia", "ppAway": "Inter", "lines": [
    {"market": "Player To Have 2 Or More Shots", "player": "Marcus Thuram", "price": 1.6},
    {"market": "Points", "player": "Cade Cunningham", "side": "OVER", "line": 24.5, "price": 1.9}],
    "team": [{"stat": "Corner kicks", "scope": "away", "line": 5.5, "over": False, "price": 1.85}],
    "goals": [{"stat": "Goals", "scope": "match", "line": 2.5, "over": True, "price": 1.7}]}}}
META = {"id": 9, "home": "Venezia", "away": "Inter"}


class Bettable(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        path = Path(self.d.name) / "pp.json"
        path.write_text(json.dumps(PP))
        bettable._IX = bettable.index(path)

    def tearDown(self):
        bettable._IX = None
        self.d.cleanup()

    def test_exact_selection_with_price(self):
        leg = {"player": "Marcus Thuram", "team": "Inter", "stat": "Shots", "alt": True, "threshold": 2, "period": "ALL"}
        self.assertEqual(bettable.check(leg, META, "football"), (True, 1.6))
        self.assertEqual(bettable.check({"team": "Inter", "stat": "Corner kicks", "line": 5.5, "over": False}, META,
                                        "football"), (True, 1.85))

    def test_line_paddy_does_not_offer(self):
        leg = {"player": "Marcus Thuram", "stat": "Shots", "alt": True, "threshold": 4, "period": "ALL"}
        self.assertFalse(bettable.check(leg, META, "football")[0])

    def test_markets_paddy_never_sells(self):
        self.assertFalse(bettable.check({"player": "X", "stat": "Turnovers", "line": 1.5, "over": True},
                                        {"id": 1}, "basketball")[0])
        self.assertFalse(bettable.check({"player": "X", "stat": "Tackles", "alt": True, "threshold": 1},
                                        {"id": 1}, "football")[0])
        self.assertFalse(bettable.check({"team": "Inter", "stat": "Corner kicks", "line": 2.5, "over": True,
                                         "period": "1ST"}, META, "football")[0])

    def test_unpriced_game_falls_back_to_what_paddy_sells(self):
        self.assertEqual(bettable.check({"player": "X", "stat": "Points", "line": 20.5, "over": True},
                                        {"id": 2}, "basketball"), (True, None))


if __name__ == "__main__":
    unittest.main()
