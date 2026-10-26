"""supersub_check.py: settlement from line-ups, the walk-forward replay and the edge scenarios.

    python -B -m unittest tests.test_supersub_check

Synthetic line-ups only. supersub.py lives on bookie-imports, not here, so
the replay is driven with a small stand-in that has the same functions; the
last test runs against the real module when SUPERSUB_CODE points at a
checkout that has it, and is skipped otherwise.
"""
import os
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import supersub_check as C  # noqa: E402


def player(pid, pos, mins, goals=0, sub=False):
    st = {"minutesPlayed": mins}
    if goals:
        st["goals"] = goals
    return {"player": {"id": pid, "name": f"p{pid}"}, "position": pos, "substitute": sub,
            "statistics": st if mins or not sub else {}}


def side(starters, subs=()):
    return {"players": list(starters) + list(subs)}


def pairs(side_):
    """supersub._pairs, as shipped: first off with the sub who played longest."""
    ps = side_.get("players") or []
    st = [p for p in ps if not p.get("substitute")]
    if len(st) != 11:
        return []

    def mins(p):
        return (p.get("statistics") or {}).get("minutesPlayed") or 0
    full = max(mins(p) for p in st)
    off = sorted((p for p in st if 0 < mins(p) < full - 1), key=mins)
    on = sorted((p for p in ps if p.get("substitute") and mins(p) > 0), key=mins, reverse=True)
    rep = {id(a): b for a, b in zip(off, on)}
    return [(p, rep.get(id(p))) for p in st]


STUB = types.SimpleNamespace(
    _pairs=pairs,
    sub_rate=lambda played, min_starts=5: (
        None if len([g for g in played if g.get("started")]) < min_starts else
        sum(1 for g in played if g.get("started") and g["minutes"] < 85)
        / len([g for g in played if g.get("started")])),
    position_of=lambda played: max(set(g["position"] for g in played),
                                   key=[g["position"] for g in played].count) if played else None,
    chance=lambda p, s, rep: p + (1 - p) * s * rep,
)


def eleven(fw_mins=60, fw_goal=0, sub_goal=0, sub_mins=None, base=0):
    starters = [player(base + 1, "F", fw_mins, fw_goal)] + [player(base + i, "D", 90) for i in range(2, 12)]
    subs = [player(base + 50, "F", sub_mins if sub_mins is not None else 90 - fw_mins, sub_goal, sub=True)]
    return side(starters, subs)


class Settlement(unittest.TestCase):

    def test_replacement_goal_wins(self):
        rows = C.side_rows(eleven(fw_mins=60, sub_goal=1), pairs)
        fw = next(r for r in rows if r["pid"] == 1)
        self.assertTrue(fw["off"])
        self.assertFalse(fw["scored"])
        self.assertTrue(fw["rep_scored"])
        self.assertTrue(fw["near_scored"])

    def test_full_match_has_no_replacement(self):
        rows = C.side_rows(eleven(fw_mins=90, sub_mins=0, sub_goal=0), pairs)
        fw = next(r for r in rows if r["pid"] == 1)
        self.assertFalse(fw["off"])
        self.assertFalse(fw["rep_scored"])

    def test_late_exit_is_not_super_sub(self):
        """Off after 85 minutes: supersub counts it as a full game."""
        rows = C.side_rows(eleven(fw_mins=88, sub_goal=1), pairs)
        fw = next(r for r in rows if r["pid"] == 1)
        self.assertFalse(fw["off"])
        self.assertFalse(fw["near_scored"])

    def test_substitutes_are_rows_but_not_starters(self):
        rows = C.side_rows(eleven(fw_mins=60, sub_goal=1), pairs)
        sub = next(r for r in rows if r["pid"] == 50)
        self.assertFalse(sub["started"])
        self.assertTrue(sub["scored"])

    def test_near_settlement_reaches_a_sub_on_at_the_same_time(self):
        """Two forwards off at 60; the time pairing gives each one a sub, the
        looser rule credits a goal by either sub to both."""
        starters = ([player(1, "F", 60), player(2, "F", 61)]
                    + [player(i, "D", 90) for i in range(3, 12)])
        subs = [player(50, "F", 30, goals=1, sub=True), player(51, "F", 29, sub=True)]
        rows = {r["pid"]: r for r in C.side_rows(side(starters, subs), pairs)}
        self.assertTrue(rows[1]["rep_scored"])
        self.assertFalse(rows[2]["rep_scored"])
        self.assertTrue(rows[2]["near_scored"])


def ts(day):
    return int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()) + day * 86400


