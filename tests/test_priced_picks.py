"""2 Nov 2026: every pick of the week carries a real Paddy Power / Bet365 price."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import weekend  # noqa: E402


def leg(fid, fair, hits, total, book=None, stat="Rushing yards", player=None):
    out = {"fixture": {"id": fid, "sport": "american-football"}, "team": "A", "teamIndex": 0,
           "period": "ALL", "stat": stat, "line": 49.5, "over": True, "venue": "home",
           "source": "x", "crossLeague": False, "hits": hits, "total": total, "fair": fair,
           "evidence": 0.5, "need": fair, "player": player}
    if book:
        out["book"] = {"name": "Paddy Power", "price": book}
    return out


class PricedOnly(unittest.TestCase):
    def setUp(self):
        self.was = weekend.PRICED_ONLY
        weekend.PRICED_ONLY = True

    def tearDown(self):
        weekend.PRICED_ONLY = self.was

    def test_no_book_price_no_single(self):
        self.assertIsNone(weekend.best_single([leg(1, 2.2, 14, 20), leg(2, 2.1, 30, 50)]))

    def test_single_comes_from_a_priced_leg(self):
        got = weekend.best_single([leg(1, 2.2, 14, 20), leg(2, 2.1, 30, 50, book=2.3)])
        self.assertEqual(got["book"]["price"], 2.3)
        self.assertTrue(got["confirmed"])

    def test_no_unpriced_banker_double_or_acca(self):
        legs = [leg(i, 1.4, 18, 20) for i in range(6)]
        self.assertIsNone(weekend.best_banker(legs))
        self.assertIsNone(weekend.best_double(legs))
        self.assertIsNone(weekend.best_acca(legs))

    def test_switch_off_restores_fair_fallback(self):
        weekend.PRICED_ONLY = False
        self.assertIsNotNone(weekend.best_single([leg(1, 2.2, 14, 20), leg(2, 2.1, 30, 50)]))


if __name__ == "__main__":
    unittest.main()
