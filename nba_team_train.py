#!/usr/bin/env python3
"""NBA team stats: train, choose and export (usmodel/nba_team.json, nba_team_points.*).

Per stat: linear (own last-10, opponent's last-10 conceded, home), linear plus
pace, or LightGBM with the game state (usgame.py) as a multiple of the side's
own average. Chosen on validation (Feb to Mar 2026) and kept only if it also
beats the plain linear model out of sample (from April); 21 Oct 2026 only
team points cleared both. Refitted on train plus validation for the page.
"""
import gzip, json, sys, warnings
from pathlib import Path
import numpy as np, pandas as pd, lightgbm as lgb, statsmodels.api as sm
from scipy import stats as sst
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import usgame
warnings.filterwarnings("ignore")
STATS = {"pts_for": "Points", "f_Rebounds": "Rebounds", "f_Assists": "Assists", "f_3 pointers": "3 pointers",
         "f_Steals": "Steals", "f_Blocks": "Blocks", "f_Turnovers": "Turnovers", "f_Free throws": "Free throws"}
OPP = {"pts_for": "pts_against", **{k: "a_" + k[2:] for k in STATS if k.startswith("f_")}}
P2 = dict(objective="poisson", learning_rate=0.03, num_leaves=7, min_data_in_leaf=50, feature_fraction=0.8,
          bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0, verbose=-1, seed=7)


def own_allow(T):
    """Each side's last-10 own and the opponent's last-10 conceded, before the game.

    Histories are updated only after both sides of a game have their row: the
    first version appended per row, so the away side's "opponent concedes"
    already held the home side's line from the same game (a leak the live
    parity test caught on 21 October)."""
    T = T.sort_values(["ts", "match"]); hist = {}; rows = []
    for mid, g in T.groupby("match", sort=False):
        recs = g.to_dict("records")
        for rec in recs:
            h = hist.setdefault(rec["team"], [])[-10:]; ho = hist.setdefault(rec["opp"], [])[-10:]
            r = {"match": rec["match"], "ts": rec["ts"], "team": rec["team"], "home": rec["home"]}
            for k in STATS:
                v = [x[k] for x in h if x.get(k) is not None and x.get(k) == x.get(k)]
                a = [x[OPP[k]] for x in ho if x.get(OPP[k]) is not None and x.get(OPP[k]) == x.get(OPP[k])]
                r["own_" + k] = np.mean(v) if len(v) >= 5 else np.nan
                r["allow_" + k] = np.mean(a) if len(a) >= 5 else np.nan
                r["y_" + k] = rec.get(k)
            rows.append(r)
        for rec in recs:
            hist[rec["team"]].append(rec)
    return pd.DataFrame(rows)


def lin(Z, k, pace):
    cols = [np.ones(len(Z)), np.log(Z["own_" + k]), np.log(Z["allow_" + k]), Z.home.astype(float)]
    if pace:
        cols.append(np.log(Z.g_pace_ratio.fillna(1).clip(.8, 1.2)))
    return np.column_stack(cols)


def ll(y, mu, own, a):
    k = np.floor(own) + 1
    p = sst.poisson.sf(k - 1, mu) if a < 1e-6 else sst.nbinom.sf(k - 1, 1 / a, (1 / a) / (1 / a + mu))
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(-np.mean(np.where(y >= k, np.log(p), np.log(1 - p))))


def alpha(y, mu):
    return max(0.0, float(np.mean((y - mu) ** 2 - mu) / np.mean(mu ** 2)))


def main(D, out):
    M, T, P = [pd.read_parquet(f"{D}/nba_{n}.parquet") for n in ("matches", "teams", "players")]
    R = own_allow(T).merge(usgame.team_features(M, T, P), on=["match", "team"], how="left")
    TRAIN_END, VAL_END = pd.Timestamp("2026-02-01").timestamp(), pd.Timestamp("2026-04-01").timestamp()
    R["split"] = np.where(R.ts < TRAIN_END, "train", np.where(R.ts < VAL_END, "val", "oos"))
    GS = [c for c in R.columns if c.startswith("g_")]
    meta = {"trained": pd.Timestamp.now().isoformat(timespec="minutes"), "stats": {}}
    for k, name in STATS.items():
        X = R[R["own_" + k].notna() & R["allow_" + k].notna() & R["y_" + k].notna()]
        y = X["y_" + k].astype(float).values
        tr, va, te = [(X.split == z).values for z in ("train", "val", "oos")]
        trva = tr | va
        own = X["own_" + k].values
        res = {}
        for nm, pace in (("linear", False), ("linear_pace", True)):
            g = sm.GLM(y[tr], lin(X[tr], k, pace), family=sm.families.Poisson()).fit()
            a = alpha(y[tr], g.predict(lin(X[tr], k, pace)))
            res[nm] = (ll(y[va], g.predict(lin(X[va], k, pace)), own[va], a), ll(y[te], g.predict(lin(X[te], k, pace)), own[te], a))
        feats = ["own_" + k, "allow_" + k, "home"] + GS
        dtr = lgb.Dataset(X.loc[tr, feats], y[tr], init_score=np.log(own[tr]))
        dva = lgb.Dataset(X.loc[va, feats], y[va], init_score=np.log(own[va]), reference=dtr)
        m = lgb.train(P2, dtr, 2000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
        mu = lambda msk: np.exp(m.predict(X.loc[msk, feats], raw_score=True)) * own[msk]  # noqa: E731
        a = alpha(y[tr], mu(tr))
        res["gbm"] = (ll(y[va], mu(va), own[va], a), ll(y[te], mu(te), own[te], a))
        best = min(res, key=lambda z: res[z][0])
        if best != "linear" and res[best][1] >= res["linear"][1]:
            best = "linear"            # a validation win that did not hold out of sample
        g = sm.GLM(y[trva], lin(X[trva], k, best == "linear_pace"), family=sm.families.Poisson()).fit()
        entry = {"page_stat": name, "use": best, "coef": [float(c) for c in g.params], "pace": best == "linear_pace",
                 "alpha": alpha(y[trva], g.predict(lin(X[trva], k, best == "linear_pace"))),
                 "val": {z: round(v[0], 4) for z, v in res.items()}, "oos": {z: round(v[1], 4) for z, v in res.items()},
                 "n_oos": int(te.sum())}
        if best == "gbm":
            d2 = lgb.Dataset(X.loc[trva, feats], y[trva], init_score=np.log(own[trva]))
            m2 = lgb.train(P2, d2, m.best_iteration or 100)
            entry.update(features=feats, alpha=alpha(y[trva], np.exp(m2.predict(X.loc[trva, feats], raw_score=True)) * own[trva]))
            with gzip.open(Path(out) / f"nba_team_{name.lower().replace(' ', '_')}.json.gz", "wt") as fh:
                json.dump(m2.dump_model(), fh)
            m2.save_model(str(Path(out) / f"nba_team_{name.lower().replace(' ', '_')}.txt"))
        meta["stats"][k] = entry
        print(name, best, entry["oos"], flush=True)
    (Path(out) / "nba_team.json").write_text(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/home/claude/usbt/data", sys.argv[2] if len(sys.argv) > 2 else "usmodel")
