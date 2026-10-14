import csv, math, sys, collections
sys.path.insert(0, sys.argv[1]); import model, weekend
rows = []
for path in sys.argv[2:]:
    rows += list(csv.DictReader(open(path)))
def f(x):
    try: return float(x)
    except: return None
for r in rows:
    for k in list(r):
        if k not in ("date","stat","period","src"): r[k] = f(r[k])
print("rows", len(rows), "fixtures", len({r['event'] for r in rows}))
def shrunk(r): return (r['hits'] + 2) / (r['n'] + 4)
def ll(p, y):
    p = min(max(p, 1e-4), 1 - 1e-4); return -(y*math.log(p) + (1-y)*math.log(1-p))
def score(name, fn, subset):
    ps = [(fn(r), r['won']) for r in subset]; ps = [(p, y) for p, y in ps if p is not None]
    L = sum(ll(p, y) for p, y in ps) / len(ps); B = sum((p - y) ** 2 for p, y in ps) / len(ps)
    mean_p = sum(p for p, _ in ps) / len(ps); hit = sum(y for _, y in ps) / len(ps)
    print(f"  {name:<26} n={len(ps):>6}  logloss {L:.4f}  brier {B:.4f}  said {mean_p:.3f} landed {hit:.3f}")
def blend(a, b, w=0.5):
    def g(r):
        x, y = a(r), b(r)
        if x is None: return y
        if y is None: return x
        return w * x + (1 - w) * y
    return g
cands = {
 "shrunk record (live p)": shrunk,
 "model p, league proj": lambda r: r['p_model'],
 "model p, record only": lambda r: r['p_rec_model'],
}
for key in ("opp75","opp125","opp200","gap75","gap125","gap200"):
    cands[f"sim rate {key}"] = (lambda k: lambda r: None if r[f'wrate_{k}'] is None else (r[f'wrate_{k}']*r[f'neff_{k}'] + 4*shrunk(r)) / (r[f'neff_{k}'] + 4))(key)
    cands[f"model p, elo exp {key}"] = (lambda k: lambda r: r[f'p_ev_{k}'])(key)
cands["blend proj + gap125 sim"] = blend(lambda r: r['p_model'], cands["sim rate gap125"])
cands["blend proj + gap125 exp"] = blend(lambda r: r['p_model'], lambda r: r['p_ev_gap125'])
cands["blend3 proj+simgap125+expgap125"] = lambda r: (r['p_model'] + cands["sim rate gap125"](r) + (r['p_ev_gap125'] if r['p_ev_gap125'] is not None else r['p_model'])) / 3
cands["blend rec + gap125 exp (no proj)"] = blend(lambda r: r['p_rec_model'], lambda r: r['p_ev_gap125'])
# Only legs a headline pick could be: realistic sample and not silly
pool = [r for r in rows if r['n'] >= 15 and 1.05 < r['fair'] < 100 and not (r['line'] == 0.5 and r['over'] == 1)]
print("\nALL CANDIDATE LEGS (headline-eligible)")
for k, fn in cands.items(): score(k, fn, pool)
# selection test: per date, top-K among fair>=2 floor, and banker range
def pick_test(label, filt, K=3):
    print(f"\nTOP-{K} PER MATCHDAY, {label}")
    by_day = collections.defaultdict(list)
    for r in pool:
        if filt(r): by_day[r['date']].append(r)
    for name in ["shrunk record (live p)", "model p, league proj", "sim rate gap125", "model p, elo exp gap125",
                 "blend proj + gap125 exp", "blend3 proj+simgap125+expgap125"]:
        fn = cands[name]; won = tot = 0; said = 0
        for day, legs in by_day.items():
            scored = [(fn(r), r) for r in legs if fn(r) is not None]
            # live rule: rank on Wilson low of the record; for the others, rank on p
            if name == "shrunk record (live p)":
                scored = [(model.wilson_low(int(r['hits']), int(r['n'])), r) for _, r in scored]
            scored.sort(key=lambda x: -x[0])
            seen = set()
            for s, r in scored:
                if r['event'] in seen: continue
                seen.add(r['event']); won += r['won']; tot += 1; said += fn(r)
                if len(seen) >= K: break
        print(f"  {name:<34} picks {tot:>4}  landed {won/tot:.3f}  (its own p said {said/tot:.3f})")
pick_test("fair >= 2.00 (best single)", lambda r: r['fair'] >= 2.0)
pick_test("fair 1.30-1.75 (banker)", lambda r: 1.30 <= r['fair'] <= 1.75)
pick_test("fair 1.25-1.80 (double legs)", lambda r: 1.25 <= r['fair'] <= 1.80, K=5)
