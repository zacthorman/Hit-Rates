"""
The picks correct themselves from their own results.

    python learner.py            # refit on every settled pick, print what it learned
    python learner.py --check    # fit on the older picks, score on the newest

Every pick the site publishes is recorded before kick-off and settled after it
(besttrack.py). That record is the only honest test of the chances the site
quotes, so it is also the thing to learn from. This fits one correction from
"what the site said" to "what landed":

    logit(true) = a[group] + b[group] * logit(said) + c[group, market]

Group is sport and team-or-player; market is the family (cards, corners,
shots, goals, yards...). Three safeguards keep it from chasing noise:

  * PRIORS. a and c are pulled towards 0 and b towards 1, i.e. towards
    "the site was right", as if 100 phantom legs said so. Thirty settled
    legs cannot swing a group; several hundred can.
  * RECENCY. Each settled leg weighs half as much every ten days, so the
    correction follows the model as the model changes rather than averaging
    over versions of it that no longer exist.
  * IT MUST EARN ITS PLACE. --check fits on everything but the newest fifth
    and scores the newest fifth. If the corrected chances do not beat the
    uncorrected ones there, the live fit is switched off (identity) until it
    does. A model that learns from mistakes has to be able to show it.

It learns from the chance the site had BEFORE this correction (chance_base,
recorded since 16 October). Older legs, recorded before the correction
existed, use one over their fair price, which was the same thing then.
Learning from its own corrected output would correct the correction, and
drift.
"""

from __future__ import annotations

import json
import math
import probability
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STORE = HERE / "best_bets.json"
OUT = HERE / "learned.json"

HALF_LIFE_DAYS = 10.0
PRIOR_LEGS = 100.0
MIN_LEGS_GROUP = 30

FAMILIES = (
    ("cards", ("card",)), ("corners", ("corner",)), ("shots on target", ("on target",)),
    ("shots", ("shot",)), ("goals", ("goal", "score")), ("fouls", ("foul",)),
    ("tackles", ("tackle",)), ("saves", ("save",)), ("receiving", ("receiving", "reception")),
    ("rushing", ("rushing",)), ("passing", ("passing", "completion")), ("180s", ("180",)),
)


def family(stat: str | None) -> str:
    low = (stat or "").lower()
    for name, words in FAMILIES:
        if any(w in low for w in words):
            return name
    return "other"


def group_of(sport: str | None, player) -> str:
    return f"{sport or 'football'}|{'player' if player else 'team'}"


def _logit(p):
    return probability.logit(p, 1e-3)


_sig = probability.sigmoid


def settled_legs(items=None) -> list[dict]:
    items = items if items is not None else (json.loads(STORE.read_text()) if STORE.exists() else [])
    unique = {}
    for item in items:
        snap = item.get("snapshot_at") or 0
        for l in item.get("legs") or []:
            if l.get("result") not in ("win", "lose"):
                continue
            base = l.get("chance_base")
            if base is None:
                fair = l.get("fair")
                if not isinstance(fair, (int, float)) or not fair > 1:
                    continue
                base = 1 / fair
            key = (l.get("event_id"), l.get("player") or l.get("team"), l.get("stat"),
                   l.get("period"), l.get("line"), l.get("over"))
            unique[key] = {"said": base, "won": l["result"] == "win", "ts": l.get("kickoff") or snap,
                           "group": group_of(l.get("sport"), l.get("player")),
                           "family": family(l.get("stat"))}
    return sorted(unique.values(), key=lambda r: r["ts"])


