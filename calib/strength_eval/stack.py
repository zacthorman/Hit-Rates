import csv, math, sys, collections
sys.path.insert(0, sys.argv[1]); import model
files = sys.argv[2:]
rows = []
for path in files:
    for r in csv.DictReader(open(path)):
        rows.append(r)
def f(x):
    try: return float(x)
    except: return None
keep = []
for r in rows:
    d = {k: f(r.get(k)) for k in ("n","hits","won","fair","p_model","p_rec_model","neff_gap125","sw_gap125","wrate_gap125","p_ev_gap125","p_ev_reg","league","event","line","over")}
    d["date"] = r["date"]; d["src"] = r["src"]
    if d["n"] < 15 or not (1.05 < d["fair"] < 100) or (d["line"] == 0.5 and d["over"] == 1): continue
    keep.append(d)
rows = keep
def lg(p): p = min(max(p, 1e-3), 1 - 1e-3); return math.log(p / (1 - p))
VERSION = sys.argv[1+len(sys.argv[2:])] if False else None
import os
V2 = os.environ.get("V2") == "1"
def feats(r, proj=True):
    shr = (r["hits"] + 2) / (r["n"] + 4)
    if V2:
        sim = shr if r["wrate_gap125"] is None else (r["wrate_gap125"] * r["sw_gap125"] + 4 * shr) / (r["sw_gap125"] + 4)
        pe = r["p_ev_reg"] if r["p_ev_reg"] is not None else r["p_rec_model"]
    else:
        sim = shr if r["wrate_gap125"] is None else (r["wrate_gap125"] * r["neff_gap125"] + 4 * shr) / (r["neff_gap125"] + 4)
        pe = r["p_ev_gap125"] if r["p_ev_gap125"] is not None else r["p_rec_model"]
    pm = r["p_model"] if proj else r["p_rec_model"]
    return [1.0, lg(shr), lg(sim), lg(pe), lg(pm)]
NAMES = ["bias", "record", "similar-opposition record", "Elo expectation", "league projection"]
def fit(data, l2=1.0, iters=25):
    k = len(data[0][0]); w = [0.0] * k
    for _ in range(iters):
        g = [0.0] * k; H = [[0.0] * k for _ in range(k)]
        for x, y in data:
            z = sum(wi * xi for wi, xi in zip(w, x)); p = 1 / (1 + math.exp(-z))
            for i in range(k):
                g[i] += (p - y) * x[i]
                for j in range(k): H[i][j] += p * (1 - p) * x[i] * x[j]
        for i in range(1, k): g[i] += l2 * w[i]; H[i][i] += l2
        # solve H d = g (Gaussian elimination)
        A = [H[i][:] + [g[i]] for i in range(k)]
        for c in range(k):
            piv = max(range(c, k), key=lambda r_: abs(A[r_][c])); A[c], A[piv] = A[piv], A[c]
            for r_ in range(k):
                if r_ != c:
                    fct = A[r_][c] / A[c][c]
                    A[r_] = [a - fct * b for a, b in zip(A[r_], A[c])]
        d = [A[i][k] / A[i][i] for i in range(k)]
        w = [wi - di for wi, di in zip(w, d)]
    return w
def pred(w, x): return 1 / (1 + math.exp(-sum(a * b for a, b in zip(w, x))))
def ll(p, y): p = min(max(p, 1e-4), 1 - 1e-4); return -(y * math.log(p) + (1 - y) * math.log(1 - p))
leagues = sorted({r["league"] for r in rows})
oof = {}
tot = collections.Counter()
for L in leagues:
    train = [(feats(r), r["won"]) for r in rows if r["league"] != L]
    w = fit(train)
    test = [r for r in rows if r["league"] == L]
    a = sum(ll(pred(w, feats(r)), r["won"]) for r in test) / len(test)
    b = sum(ll(r["p_model"], r["won"]) for r in test) / len(test)
    c = sum(ll((r["hits"] + 2) / (r["n"] + 4), r["won"]) for r in test) / len(test)
    print(f"league {int(L):>4}: held-out log loss  stacked {a:.4f}   projection {b:.4f}   live record {c:.4f}   ({len(test)} legs)")
    for r in test: oof[id(r)] = pred(w, feats(r))
