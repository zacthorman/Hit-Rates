"""Final NBA / NFL player models: choose on validation, report out of sample, export.

    python3 train_us.py nba|nfl

For each market:
  1. settings (feature groups, tree shape) chosen on validation deviance
  2. a train-only model predicts validation; on validation, fitted once and
     pooled over all line rungs: the spread around the prediction, a Platt
     calibration, and the blend with the site's own (recalibrated) chance
  3. the same pipeline scored on the out-of-sample period: the honest report
  4. production: refit on every game with the chosen settings, exported as
     JSON trees plus the fitted spread / calibration / blend in meta
"""
import gzip
import json
import sys
import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

warnings.filterwarnings("ignore")
sys.argv = [sys.argv[0], sys.argv[1], "auto"]
import evaluate_us as E  # noqa: E402  (data, splits, groups, lines, baseline)

SPORT = E.SPORT
OUT = "/home/claude/usbt/export"
PAGE_STAT = {
    "points": "Points", "rebounds": "Rebounds", "assists": "Assists", "threes": "Three pointers made",
    "steals": "Steals", "blocks": "Blocks", "turnovers": "Turnovers", "pra": "Points rebounds and assists",
    "pr": "Points and rebounds", "pa": "Points and assists", "ra": "Rebounds and assists",
    "pass_yds": "Passing yards", "rush_yds": "Rushing yards", "rec_yds": "Receiving yards",
    "rec": "Receiving receptions", "rush_rec_yds": "Rushing and receiving yards",
    "pass_rush_yds": "Passing and rushing yards", "pass_td": "Passing touchdowns", "td": "Anytime touchdown",
    "pass_cmp": "Passing completions", "pass_att": "Passing attempts", "rush_att": "Rushing attempts",
    "tackles": "Defensive combined tackles",
}
lo = lambda q: np.log(np.clip(q, 1e-4, 1 - 1e-4) / (1 - np.clip(q, 1e-4, 1 - 1e-4)))
sig = lambda z: 1 / (1 + np.exp(-z))


def spread_meta(sp):
    if sp.yards:
        return {"type": "ratio", "edges": [float(x) for x in sp.edges],
                "q": [[float(x) for x in np.quantile(r, np.linspace(0, 1, 201))] for r in sp.ratios]}
    return {"type": "nb", "size": float(sp.size)}


def recent_shift(Te, F):
    """How far the blend ran from what landed on the most recent stretch of the
    out-of-sample period (the last 120 days with games, at least 400 lines),
    as a log-odds shift for the live model's intercept. Scoring levels move
    between seasons: on the 2026 NFL games the blend said 43.0% and 44.6%
    landed. Measured after the honest report, so it only touches production."""
    ts = F.ts.values[Te.row.values]
    recent = Te[ts >= ts.max() - 120 * 86400]
    if len(recent) < 400:
        return 0.0
    said, landed = recent.p_blend.mean(), recent.y.mean()
    shift = float(lo(np.array([landed]))[0] - lo(np.array([said]))[0])
    return max(-0.3, min(0.3, shift))


