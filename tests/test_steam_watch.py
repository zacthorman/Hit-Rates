import json
import tempfile
import time
import unittest
from pathlib import Path

import steam_watch as sw


def _soft(fid, player, market, side, line, price, at=None):
    return {"events": {str(fid): {"fetchedAt": at or time.time(), "lines": [
        {"market": market, "player": player, "side": side, "line": line, "price": price, "selection": ""}]}}}


GAME = {"gid": "900", "name": "Dallas Mavericks v Sacramento Kings", "kickoff": time.time() + 3600, "fid": 16824700}
ROW = {"player": "Max Christie", "stat": "Points", "line": 9.5, "over": True, "price": 1.80, "p": 0.5192}


class Decide(unittest.TestCase):
    def idx(self, price=2.625, at=None):
        return sw.soft_index({"Paddy": _soft(16824700, "Max Christie", "Points", "OVER", 9.5, price, at)})

    def test_christie_alerts(self):
        got = sw.decide([ROW], {}, self.idx(), {}, GAME, time.time())
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["book"], "Paddy")
        self.assertAlmostEqual(got[0]["edge"], 2.625 * 0.5192 - 1, places=3)

    def test_no_alert_under_three_percent(self):
        self.assertEqual(sw.decide([ROW], {}, self.idx(1.95), {}, GAME, time.time()), [])

    def test_same_line_only(self):
        other = dict(ROW, line=10.5)
        self.assertEqual(sw.decide([other], {}, self.idx(), {}, GAME, time.time()), [])

    def test_not_twice_unless_edge_grows(self):
        first = sw.decide([ROW], {}, self.idx(), {}, GAME, time.time())[0]
        alerted = {first["key"]: first["edge"]}
        self.assertEqual(sw.decide([ROW], {}, self.idx(), alerted, GAME, time.time()), [])
        bigger = dict(ROW, p=0.56)
        self.assertEqual(len(sw.decide([bigger], {}, self.idx(), alerted, GAME, time.time())), 1)

    def test_stale_soft_price_ignored(self):
        old = time.time() - (sw.STALE_SOFT_HOURS + 1) * 3600
        self.assertEqual(sw.decide([ROW], {}, self.idx(at=old), {}, GAME, time.time()), [])

    def test_move_flagged(self):
        key = f"900|{sw.norm('Max Christie')}|Points|9.5|1"
        got = sw.decide([ROW], {key: 0.47}, self.idx(), {}, GAME, time.time())
        self.assertTrue(got[0]["moved"])
        title, body = sw.message(got[0])
        self.assertIn("was 2.13", body)
        self.assertIn("Paddy 2.62", title)


class Poll(unittest.TestCase):
    def test_one_learning_call_then_one_price_call_per_poll(self):
        import pinnacle_prices as PP
        d = Path(tempfile.mkdtemp())
        saved = (sw.PROPS, sw.SOFT, sw.STATE, sw.ALERTS, sw.TOPIC_FILE, PP.get, sw.notify)
        (d / "props.json").write_text(json.dumps({"events": {"900": dict(GAME, sport="basketball")}}))
        (d / "pp.json").write_text(json.dumps(_soft(16824700, "Max Christie", "Points", "OVER", 9.5, 2.625)))
        sw.PROPS, sw.SOFT, sw.STATE, sw.ALERTS = d / "props.json", {"Paddy": d / "pp.json"}, d / "st.json", d / "a.jsonl"
        sw.TOPIC_FILE = d / "topic.txt"
        calls, sent = [], []

        def fake_get(path, st):
            calls.append(path)
            if path.endswith("/related"):
                return [{"id": 5, "type": "special",
                         "special": {"category": "Player Props", "description": "Max Christie (Points)"},
                         "participants": [{"id": 11, "name": "Over"}, {"id": 12, "name": "Under"}]}]
            return [{"matchupId": 5, "period": 0, "status": "open", "prices": [
                {"participantId": 11, "price": -125, "points": 9.5},
                {"participantId": 12, "price": 106, "points": 9.5}]}]
        PP.get = fake_get
        sw.notify = lambda t, b: sent.append(t)
        real_recheck = sw.recheck_paddy
        sw.recheck_paddy = lambda fid, st: [{"market": "Points", "player": "Max Christie", "side": "OVER",
                                             "line": 9.5, "price": 2.625, "selection": ""}]
        try:
            st = {}
            self.assertEqual(sw.poll(st), 1)
            self.assertEqual(sw.poll(st), 0)          # same edge: no second alert
            self.assertEqual(sum(p.endswith("/related") for p in calls), 1)
            self.assertEqual(sum(p.endswith("/straight") for p in calls), 2)
            self.assertEqual(len((d / "a.jsonl").read_text().splitlines()), 1)
        finally:
            sw.recheck_paddy = real_recheck
            sw.PROPS, sw.SOFT, sw.STATE, sw.ALERTS, sw.TOPIC_FILE, PP.get, sw.notify = saved

    def test_topic_made_once(self):
        d = Path(tempfile.mkdtemp())
        saved = sw.TOPIC_FILE
        sw.TOPIC_FILE = d / "t.txt"
        try:
            t = sw.topic()
            self.assertTrue(t.startswith("hitrates-steam-"))
            self.assertEqual(sw.topic(), t)
        finally:
            sw.TOPIC_FILE = saved


