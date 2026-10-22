"""Conditional table for boost legs: P(shots-on-target winner, corners winner | result, favourite bucket).
From every match in the site's cache with both stats. Bucket from each side's last-5 xG difference before
kick-off (home minus away), which the live page can compute the same way."""
import json, numpy as np, pandas as pd
T = pd.read_parquet('/home/claude/bt/data/teams.parquet').sort_values('ts')
T['xd'] = T['f_Expected goals'] - T['a_Expected goals']
T['form5'] = T.groupby('team')['xd'].transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())
H = T[T.home == 1].merge(T[T.home == 0][['match', 'form5']].rename(columns={'form5': 'form5_away'}), on='match')
H = H.dropna(subset=['form5', 'form5_away', 'f_Shots on target', 'a_Shots on target', 'f_Corner kicks', 'a_Corner kicks'])
H['d'] = H.form5 - H.form5_away
print(len(H), H.d.describe().round(2).to_dict())
CUT = 0.5
H['bucket'] = np.where(H.d > CUT, 'home_fav', np.where(H.d < -CUT, 'away_fav', 'even'))
H['res'] = np.where(H.gf > H.ga, 'H', np.where(H.gf < H.ga, 'A', 'D'))
cmp = lambda a, b: np.where(a > b, 'H', np.where(a < b, 'A', 'T'))
H['sot'] = cmp(H['f_Shots on target'], H['a_Shots on target'])
H['cor'] = cmp(H['f_Corner kicks'], H['a_Corner kicks'])
out = {'cut': CUT, 'n': int(len(H)), 'made': pd.Timestamp.now().strftime('%Y-%m-%d'), 'table': {}}
for (b, r), g in H.groupby(['bucket', 'res']):
    ct = g.groupby(['sot', 'cor']).size()
    # light smoothing so no cell is exactly 0
    cells = {f'{s}{c}': (int(ct.get((s, c), 0)) + 0.5) / (len(g) + 4.5) for s in 'HAT' for c in 'HAT'}
    out['table'][f'{b}|{r}'] = {'n': int(len(g)), 'p': {k: round(v, 4) for k, v in cells.items()}}
json.dump(out, open('boost_table.json', 'w'), indent=1)
for k, v in out['table'].items():
    p = v['p']; print(k, v['n'], 'homeSOT', round(p['HH']+p['HA']+p['HT'],2), 'homeCor', round(p['HH']+p['AH']+p['TH'],2), 'both home', p['HH'])
