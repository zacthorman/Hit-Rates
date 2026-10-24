"""teammodel_train.py --weekly: the adoption test and the weekly run.

    .venv/bin/python -B -m unittest tests.test_teammodel_weekly

Synthetic data only. Skipped where lightgbm is not installed (the Mac page
does not need it; the weekly job does).
"""
import inspect
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import teammodel_train as T  # noqa: E402

try:
    import lightgbm as lgb
except ImportError:  # pragma: no cover
    lgb = None

S = "Shots on target"


def frame(n=3000, seed=0, days=200, end=pd.Timestamp("2026-10-19").timestamp()):
    rng = np.random.default_rng(seed)
    own = rng.uniform(2, 7, n)
    conc = rng.uniform(2, 7, n)
    home = rng.integers(0, 2, n).astype(float)
    mu = np.exp(0.2 + 0.5 * np.log(own) + 0.3 * np.log(conc) + 0.2 * home)
    ts = np.sort(end - rng.uniform(0, days * 86400, n))
    return pd.DataFrame({"own_" + S: own, "opp_conc_" + S: conc, "home": home, "n": 10.0,
                         "y_" + S: rng.poisson(mu).astype(float), "ts": ts})


FEATS = ["own_" + S, "opp_conc_" + S, "home", "n"]


def base_model(R):
    return lgb.train(T.PARAMS, lgb.Dataset(R[FEATS], R["y_" + S]), 60)


@unittest.skipIf(lgb is None, "lightgbm not installed")
class AdoptionTest(unittest.TestCase):
    def setUp(self):
        self.R = frame()
        self.old = base_model(self.R.iloc[:1500])
        now = self.R.ts.max()
        self.h = (self.R.ts >= now - T.HOLDOUT_DAYS * 86400).values
        self.w = np.power(0.5, (now - self.R.ts.values) / 86400 / T.HALF_LIFE_DAYS)

    def args(self, yh=None):
        R, h = self.R, self.h
        y = R["y_" + S].values
        return (lgb, self.old, R.loc[~h, FEATS], y[~h], self.w[~h], R.loc[h, FEATS],
                y[h] if yh is None else yh, R.loc[h, "own_" + S].values, 0.05)

    def test_candidate_takes_no_holdout_labels(self):
        params = list(inspect.signature(T.weekly_candidate).parameters)
        self.assertEqual(params, ["lgb", "old", "Xtr", "ytr", "wtr", "Xh"])

    def test_holdout_labels_do_not_change_the_candidate(self):
        # Any holdout labels at all: the model adopted (when adopted) is the same one.
        y = self.R["y_" + S].values[self.h]
        with mock.patch.object(T, "tail_ll", side_effect=[1.0, 0.5]):
            a, ra = T.weekly_step(*self.args(y))
        with mock.patch.object(T, "tail_ll", side_effect=[1.0, 0.5]):
            b, rb = T.weekly_step(*self.args(np.zeros_like(y) + 40))
        self.assertEqual(a.model_to_string(), b.model_to_string())
        self.assertEqual(ra["shift"], rb["shift"])

    def test_scores_the_model_it_adopts_after_halving(self):
        with mock.patch.object(T, "MAX_SHIFT", 0.0):
            new, rep = T.weekly_step(*self.args())
            halved, _, _ = T.weekly_candidate(*self.args()[:6])
        self.assertTrue(rep["halved"])
        self.assertLess(rep["adopted_shift"], rep["shift"])
        h, y = self.h, self.R["y_" + S].values
        self.assertAlmostEqual(rep["after"], T.tail_ll(y[h], halved.predict(self.R.loc[h, FEATS]),
                                                       self.R.loc[h, "own_" + S].values, 0.05), places=12)
        if new is not None:
            self.assertEqual(new.model_to_string(), halved.model_to_string())

    def test_no_slack_in_no_worse(self):
        with mock.patch.object(T, "tail_ll", side_effect=[0.6000, 0.60005]):
            new, rep = T.weekly_step(*self.args())
        self.assertIsNone(new)
        with mock.patch.object(T, "tail_ll", side_effect=[0.6000, 0.6000]):
            new, rep = T.weekly_step(*self.args())
        self.assertIsNotNone(new)

    def test_halving_moves_about_half(self):
        _, shift, halved = T.weekly_candidate(*self.args()[:6])
        with mock.patch.object(T, "MAX_SHIFT", 0.0):
            new, shift2, halved2 = T.weekly_candidate(*self.args()[:6])
        Xh = self.args()[5]
        mo = self.old.predict(Xh)
        moved = float(np.mean(np.abs(new.predict(Xh) - mo) / mo))
        self.assertEqual(shift, shift2)
        self.assertTrue(halved2)
        self.assertGreater(moved, 0.35 * shift)
        self.assertLess(moved, 0.65 * shift)


@unittest.skipIf(lgb is None, "lightgbm not installed")
class WeeklyRunTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.R = frame(seed=1)
        old = base_model(self.R.iloc[:1500])
        old.save_model(str(self.dir / "shots_on_target.txt"))
        meta = {"stats": {S: {"use": "gbm", "features": FEATS, "alpha_gbm": 0.05, "trees": 60},
                          "Total shots": {"use": "linear"}}}
        (self.dir / "meta.json").write_text(json.dumps(meta))

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_writes_changelog_and_meta(self):
        with mock.patch.object(T, "rows", return_value=self.R):
            T.weekly("unused", self.dir)
        log = (self.dir / "CHANGELOG.md").read_text()
        self.assertIn(f"- {S}: ", log)
        self.assertNotIn("Total shots", log)
        meta = json.loads((self.dir / "meta.json").read_text())
        self.assertIn("weekly", meta)
        if "updated" in log:
            self.assertEqual(meta["stats"][S]["trees"], 60 + T.WEEKLY_TREES)
            self.assertTrue((self.dir / "shots_on_target.json.gz").exists())
        else:
            self.assertIn("update rejected", log)

    def test_rejection_leaves_the_model_alone(self):
        before = (self.dir / "shots_on_target.txt").read_text()
        with mock.patch.object(T, "rows", return_value=self.R), \
                mock.patch.object(T, "tail_ll", side_effect=[0.5, 0.6]):
            T.weekly("unused", self.dir)
        self.assertEqual((self.dir / "shots_on_target.txt").read_text(), before)
        self.assertIn("update rejected (latest 21 days: 0.5000 before, 0.6000 after)",
                      (self.dir / "CHANGELOG.md").read_text())

    def test_too_few_new_matches(self):
        R = self.R[self.R.ts < self.R.ts.max() - 30 * 86400]
        R = pd.concat([R, self.R.tail(10)])
        with mock.patch.object(T, "rows", return_value=R):
            T.weekly("unused", self.dir)
        self.assertIn("too few new matches, unchanged", (self.dir / "CHANGELOG.md").read_text())


class AuditHelpersTest(unittest.TestCase):
    def test_mondays_at_run_time(self):
        import teammodel_audit as A
        ts = list(A.mondays("2026-07-06", "2026-07-20"))
        self.assertEqual(len(ts), 3)
        for t in ts:
            d = pd.Timestamp(t, unit="s")
            self.assertEqual((d.dayofweek, d.hour, d.minute), (0, 5, 34))


if __name__ == "__main__":
    unittest.main()
