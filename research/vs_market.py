"""Result (1X2) from the style model and the plain GLM against closing market odds
(football-data.co.uk: average and Pinnacle closing). Same matches, per-match log loss."""
import glob, json, re, unicodedata, difflib
import numpy as np, pandas as pd, lightgbm as lgb
from scipy.stats import poisson
D = "/home/claude/bt/data"
def nm(s): s = unicodedata.normalize("NFKD", str(s).lower()); return re.sub(r"[^a-z]", "", "".join(c for c in s if not unicodedata.combining(c)))
odds = []
for f in glob.glob("/home/claude/bt/odds/*.csv"):
    o = pd.read_csv(f, encoding="latin1"); o["lg"] = f.split("/")[-1][:-9]; odds.append(o)
O = pd.concat(odds, ignore_index=True).dropna(subset=["HomeTeam", "FTHG"])
O["date"] = pd.to_datetime(O.Date, dayfirst=True).dt.date
M = pd.read_parquet(f"{D}/matches.parquet")
M["date"] = pd.to_datetime(M.ts, unit="s").dt.date
T = pd.read_parquet(f"{D}/ts_rows.parquet")
meta = json.load(open(f"{D}/open_meta.json")); b = meta["glm"]; mdl = lgb.Booster(model_file=f"{D}/open_model.txt")
T["m_counter"] = T.tk_k_xg / T.tk_k_poss.clip(lower=20); T["m_opp_high_line"] = T["opp_conc_Offsides"]
T["m_counter_v_line"] = T.m_counter * T.m_opp_high_line; T["m_press_v_build"] = (1 / T.tk_k_ppda) * (1 - 10 * T.ok_k_direct)
T["m_open_both"] = T.tk_k_xg * T.ok_k_xg * T.tk_k_xga * T.ok_k_xga
T = T[(T.tk_k_xg > 0) & (T.ok_k_xga > 0)].dropna(subset=["elo_diff"])
eta = b["const"] + b["l_xg"] * np.log(T.tk_k_xg) + b["l_xga"] * np.log(T.ok_k_xga) + b["is_home"] * T.home + b["elo_diff"] * T.elo_diff
T["mu_cur"] = np.exp(eta); T["mu_sty"] = np.exp(eta + mdl.predict(T[meta["features"]], raw_score=True))
H = T[T.home == 1].set_index("match")[["mu_cur", "mu_sty"]]; A = T[T.home == 0].set_index("match")[["mu_cur", "mu_sty"]]
J = M.set_index("match").join(H).join(A, rsuffix="_a", how="inner").dropna(subset=["mu_cur", "mu_cur_a"]).reset_index()
# match to odds rows: same date (±1 day), same score, best name similarity
O["key"] = O.HomeTeam.map(nm) + "|" + O.AwayTeam.map(nm)
rows = []
byd = {d: g for d, g in O.groupby("date")}
for r in J.itertuples():
    cands = []
    for dd in (r.date, r.date - pd.Timedelta(days=1), r.date + pd.Timedelta(days=1)):
        g = byd.get(dd)
        if g is not None: cands.append(g[(g.FTHG == r.hg) & (g.FTAG == r.ag)])
    if not cands: continue
    c = pd.concat(cands)
    if c.empty: continue
    k = nm(r.home_name) + "|" + nm(r.away_name)
    s = c.key.map(lambda x: difflib.SequenceMatcher(None, x, k).ratio())
    if s.max() < 0.55: continue
    o = c.loc[s.idxmax()]
    rows.append({**r._asdict(), **{x: o.get(x) for x in ("AvgCH", "AvgCD", "AvgCA", "PSCH", "PSCD", "PSCA", "MaxCH", "MaxCD", "MaxCA", "lg")}})
