"""Pinnacle in the value check (28 Oct 2026).

1. Reaching our own daily request cap stops the run but does not lock the
   feed out (it used to lock it out for 24 hours, so a day went unfetched).
2. Team lines are checked against Pinnacle first, Betfair second, and the
   snapshot says which; side lines only when Pinnacle's home side is ours.
3. Paddy Power's match goals totals are read into their own key.
"""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pinnacle_prices  # noqa: E402
import sharp  # noqa: E402
import paddypower_prices  # noqa: E402


class Cap(unittest.TestCase):
    def test_own_cap_is_not_a_refusal(self):
        st = {"count": {pinnacle_prices.today(): pinnacle_prices.MAX_PER_DAY}}
        with self.assertRaises(pinnacle_prices.Capped):
            pinnacle_prices.get("/x", st)
        self.assertFalse(issubclass(pinnacle_prices.Capped, pinnacle_prices.Refused))

    def test_old_cap_lockout_is_cleared(self):
        with tempfile.TemporaryDirectory() as d:
            state, out = Path(d) / "s.json", Path(d) / "o.json"
            state.write_text(json.dumps({"lockedUntil": time.time() + 9999,
                                         "lockedWhy": "daily cap of 150 reached"}))
            with mock.patch.object(pinnacle_prices, "STATE", state), \
                    mock.patch.object(pinnacle_prices, "OUT", out), \
                    mock.patch.object(pinnacle_prices, "OFF", Path(d) / "off"), \
                    mock.patch.object(pinnacle_prices, "pin_events", return_value={}), \
                    mock.patch.object(pinnacle_prices, "league_ids", return_value={}):
                pinnacle_prices.run()
            self.assertNotIn("lockedUntil", json.loads(state.read_text()))


class TeamView(unittest.TestCase):
    def setUp(self):
        self.pin = {"1": {"name": "Monza v Napoli", "lines": {
            ("match", "Corner kicks", 9.5, True): {"p": 0.45, "how": "pinnacle"},
            ("side1", "Corner kicks", 5.5, True): {"p": 0.44, "how": "pinnacle"},
            ("match", "Goals", 2.5, True): {"p": 0.52, "how": "pinnacle"}}}}
        self.bf = {"1": {("match", "Corner kicks", 9.5, True): {"p": 0.49, "back": 2.0, "lay": 2.1, "how": "exchange"},
                         ("match", "Yellow cards", 3.5, True): {"p": 0.5, "back": 1.9, "lay": 2.1, "how": "exchange"}}}

    def row(self, **k):
        r = {"event_id": 1, "fixture": "Monza v SSC Napoli", "scope": "match", "side": None,
             "stat": "Corner kicks", "line": 9.5, "over": True}
        r.update(k)
        return r

    def test_pinnacle_first_betfair_kept(self):
        v = sharp.lookup(self.bf, self.row(), self.pin)
        self.assertEqual((v["src"], v["p"], v["bf_p"], v["lay"]), ("pinnacle", 0.45, 0.49, 2.1))

    def test_betfair_fallback(self):
        v = sharp.lookup(self.bf, self.row(stat="Yellow cards", line=3.5), self.pin)
        self.assertEqual(v["src"], "betfair")

    def test_goals_and_sides_from_pinnacle(self):
        self.assertEqual(sharp.lookup({}, self.row(stat="Goals", line=2.5), self.pin)["p"], 0.52)
        self.assertEqual(sharp.lookup({}, self.row(scope="away", side=1, line=5.5), self.pin)["p"], 0.44)

    def test_side_lines_need_the_same_home_team(self):
        r = self.row(scope="away", side=1, line=5.5, fixture="Napoli v Monza")
        self.assertIsNone(sharp.lookup({}, r, self.pin))

    def test_snapshot_records_source(self):
        s = sharp.snap({"last": {"price": 2.4}}, dict(self.pin["1"]["lines"][("match", "Corner kicks", 9.5, True)],
                                                      src="pinnacle", bf_p=0.49), 0)
        self.assertEqual((s["src"], s["bf_p"], s["edge"]), ("pinnacle", 0.49, 0.08))


class PaddyGoals(unittest.TestCase):
    def test_goal_totals_read(self):
        m = {"marketType": "OVER_UNDER_25", "marketName": "Over/Under 2.5 Goals", "runners": [
            {"runnerStatus": "ACTIVE", "runnerName": "Over 2.5 Goals",
             "winRunnerOdds": {"trueOdds": {"decimalOdds": {"decimalOdds": 1.9}}}},
            {"runnerStatus": "ACTIVE", "runnerName": "Under 2.5 Goals",
             "winRunnerOdds": {"trueOdds": {"decimalOdds": {"decimalOdds": 1.95}}}}]}
        other = {"marketType": "TOTAL_CORNERS_9.5", "runners": []}
        got = paddypower_prices.goal_lines({"attachments": {"markets": {"a": m, "b": other}}})
        self.assertEqual([(g["stat"], g["line"], g["over"], g["price"]) for g in got],
                         [("Goals", 2.5, True, 1.9), ("Goals", 2.5, False, 1.95)])


if __name__ == "__main__":
    unittest.main()
