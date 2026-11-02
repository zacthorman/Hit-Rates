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


class StopList(unittest.TestCase):
    """2 Nov 2026 backtest: markets kept out of every pick."""

    def mk(self, sport, **kw):
        l = leg(1, kw.pop("fair", 1.6), 15, 20, book=kw.pop("book", None), stat=kw.pop("stat", "Points"),
                player=kw.pop("player", "P"))
        l["fixture"]["sport"] = sport
        l.update(kw)
        return l

    def test_football_player_props_out_team_lines_in(self):
        self.assertTrue(weekend.stopped(self.mk("football", stat="Shots")))
        self.assertFalse(weekend.stopped(self.mk("football", stat="Corner kicks", player=None)))

    def test_long_alt_overs_out(self):
        self.assertTrue(weekend.stopped(self.mk("basketball", alt=True, book=3.4)))
        self.assertFalse(weekend.stopped(self.mk("basketball", alt=True, book=1.8)))

    def test_nba_main_overs_out_unders_in(self):
        self.assertTrue(weekend.stopped(self.mk("basketball")))
        self.assertFalse(weekend.stopped(self.mk("basketball", over=False)))

    def test_nfl_low_volume_receiving_out(self):
        self.assertTrue(weekend.stopped(self.mk("american-football", stat="Receiving yards", position="RB", avg=40)))
        self.assertTrue(weekend.stopped(self.mk("american-football", stat="Receiving yards", position="WR", avg=18)))
        self.assertFalse(weekend.stopped(self.mk("american-football", stat="Receiving yards", position="WR", avg=60)))


if __name__ == "__main__":
    unittest.main()
