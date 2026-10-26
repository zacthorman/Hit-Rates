#!/usr/bin/env python3
"""Weekly small-step update of the NBA and NFL player models (usmodel/).

    python usmodel_weekly.py nba|nfl|all        # Mondays, from update.py; needs lightgbm

The production models in usmodel/ were exported as trees only, so they cannot
be continued directly. Instead each week this trains a small correction on
top of them: 40 trees at a low learning rate, Poisson, starting from the
current model's own expected number (init_score), on recency-weighted games
(half-life 120 days). The correction multiplies the expected number, exactly
as more trees on the original model would. Same rules as the football team
model's weekly update (teammodel_train.py --weekly):

  * scored against the current model on the latest 21 days it did not train
    on, and adopted only if it is no worse (Poisson deviance);
  * a correction that moves the expected number by more than 3% on average is
    retrained at half the learning rate;
  * adopted corrections are refitted on every game and stack week on week
    (meta["deltas"][target], applied in order by usmodel_live.py).

Every week is written to usmodel/CHANGELOG.md. Reads cache/ only.
"""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import usfeatures as U  # noqa: E402
import usmodel_live as L  # noqa: E402

MODELS = ROOT / "usmodel"
DELTA = MODELS / "delta"
LOG = MODELS / "CHANGELOG.md"
TREES = 40
PARAMS = dict(objective="poisson", learning_rate=0.01, num_leaves=15, min_data_in_leaf=100,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=10.0, verbose=-1,
              seed=7)
HALF_LIFE_DAYS = 120
HOLDOUT_DAYS = 21
MAX_SHIFT = 0.03


def table(sport: str):
    M, T, P = U.build(str(ROOT / "cache"), sport)
    if sport == "nba":
        P["pra"] = P.points + P.rebounds + P.assists
        P["pr"] = P.points + P.rebounds
        P["pa"] = P.points + P.assists
        P["ra"] = P.rebounds + P.assists
    else:
        P["rush_rec_yds"] = P.rush_yds + P.rec_yds
        P["pass_rush_yds"] = P.pass_yds + P.rush_yds
    F = U.features(M, T, P, sport)
    return F, P


def eligible(F, tgt, m):
    if tgt == "td":
        ok = F["rec_m10"].astype(float) + F["rush_att_m10"].astype(float) >= 3
    else:
        ok = F[f"{tgt}_med10"].astype(float) >= m["eligible"]["min_median"]
    if m["eligible"]["positions"]:
        ok &= F.pos.isin(m["eligible"]["positions"])
    return ok.fillna(False)


def current_mu(sub, tgt, m, meta, sport):
    base = np.clip(sub[m["base"]].astype(float).fillna(0).values, 0.05, None)
    X = sub.reindex(columns=m["features"]).astype(float).values
    mu = base * L.Model(MODELS / f"{sport}_{tgt}.json.gz").predict(X)
    for f in (meta.get("deltas") or {}).get(tgt, []):
        mu = mu * L.Model(DELTA / f).predict(X)
    return mu, X


def deviance(y, mu):
    mu = np.clip(mu, 1e-6, None)
    t = np.where(y > 0, y * np.log(np.where(y > 0, y, 1) / mu), 0.0)
    return float(np.mean(2 * (t - (y - mu))))


def weekly(sport: str, only: set | None = None) -> list[str]:
    import lightgbm as lgb
    meta_path = MODELS / f"{sport}_meta.json"
    meta = json.loads(meta_path.read_text())
    F, P = table(sport)
    pos_codes = meta.get("pos_codes")
    F["pos_c"] = F.pos.map(pos_codes).fillna(-1) if pos_codes else F.pos.astype("category").cat.codes
    now = F.ts.max()
    lines = []
    DELTA.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    for tgt, m in meta["targets"].items():
        if tgt not in P.columns or (only and tgt not in only):
            continue
        sub = F[eligible(F, tgt, m)].merge(P[["match", "pid", tgt]], on=["match", "pid"], how="inner")
        sub = sub[sub[tgt].notna()]
        if len(sub) < 2000:
            lines.append(f"- {sport} {m['page_stat']}: skipped, {len(sub)} rows")
            continue
        y = np.clip(sub[tgt].astype(float).values, 0, None)  # negative yards count as 0 (Poisson)
        mu, X = current_mu(sub, tgt, m, meta, sport)
        age = (now - sub.ts.values) / 86400
        w = 0.5 ** (age / HALF_LIFE_DAYS)
        hold = age <= HOLDOUT_DAYS
        if hold.sum() < 200:
            lines.append(f"- {sport} {m['page_stat']}: skipped, {int(hold.sum())} rows in the latest {HOLDOUT_DAYS} days")
            continue

        def train(mask, lr):
            d = lgb.Dataset(X[mask], y[mask], weight=w[mask], init_score=np.log(np.clip(mu[mask], 1e-6, None)),
                            free_raw_data=False)
            return lgb.train(dict(PARAMS, learning_rate=lr), d, TREES)

        lr = PARAMS["learning_rate"]
        b = train(~hold, lr)
        fac = np.exp(b.predict(X[~hold], raw_score=True))
        note = ""
        if np.mean(np.abs(fac - 1)) > MAX_SHIFT:
            lr /= 2
            b = train(~hold, lr)
            note = " (big move, halved)"
        old = deviance(y[hold], mu[hold])
        new = deviance(y[hold], mu[hold] * np.exp(b.predict(X[hold], raw_score=True)))
        if new >= old:
            lines.append(f"- {sport} {m['page_stat']}: rejected (latest {HOLDOUT_DAYS} days: {old:.4f} before, {new:.4f} after)")
            continue
        full = train(np.ones(len(y), bool), lr)
        name = f"{sport}_{tgt}_{stamp}.json.gz"
        with gzip.open(DELTA / name, "wt") as fh:
            json.dump(full.dump_model(), fh)
        if name not in meta.setdefault("deltas", {}).setdefault(tgt, []):
            meta["deltas"][tgt].append(name)
        meta_path.write_text(json.dumps(meta, indent=1))  # saved per target, so a cut-off run keeps what it did
        lines.append(f"- {sport} {m['page_stat']}: updated{note}, {TREES} trees (latest {HOLDOUT_DAYS} days: "
                     f"{old:.4f} before, {new:.4f} after)")
    meta["weekly"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta_path.write_text(json.dumps(meta, indent=1))
    return lines


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    sports = ["nba", "nfl"] if not argv or argv[0] == "all" else [argv[0]]
    only = set(argv[1:]) or None  # optional targets, e.g. nba points rebounds
    try:
        import lightgbm  # noqa: F401
    except ImportError:
        print("  usmodel weekly: lightgbm not installed (.venv/bin/pip install lightgbm), skipped")
        return 0
    out = [f"\n## {datetime.now(timezone.utc):%Y-%m-%d}: weekly update\n"]
    for s in sports:
        try:
            out += weekly(s, only)
        except Exception as exc:  # noqa: BLE001  never fatal
            out.append(f"- {s}: failed ({type(exc).__name__}: {exc})")
    prev = LOG.read_text() if LOG.exists() else "# NBA and NFL model weekly updates\n"
    LOG.write_text(prev + "\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
