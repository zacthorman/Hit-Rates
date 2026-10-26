import pickle, collections, sys, numpy as np
sys.path.insert(0,'.')
import pplog
S = pickle.load(open('research/selbt/nba_scored.pkl','rb')) + pickle.load(open('research/selbt/nfl_scored.pkl','rb'))
idx = {(r['match'], pplog._norm(r['name']), r['stat']): r for r in S}
rows = pplog.all_rows()
sides = collections.defaultdict(dict)
for r in rows:
    f = r.get('first') or {}
    if f.get('price'): sides[(r['event_id'], pplog._norm(r['player']), r['stat'], r['line'])][bool(r['over'])] = (f['price'], r)
diff = []; po = []; pu = []; same = 0; n = 0
for (ev, pl, st, line), d in sides.items():
    if len(d) != 2: continue
    s = idx.get((ev, pl, st))
    if not s: continue
    n += 1
    diff.append(line - s['line']); same += abs(line - s['line']) < 1e-9 or abs(line - s['line'])/max(line,1) < 0.05
    po.append(d[True][0]); pu.append(d[False][0])
print('main lines matched', n, 'proxy within 5% of Paddy line', f"{same/max(n,1):.0%}")
diff = np.array(diff); print('Paddy line minus proxy: median', np.median(diff), 'mean', diff.mean().round(2))
print('avg over price', np.mean(po).round(3), 'avg under price', np.mean(pu).round(3), 'avg overround', np.mean([1/a+1/b for a,b in zip(po,pu)]).round(3))