X = pd.DataFrame(rows).dropna(subset=["AvgCH", "AvgCD", "AvgCA"])
print("matched", len(X), "of", len(J))
K = np.arange(11)
def p1x2(lh, la):
    ph, pa = poisson.pmf(K[None], lh[:, None]), poisson.pmf(K[None], la[:, None]); g = ph[:, :, None] * pa[:, None, :]
    i, j = np.meshgrid(K, K, indexing="ij"); return np.stack([(g * (i > j)).sum((1, 2)), (g * (i == j)).sum((1, 2)), (g * (i < j)).sum((1, 2))], 1)
X["res"] = np.where(X.hg > X.ag, 0, np.where(X.hg == X.ag, 1, 2))
P = {"cur": p1x2(X.mu_cur.values, X.mu_cur_a.values), "style": p1x2(X.mu_sty.values, X.mu_sty_a.values)}
inv = 1 / X[["AvgCH", "AvgCD", "AvgCA"]].values; P["market_avg"] = inv / inv.sum(1, keepdims=True)
pin = X[["PSCH", "PSCD", "PSCA"]].values.astype(float); ok_pin = ~np.isnan(pin).any(1)
inv = 1 / np.where(ok_pin[:, None], pin, 1); P["pinnacle"] = inv / inv.sum(1, keepdims=True)
X["split"] = np.where(X.ts < pd.Timestamp("2026-04-01").timestamp(), "train", np.where(X.ts < pd.Timestamp("2026-07-01").timestamp(), "val", "oos"))
y = X.res.values
ll = lambda p: -np.log(np.clip(p[np.arange(len(y)), y], 1e-4, 1))
for sp in ("val", "oos", "all"):
    m = (X.split == sp).values if sp != "all" else np.ones(len(X), bool)
    mp = m & ok_pin
    print(sp, f"n={m.sum()}", {k: round(ll(v)[m].mean(), 4) for k, v in P.items() if k != "pinnacle"}, f"| with Pinnacle n={mp.sum()}",
          {k: round(ll(v)[mp].mean(), 4) for k, v in P.items()})
# does adding the style model to the market help? logit blend fitted on train+val, tested on oos
from sklearn.linear_model import LogisticRegression
def feats(src): return np.log(np.clip(src, 1e-4, 1))
fit = (X.split != "oos").values; te = (X.split == "oos").values
for extra in ("cur", "style"):
    Z = np.hstack([feats(P["market_avg"]), feats(P[extra])])
    lr = LogisticRegression(C=1.0, max_iter=2000).fit(Z[fit], y[fit])
    lr0 = LogisticRegression(C=1.0, max_iter=2000).fit(feats(P["market_avg"])[fit], y[fit])
    pb, p0 = lr.predict_proba(Z[te]), lr0.predict_proba(feats(P["market_avg"])[te])
    d = -np.log(p0[np.arange(te.sum()), y[te]]) + np.log(pb[np.arange(te.sum()), y[te]])
    boot = [d[np.random.default_rng(i).integers(0, len(d), len(d))].mean() for i in range(2000)]
    print(f"market + {extra}: oos gain {d.mean():+.4f} per match, 95% CI {np.quantile(boot,.025):+.4f} to {np.quantile(boot,.975):+.4f}")
# betting: back the outcome where the style model beats the best closing price by 5%+
for src in ("style", "cur"):
    pr = P[src]; best = X[["MaxCH", "MaxCD", "MaxCA"]].values.astype(float)
    for edge in (0.05, 0.10):
        sel = (pr * best - 1 >= edge) & ~np.isnan(best)
        for sp in ("val", "oos"):
            m = (X.split == sp).values[:, None] & sel
            n = m.sum(); won = (m & (np.arange(3)[None] == y[:, None])).sum()
            prof = ((best - 1) * (np.arange(3)[None] == y[:, None]) - (np.arange(3)[None] != y[:, None]))[m].sum()
            print(f"{src} edge>={edge:.2f} {sp}: bets {n}, won {won}, profit {prof:+.1f} pts at best closing price ({prof / max(n,1) * 100:+.1f}%)")
