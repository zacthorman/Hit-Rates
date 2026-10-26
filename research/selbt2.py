"""Back-test v2: a stand-in bookmaker line fitted to how Paddy set October's main lines.

For each market, Paddy's main line is regressed on what anyone could know (the
player's weighted average, last 3/5/10/20 means and last-10 median). That fitted
line, rounded to .5, is the historical 'Paddy line', priced at Paddy's average
main-line prices (over 1.91, under 1.84). The train-only model (selbt.py train)
and the form filter then pick from it, on games the model never saw.
"""
import sys, json, pickle, collections
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pplog, usmodel_live as L
OUT = ROOT / "research" / "selbt"
SP = {"nba": "basketball", "nfl": "american-football"}
PO, PU = 1.91, 1.84

def feats(F, t):
    cols = [f"{t}_ew", f"{t}_m3", f"{t}_m5", f"{t}_m10", f"{t}_m20", f"{t}_med10"]
    X = F.reindex(columns=cols).astype(float)
    X = X.fillna(X[f"{t}_ew"] if f"{t}_ew" in X else 0, axis=0) if False else X
    return X

def build(sport):
    F = pickle.load(open(OUT / f"{sport}_F.pkl", "rb"))
    S = pickle.load(open(OUT / f"{sport}_scored.pkl", "rb"))
    meta = json.loads((ROOT / "usmodel" / f"{sport}_meta.json").read_text())
    stat2t = {m["page_stat"]: t for t, m in meta["targets"].items()}
    # October's real main lines
    sides = collections.defaultdict(dict)
    for r in pplog.all_rows():
        if r["sport"] != SP[sport] or not (r.get("first") or {}).get("price"):
            continue
        sides[(r["event_id"], pplog._norm(r["player"]), r["stat"], r["line"])][bool(r["over"])] = r
    main = {}
    for (ev, pl, st, line), d in sides.items():
        if len(d) == 2 and st in stat2t:
            k = (ev, pl, stat2t[st])
            o, u = 1 / d[True]["first"]["price"], 1 / d[False]["first"]["price"]
            # several main lines for one player: keep the most balanced
            if k not in main or abs(o / (o + u) - .5) < abs(main[k][1] - .5):
                main[k] = (line, o / (o + u))
    F["key_n"] = [pplog._norm(n) for n in F.name]
    Fi = F.set_index(["match", "key_n"])
    coefs = {}
    for t in meta["targets"]:
        cols = [f"{t}_ew", f"{t}_m3", f"{t}_m5", f"{t}_m10", f"{t}_m20", f"{t}_med10"]
        if any(c not in F for c in cols):
            continue
        xs, ys, meds = [], [], []
        for (ev, pl, tt), (line, fair) in main.items():
            if tt != t or (ev, pl) not in Fi.index:
                continue
            row = Fi.loc[(ev, pl)]
            row = row.iloc[0] if row.ndim > 1 else row
            x = row[cols].astype(float).values
            if np.isnan(x).any():
                continue
            xs.append(np.r_[1, x]); ys.append(line); meds.append(np.floor(x[-1]) + .5)
        if len(xs) < 40:
            coefs[t] = None
            print(f"{sport} {t}: {len(xs)} Paddy main lines, too few, uses the median")
            continue
        X, y = np.array(xs), np.array(ys)
        lam = 1.0 * len(y)
        A = X.T @ X + lam * np.diag([0, 1, 1, 1, 1, 1, 1]) * 1e-3
        b = np.linalg.solve(A, X.T @ y)
        pred = np.floor(X @ b) + .5
        print(f"{sport} {t}: {len(y)} lines; MAE fitted {np.abs(pred - y).mean():.2f} v median {np.abs(np.array(meds) - y).mean():.2f}; exact {np.mean(pred == y):.0%} v {np.mean(np.array(meds) == y):.0%}")
        coefs[t] = b.tolist()
    # scored rows -> stand-in line, model chance, form at that line
    Fm = F.set_index(["match", "pid"])
    out = []
    for r in S:
        t = r["tgt"]; m = meta["targets"][t]
        try:
            row = Fm.loc[(r["match"], r["pid"])]
        except KeyError:
            continue
        row = row.iloc[0] if row.ndim > 1 else row
        h = np.array(row["h_" + t], float)
        if len(h) < 6:
            continue
        if t == "td":
            line = 0.5
        elif coefs.get(t):
            x = np.r_[1, row[[f"{t}_ew", f"{t}_m3", f"{t}_m5", f"{t}_m10", f"{t}_m20", f"{t}_med10"]].astype(float).values]
            if np.isnan(x).any():
                continue
            line = max(0.5, np.floor(x @ np.array(coefs[t])) + .5)
        else:
            line = np.floor(np.median(h)) + .5
        if r["y"] == line:
            continue
        po = L.calibrate(L.p_over(m["spread"], r["mu"], line), m["cal"])
        out.append(dict(sport=sport, tgt=t, stat=r["stat"], match=r["match"], pid=r["pid"], name=r["name"], ts=r["ts"],
                        line=line, p_over=po, k10o=int((h > line).sum()), n10=len(h), k5o=int((h[:5] > line).sum()),
                        n5=min(5, len(h)), y=r["y"]))
    pickle.dump(out, open(OUT / f"{sport}_v2.pkl", "wb"))
    print(sport, len(out), "rows at the stand-in Paddy line")

if __name__ == "__main__":
    build(sys.argv[1])
