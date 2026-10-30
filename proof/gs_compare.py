"""Coefficient movement between two gs_fit.json files.  python3 -B proof/gs_compare.py OLD NEW"""
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
print(f"Matches {a['matches']} to {b['matches']}; team rows {a['team_rows']} to {b['team_rows']}; player rows {a['player_rows']} to {b['player_rows']}.")
print(f"Possession error {a['possession']['mae_predicted']:.2f} to {b['possession']['mae_predicted']:.2f} points (usual share only {a['possession']['mae_usual_only']:.2f} to {b['possession']['mae_usual_only']:.2f}).\n")
print("| Scope | Stat | n (21 Oct / 30 Oct) | game state coef | opponent coef | own coef | alpha | M2 - M1 log loss | used |")
print("|---|---|---|---|---|---|---|---|---|")
big = []
for scope in ("team", "player"):
    for s, x in a[scope].items():
        y = b[scope].get(s)
        if not y:
            continue
        f = lambda i: f"{x['coef'][i]:+.3f} to {y['coef'][i]:+.3f}"
        d = lambda z: z["M2"]["ll"] - z["M1"]["ll"]
        big.append((max(abs(x['coef'][i] - y['coef'][i]) for i in range(len(x['coef']))), scope, s))
        print(f"| {scope} | {s} | {x['n_all']} / {y['n_all']} | {f(-1)} | {f(-2)} | {f(1)} | {x['alpha']:.3f} to {y['alpha']:.3f} | "
              f"{d(x):+.4f} to {d(y):+.4f} | {'yes' if x['use'] else 'no'} / {'yes' if y['use'] else 'no'} |")
m = max(big)
print(f"\nLargest move in any coefficient: {m[0]:.3f} ({m[1]} {m[2]}).")
print("Used flags changed: " + (", ".join(f"{sc} {s}" for sc in ("team", "player") for s in a[sc] if s in b[sc] and a[sc][s]['use'] != b[sc][s]['use']) or "none") + ".")
