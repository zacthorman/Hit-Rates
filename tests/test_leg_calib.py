"""leg_calib.py: the simple fits, the night-by-night replay and the fixed rule.

    python -B -m unittest tests.test_leg_calib

Synthetic legs only. Nothing here writes learned.json: learner.fit and
learner.check only fit.
"""
import math
import random
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import leg_calib as L  # noqa: E402
import learner  # noqa: E402


def legs(n_nights=30, per_night=60, shift=0.3, seed=1, group="football|team"):
    """Legs whose true chance is the stated one shifted up by `shift` on the log-odds scale."""
    rnd = random.Random(seed)
    t0 = datetime(2026, 9, 20, tzinfo=timezone.utc).timestamp()
    out = []
    for d in range(n_nights):
        for _ in range(per_night):
            said = rnd.uniform(0.55, 0.85)
            true = 1 / (1 + math.exp(-(math.log(said / (1 - said)) + shift)))
            out.append({"said": said, "won": rnd.random() < true, "ts": t0 + d * 86400 + 3600,
                        "group": group, "family": "shots"})
    return out


class Fits(unittest.TestCase):

    def test_shift_recovers_a_known_shift(self):
        rows = legs(shift=0.4, per_night=200)
        m = L.fit_shift(rows, now=rows[-1]["ts"], prior=1.0, half_life=1e9)
        a, b = m["football|team"]
        self.assertAlmostEqual(a, 0.4, delta=0.1)
        self.assertEqual(b, 1.0)

    def test_shift_with_no_signal_stays_near_zero(self):
        rows = legs(shift=0.0, per_night=200)
        a, b = L.fit_shift(rows, now=rows[-1]["ts"], slope=True)["football|team"]
        self.assertAlmostEqual(a + b * 1.0 - 1.0, 0.0, delta=0.25)

    def test_small_groups_are_left_alone(self):
        rows = legs(n_nights=1, per_night=10)
        self.assertEqual(L.fit_shift(rows, now=rows[-1]["ts"]), {})
        self.assertAlmostEqual(L.apply_shift({}, rows[0]), rows[0]["said"], places=6)


class Replay(unittest.TestCase):

    def test_no_lookahead(self):
        rows = legs()
        cut = L.night_of(rows[len(rows) // 2]["ts"])
        a = {(r["ts"], r["said"]): r["shift"] for r in L.replay([dict(r) for r in rows], cut)}
        flipped = [dict(r, won=not r["won"]) if L.night_of(r["ts"]) >= "2026-10-15" else dict(r) for r in rows]
        b = {(r["ts"], r["said"]): r["shift"] for r in L.replay(flipped, cut)}
        for k, v in a.items():
            if L.night_of(k[0]) <= "2026-10-15":     # fitted only on nights before the flip
                self.assertAlmostEqual(v, b[k])

    def test_identity_is_said_and_scored_nights_from_cut(self):
        rows = legs(n_nights=12)
        cut = L.night_of(rows[400]["ts"])
        out = L.replay([dict(r) for r in rows], cut)
        self.assertTrue(all(r["night"] >= cut for r in out))
        self.assertTrue(all(r["identity"] == r["said"] for r in out))

    def test_monthly_refit_and_cap(self):
        rows = legs(n_nights=40, per_night=30)
        out = L.replay([dict(r) for r in rows], "2026-10-01", refit="month", window_days=90, cap=300)
        self.assertTrue(out)
        self.assertTrue(all(r["night"] >= "2026-10-01" for r in out))

    def test_a_real_shift_beats_identity_out_of_sample(self):
        rows = legs(shift=0.5, per_night=120)
        out = L.replay([dict(r) for r in rows], L.night_of(rows[len(rows) // 2]["ts"]))
        d, lo, hi = L.boot_diff(out, "shift", "identity")
        self.assertLess(hi, 0)


class Rule(unittest.TestCase):

    def test_rule_needs_interval_below_zero_and_no_worse_group(self):
        rows = []
        for i in range(400):
            y = (i // 20) % 4 != 0      # every night the same mix, 75% landed
            rows.append({"night": f"n{i % 20}", "won": y, "group": "football|team", "said": 0.6,
                         "identity": 0.6, "learner, live": 0.6, "learner, on": 0.75, "shift": 0.75,
                         "shift + slope": 0.6})
        v = L.verdicts(rows)
        self.assertTrue(v["shift"]["holds"])
        self.assertFalse(v["shift + slope"]["holds"])
        self.assertFalse(v["identity"]["holds"])

    def test_learner_fit_is_not_saved(self):
        before = learner.OUT.read_bytes() if learner.OUT.exists() else None
        rows = legs(n_nights=8)
        L.replay([dict(r) for r in rows], L.night_of(rows[200]["ts"]))
        after = learner.OUT.read_bytes() if learner.OUT.exists() else None
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
