"""Markdown tables from audit_us.py's {sport}_audit.json.

    python3 audit_report.py OUT_DIR/nfl_audit.json [--before OTHER/nfl_audit.json]

--before: a run on the features before a fix, for the before-and-after table.
"""
import argparse
import json


def f4(x):
    return f"{x:.4f}"


def pct(x):
    return f"{x * 100:+.1f}%"


def tables(d, before=None):
    M = d["markets"]
    out = []
    out.append(f"Folds (test blocks): {', '.join(d['folds'])}\n")
    out.append("### Log loss, pooled over every test block (lower is better)\n")
    out.append("| market | folds | games | lines | site | site recal | model | blend | live | live v recal |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for s, r in M.items():
        out.append(f"| {s} | {r['folds']} | {r['games']} | {r['lines']} | {f4(r['ll_site'])} | {f4(r['ll_site_fair'])}"
                   f" | {f4(r['ll_new'])} | {f4(r['ll_blend'])} | {f4(r['ll_live'])}"
                   f" | {r['ll_site_fair'] - r['ll_live']:+.4f} |")
    out.append("\n### Brier score (lower is better)\n")
    out.append("| market | site | site recal | model | blend | live |")
    out.append("|---|---|---|---|---|---|")
    for s, r in M.items():
        out.append(f"| {s} | " + " | ".join(f4(r[f'brier_{v}']) for v in ("site", "site_fair", "new", "blend", "live")) + " |")
    out.append("\n### Calibration: said v landed, slope of outcome on log-odds (1 is right), ten-bin ECE\n")
    out.append("| market | landed | site said | site slope | site ECE | recal said | recal slope | recal ECE | live said | live slope | live ECE |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for s, r in M.items():
        c = [r[f"cal_{v}"] for v in ("site", "site_fair", "live")]
        out.append(f"| {s} | {c[0]['landed']:.3f} | " + " | ".join(
            f"{x['said']:.3f} | {x['cal_slope']:.2f} | {x['ece']:.3f}" for x in c) + " |")
    out.append("\n### Log-loss gain of live per test block, against the recalibrated site (positive: live better)\n")
    folds = d["folds"]
    out.append("| market | " + " | ".join(folds) + " | blocks won |")
    out.append("|---|" + "---|" * (len(folds) + 1))
    for s, r in M.items():
        g = r["fold_gains_vs_site_fair"]
        cells = [f"{g[f]:+.4f}" if f in g else "" for f in folds]
        out.append(f"| {s} | " + " | ".join(cells) + f" | {sum(v > 0 for v in g.values())} of {len(g)} |")
    out.append("\n### Bootstrap: live's log-loss gain, 95% interval, resampling whole games\n")
    out.append("| market | v site | 95% interval | v recal site | 95% interval | P(gain <= 0) | survives | survives Bonferroni |")
    out.append("|---|---|---|---|---|---|---|---|")
    for s, r in M.items():
        a, b = r["gain_vs_site"], r["gain_vs_site_fair"]
        out.append(f"| {s} | {a['gain']:+.4f} | {a['lo']:+.4f} to {a['hi']:+.4f} | {b['gain']:+.4f} | "
                   f"{b['lo']:+.4f} to {b['hi']:+.4f} | {b['p_le0']:.3f} | {'yes' if b['survives'] else 'no'} | "
                   f"{'yes' if b['survives_bonf'] else 'no'} |")
    out.append("\n### Blend or model alone: gain of the blend over the model alone, 95% interval\n")
    out.append("| market | blend chosen in | blend gain | 95% interval | weights per block (model, site) |")
    out.append("|---|---|---|---|---|")
    for s, r in M.items():
        b = r["blend_vs_new"]
        w = "; ".join(f"{f}: {v[0]:.2f}, {v[1]:.2f}" for f, v in r["weights"].items())
        out.append(f"| {s} | {r['blend_chosen_folds']} of {r['folds']} | {b['gain']:+.4f} | {b['lo']:+.4f} to {b['hi']:+.4f} | {w} |")
    out.append("\n### The page's take rule, flat one-unit stakes, against a synthetic book\n")
    out.append("Book: the recalibrated site chance with a two-way margin. ROI interval resamples whole games.\n")
    out.append("| market | bets (7.5%) | won | ROI 7.5% | 95% interval | ROI 5% margin | ROI 10% margin | best rung only: bets, ROI, interval | book = raw site, 7.5%: bets, ROI |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for s, b in d["betting"].items():
        m = b["live|site_fair|0.075"]
        m5, m10 = b["live|site_fair|0.05"], b["live|site_fair|0.1"]
        br = b["live_best_rung|site_fair|0.075"]
        rs = b["live|site|0.075"]

        def roi(x):
            return pct(x["roi"]) if x["bets"] else "no bets"
        out.append(f"| {s} | {m['bets']} | {m['won']} | {roi(m)} | "
                   + (f"{pct(m['lo'])} to {pct(m['hi'])}" if m["bets"] else "") +
                   f" | {roi(m5)} ({m5['bets']}) | {roi(m10)} ({m10['bets']}) | {br['bets']}, {roi(br)}, "
                   + (f"{pct(br['lo'])} to {pct(br['hi'])}" if br["bets"] else "") +
                   f" | {rs['bets']}, {roi(rs)} |")
    a = d["betting_all"]
    out.append(f"\nAll markets together (7.5% margin): {a['bets']} bets, {a['won']} won, ROI {pct(a['roi'])}, "
               f"95% interval {pct(a['lo'])} to {pct(a['hi'])}.\n")
    if before:
        out.append("\n### The zero-stat fix: before and after\n")
        out.append("| market | lines before | lines after | live log loss before | after | gain v recal before | after |")
        out.append("|---|---|---|---|---|---|---|")
        for s, r in M.items():
            q = before["markets"].get(s)
            if not q:
                continue
            out.append(f"| {s} | {q['lines']} | {r['lines']} | {f4(q['ll_live'])} | {f4(r['ll_live'])} | "
                       f"{q['gain_vs_site_fair']['gain']:+.4f} | {r['gain_vs_site_fair']['gain']:+.4f} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audit")
    ap.add_argument("--before")
    a = ap.parse_args()
    d = json.load(open(a.audit))
    print(tables(d, json.load(open(a.before)) if a.before else None))


if __name__ == "__main__":
    main()