wall = fit([(feats(r), r["won"]) for r in rows])
print("\nweights on all leagues:", ", ".join(f"{n} {v:+.3f}" for n, v in zip(NAMES, wall)))
# no-projection version (for cross-league fixtures)
wnp = fit([(feats(r, proj=False)[:4], r["won"]) for r in rows])
print("weights without projection:", ", ".join(f"{n} {v:+.3f}" for n, v in zip(NAMES[:4], wnp)))
# calibration of OOF
print("\nheld-out calibration of the stacked probability")
bk = collections.defaultdict(lambda: [0, 0, 0.0])
for r in rows:
    p = oof[id(r)]; b = min(int(p * 10), 9); bk[b][0] += 1; bk[b][1] += r["won"]; bk[b][2] += p
for b in sorted(bk):
    n, y, s = bk[b]; print(f"  {b/10:.1f}-{(b+1)/10:.1f}: {n:>6} legs, said {s/n:.3f}, landed {y/n:.3f}")
# selection with oof
def pick_test(label, filt, K):
    by_day = collections.defaultdict(list)
    for r in rows:
        if filt(r): by_day[r["date"]].append(r)
    res = {}
    for name, key in (("live (Wilson on record)", lambda r: model.wilson_low(int(r["hits"]), int(r["n"]))),
                      ("stacked p", lambda r: oof[id(r)])):
        won = tot = 0; said = 0.0
        for day, legs in by_day.items():
            seen = set()
            for r in sorted(legs, key=lambda r: -key(r)):
                if r["event"] in seen: continue
                seen.add(r["event"]); won += r["won"]; tot += 1
                said += (r["hits"] + 2) / (r["n"] + 4) if name.startswith("live") else oof[id(r)]
                if len(seen) >= K: break
        res[name] = (tot, won / tot, said / tot)
    print(f"\n{label}")
    for k, (t, h, s) in res.items():
        se = math.sqrt(h * (1 - h) / t)
        print(f"  {k:<26} {t:>4} picks  landed {h:.3f} (+/- {se:.3f})  said {s:.3f}")
pick_test("best single pool, fair >= 2.00, top 3 a day", lambda r: r["fair"] >= 2.0, 3)
pick_test("banker pool, fair 1.30-1.75, top 3 a day", lambda r: 1.30 <= r["fair"] <= 1.75, 3)
pick_test("double pool, fair 1.25-1.80, top 5 a day", lambda r: 1.25 <= r["fair"] <= 1.80, 5)
pick_test("any price, top 5 a day", lambda r: True, 5)
open(("weights_v2.txt" if V2 else "weights.txt"), "w").write(repr({"with_projection": wall, "without_projection": wnp}))
ucl = os.environ.get("UCL")
if ucl:
    U = []
    for r in csv.DictReader(open(ucl)):
        d = {k: f(r.get(k)) for k in ("n","hits","won","fair","p_model","p_rec_model","neff_gap125","sw_gap125","wrate_gap125","p_ev_gap125","p_ev_reg","line","over")}
        if d["n"] < 10: continue
        U.append(d)
    a = sum(ll(pred(wnp, feats(r, proj=False)[:4]), r["won"]) for r in U) / len(U)
    b = sum(ll(r["p_rec_model"], r["won"]) for r in U) / len(U)
    c = sum(ll((r["hits"] + 2) / (r["n"] + 4), r["won"]) for r in U) / len(U)
    said = sum(pred(wnp, feats(r, proj=False)[:4]) for r in U) / len(U); hit = sum(r["won"] for r in U) / len(U)
    print(f"\nCHAMPIONS LEAGUE, never seen in fitting ({len(U)} legs): strength (no projection) {a:.4f}  record-only price {b:.4f}  live record {c:.4f}   said {said:.3f} landed {hit:.3f}")
