"""Open game / upset model. Does a style matchup beat the score model on
total goals (over 1.5/2.5/3.5), both teams to score and the result?

Baseline ("cur"): each side's goals ~ Poisson GLM on its recent xG for, the
opponent's recent xG against, home and Elo difference: the site's score model
(Elo for the result, recent xG for goals) as a fitted model.
"style": LightGBM Poisson on top (init_score = baseline), with every team-style,
shape, press/build, cross/box, flank and transition feature for both sides.
Both sides' goals independent Poisson -> grid -> market probabilities.
fmodel's split; per-match log loss; bootstrap by match; Holm across markets."""
import json, sys, warnings
import numpy as np, pandas as pd, lightgbm as lgb
from scipy.stats import poisson
import statsmodels.api as sm
warnings.filterwarnings("ignore")
D = "/home/claude/bt/data"
T = pd.read_parquet(f"{D}/team_rows.parquet")
M = pd.read_parquet(f"{D}/matches.parquet")[["match", "home", "away", "hg", "ag"]]
T = T.merge(M, on="match", how="inner")
T["goals"] = np.where(T.team == T.home_y if "home_y" in T else T.team == T["home"], T.hg, T.ag) if False else np.nan
hid = M.set_index("match")["home"]
T["is_home"] = (T.team.values == hid.reindex(T.match).values).astype(int)
T["goals"] = np.where(T.is_home == 1, T.hg, T.ag)
try:
    raise RuntimeError("flank off: not live")
    own = FT.add_prefix("o_").rename(columns={"o_match": "match", "o_team": "team"})
    opp = FT.add_prefix("q_").rename(columns={"q_match": "match", "q_team": "opp"})
    T = T.merge(own, on=["match", "team"], how="left").merge(opp, on=["match", "opp"], how="left")
    # our strong side into their weak side
    T["m_flank_target"] = (T.o_fl_att_L * T.q_fl_conc_R + T.o_fl_att_R * T.q_fl_conc_L) / \
        ((T.o_fl_att_L + T.o_fl_att_R) * (T.q_fl_conc_L + T.q_fl_conc_R) / 2)
except Exception as e:
    print("no flank team features", e)
# transition / line-height proxies
T["m_counter"] = T.tk_k_xg / T.tk_k_poss.clip(lower=20)            # chances per share of ball
T["m_opp_high_line"] = T["opp_conc_Offsides"]                       # offsides their opponents commit: a high line
T["m_counter_v_line"] = T.m_counter * T.m_opp_high_line
T["m_press_v_build"] = (1 / T.tk_k_ppda) * (1 - 10 * T.ok_k_direct)
T["m_open_both"] = T.tk_k_xg * T.ok_k_xg * T.tk_k_xga * T.ok_k_xga
T = T.dropna(subset=["tk_k_xg", "ok_k_xga", "elo_diff", "goals"])
T = T[(T.tk_k_xg > 0) & (T.ok_k_xga > 0)]
BASE = ["l_xg", "l_xga", "is_home", "elo_diff"]
T["l_xg"], T["l_xga"] = np.log(T.tk_k_xg), np.log(T.ok_k_xga)
STYLE = [c for c in T.columns if c.startswith(("tk_", "ok_", "x_", "m_", "o_fl", "q_fl", "own_", "conc_", "opp_own_", "opp_conc_"))]
tr, va, te = [(T.split == s).values for s in ("train", "val", "oos")]
X = sm.add_constant(T[BASE])
glm = sm.GLM(T.goals[tr], X[tr], family=sm.families.Poisson()).fit()
T["mu_cur"] = glm.predict(X)
y = T.goals.values
dtr = lgb.Dataset(T.loc[tr, STYLE], y[tr], init_score=np.log(T.mu_cur[tr]))
dva = lgb.Dataset(T.loc[va, STYLE], y[va], init_score=np.log(T.mu_cur[va]), reference=dtr)
P = dict(objective="poisson", learning_rate=0.02, num_leaves=7, min_data_in_leaf=150, feature_fraction=0.6,
         bagging_fraction=0.8, bagging_freq=1, lambda_l2=10.0, verbose=-1, seed=3)
