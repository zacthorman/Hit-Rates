"""besttrack._team_value: a half-period card leg reads that half, never the match.

SofaScore leaves a card row out of a half's statistics bucket when nobody was
booked in that half. That is 0 cards in the half, not a cue to read the full
match. Run from the repo root with the repo's own Python:

    .venv/bin/python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import besttrack  # noqa: E402

EVENT = {"homeTeam": {"name": "Home FC"}, "awayTeam": {"name": "Away FC"},
         "homeScore": {"current": 1, "period1": 1, "period2": 0},
         "awayScore": {"current": 0, "period1": 0, "period2": 0}}

# Home booked twice in the first half and never in the second, so the feed's
# 2ND bucket has no card row at all.
STATS = {"ALL": {"Yellow cards": [2.0, 0.0], "Corner kicks": [6.0, 3.0]},
         "1ST": {"Yellow cards": [2.0, 0.0], "Corner kicks": [4.0, 1.0]},
         "2ND": {"Corner kicks": [2.0, 2.0]}}


def leg(stat: str, period: str, team: str = "Home FC") -> dict:
    return {"team": team, "stat": stat, "period": period}


class HalfCardTest(unittest.TestCase):
    def test_missing_card_row_in_a_half_is_zero(self) -> None:
        self.assertEqual(besttrack._team_value(leg("Yellow cards", "2ND"), EVENT, STATS), 0.0)

    def test_missing_card_row_in_the_first_half_is_zero(self) -> None:
        stats = {"ALL": {"Yellow cards": [0.0, 3.0]}, "1ST": {"Corner kicks": [1.0, 1.0]},
                 "2ND": {"Yellow cards": [0.0, 3.0]}}
        self.assertEqual(besttrack._team_value(leg("Yellow cards", "1ST", "Away FC"),
                                               EVENT, stats), 0.0)

    def test_present_card_row_in_a_half_is_read(self) -> None:
        self.assertEqual(besttrack._team_value(leg("Yellow cards", "1ST"), EVENT, STATS), 2.0)

    def test_empty_half_bucket_is_left_unsettled(self) -> None:
        # No half statistics at all means the feed has not got them, not 0 cards.
        stats = {"ALL": {"Yellow cards": [2.0, 0.0]}, "1ST": {}, "2ND": {}}
        self.assertIsNone(besttrack._team_value(leg("Yellow cards", "2ND"), EVENT, stats))
        stats = {"ALL": {"Yellow cards": [2.0, 0.0]}}
        self.assertIsNone(besttrack._team_value(leg("Yellow cards", "2ND"), EVENT, stats))

    def test_half_never_falls_back_to_the_full_match(self) -> None:
        # A non-card stat missing from a half is unknown, not the match total.
        self.assertIsNone(besttrack._team_value(leg("Yellow cards", "2ND"), EVENT,
                                                {"ALL": {"Yellow cards": [2.0, 0.0]},
                                                 "2ND": {}}))
        self.assertIsNone(besttrack._team_value(leg("Total shots", "2ND"), EVENT,
                                                {"ALL": {"Total shots": [9.0, 4.0]},
                                                 "2ND": {"Corner kicks": [2.0, 2.0]}}))


class FullMatchUnchangedTest(unittest.TestCase):
    def test_full_match_card_row_missing_is_still_zero(self) -> None:
        stats = {"ALL": {"Corner kicks": [6.0, 3.0]}}
        self.assertEqual(besttrack._team_value(leg("Yellow cards", "ALL", "Away FC"),
                                               EVENT, stats), 0.0)

    def test_full_match_reads_the_bucket(self) -> None:
        self.assertEqual(besttrack._team_value(leg("Corner kicks", "ALL"), EVENT, STATS), 6.0)

    def test_full_match_market_is_still_derived(self) -> None:
        self.assertEqual(besttrack._team_value(leg("Match corners", "ALL"), EVENT, STATS), 9.0)

    def test_half_goals_read_the_period_score(self) -> None:
        self.assertEqual(besttrack._team_value(leg("Goals", "1ST"), EVENT, STATS), 1.0)
        self.assertEqual(besttrack._team_value(leg("Goals", "2ND"), EVENT, STATS), 0.0)


class SettleTest(unittest.TestCase):
    """besttrack.settle end to end: the second-half over loses on 0 cards."""

    def test_second_half_over_with_first_half_cards_loses(self) -> None:
        import hitrates
        import sofascore_api as api

        tmp = Path(tempfile.mkdtemp())
        saved_store, saved_leads = besttrack.STORE, besttrack.LEAD_LOG
        saved = (api.get_json, api.event_statistics, hitrates.extract_match_stats)
        try:
            besttrack.STORE = tmp / "best_bets.json"
            besttrack.LEAD_LOG = tmp / "lead_log.json"   # settle also tracks logged leads
            past = int(time.time()) - 4 * 3600  # settle waits 3 hours after kick-off
            base = {"event_id": 1, "kickoff": past, "sport": "football", "player": None, "team": "Home FC",
                    "stat": "Yellow cards", "period": "2ND", "line": 0.5,
                    "value": None, "result": None}
            besttrack.save([{"result": None, "legs": [dict(base, over=True)]},
                            {"result": None, "legs": [dict(base, over=False)]}])
            api.get_json = lambda *a, **k: {"event": dict(EVENT, status={"type": "finished"})}
            api.event_statistics = lambda *a, **k: {}
            hitrates.extract_match_stats = lambda *a, **k: STATS
            with contextlib.redirect_stdout(io.StringIO()):
                besttrack.settle()
            over, under = besttrack.load()
            self.assertEqual((over["legs"][0]["value"], over["legs"][0]["result"]), (0.0, "lose"))
            self.assertEqual((under["legs"][0]["value"], under["legs"][0]["result"]), (0.0, "win"))
        finally:
            besttrack.STORE, besttrack.LEAD_LOG = saved_store, saved_leads
            api.get_json, api.event_statistics, hitrates.extract_match_stats = saved
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