class Confirm(unittest.TestCase):
    def setUp(self):
        self.real = sw.recheck_paddy

    def tearDown(self):
        sw.recheck_paddy = self.real

    def cands(self):
        idx = sw.soft_index({"Paddy": _soft(16824700, "Max Christie", "Points", "OVER", 9.5, 2.625)})
        return sw.decide([ROW], {}, idx, {}, GAME, time.time())

    def test_price_already_moved_is_not_sent(self):
        sw.recheck_paddy = lambda fid, st: [{"market": "Points", "player": "Max Christie", "side": "OVER",
                                             "line": 9.5, "price": 2.0, "selection": ""}]
        self.assertEqual(sw.confirm(self.cands(), [ROW], {}, {}, GAME, {}), [])

    def test_still_there_is_sent(self):
        sw.recheck_paddy = lambda fid, st: [{"market": "Points", "player": "Max Christie", "side": "OVER",
                                             "line": 9.5, "price": 2.5, "selection": ""}]
        got = sw.confirm(self.cands(), [ROW], {}, {}, GAME, {})
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["price"], 2.5)

    def test_no_recheck_allowed_is_not_sent(self):
        sw.recheck_paddy = lambda fid, st: None
        self.assertEqual(sw.confirm(self.cands(), [ROW], {}, {}, GAME, {}), [])

    def test_duplicate_soft_lines_alert_once(self):
        d = _soft(16824700, "Max Christie", "Points", "OVER", 9.5, 2.625)
        ev = d["events"]["16824700"]
        ev["lines"] = ev["lines"] * 3
        self.assertEqual(len(sw.decide([ROW], {}, sw.soft_index({"Paddy": d}), {}, GAME, time.time())), 1)

    def test_confirm_room_caps(self):
        st = {}
        for _ in range(sw.CONFIRM_PER_NIGHT):
            self.assertTrue(sw._confirm_room(st, "Paddy", str(len(st.get("confirm", {}).get("last", {})))))
            sw.STATE_SAVED = None
            st["confirm"]["Paddy"] = st["confirm"].get("Paddy", 0) + 1
        self.assertFalse(sw._confirm_room(st, "Paddy", "new"))


class Waiting(unittest.TestCase):
    def test_next_kickoff_inside_wait_only(self):
        d = Path(tempfile.mkdtemp())
        saved = sw.PROPS
        now = time.time()
        (d / "p.json").write_text(json.dumps({"events": {
            "soon": {"sport": "basketball", "kickoff": now + 3600},            # already in the window
            "tonight": {"sport": "basketball", "kickoff": now + 9 * 3600},
            "later": {"sport": "american-football", "kickoff": now + 11 * 3600},
            "tomorrow": {"sport": "basketball", "kickoff": now + 20 * 3600},
            "football": {"sport": "football", "kickoff": now + 5 * 3600}}}))
        sw.PROPS = d / "p.json"
        try:
            self.assertAlmostEqual(sw.next_kickoff(now), now + 9 * 3600, delta=1)
            self.assertAlmostEqual(sw.next_kickoff(now + 12 * 3600), now + 20 * 3600, delta=1)
            self.assertIsNone(sw.next_kickoff(now + 19 * 3600))      # last game already inside the window
        finally:
            sw.PROPS = saved


if __name__ == "__main__":
    unittest.main()