m = lgb.train(P, dtr, 3000, valid_sets=[dva], callbacks=[lgb.early_stopping(150, verbose=False)])
T["mu_style"] = T.mu_cur * np.exp(m.predict(T[STYLE], raw_score=True))
print("trees", m.best_iteration)
imp = pd.Series(m.feature_importance("gain"), index=STYLE).sort_values(ascending=False)
print("top features", (imp / imp.sum()).head(12).round(3).to_dict())
# pair the two sides of each match
H = T[T.is_home == 1].set_index("match"); A = T[T.is_home == 0].set_index("match")
J = H[["split", "goals", "mu_cur", "mu_style"]].join(A[["goals", "mu_cur", "mu_style"]], rsuffix="_a", how="inner")
K = np.arange(11)
def probs(lh, la):
    ph, pa = poisson.pmf(K[None, :], lh[:, None]), poisson.pmf(K[None, :], la[:, None])
    g = ph[:, :, None] * pa[:, None, :]
    i, j = np.meshgrid(K, K, indexing="ij")
    tot = i + j
    return {"o1.5": (g * (tot > 1.5)).sum((1, 2)), "o2.5": (g * (tot > 2.5)).sum((1, 2)),
            "o3.5": (g * (tot > 3.5)).sum((1, 2)), "btts": (g * ((i > 0) & (j > 0))).sum((1, 2)),
            "H": (g * (i > j)).sum((1, 2)), "D": (g * (i == j)).sum((1, 2)), "A": (g * (i < j)).sum((1, 2))}
hg, ag = J.goals.values, J.goals_a.values
outc = {"o1.5": hg + ag > 1.5, "o2.5": hg + ag > 2.5, "o3.5": hg + ag > 3.5, "btts": (hg > 0) & (ag > 0)}
res = []
rng = np.random.default_rng(9)
PR = {v: probs(J[f"mu_{v}"].values, J[f"mu_{v}_a"].values) for v in ("cur", "style")}
def ll_bin(p, o): p = np.clip(p, 1e-4, 1 - 1e-4); return -(o * np.log(p) + (1 - o) * np.log(1 - p))
def ll_1x2(pr):
    pick = np.where(hg > ag, pr["H"], np.where(hg < ag, pr["A"], pr["D"])); return -np.log(np.clip(pick, 1e-4, 1))
for mk in ["o1.5", "o2.5", "o3.5", "btts", "1x2"]:
    L = {v: (ll_1x2(PR[v]) if mk == "1x2" else ll_bin(PR[v][mk], outc[mk].astype(float))) for v in PR}
    vmask, tmask = (J.split == "val").values, (J.split == "oos").values
    d = L["cur"][tmask] - L["style"][tmask]
    boot = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)])
    res.append(dict(market=mk, n_oos=int(tmask.sum()), gain_val=L["cur"][vmask].mean() - L["style"][vmask].mean(),
                    gain_oos_pct=100 * d.mean() / L["cur"][tmask].mean(), ci_lo=np.quantile(boot, .025),
                    ci_hi=np.quantile(boot, .975), p=float((boot <= 0).mean())))
R = pd.DataFrame(res).sort_values("p"); n = len(R)
R["p_holm"] = np.minimum(1, np.maximum.accumulate([(n - i) * p for i, p in enumerate(R.p)]))
R["adopt"] = (R.gain_val > 0) & (R.p_holm < 0.05)
print(R.round(4).to_string())
# calibration of over 2.5 on oos
o = J[J.split == "oos"]; p = PR["style"]["o2.5"][(J.split == "oos").values]
b = pd.cut(p, [0, .35, .45, .55, .65, 1])
print(pd.DataFrame({"p": p, "o": outc["o2.5"][(J.split == "oos").values]}).groupby(b).agg(n=("o", "size"), pred=("p", "mean"), hit=("o", "mean")).round(3))
R.to_csv(f"{D}/open_results.csv", index=False)
m.save_model(f"{D}/open_model.txt")
json.dump({"glm": glm.params.to_dict(), "features": STYLE, "best_iteration": m.best_iteration},
          open(f"{D}/open_meta.json", "w"), indent=1)
# ---- upsets: where the style model moved the underdog, how did underdogs do?
oos = (J.split == "oos").values
fav_h = PR["cur"]["H"][oos] > PR["cur"]["A"][oos]
dog_cur = np.where(fav_h, PR["cur"]["A"][oos], PR["cur"]["H"][oos])
dog_sty = np.where(fav_h, PR["style"]["A"][oos], PR["style"]["H"][oos])
dog_won = np.where(fav_h, ag[oos] > hg[oos], hg[oos] > ag[oos])
lift = dog_sty - dog_cur
U = pd.DataFrame({"lift": lift, "dog_cur": dog_cur, "dog_sty": dog_sty, "won": dog_won})
U["band"] = pd.cut(U.lift, [-1, -0.04, -0.01, 0.01, 0.04, 1], labels=["style much less", "less", "same", "more", "style much more"])
print("\nUnderdogs, by how much the style model moved their chance (oos):")
print(U.groupby("band").agg(n=("won", "size"), cur=("dog_cur", "mean"), style=("dog_sty", "mean"), won=("won", "mean")).round(3))
# export for the live page
import gzip
d = m.dump_model()
with gzip.open(f"{D}/open_goals.json.gz", "wt") as fh: json.dump(d, fh)
