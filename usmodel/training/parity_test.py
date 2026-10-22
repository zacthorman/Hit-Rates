import sys, gzip, json, math, numpy as np, pandas as pd, lightgbm as lgb
from pathlib import Path
from scipy import stats as sst
sys.path.insert(0, "/home/claude/usbt/mac")
from fmodel_trees import Tree
src = open("/home/claude/usbt/src/usmodel_live.py").read()
ns = {"np": np, "math": math, "gzip": gzip, "json": json, "Tree": Tree, "Path": Path}
exec(src[src.index("class Model"):src.index("def payload")], ns)
for size, mu, line in ((3, 4.2, 3.5), (12, 18.3, 20.5), (0.5, 0.7, 0.5), (60, 1.5, 1.5), (1e4, 2.2, 0.5)):
    p = size / (size + mu)
    a, b = ns["p_over"]({"type": "nb", "size": size}, mu, line), 1 - sst.nbinom.cdf(math.floor(line), size, p)
    assert abs(a - b) < 1e-6, (size, mu, line, a, b)
print("negative binomial: matches scipy")
F = pd.read_parquet("/home/claude/usbt/data/nfl_features.parquet")
feats = [c for c in F.columns if c.endswith(("_m5", "_m10", "_ew")) and F[c].dtype.kind == "f"][:40]
y = np.clip(F.y_rec_yds.fillna(0).values, 0, None)
bst = lgb.train(dict(objective="poisson", num_leaves=15, verbose=-1, seed=1), lgb.Dataset(F[feats], y), 120)
with gzip.open("/tmp/claude-0/t.json.gz" if False else "/home/claude/usbt/t.json.gz", "wt") as f:
    json.dump(bst.dump_model(), f)
X = F[feats].astype(float).values[:2000]
a, b = bst.predict(X), ns["Model"](Path("/home/claude/usbt/t.json.gz")).predict(X)
print("trees: max relative difference", float(np.max(np.abs(a - b) / a)))