def fit(legs: list[dict], now: float | None = None) -> dict:
    """Penalised, recency-weighted logistic fit, one group at a time."""
    now = now or time.time()
    out = {"groups": {}, "legs": len(legs), "updated": time.strftime("%d %b %Y %H:%M", time.localtime(now))}
    by_group = {}
    for r in legs:
        by_group.setdefault(r["group"], []).append(r)
    for g, rows in by_group.items():
        if len(rows) < MIN_LEGS_GROUP:
            continue
        fams = sorted({r["family"] for r in rows})
        # parameters: a, b, then one c per family
        k = 2 + len(fams)
        theta = [0.0, 1.0] + [0.0] * len(fams)
        prior_mean = [0.0, 1.0] + [0.0] * len(fams)
        # Prior precision as phantom legs: a and c at 1/0.5^2-ish per leg.
        prior_prec = [PRIOR_LEGS * 0.25, PRIOR_LEGS * 0.25] + [PRIOR_LEGS * 0.25] * len(fams)
        X, Y, W = [], [], []
        for r in rows:
            x = [1.0, _logit(r["said"])] + [1.0 if r["family"] == f else 0.0 for f in fams]
            X.append(x)
            Y.append(1.0 if r["won"] else 0.0)
            age = max(0.0, (now - r["ts"]) / 86400)
            W.append(0.5 ** (age / HALF_LIFE_DAYS))
        for _ in range(30):
            grad = [prior_prec[i] * (theta[i] - prior_mean[i]) for i in range(k)]
            hess = [[0.0] * k for _ in range(k)]
            for i in range(k):
                hess[i][i] = prior_prec[i]
            for x, y, w in zip(X, Y, W):
                p = _sig(sum(t * xi for t, xi in zip(theta, x)))
                for i in range(k):
                    if x[i] == 0:
                        continue
                    grad[i] += w * (p - y) * x[i]
                    for j in range(k):
                        if x[j]:
                            hess[i][j] += w * p * (1 - p) * x[i] * x[j]
            step = _solve(hess, grad)
            theta = [t - s for t, s in zip(theta, step)]
            if max(abs(s) for s in step) < 1e-7:
                break
        said = sum(r["said"] for r in rows) / len(rows)
        won = sum(r["won"] for r in rows) / len(rows)
        out["groups"][g] = {"a": round(theta[0], 4), "b": round(theta[1], 4),
                            "c": {f: round(c, 4) for f, c in zip(fams, theta[2:])},
                            "legs": len(rows), "said": round(said, 4), "landed": round(won, 4)}
    return out


def _solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        if abs(M[c][c]) < 1e-12:
            return [0.0] * n
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                M[r] = [x - f * y for x, y in zip(M[r], M[c])]
    return [M[i][n] / M[i][i] for i in range(n)]


def apply(model: dict, p: float, sport, player, stat) -> float:
    g = (model.get("groups") or {}).get(group_of(sport, player))
    if not g or not model.get("active", True):
        return p
    z = g["a"] + g["b"] * _logit(p) + (g.get("c") or {}).get(family(stat), 0.0)
    return _sig(z)


def check(legs: list[dict]) -> dict:
    """Fit on all but the newest fifth, score the newest fifth."""
    if len(legs) < 100:
        return {"ok": False, "reason": "fewer than 100 settled legs"}
    cut = int(len(legs) * 0.8)
    train, test = legs[:cut], legs[cut:]
    m = fit(train, now=test[0]["ts"])
    m["active"] = True
    ll0 = ll1 = 0.0
    for r in test:
        p0 = min(max(r["said"], 1e-4), 1 - 1e-4)
        p1 = min(max(apply(m, r["said"], *_split(r)), 1e-4), 1 - 1e-4)
        ll0 -= math.log(p0 if r["won"] else 1 - p0)
        ll1 -= math.log(p1 if r["won"] else 1 - p1)
    n = len(test)
    # On 16 October no setting beat leaving the chances alone (newest 233
    # legs: 0.5885 uncorrected, 0.5892 at best corrected). The picks priced
    # since the strength model went in said 70% and landed 71%, so there was
    # nothing left to correct; the fit stays off until it can show otherwise.
    return {"ok": ll1 < ll0, "test": n, "uncorrected": round(ll0 / n, 4), "corrected": round(ll1 / n, 4),
            "said": round(sum(r["said"] for r in test) / n, 4),
            "corrected_said": round(sum(apply(m, r["said"], *_split(r)) for r in test) / n, 4),
            "landed": round(sum(r["won"] for r in test) / n, 4)}


def _split(r):
    sport, kind = r["group"].split("|")
    # family is all apply() needs from the stat; pass a word that maps back to it
    return sport, kind == "player", dict(FAMILIES).get(r["family"], ("",))[0] if r["family"] != "other" else ""


_MODEL: dict | None = None


def model() -> dict:
    """The live correction, refitted once per process from best_bets.json and
    written to learned.json so the page and the summary can say what it did."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    try:
        legs = settled_legs()
        m = fit(legs)
        chk = check(legs)
        m["check"] = chk
        m["active"] = bool(chk.get("ok"))
        try:
            OUT.write_text(json.dumps(m, indent=1))
        except OSError:
            pass
        _MODEL = m
    except Exception as exc:
        print(f"  learner off: {type(exc).__name__}: {exc}")
        _MODEL = {"groups": {}, "active": False, "legs": 0}
    return _MODEL


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    legs = settled_legs()
    if args.check:
        print(json.dumps(check(legs), indent=1))
        return
    m = model()
    print(f"{m['legs']} settled legs, correction {'ON' if m.get('active') else 'OFF'}; check: {m.get('check')}")
    for g, v in sorted(m["groups"].items()):
        print(f"  {g:<26} {v['legs']:>4} legs  said {v['said']:.3f} landed {v['landed']:.3f}  "
              f"a {v['a']:+.3f} b {v['b']:.3f}  markets {v['c']}")


if __name__ == "__main__":
    main()
