import pickle, collections, datetime, random, numpy as np
PRICE = 1.87
S = pickle.load(open('research/selbt/nba_scored.pkl','rb')) + pickle.load(open('research/selbt/nfl_scored.pkl','rb'))
B = []
for r in S:
    if r['y'] == r['line']: continue
    for over in (True, False):
        p = r['p_over'] if over else 1 - r['p_over']
        k10 = r['k10o'] if over else r['n10'] - r['k10o'] - 0  # pushes impossible at .5 lines
        k5 = r['k5o'] if over else r['n5'] - r['k5o']
        win = (r['y'] > r['line']) == over
        B.append(dict(r, over=over, p=p, edge=p*PRICE-1, k10=k10, k5=k5, win=win,
                      day=datetime.datetime.utcfromtimestamp(r['ts']-6*3600).date()))
def roi(b):
    return sum(PRICE-1 if x['win'] else -1 for x in b)/len(b) if b else 0
def show(name, b):
    print(f"{name:52s} {len(b):6d} bets {len({x['match'] for x in b}):5d} games  won {np.mean([x['win'] for x in b]) if b else 0:.1%}  ROI at {PRICE} {roi(b):+.1%}")
form = lambda x, a=.7, c=.6: x['k10']/x['n10'] >= a and x['k5']/x['n5'] >= c
def dedupe(b):
    best = {}
    for x in b:
        k = (x['match'], x['pid'])
        if k not in best or x['edge'] > best[k]['edge']: best[k] = x
    return list(best.values())
def daily(b, cap=8, pergame=2):
    out = []; byd = collections.defaultdict(list)
    for x in dedupe(b): byd[(x['sport'], x['day'])].append(x)
    for d, xs in byd.items():
        xs.sort(key=lambda x: -x['edge']); g = collections.Counter(); n = 0
        for x in xs:
            if n >= cap or g[x['match']] >= pergame: continue
            out.append(x); g[x['match']] += 1; n += 1
    return out
for sp in ('nfl', 'nba'):
    A = [x for x in B if x['sport'] == sp]
    rng = (min(x['day'] for x in A), max(x['day'] for x in A))
    print(f"\n===== {sp.upper()} out of sample {rng[0]} to {rng[1]}")
    show('every line, both sides', A)
    V = [x for x in A if x['edge'] >= .03]; show('model value 3%+', V)
    F = [x for x in V if form(x)]; show(' + form L10>=70%, L5>=60%', F)
    show(' + form only (no model)', [x for x in A if form(x)])
    D = daily(F); show(' DAILY SELECTIONS (1/player, 2/game, 8/day)', D)
    for ov in (True, False): show(f"   {'overs' if ov else 'unders'}", [x for x in D if x['over'] == ov])
    by = collections.defaultdict(list)
    for x in D: by[x['stat']].append(x)
    for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])): show(f"   {k}", v)
    bym = collections.defaultdict(list)
    for x in D: bym[x['day'].strftime('%Y-%m')].append(x)
    for k in sorted(bym): show(f"   month {k}", bym[k])
    days = collections.defaultdict(list)
    for x in D: days[x['day']].append(x)
    ks = list(days); random.seed(1); res = sorted(roi([x for k in random.choices(ks, k=len(ks)) for x in days[k]]) for _ in range(1000))
    print(f"   {len(ks)} betting days; 90% range {res[50]:+.1%} to {res[950]:+.1%}; days in profit {np.mean([roi(v) > 0 for v in days.values()]):.0%}")
