# Assists and thin-market watch

Written 24 October 2026 on the `assists-watch` branch, from `main-sync`. Two jobs:

1. **A properly sized, out-of-sample check of football assists 1+** and the other low-count player lines the page prices (to score, shots on target 2+; cards cannot be settled from the cache, see below).
2. **A watch in `rule_review.py`,** fixed in advance, that flags any player stat line running short once 50 lines of it have settled in `pplog/`.

## Verdict

**Assists 1+ is badly overconfident, everywhere, and is now a long shot.** The rule, set in the brief before this was run: assists 1+ becomes a long shot in `verdictOf` if, for starters we make 50% or more (the only lines the verdict could call acceptable), landed minus said has a 95% interval wholly below zero on the months before September and again on the months from it. It does on both:

- **Before 1 September:** 264 lines, said 52.9%, landed 22.3%, −30.6 points (95% −35.7 to −25.1).
- **1 September to 19 October:** 59 lines, said 53.2%, landed 20.3%, −32.9 points (95% −42.8 to −23.0).

These are the same lines and figures ACCEPTABLE-CHECK.md (#17) reported. Its 500-line bar was what held it back. The size problem goes away once the whole line is read rather than only the 50%+ band:

- **Every chance:** across all 81,203 starter lines, ours said 16.8% and 7.2% landed before September (−9.6 points, −9.8 to −9.4). From September it said 17.6% and 7.6% landed (−9.9, −10.5 to −9.3).
- **Price bands:** every band to 10.0 is short in both periods, with intervals clear of zero.
- **Positions:** every position is short in both periods.
- **At fair price:** backed at our fair price, assists 1+ lost about a third of its stake in both periods.

**Change:** `report.py RUNS_HIGH` now returns true for a football assists over at 1+, alongside fouls, fouled and tackles at 2+. `rule_review.runs_high` mirrors it, and the long-shot tooltip names it. Nothing else in the verdict moves: a price 5% or more either side of our chance is still avoid. A test runs the page's `verdictOf` in node against the Python mirror on 3,000 random lines, assists included.

**Why it runs high, and the fix that should follow (not made here).** The players' own records are honest: hits over their last ten said 7.4% for these starters, and 7.2% landed. The page's chance comes from `model.price_player`, and its player calibration pulls every chance a long way towards 50%. That turns a 7% record into a 17% price. SCORER-AUDIT.md found the same squeeze and fixed it for shots and shots on target with a per-line map (`fmodel/site_calib.json`, applied by `siteCalibrated`), but assists were not among its lines. As a check, a Platt map fitted on the earlier months' starters (logit chance = −1.865 + 0.392 × logit ours) brings the later months to 7.3% said against 7.6% landed. Log loss on those 10,396 lines falls from 0.3217 to 0.2636, and landed minus said becomes +0.3 points (−0.2 to +0.8).

Two changes would carry it to the live price:

- **The page:** add an `Assists|1` entry to `fmodel/site_calib.json`, where `siteCalibrated` would read it once its stat list includes assists.
- **pplog:** apply the same map to Paddy Power assists lines in `pplog.snapshot`, which uses the raw `price_player`.

That is a pricing change across the page and pplog, beyond this brief, so it is described rather than made. Until then the long-shot verdict stops the page calling an assists line acceptable. It does not correct the chance shown beside it.

**To score and shots on target 2+ are calibrated for starters.**

- **To score:** said 10.0% and landed 10.0% before September, and 10.0% against 10.1% from it, with every price band and position within its interval.
- **Shots on target 2+:** 7.4% against 7.1%, then 7.2% against 7.5%.

These lines use fmodel for starters from July (SCORER-AUDIT.md), so this is fmodel's calibration, seen again. Neither passes any rule for a change, so neither is changed.

**Every line is far too high for players who came on.** Assists 17% said against 3–4% landed; to score 11–12% against 5–6%; shots on target 2+ 21% against 2–3%. This is the substitute problem ACCEPTABLE-CHECK.md raised: our chance is a starter's chance. It matters only if Paddy Power settles a substitute's bet as live, which is still to be checked against its terms.

**Cards are not scored.** The page prices "to be shown a card", but the cached line-ups carry no player card counts, so nothing can settle them here. The card estimate is already never acceptable (`v.heuristic` in `verdictOf`). The watch below covers cards from `pplog/`, which settles them.

**NBA threes and rebounds plus assists** (nba-check, #22) are not in the cache, which holds no basketball line-ups with statistics. The watch is the place they will show.

## The thin-market watch

`python rule_review.py watch [--pplog DIR]`. The full `python rule_review.py` prints it first in the Paddy Power section whenever `pplog/` is present. These rules were fixed now, before the lines it judges settle:

- **What counts:** every settled Paddy Power player line in `pplog/`, at the chance first seen.
- **Grouping:** by sport, stat, line and side, for example "football · Assists 1+" or "basketball · Three pointers made 3+".
- **When a group is judged:** once it holds 50 settled lines (`WATCH_MIN`). Until then it reads "waiting (n of 50)".
- **The measure:** landed minus said, with a 95% interval resampling whole fixtures.
- **The call:** running short if the interval lies wholly below zero, running long if wholly above, in line otherwise. Short lines come first.
- **What it does:** it reports and changes no verdict. A line it flags is a candidate for the kind of check above, made on the cache or on later lines, before anything changes.
- **False alarms:** at 95%, about one judged line in 40 will be flagged short by chance. The header says how many lines are judged, so a single flag among many can be read for what it is.

It cannot be run here: `pplog/` is gitignored and lives on the Mac. On the cache figures above, football assists 1+ would be flagged within its first 50 settled lines.

## How the cache check was done

- **The replay is acceptable-check's.** `acceptable_check.py fmodel` and `build` replay every football player line on Paddy Power's menu, for every player who played, priced before kick-off as pplog prices it, and settled from the match's own statistics. Here that came to 1,388,400 lines from 6,641 matches. `assists_watch.py` reads those rows rather than building a second copy.
- **Which matches:** the report competitions (`acceptable_check.REPORT_TIDS`), as there.
- **Periods:** matches before 1 September 2026, and from it to 19 October.
- **Intervals:** 95% percentile bootstraps resampling whole matches (1,000 draws).
- **Lines left out:** 923 to-score lines that `pplog._score_chance` priced at exactly 0, which have no fair price. Nearly all are substitutes (906), and 13 of them scored. A zero chance on a player who can score is its own small fault in the to-score fallback, noted rather than fixed.

Reproducing:

    python -B acceptable_check.py fmodel --cache CACHE --fmodel FM.pkl     # about 9 minutes
    python -B acceptable_check.py build --cache CACHE --fmodel FM.pkl --rows ROWS.json.gz
    python -B assists_watch.py --rows ROWS.json.gz                          # about 30 seconds

## Files

- `report.py`: `RUNS_HIGH` takes football assists 1+, and the long-shot tooltip says so.
- `rule_review.py`: `runs_high` mirrors it; `watch_rows`, `watch_groups`, `watch_text` and the `watch` command.
- `assists_watch.py`: the cache check and these tables.
- `tests/test_assists_watch.py`: 12 tests on synthetic rows and pplog files, and one running `verdictOf` in node against the mirror.

## Every table

Generated 2026-10-24 14:53 UTC by `assists_watch.py`. Earlier: matches before 1 September 2026; later: from it. Intervals resample whole matches, 1,000 draws.


### Assists 1+

| who and chance | period | lines | matches | said | landed | landed minus said | 95% | return at fair | 95% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| starters, every chance | earlier | 70,807 | 3,812 | 16.8% | 7.2% | -9.6% | -9.8 to -9.4 | -34.0% | -36.3 to -31.5 |
| starters, every chance | later | 10,396 | 561 | 17.6% | 7.6% | -9.9% | -10.5 to -9.3 | -32.9% | -39.1 to -26.0 |
| starters, ours 50%+ | earlier | 264 | 249 | 52.9% | 22.3% | -30.6% | -35.7 to -25.1 | -58.1% | -67.9 to -48.1 |
| starters, ours 50%+ | later | 59 | 56 | 53.2% | 20.3% | -32.9% | -42.8 to -23.0 | -62.9% | -80.9 to -44.3 |
| starters, under 50% | earlier | 70,543 | 3,812 | 16.6% | 7.1% | -9.5% | -9.7 to -9.3 | -33.9% | -36.2 to -31.4 |
| starters, under 50% | later | 10,337 | 561 | 17.3% | 7.6% | -9.8% | -10.3 to -9.2 | -32.8% | -38.9 to -25.8 |
| came on, every chance | earlier | 21,245 | 3,698 | 17.0% | 3.4% | -13.6% | -13.9 to -13.3 | -67.4% | -70.2 to -64.5 |
| came on, every chance | later | 3,274 | 558 | 18.1% | 3.9% | -14.2% | -15.0 to -13.4 | -66.8% | -73.8 to -59.1 |

Starters by fair price (one over our chance):

| fair price | period | lines | matches | said | landed | landed minus said | 95% | return at fair | 95% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1.5 to 2 | earlier | 264 | 249 | 52.9% | 22.3% | -30.6% | -35.7 to -25.1 | -58.1% | -67.9 to -48.1 |
| 1.5 to 2 | later | 59 | 56 | 53.2% | 20.3% | -32.9% | -42.8 to -23.0 | -62.9% | -80.9 to -44.3 |
| 2 to 3 | earlier | 12,313 | 3,594 | 37.5% | 12.2% | -25.4% | -25.9 to -24.8 | -67.6% | -69.1 to -66.1 |
| 2 to 3 | later | 2,059 | 538 | 37.8% | 12.6% | -25.1% | -26.4 to -23.6 | -66.9% | -70.3 to -62.9 |
| 3 to 5 | earlier | 16,226 | 3,473 | 27.8% | 8.7% | -19.1% | -19.6 to -18.7 | -68.8% | -70.4 to -67.1 |
| 3 to 5 | later | 2,344 | 543 | 27.6% | 9.0% | -18.6% | -19.7 to -17.5 | -67.4% | -71.3 to -63.2 |
| 5 to 10 | earlier | 3,659 | 1,821 | 12.5% | 5.4% | -7.1% | -7.9 to -6.4 | -57.1% | -63.3 to -51.3 |
| 5 to 10 | later | 553 | 324 | 12.5% | 6.3% | -6.2% | -8.0 to -4.0 | -49.4% | -64.3 to -32.2 |
| 10+ | earlier | 38,345 | 3,736 | 5.6% | 5.0% | -0.6% | -0.8 to -0.4 | -6.1% | -10.3 to -1.8 |
| 10+ | later | 5,381 | 561 | 5.6% | 5.1% | -0.4% | -1.0 to +0.2 | -2.9% | -14.6 to +9.7 |

Starters by position:

| position | period | lines | matches | said | landed | landed minus said | 95% | return at fair | 95% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| forwards | earlier | 11,732 | 3,686 | 21.7% | 10.6% | -11.1% | -11.8 to -10.6 | -12.9% | -19.2 to -6.4 |
| forwards | later | 1,657 | 548 | 23.9% | 12.4% | -11.5% | -13.2 to -9.8 | -9.1% | -24.6 to +7.6 |
| midfielders | earlier | 28,027 | 3,800 | 20.1% | 9.7% | -10.3% | -10.7 to -10.0 | -17.6% | -21.6 to -13.5 |
| midfielders | later | 4,133 | 561 | 21.5% | 10.4% | -11.1% | -12.1 to -10.1 | -16.0% | -26.6 to -5.0 |
| defenders | earlier | 24,430 | 3,790 | 13.4% | 4.4% | -9.0% | -9.3 to -8.7 | -47.1% | -51.1 to -43.2 |
| defenders | later | 3,625 | 561 | 13.1% | 4.3% | -8.8% | -9.5 to -8.1 | -47.7% | -56.7 to -37.0 |
| goalkeepers | earlier | 6,618 | 3,678 | 6.4% | 0.4% | -6.0% | -6.2 to -5.9 | -92.4% | -95.3 to -89.2 |
| goalkeepers | later | 981 | 547 | 6.6% | 0.5% | -6.1% | -6.6 to -5.5 | -90.2% | -97.8 to -80.6 |

### To score

| who and chance | period | lines | matches | said | landed | landed minus said | 95% | return at fair | 95% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| starters, every chance | earlier | 6,321 | 384 | 10.0% | 10.0% | +0.0% | -0.7 to +0.7 | -1.2% | -11.1 to +9.6 |
| starters, every chance | later | 10,317 | 561 | 10.0% | 10.1% | +0.1% | -0.4 to +0.6 | -13.9% | -20.1 to -6.7 |
| starters, ours 50%+ | earlier | 18 | 18 | 57.1% | 55.6% | -1.5% | -27.5 to +22.8 | +3.1% | -39.2 to +44.9 |
| starters, ours 50%+ | later | 32 | 32 | 52.3% | 65.6% | +13.3% | -2.8 to +29.4 | +25.0% | -6.4 to +56.1 |
| starters, under 50% | earlier | 6,303 | 383 | 9.9% | 9.9% | +0.0% | -0.7 to +0.7 | -1.2% | -11.8 to +9.5 |
| starters, under 50% | later | 10,285 | 561 | 9.9% | 9.9% | +0.0% | -0.5 to +0.5 | -14.0% | -20.3 to -6.8 |
| came on, every chance | earlier | 19,173 | 3,673 | 11.1% | 5.0% | -6.0% | -6.3 to -5.7 | -1.0% | -17.7 to +16.2 |
| came on, every chance | later | 2,924 | 546 | 11.9% | 5.5% | -6.3% | -7.1 to -5.5 | -16.3% | -49.3 to +36.0 |

Starters by fair price (one over our chance):

| fair price | period | lines | matches | said | landed | landed minus said | 95% | return at fair | 95% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1.5 to 2 | later | 32 | 32 | 52.3% | 65.6% | +13.3% | -2.8 to +29.4 | +25.0% | -6.4 to +56.1 |
| 2 to 3 | earlier | 276 | 185 | 39.8% | 38.4% | -1.4% | -6.9 to +4.3 | -3.9% | -17.5 to +10.3 |
| 2 to 3 | later | 400 | 281 | 39.1% | 39.2% | +0.1% | -4.9 to +4.9 | -0.5% | -13.7 to +12.3 |
| 3 to 5 | earlier | 700 | 325 | 25.8% | 24.0% | -1.8% | -4.9 to +1.3 | -7.6% | -20.3 to +4.6 |
| 3 to 5 | later | 1,200 | 510 | 25.6% | 27.0% | +1.4% | -1.0 to +3.9 | +5.2% | -4.4 to +14.8 |
| 5 to 10 | earlier | 1,096 | 342 | 14.7% | 15.2% | +0.5% | -1.6 to +2.7 | +6.2% | -9.0 to +22.2 |
| 5 to 10 | later | 1,744 | 541 | 14.7% | 14.9% | +0.2% | -1.4 to +1.9 | +2.2% | -8.9 to +13.4 |
| 10+ | earlier | 4,231 | 380 | 4.1% | 4.3% | +0.3% | -0.4 to +0.9 | -1.9% | -16.5 to +13.3 |
| 10+ | later | 6,941 | 561 | 4.2% | 4.0% | -0.3% | -0.7 to +0.2 | -22.1% | -31.4 to -12.1 |

Starters by position:

| position | period | lines | matches | said | landed | landed minus said | 95% | return at fair | 95% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| forwards | earlier | 989 | 350 | 26.9% | 26.8% | -0.1% | -2.9 to +2.7 | +11.4% | -5.8 to +30.6 |
| forwards | later | 1,635 | 547 | 26.3% | 27.8% | +1.5% | -0.7 to +3.7 | +4.5% | -5.6 to +14.7 |
| midfielders | earlier | 2,470 | 370 | 11.1% | 10.2% | -0.9% | -2.0 to +0.3 | -12.0% | -25.0 to +1.3 |
| midfielders | later | 4,088 | 561 | 10.9% | 10.7% | -0.2% | -1.0 to +0.7 | -2.9% | -12.2 to +7.0 |
| defenders | earlier | 2,269 | 369 | 4.1% | 5.2% | +1.1% | +0.3 to +1.9 | +30.9% | +8.7 to +55.5 |
| defenders | later | 3,613 | 561 | 4.2% | 4.0% | -0.2% | -0.8 to +0.4 | -11.2% | -25.3 to +3.6 |
| goalkeepers | earlier | 593 | 338 | 0.3% | 0.0% | -0.3% | -0.3 to -0.3 | -100.0% | -100.0 to -100.0 |
| goalkeepers | later | 981 | 547 | 0.3% | 0.0% | -0.3% | -0.3 to -0.3 | -100.0% | -100.0 to -100.0 |

### Shots on target 2+

| who and chance | period | lines | matches | said | landed | landed minus said | 95% | return at fair | 95% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| starters, every chance | earlier | 6,407 | 389 | 7.4% | 7.1% | -0.3% | -0.9 to +0.3 | -4.7% | -22.7 to +15.9 |
| starters, every chance | later | 10,385 | 561 | 7.2% | 7.5% | +0.3% | -0.1 to +0.8 | -9.5% | -21.0 to +2.9 |
| starters, ours 50%+ | earlier | 32 | 32 | 58.6% | 56.2% | -2.3% | -20.3 to +14.6 | -3.3% | -34.4 to +25.8 |
| starters, ours 50%+ | later | 63 | 55 | 57.5% | 61.9% | +4.4% | -7.0 to +16.1 | +7.3% | -13.0 to +27.9 |
| starters, under 50% | earlier | 6,375 | 388 | 7.1% | 6.9% | -0.3% | -0.9 to +0.3 | -4.7% | -22.4 to +17.2 |
| starters, under 50% | later | 10,322 | 561 | 6.9% | 7.2% | +0.3% | -0.1 to +0.7 | -9.6% | -21.1 to +3.0 |
| came on, every chance | earlier | 21,235 | 3,698 | 20.5% | 2.0% | -18.4% | -18.7 to -18.2 | -91.3% | -92.3 to -90.3 |
| came on, every chance | later | 3,269 | 558 | 21.0% | 2.7% | -18.3% | -19.0 to -17.6 | -89.1% | -91.5 to -86.4 |

Starters by fair price (one over our chance):

| fair price | period | lines | matches | said | landed | landed minus said | 95% | return at fair | 95% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1.5 to 2 | earlier | 28 | 28 | 56.3% | 57.1% | +0.8% | -17.4 to +18.7 | +1.0% | -32.0 to +33.1 |
| 1.5 to 2 | later | 55 | 47 | 55.8% | 60.0% | +4.2% | -8.5 to +16.7 | +7.3% | -16.2 to +30.0 |
| 2 to 3 | earlier | 173 | 136 | 39.2% | 37.0% | -2.2% | -9.1 to +5.5 | -5.8% | -24.1 to +14.5 |
| 2 to 3 | later | 241 | 198 | 39.7% | 36.1% | -3.6% | -9.9 to +2.8 | -8.5% | -24.6 to +8.3 |
| 3 to 5 | earlier | 556 | 307 | 25.1% | 22.5% | -2.6% | -6.0 to +0.9 | -10.9% | -24.5 to +3.3 |
| 3 to 5 | later | 884 | 453 | 25.1% | 26.0% | +0.9% | -2.0 to +3.9 | +3.6% | -7.5 to +15.8 |
| 5 to 10 | earlier | 927 | 358 | 14.8% | 15.4% | +0.7% | -1.6 to +2.9 | +4.0% | -11.4 to +19.7 |
| 5 to 10 | later | 1,488 | 537 | 14.7% | 16.1% | +1.4% | -0.5 to +3.4 | +9.7% | -3.2 to +23.8 |
| 10+ | earlier | 4,719 | 360 | 2.4% | 2.2% | -0.1% | -0.5 to +0.3 | -5.6% | -28.3 to +23.0 |
| 10+ | later | 7,709 | 561 | 2.3% | 2.4% | +0.1% | -0.2 to +0.5 | -14.8% | -29.7 to +2.6 |

Starters by position:

| position | period | lines | matches | said | landed | landed minus said | 95% | return at fair | 95% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| forwards | earlier | 1,018 | 352 | 22.9% | 23.2% | +0.3% | -2.0 to +2.9 | +3.9% | -8.6 to +18.9 |
| forwards | later | 1,654 | 548 | 23.0% | 23.7% | +0.7% | -1.1 to +2.7 | +4.8% | -5.4 to +15.7 |
| midfielders | earlier | 2,511 | 372 | 8.0% | 7.5% | -0.5% | -1.4 to +0.6 | -11.7% | -28.5 to +6.9 |
| midfielders | later | 4,129 | 561 | 7.7% | 8.3% | +0.5% | -0.2 to +1.4 | +3.2% | -11.2 to +19.3 |
| defenders | earlier | 2,276 | 372 | 1.7% | 1.4% | -0.3% | -0.8 to +0.2 | +24.5% | -24.8 to +79.8 |
| defenders | later | 3,622 | 561 | 1.4% | 1.4% | -0.1% | -0.4 to +0.3 | -5.9% | -32.2 to +25.2 |
| goalkeepers | earlier | 602 | 346 | 0.2% | 0.0% | -0.2% | -0.4 to -0.2 | -100.0% | -100.0 to -100.0 |
| goalkeepers | later | 980 | 547 | 0.1% | 0.0% | -0.1% | -0.1 to -0.1 | -100.0% | -100.0 to -100.0 |

### The rule for assists 1+

Starters at 50% or more, landed minus said: the 95% interval must lie wholly below zero on the earlier months and on the later months.

| assists 1+, starters 50%+ | period | lines | matches | said | landed | landed minus said | 95% | return at fair | 95% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| assists 1+ | earlier | 264 | 249 | 52.9% | 22.3% | -30.6% | -35.7 to -25.1 | -58.1% | -67.9 to -48.1 |
| assists 1+ | later | 59 | 56 | 53.2% | 20.3% | -32.9% | -42.8 to -23.0 | -62.9% | -80.9 to -44.3 |

Holds: yes.

Where the gap comes from, starters on assists 1+: their own record (hits over their last ten) says 7.4%, model.price_player says 16.9%, and 7.2% landed.

### Evidence for a follow-up: a Platt map on assists 1+

Fitted on the earlier months' starters: logit(chance) = -1.865 +0.392 x logit(ours). On the later months (10,396 starter lines): ours said 17.6%, mapped 7.3%, landed 7.6%; log loss 0.3217 as now, 0.2636 mapped. Mapped, 0 later lines would be at 50% or more. Not wired in here.

| assists 1+, starters, mapped | period | lines | matches | said | landed | landed minus said | 95% | return at fair | 95% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| every chance | later | 10,396 | 561 | 7.3% | 7.6% | +0.3% | -0.2 to +0.8 | +4.3% | -3.4 to +12.4 |
