"""Score exported LightGBM models with plain Python and numpy.

The models are trained in the backtest (LightGBM) and dumped to JSON, so the
Mac needs neither lightgbm nor any compiler. Each tree is flattened into
arrays once; a prediction walks every tree for every row, vectorised by row.
"""
from __future__ import annotations
import gzip
import json
import math
from pathlib import Path
import numpy as np


class Tree:
    def __init__(self, node):
        self.feat, self.thr, self.left, self.right = [], [], [], []
        self.dleft, self.mtype, self.cats, self.leaf = [], [], [], []
        self._add(node)
        self.feat = np.array(self.feat); self.thr = np.array(self.thr, float)
        self.left = np.array(self.left); self.right = np.array(self.right)
        self.dleft = np.array(self.dleft, bool); self.mtype = np.array(self.mtype)
        self.leaf = np.array(self.leaf, float)

    def _add(self, n):
        i = len(self.feat)
        for a in (self.feat, self.thr, self.left, self.right, self.dleft, self.mtype, self.cats, self.leaf):
            a.append(0)
        if "leaf_value" in n:
            self.feat[i] = -1
            self.leaf[i] = n["leaf_value"]
            self.cats[i] = None
            return i
        self.feat[i] = n["split_feature"]
        self.dleft[i] = bool(n.get("default_left"))
        self.mtype[i] = {"None": 0, "Zero": 1, "NaN": 2}[n.get("missing_type", "None")]
        if n.get("decision_type") == "==":
            self.cats[i] = {int(c) for c in str(n["threshold"]).split("||")}
        else:
            self.cats[i] = None
            self.thr[i] = float(n["threshold"])
        self.left[i] = self._add(n["left_child"])
        self.right[i] = self._add(n["right_child"])
        return i

    def predict(self, X):
        out = np.empty(len(X))
        for r in range(len(X)):
            i = 0
            x = X[r]
            while self.feat[i] >= 0:
                v = x[self.feat[i]]
                c = self.cats[i]
                if c is not None:
                    go_left = (not math.isnan(v)) and v >= 0 and int(v) in c
                else:
                    mt = self.mtype[i]
                    nan = math.isnan(v)
                    if mt == 2 and nan:
                        go_left = self.dleft[i]
                    else:
                        if nan:
                            v = 0.0
                        if mt == 1 and v == 0.0:
                            go_left = self.dleft[i]
                        else:
                            go_left = v <= self.thr[i]
                i = self.left[i] if go_left else self.right[i]
            out[r] = self.leaf[i]
        return out


class Model:
    def __init__(self, path):
        path = Path(path)
        gz = path.with_name(path.name + ".gz")
        if gz.exists():
            with gzip.open(gz, "rt") as f:
                d = json.load(f)
        else:
            d = json.loads(path.read_text())
        self.features = d["feature_names"]
        self.trees = [Tree(t["tree_structure"]) for t in d["tree_info"]]

    def predict(self, X):
        X = np.asarray(X, float)
        raw = np.zeros(len(X))
        for t in self.trees:
            raw += t.predict(X)
        return 1 / (1 + np.exp(-raw))