class Replay(unittest.TestCase):

    def games(self):
        """Forward 1 starts every week, taken off at 60 every time; his sub
        scores in the first ten games and never after."""
        out = []
        for d in range(0, 300, 7):
            goal = 1 if d < 70 else 0
            rows = C.side_rows(eleven(fw_mins=60, sub_goal=goal), pairs)
            out.append((ts(d), 1000 + d, rows))
        return out

    def test_rep_fit_uses_only_earlier_matches(self):
        g = self.games()
        early = C.rep_fit(g, ts(70))
        late = C.rep_fit(g, ts(400))
        self.assertAlmostEqual(early["F"], 1.0)
        self.assertLess(late["F"], 0.5)

    def test_replay_prices_from_earlier_starts_only(self):
        g = self.games()
        own = {(eid, 1): 0.2 for _, eid, _ in g}
        old, C.OOS_FROM = C.OOS_FROM, ts(0)
        try:
            rows = C.replay(g, own, STUB, {"F": 0.08})
        finally:
            C.OOS_FROM = old
        first = rows[0]
        self.assertIsNone(first["s"])              # no earlier starts: no uplift
        self.assertEqual(first["ss"], first["own"])
        later = rows[10]
        self.assertAlmostEqual(later["s"], 1.0)    # taken off in every earlier start
        self.assertGreater(later["ss"], later["own"])
        self.assertEqual(later["won"], 0)
        self.assertAlmostEqual(later["ss_shipped"], 0.2 + 0.8 * 1.0 * 0.08)

    def test_replay_has_no_lookahead(self):
        g = self.games()
        own = {(eid, 1): 0.2 for _, eid, _ in g}
        old, C.OOS_FROM = C.OOS_FROM, ts(0)
        try:
            short = C.replay(g[:20], own, STUB, {"F": 0.08})
            full = C.replay(g, own, STUB, {"F": 0.08})
        finally:
            C.OOS_FROM = old
        for a, b in zip(short, full[:len(short)]):
            self.assertEqual((a["s"], a["ss"]), (b["s"], b["ss"]))


class Measures(unittest.TestCase):

    def test_verdict_mirrors_verdictof(self):
        self.assertEqual(C.verdict(0.30, 3.4), "long")      # +2% and under 50%
        self.assertEqual(C.verdict(0.30, 4.0), "long")      # +20%, still a long shot
        self.assertEqual(C.verdict(0.30, 3.0), "avoid")     # 10% worse
        self.assertEqual(C.verdict(0.55, 1.85), "ok")       # +1.75%
        self.assertEqual(C.verdict(0.55, 2.0), "avoid")     # +10%

    def test_verdict_changes_under_a_margin(self):
        rows = [{"own": 0.48, "ss": 0.50},    # long -> ok at a 0% margin (+4.2%)
                {"own": 0.55, "ss": 0.60},    # ok -> avoid: 0.60 / 0.55 = 1.09
                {"own": 0.10, "ss": 0.11}]    # long -> long
        got = {m: c for m, n, c in C.verdict_changes(rows, margins=(0.0, 0.10))}
        self.assertEqual(got[0.0][("long", "ok")], 1)
        self.assertEqual(got[0.0][("ok", "avoid")], 1)
        self.assertEqual(got[0.0][("long", "long")], 1)
        # at a 10% margin the own price is 9% worse than fair: avoid before
        # Super Sub, and the uplift lifts the 0.55 line to acceptable
        self.assertEqual(got[0.10][("avoid", "ok")], 1)

    def test_ratio_interval_contains_point(self):
        rows = [{"night": f"n{i % 40}", "won": int(i % 10 == 0), "ss": 0.1} for i in range(800)]
        r, lo, hi = C.ratio(rows)
        self.assertTrue(lo <= r <= hi)
        self.assertAlmostEqual(r, 1.0, delta=0.01)

    def test_ll_diff_sign(self):
        rows = [{"night": f"n{i % 20}", "won": int(i % 5 == 0), "ss": 0.2, "own": 0.1} for i in range(400)]
        d, lo, hi = C.ll_diff(rows, "ss", "own")
        self.assertLess(d, 0)       # 0.2 is the true rate, so it scores better

    def test_extra_rows_skip_scorers_and_uncovered(self):
        rows = [{"scored": 1, "s": 0.5, "rep_wf": 0.08, "won": 1, "won_near": 1},
                {"scored": 0, "s": None, "rep_wf": 0.08, "won": 0, "won_near": 0},
                {"scored": 0, "s": 0.5, "rep_wf": 0.08, "won": 1, "won_near": 1}]
        ex = C.extra_rows(rows)
        self.assertEqual(len(ex), 1)
        self.assertAlmostEqual(ex[0]["said_extra"], 0.04)


@unittest.skipUnless(os.environ.get("SUPERSUB_CODE"), "SUPERSUB_CODE not set (supersub.py is on bookie-imports)")
class AgainstTheRealModule(unittest.TestCase):

    def test_stub_matches_supersub(self):
        sys.path.insert(0, os.environ["SUPERSUB_CODE"])
        import supersub
        s = eleven(fw_mins=60, sub_goal=1)
        self.assertEqual([(a["player"]["id"], b and b["player"]["id"]) for a, b in supersub._pairs(s)],
                         [(a["player"]["id"], b and b["player"]["id"]) for a, b in pairs(s)])
        played = [{"started": True, "minutes": m, "position": "F"} for m in (60, 90, 70, 90, 80, 90)]
        self.assertAlmostEqual(supersub.sub_rate(played), STUB.sub_rate(played))
        self.assertEqual(supersub.position_of(played), STUB.position_of(played))
        self.assertAlmostEqual(supersub.chance(0.2, 0.5, 0.08), STUB.chance(0.2, 0.5, 0.08))


if __name__ == "__main__":
    unittest.main()