def main():
    F, site, chosen = E.F, E.site_probs(), json.load(open(f"{E.D}/{SPORT}_groups.json"))
    meta = {"sport": SPORT, "trained": pd.Timestamp.now().isoformat()[:16], "pos_codes": E.POS_CODES, "targets": {}}
    report = []
    allpred = []
    for s in E.TARGETS:
        E.CUR["s"] = s
        ok = E.eligible(s).values
        y = np.clip(F[f"y_{s}"].astype(float).values, 0, None)
        tr, va, te = (ok & (F.split == k).values for k in ("train", "val", "oos"))
        if tr.sum() < 300 or va.sum() < 100 or te.sum() < 100:
            print(s, "skipped, too few rows")
            continue
        best = None
        base = dict(E.PARAMS)
        for gs in (chosen.get(s, E.ORDER), E.ORDER):
            feats = sum((E.G[g] for g in gs), [])
            for nl, md in ((7, 50), (15, 100), (31, 200), (15, 300)):
                E.PARAMS = dict(base, num_leaves=nl, min_data_in_leaf=md)
                m = E.fit(feats, y, tr, va)
                dv = E.poisson_dev(y[va], E.predict(m, va, feats))
                if best is None or dv < best[0]:
                    best = (dv, gs, feats, m, dict(E.PARAMS))
        _, gs, feats, m, params = best
        E.PARAMS = base
        m.save_model(f"{OUT}/oos_{SPORT}_{s}.txt")  # train-only, for honest checks
        mu_va, mu_te = E.predict(m, va, feats), E.predict(m, te, feats)
        sp = E.Spread(y[va], mu_va, s in E.YARDS)
        # pooled over the rungs: calibration, site recalibration, blend
        V, Te = [], []
        for li, L in enumerate(E.lines_for(s)):
            for mask, mu, bucket in ((va, mu_va, V), (te, mu_te, Te)):
                Ls = L.values[mask]
                sp_ = site[(s, li)][mask]
                bucket.append(pd.DataFrame({"p": sp.p_over(mu, Ls), "site": sp_, "y": (y[mask] > Ls).astype(int),
                                            "line": Ls, "mu": mu, "rung": li, "row": np.where(mask)[0]}))
        V, Te = pd.concat(V), pd.concat(Te)
        V, Te = V[V.site.notna()], Te[Te.site.notna()]
        trs = []
        for li, L in enumerate(E.lines_for(s)):
            sm = tr & ~np.isnan(site[(s, li)])
            trs.append(pd.DataFrame({"site": site[(s, li)][sm], "y": (y[sm] > L.values[sm]).astype(int)}))
        trs = pd.concat(trs)
        sf = LogisticRegression(C=1e6).fit(lo(trs.site.values).reshape(-1, 1), trs.y)
        cal = LogisticRegression(C=1e6).fit(lo(V.p.values).reshape(-1, 1), V.y)
        fcal = lambda q: cal.predict_proba(lo(q).reshape(-1, 1))[:, 1]
        fsf = lambda q: sf.predict_proba(lo(q).reshape(-1, 1))[:, 1]
        bl = LogisticRegression(C=1.0).fit(np.c_[lo(fcal(V.p.values)), lo(fsf(V.site.values))], V.y)
        # Blend or the model alone? Decided inside validation: blend fitted on
        # its first half (by date), both scored on the second half.
        vts = F.ts.values[V.row.values]
        h1, h2 = vts < np.median(vts), vts >= np.median(vts)
        bl1 = LogisticRegression(C=1.0).fit(np.c_[lo(fcal(V.p.values[h1])), lo(fsf(V.site.values[h1]))], V.y.values[h1])
        pb2 = bl1.predict_proba(np.c_[lo(fcal(V.p.values[h2])), lo(fsf(V.site.values[h2]))])[:, 1]
        use_blend = E.ll(V.y.values[h2], pb2) < E.ll(V.y.values[h2], fcal(V.p.values[h2]))
        Te["p_new"] = fcal(Te.p.values)
        Te["p_site_fair"] = fsf(Te.site.values)
        Te["p_blend"] = (bl.predict_proba(np.c_[lo(Te.p_new.values), lo(Te.p_site_fair.values)])[:, 1]
                         if use_blend else Te.p_new.values)
        Te["target"] = s
        allpred.append(Te)
        r = {"target": s, "lines": len(Te), "groups": "+".join(gs), "use_blend": bool(use_blend),
             "shape": f"{params['num_leaves']}/{params['min_data_in_leaf']}"}
        for k, col in (("site", "site"), ("site_fair", "p_site_fair"), ("new", "p_new"), ("blend", "p_blend")):
            r["ll_" + k] = E.ll(Te.y.values, Te[col].values)
        r["ll_coin"] = E.ll(Te.y.values, np.full(len(Te), Te.y.mean()))
        report.append(r)
        print(json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}), flush=True)
        # production refit on every eligible game, tree count from validation
        allm = ok
        n_trees = max(50, int((m.best_iteration or m.current_iteration()) * 1.1))
        prod = lgb.train(params, lgb.Dataset(F.loc[allm, feats], y[allm], init_score=np.log(E.base_of(s, allm))), n_trees)
        with gzip.open(f"{OUT}/{SPORT}_{s}.json.gz", "wt") as fh:
            json.dump(prod.dump_model(), fh)
        meta["targets"][s] = {
            "page_stat": PAGE_STAT[s], "features": feats, "base": f"{s}_ew", "spread": spread_meta(sp),
            "cal": [float(cal.intercept_[0]), float(cal.coef_[0][0])],
            "site_cal": [float(sf.intercept_[0]), float(sf.coef_[0][0])],
            "blend": ([float(bl.intercept_[0]) + recent_shift(Te, F), float(bl.coef_[0][0]), float(bl.coef_[0][1])]
                      if use_blend else [recent_shift(Te, F), 1.0, 0.0]),
            "use_blend": bool(use_blend),
            "eligible": {"min_median": E.TARGETS[s], "positions": sorted(E.POS.get(s, []))},
            "oos": {k: round(v, 4) for k, v in r.items() if k.startswith("ll_")},
        }
    json.dump(meta, open(f"{OUT}/{SPORT}_meta.json", "w"), indent=1)
    pd.DataFrame(report).to_csv(f"{E.D}/{SPORT}_final_report.csv", index=False)
    pd.concat(allpred).to_parquet(f"{E.D}/{SPORT}_final_oos.parquet")


if __name__ == "__main__":
    main()
