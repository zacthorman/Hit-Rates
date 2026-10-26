"""How well does a form-only pricer reproduce Paddy's margin-free price on October's main lines?"""
import sys, collections, numpy as np, json
sys.path.insert(0,'.')
import pplog
rows = pplog.all_rows()
d = collections.defaultdict(dict)
for r in rows:
    f = r.get('first') or {}
    if f.get('price') and r['sport'] in ('basketball','american-football') and r.get('n10'):
        d[(r['event_id'], pplog._norm(r['player']), r['stat'], r['line'])][bool(r['over'])] = r
X=[];Y=[];G=[];SP=[];ST=[]
lg = lambda p: np.log(p/(1-p))
for k, s in d.items():
    if len(s) != 2: continue
    o, u = s[True], s[False]
    a, b = 1/o['first']['price'], 1/u['first']['price']
    fair = a/(a+b)
    r10 = (o['k10']+1)/(o['n10']+2); r5 = (o['k5']+.5)/(o['n5']+1)
    X.append([1, lg(r10), lg(r5)]); Y.append(fair); G.append(o['event_id']); SP.append(o['sport']); ST.append(o['stat'])
X=np.array(X);Y=np.array(Y);SP=np.array(SP)
out={}
for sp in ('basketball','american-football'):
    m = SP==sp
    beta,*_ = np.linalg.lstsq(X[m], lg(np.clip(Y[m],.02,.98)), rcond=None)
    pred = 1/(1+np.exp(-X[m]@beta))
    print(sp, m.sum(), 'beta', beta.round(3), 'mean abs error in chance', np.abs(pred-Y[m]).mean().round(3), 'corr', np.corrcoef(pred,Y[m])[0,1].round(2))
    out[sp]=beta.tolist()
json.dump(out, open('research/selbt/synth.json','w'))
