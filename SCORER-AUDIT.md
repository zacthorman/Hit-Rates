# Scorer audit: verdict

Branch `scorer-audit`, 22 October 2026. Everything below the verdict is written by `python -B scorer_audit.py test` and is regenerated on every run; this section is not.

## The short version

**The page's main number for these legs is honest. Two of the numbers around it were not, for the same reason, and both are now fixed.**

1. **fmodel, the Players tab's chance for any starter it covers, is calibrated.** On 25,280 starters since 1 July (none of them seen in training) its average is within about a point of what landed on every leg, and within two points for defenders, midfielders and forwards, at every minutes expectation and in almost every big league. On to score and shots on target it is within a point or two in every band with 300+ rows. On shots it runs a little cautious in the middle bands (shots 3+ at 30% to 40%: said 34.7%, landed 39.2%; shots 1+ at 40% to 50%: 45.0% for 48.0%), never too bold. It beats every other source on every leg. Six kinds of calibration fix were tried on it (Platt, and Platt with pre-match minutes, rotation, penalty, position and thin-record terms); none beat leaving it alone on August, so it is unchanged. The replay reproduces the original backtest exactly (shots 1+ log loss 0.5282, to score 0.2824), so these are the page's own numbers.

2. **tonight.html's "With the record" chance was too high on every line except shots 1+.** It averages fmodel with the record shrunk towards 50% by six phantom hits and six phantom misses. The shrink was fitted on legs the page picked, which are nearly all 60% to 80% lines, so pulling to 50% suited them. For a low line it adds points out of nothing: on to score the page said 23.8% where 10.7% landed (fmodel alone: 10.5%), shots on target 2+ said 15.9% for 9.1%, shots 3+ 20.4% for 15.3%. To score was the worst, because tonight.html did not use fmodel for it at all and, where Betfair had no price, showed the shrunk record alone. **Fixed:** the weight on fmodel is now chosen per line on earlier months and only kept where it beat the half and half on every later month. It is 1.0 for to score, shots 3+ and both shots on target lines and 0.9 for shots 2+; shots 1+ stays half and half, because in August the fitted weight lost on Brier by 0.0002.

3. **The Players tab's own chance, used where fmodel has none, was too high on every line but shots 1+.** pricePlayer's player calibration squeezes every log-odds to 45% of its size, towards 50%, again fitted on picked bets that said 75%. Shots on target 2+ said 18.8% and landed 7.4%; shots 1+ said 50.0% and landed 54.0%. **Fixed:** a Platt map per line (slopes 1.2 to 1.7, undoing most of the squeeze), chosen on August and beating the page on September and October by large margins (shots on target 2+ log loss 0.276 to 0.213 in September). To score on this path (scoreCase) is close to calibrated already and its map lost on Brier in August, so it is unchanged.

## Where the page was over or underconfident, and why

| What | Direction | Size | Why |
|---|---|---|---|
| tonight.html, to score | over | said 23.8%, landed 10.7% | shrunk record alone; 50% is the wrong place to shrink a 10% bet to |
| tonight.html, shots 2+, 3+, on target 1+, 2+ | over | 2 to 7 points | half of the chance is that shrunk record |
| tonight.html, shots 1+ | under for forwards | forwards said 76.5%, landed 84.8% | the same shrink pulls a 90% record down |
| Players tab fallback, all lines but shots 1+ | over | up to 11 points | player calibration squeezes towards 50% |
| Players tab fallback, shots 1+ | under | 4 points | the same squeeze, from the other side |
| fmodel | slightly under on shots | 1 to 2 points on average, up to 4 in the middle bands, 2 to 3 in Bundesliga and Serie A | a Platt map helped shots in September and October but lost in August, so it did not qualify; left alone |
| fmodel, shots on target 1+ in the Championship | slightly over | 2.5 points | one league, 2,422 rows; not enough to act on |

**Minutes risk.** About one start in five ends before 70 minutes, and those are where the misses are: a starter off between 45 and 69 minutes landed shots 1+ 56% of the time where fmodel said 65%, and the 1% off before half-time landed 24%. But it is priced: fmodel is within 2 points for players whose recent minutes are low and for rotation players, because it was trained on every start, early substitutions included. No pre-match minutes term improved it. The shrunk record has no idea about minutes, and tonight.html's chance was 10 points too high on shots on target 2+ for rotation players.

**Penalties.** A penalty taker (marked where his last 38 games show a one-shot game worth a penalty's xG, which catches only some takers) scored 20.4% of the time where fmodel said 19.2%: slightly under, within noise, and a penalty term did not help out of sample. tonight.html had them 12 points too high, like everyone else.

**Substitutes.** fmodel scores starters only. A player who comes off the bench plays a median 21 minutes; on the record tonight.html shows for anyone with ten full appearances he lands shots 1+ 36% of the time where his record says 63%, and scores 5.7% where it says 12.8%. Paddy Power voids a non-starter's bet, so there it costs nothing. **A book that lets the bet stand once he comes on is settling it at those rates, and tonight.html lists legs for players whether or not they are in the XI.** Not changed here: it is a question of which legs to show, not of calibration.

**Small samples.** fmodel is calibrated even on three to five appearances. The shrunk record is worst there (to score at 3 to 5 appearances: said 40%, landed 8%), but tonight.html needs ten, so the page never showed those.

**The live record agrees, for what it covers.** The 185 settled football player legs the page picked said 70.7% and landed 70.3%. They are almost all shots 1+ and 2+ at 60% to 80%, the lines the shrink was fitted on and where it does least harm. The faults above are on the lines the picks rarely reach.

## What changed

- `context.py`: tonight.html's player chance is `w x fmodel + (1 - w) x shrunk record`, with `w` per line from `fmodel/tonight_blend.json` (0.5 where the file has no entry, as before), and to score now gets fmodel. Exchange-priced legs and unders are untouched.
- `report.py`: where fmodel has no chance, the Players tab's football shots and shots on target chance goes through the map in `fmodel/site_calib.json`, injected at render (`siteCalibrated`, called from `withModel`, so profiles, strongest lines, Paddy Power lines and custom lines all get it).
- `tonight.py`: says "The record adds nothing on this line" instead of repeating the model's number as "With the record", and shows no opponent factor for to score, which has no game-state fit.
- `fmodel_live.py`: `features()` takes `emit`, so a replay of finished matches goes through the live feature code. Default behaviour is unchanged (tested).
- `scorer_audit.py` and `tests/test_scorer_audit.py` (17 tests: the replay hook against the live path, the vectorised tree scorer against fmodel's own, the scoring maths, the context blend, the page's JavaScript run in node). Every test file passes, and `verify.py` still finds model.py and report.py in agreement.

Nothing was published and no report was rebuilt. The changes reach the pages at the next render.

## Honest limits

- **Line-ups.** The cache holds the real XI, so this measures the page with the right XI. When the predicted XI is wrong, fmodel's chance belongs to a player who may not start; that cannot be replayed from the cache.
- **Exchange prices.** Where Betfair prices a leg the page anchors to the market (pExchange). There are no historical prices in the cache, so that path is not scored.
- **The Players tab fallback** is replayed with no team-projection adjustment (as `fmodel/training/baseline.py` did), and its map was fitted on starters. It is the right conditional for a bet void unless he starts; a player who comes on is still overrated by it.
- **The record window** is his last 38 appearances; the page uses his appearances in the team's last 38 games. Close, not identical.
- **The shrink of 6** is fitted on best_bets.json, which overlaps September and October, and the player calibration constants were fitted on data to 30 August. Both flatter the page's existing numbers in the windows, so the fixes' wins are if anything understated.
- **Four windows, one season.** July is training only, October stops on the 19th. The fixes held on every window, but that is three windows, not thirty. Rerun `scorer_audit.py build` and `test` as the cache grows: the test refits both files and drops any line whose fix stops holding.

## Rerunning

    python -B scorer_audit.py build   # about 20 minutes; replays cache/ into cache/scorer_audit.pkl
    python -B scorer_audit.py test    # a minute; rewrites the tables below, fmodel/tonight_blend.json, fmodel/site_calib.json
    python -B -m unittest tests.test_scorer_audit

<!-- tables below are written by scorer_audit.py test -->

# Scorer audit: anytime goalscorer, shots and shots on target

Generated 2026-10-22 21:12 UTC by `scorer_audit.py test`. Branch `scorer-audit`.

Every starter in every cached match from 1 July 2026 (when fmodel's training ended) to 19 October 2026, replayed with only what was known before kick-off: 1,332 matches, 25,280 starter rows, plus 12,548 substitute appearances. Months 2026-07, 2026-08, 2026-09, 2026-10 are the walk-forward windows.

## What the page shows for each leg

| Source | What it is | Where the page uses it |
|---|---|---|
| record | hits over his appearances of 45+ minutes in the last 38 | the 'k/n' beside every leg |
| shrunk | record pulled to 50% by 6 phantom hits and misses (weekend.player_shrink) | tonight.html rank (pShrunk) |
| site | model.price_player per 90 x minutes, calibrated; for to score the profile's scoreCase (60% xG, 40% goals per 90) | Players tab where fmodel has no chance |
| gs | gs_backtest.py's game-state model, refitted before each month on earlier 60+ minute rows | 'Backtested model X%' where fmodel has none |
| fmodel | the backtested player model (fmodel/) | Players tab, Paddy Power value, every starter it covers |
| tonight | shrunk and fmodel averaged (shots, shots on target); shrunk alone for goals | tonight.html 'With the record' and its ranking |

Log loss and Brier: lower is better. Raw records of 0/n or n/n are clipped to 0.5% and 99.5% for log loss. ECE is the n-weighted gap between said and landed across ten-point bands. Shots and shots on target are only scored where the match carries player shot numbers.

## 1. Head to head, same rows

Starters with a record of 10+ appearances (the floor tonight.html uses) and, for shots, the inputs the game-state model needs, so every source is scored on identical rows.

| Leg | n | landed | metric | record | shrunk | site | gs | fmodel | tonight |
|---|---|---|---|---|---|---|---|---|---|
| Anytime goalscorer | 20371 | 10.7% | log loss | 0.3078 | 0.3685 | 0.2969 | n/a | 0.2871 | 0.3685 |
|  |  |  | Brier | 0.0872 | 0.1047 | 0.0859 | n/a | 0.0840 | 0.1047 |
|  |  |  | ECE | 0.0220 | 0.1311 | 0.0129 | n/a | 0.0035 | 0.1311 |
| Shots 1+ | 15980 | 59.8% | log loss | 0.6020 | 0.5999 | 0.6080 | 0.5971 | 0.5818 | 0.5855 |
|  |  |  | Brier | 0.2055 | 0.2064 | 0.2096 | 0.2060 | 0.1995 | 0.2005 |
|  |  |  | ECE | 0.0314 | 0.0404 | 0.0720 | 0.0313 | 0.0144 | 0.0277 |
| Shots 2+ | 15980 | 31.5% | log loss | 0.5295 | 0.5364 | 0.5474 | 0.5207 | 0.5056 | 0.5129 |
|  |  |  | Brier | 0.1723 | 0.1775 | 0.1822 | 0.1720 | 0.1669 | 0.1687 |
|  |  |  | ECE | 0.0238 | 0.0670 | 0.1009 | 0.0202 | 0.0133 | 0.0381 |
| Shots 3+ | 15980 | 15.3% | log loss | 0.3551 | 0.4052 | 0.3985 | 0.3406 | 0.3325 | 0.3581 |
|  |  |  | Brier | 0.1073 | 0.1212 | 0.1210 | 0.1053 | 0.1033 | 0.1073 |
|  |  |  | ECE | 0.0200 | 0.1113 | 0.1166 | 0.0097 | 0.0091 | 0.0528 |
| Shots on target 1+ | 14079 | 31.7% | log loss | 0.5663 | 0.5757 | 0.5905 | 0.5678 | 0.5446 | 0.5536 |
|  |  |  | Brier | 0.1903 | 0.1946 | 0.2008 | 0.1916 | 0.1822 | 0.1854 |
|  |  |  | ECE | 0.0303 | 0.0696 | 0.0963 | 0.0216 | 0.0050 | 0.0383 |
| Shots on target 2+ | 14079 | 9.1% | log loss | 0.2676 | 0.3428 | 0.3286 | 0.2612 | 0.2486 | 0.2838 |
|  |  |  | Brier | 0.0748 | 0.0940 | 0.0921 | 0.0743 | 0.0720 | 0.0773 |
|  |  |  | ECE | 0.0173 | 0.1367 | 0.1308 | 0.0043 | 0.0034 | 0.0684 |

### fmodel on every starter it covers

The Players tab shows fmodel for any starter with three 45-minute appearances, not only those with ten.

| Leg | n | landed | said | log loss | Brier | ECE | base-rate log loss |
|---|---|---|---|---|---|---|---|
| Anytime goalscorer | 25,280 | 10.4% | 10.4% | 0.2824 | 0.0823 | 0.0030 | 0.3336 |
| Shots 1+ | 25,258 | 54.0% | 53.0% | 0.5282 | 0.1806 | 0.0121 | 0.6900 |
| Shots 2+ | 25,258 | 28.4% | 27.3% | 0.4569 | 0.1507 | 0.0127 | 0.5965 |
| Shots 3+ | 25,258 | 13.8% | 13.1% | 0.3041 | 0.0942 | 0.0077 | 0.4021 |
| Shots on target 1+ | 25,230 | 26.6% | 26.7% | 0.4734 | 0.1566 | 0.0049 | 0.5790 |
| Shots on target 2+ | 25,230 | 7.4% | 7.4% | 0.2083 | 0.0594 | 0.0030 | 0.2648 |

## 2. Calibration by chance band

Said / landed (n) per band, on the head-to-head rows. A band where landed is below said is overconfident.

### Anytime goalscorer

| Band | fmodel | tonight | shrunk | record | site |
|---|---|---|---|---|---|
| 0%-10% | 4.3% / 4.4% (13236) |  |  | 3.0% / 4.7% (12600) | 3.6% / 4.7% (12850) |
| 10%-20% | 14.6% / 14.8% (3678) | 15.8% / 4.2% (8192) | 15.8% / 4.2% (8192) | 14.3% / 13.6% (3674) | 14.4% / 13.9% (3990) |
| 20%-30% | 24.5% / 23.9% (2029) | 24.2% / 9.4% (7656) | 24.2% / 9.4% (7656) | 23.9% / 20.2% (2176) | 24.6% / 22.8% (1886) |
| 30%-40% | 34.1% / 35.5% (1001) | 33.9% / 20.0% (3161) | 33.9% / 20.0% (3161) | 34.4% / 30.2% (1080) | 34.2% / 30.0% (1015) |
| 40%-50% | 43.9% / 46.6% (365) | 43.6% / 32.8% (1067) | 43.6% / 32.8% (1067) | 43.5% / 34.8% (546) | 44.4% / 41.4% (442) |
| 50%-60% | 52.9% / 73.8% (61) | 52.9% / 41.0% (234) | 52.9% / 41.0% (234) | 52.2% / 36.6% (183) | 53.8% / 52.5% (162) |
| 60%-70% |  | 63.6% / 67.2% (58) | 63.6% / 67.2% (58) | 64.2% / 60.5% (86) |  |

### Shots 1+

| Band | fmodel | tonight | shrunk | record | site |
|---|---|---|---|---|---|
| 0%-10% |  |  |  | 7.2% / 26.8% (71) |  |
| 10%-20% |  |  |  | 15.9% / 27.3% (491) |  |
| 20%-30% | 26.7% / 27.4% (1179) | 27.1% / 25.7% (674) | 26.5% / 24.3% (510) | 25.3% / 32.6% (1339) | 26.9% / 25.3% (150) |
| 30%-40% | 35.2% / 37.2% (2626) | 35.4% / 35.0% (2527) | 35.4% / 35.9% (2226) | 34.9% / 41.1% (1858) | 36.6% / 31.0% (1412) |
| 40%-50% | 45.0% / 48.1% (2818) | 44.9% / 45.0% (3208) | 44.7% / 44.0% (3219) | 44.2% / 44.9% (2208) | 45.4% / 41.7% (4368) |
| 50%-60% | 54.7% / 55.2% (2104) | 54.8% / 56.4% (2555) | 54.4% / 56.5% (3250) | 54.2% / 54.5% (2236) | 54.8% / 59.1% (4323) |
| 60%-70% | 65.0% / 64.7% (1751) | 65.0% / 68.9% (2259) | 64.8% / 72.2% (2936) | 64.8% / 63.4% (1971) | 64.8% / 77.7% (3223) |
| 70%-80% | 75.3% / 76.9% (1961) | 75.2% / 81.8% (2611) | 74.5% / 82.6% (2737) | 74.7% / 74.6% (1804) | 74.1% / 87.0% (2102) |
| 80%-90% | 85.1% / 86.2% (2611) | 84.1% / 89.6% (2097) | 82.9% / 91.3% (1090) | 84.4% / 81.5% (2152) | 82.8% / 93.1% (375) |
| 90%-100% | 92.0% / 92.1% (917) | 90.5% / 100.0% (45) |  | 94.7% / 88.9% (1850) |  |

### Shots 2+

| Band | fmodel | tonight | shrunk | record | site |
|---|---|---|---|---|---|
| 0%-10% | 7.5% / 7.6% (3032) | 9.3% / 3.1% (130) |  | 4.6% / 10.0% (3653) | 7.8% / 5.3% (150) |
| 10%-20% | 14.2% / 15.9% (4380) | 15.5% / 10.2% (4970) | 16.9% / 8.5% (1972) | 14.6% / 15.8% (3154) | 16.1% / 6.2% (1203) |
| 20%-30% | 24.6% / 25.8% (2065) | 24.4% / 20.0% (3483) | 24.7% / 14.7% (4715) | 24.3% / 24.3% (2407) | 25.7% / 11.3% (3453) |
| 30%-40% | 34.9% / 37.5% (1495) | 34.7% / 32.4% (2104) | 34.3% / 25.9% (3305) | 34.5% / 35.1% (1634) | 34.9% / 21.0% (4052) |
| 40%-50% | 45.0% / 46.1% (1354) | 44.9% / 45.2% (1593) | 44.2% / 41.0% (2093) | 44.0% / 44.5% (1237) | 44.7% / 38.3% (3305) |
| 50%-60% | 55.0% / 56.9% (1471) | 55.2% / 57.8% (1711) | 54.6% / 56.3% (1942) | 54.4% / 55.0% (1275) | 55.0% / 59.9% (2589) |
| 60%-70% | 64.8% / 65.7% (1287) | 64.3% / 67.7% (1380) | 64.1% / 66.2% (1446) | 64.6% / 62.3% (1320) | 63.7% / 69.8% (1059) |
| 70%-80% | 74.3% / 75.4% (720) | 74.0% / 79.2% (523) | 73.9% / 78.2% (427) | 74.0% / 67.0% (807) | 73.0% / 87.8% (148) |
| 80%-90% | 83.1% / 90.1% (172) | 83.0% / 94.2% (86) | 82.2% / 88.8% (80) | 83.9% / 77.6% (384) |  |
| 90%-100% |  |  |  | 93.5% / 84.4% (109) |  |

### Shots 3+

| Band | fmodel | tonight | shrunk | record | site |
|---|---|---|---|---|---|
| 0%-10% | 3.9% / 3.9% (9069) | 8.6% / 2.6% (3550) |  | 2.7% / 4.6% (8860) | 6.9% / 1.6% (1669) |
| 10%-20% | 14.5% / 16.3% (2396) | 13.9% / 6.1% (6565) | 15.9% / 4.1% (5879) | 14.1% / 14.0% (2504) | 15.3% / 3.1% (4345) |
| 20%-30% | 24.9% / 25.9% (1770) | 24.5% / 20.6% (2292) | 24.1% / 9.6% (5286) | 24.5% / 26.6% (1563) | 24.8% / 8.6% (3784) |
| 30%-40% | 34.7% / 38.6% (1330) | 35.0% / 34.2% (1860) | 34.5% / 26.5% (2363) | 34.5% / 35.5% (1266) | 34.6% / 20.2% (2853) |
| 40%-50% | 44.5% / 46.0% (837) | 44.4% / 44.2% (1137) | 43.9% / 38.5% (1538) | 43.6% / 39.2% (873) | 44.7% / 36.7% (2418) |
| 50%-60% | 54.1% / 53.6% (422) | 54.2% / 54.3% (429) | 54.0% / 48.7% (690) | 53.9% / 46.5% (518) | 53.7% / 51.0% (775) |
| 60%-70% | 64.0% / 71.3% (122) | 64.0% / 71.7% (113) | 63.3% / 60.1% (168) | 63.7% / 57.1% (280) | 63.0% / 68.1% (116) |
| 70%-80% | 73.4% / 90.9% (33) | 75.4% / 78.1% (32) | 73.6% / 72.5% (40) | 74.1% / 63.6% (66) |  |
| 80%-90% |  |  |  | 83.5% / 66.7% (33) |  |

### Shots on target 1+

| Band | fmodel | tonight | shrunk | record | site |
|---|---|---|---|---|---|
| 0%-10% | 9.0% / 9.1% (508) |  |  | 7.0% / 13.4% (1258) |  |
| 10%-20% | 15.0% / 15.1% (4807) | 17.3% / 12.6% (2374) | 17.9% / 12.9% (466) | 14.8% / 15.7% (3414) | 18.4% / 12.0% (125) |
| 20%-30% | 24.3% / 23.3% (2567) | 24.4% / 18.0% (4483) | 25.3% / 15.7% (4185) | 24.2% / 22.8% (2807) | 26.4% / 14.1% (2169) |
| 30%-40% | 34.9% / 35.0% (1579) | 34.6% / 31.0% (2278) | 34.2% / 24.6% (3624) | 34.5% / 32.7% (1750) | 35.0% / 19.3% (4950) |
| 40%-50% | 45.3% / 45.4% (1785) | 45.2% / 44.0% (1973) | 44.4% / 40.2% (2512) | 44.1% / 44.9% (1558) | 45.0% / 37.7% (3665) |
| 50%-60% | 54.7% / 56.2% (1675) | 54.5% / 54.4% (1836) | 54.2% / 50.4% (2037) | 54.0% / 48.7% (1443) | 54.3% / 53.9% (2501) |
| 60%-70% | 64.5% / 63.9% (815) | 64.2% / 65.8% (886) | 64.0% / 62.0% (985) | 64.2% / 56.8% (1018) | 63.1% / 66.6% (616) |
| 70%-80% | 73.6% / 75.9% (315) | 73.3% / 79.3% (232) | 73.2% / 74.6% (232) | 73.9% / 67.2% (582) | 73.6% / 86.3% (51) |
| 80%-90% |  |  | 81.1% / 76.3% (38) | 82.9% / 65.8% (199) |  |
| 90%-100% |  |  |  | 92.4% / 74.0% (50) |  |

### Shots on target 2+

| Band | fmodel | tonight | shrunk | record | site |
|---|---|---|---|---|---|
| 0%-10% | 3.0% / 3.1% (9445) | 8.2% / 1.8% (4512) |  | 2.5% / 3.7% (9377) | 7.6% / 1.0% (2581) |
| 10%-20% | 14.7% / 15.3% (2534) | 13.8% / 5.8% (5889) | 15.7% / 2.8% (6301) | 14.3% / 13.4% (2294) | 15.0% / 2.9% (4184) |
| 20%-30% | 24.2% / 24.0% (1371) | 24.5% / 18.6% (2523) | 24.1% / 8.9% (5181) | 23.9% / 20.3% (1362) | 24.6% / 8.1% (3467) |
| 30%-40% | 34.2% / 31.3% (457) | 33.7% / 28.1% (800) | 33.9% / 21.4% (1920) | 33.8% / 30.9% (624) | 34.4% / 16.8% (2708) |
| 40%-50% | 43.9% / 40.9% (176) | 44.2% / 42.5% (280) | 43.6% / 31.9% (521) | 44.0% / 35.0% (266) | 43.8% / 33.7% (1015) |
| 50%-60% | 53.3% / 50.8% (63) | 53.6% / 51.0% (49) | 53.5% / 38.4% (125) | 53.8% / 40.8% (103) | 53.1% / 38.3% (107) |
| 60%-70% |  |  |  | 62.7% / 40.0% (35) |  |

## 3. By position

Gap is landed minus said, in points: negative means the page was too high.

| Leg | Group | n | fmodel said / landed | gap | tonight said / landed | gap | fmodel log loss |
|---|---|---|---|---|---|---|---|
| Anytime goalscorer | defender | 8,875 | 4.5% / 4.5% | -0.1 | 22.5% / 4.5% | -18.0 | 0.1791 |
| Anytime goalscorer | midfielder | 9,992 | 11.5% / 11.1% | -0.4 | 27.3% / 11.1% | -16.3 | 0.3260 |
| Anytime goalscorer | forward | 4,076 | 26.0% / 27.5% | +1.5 | 37.1% / 27.5% | -9.6 | 0.5595 |
| Shots 1+ | defender | 8,868 | 40.0% / 41.3% | +1.2 | 42.3% / 41.3% | -1.0 | 0.6511 |
| Shots 1+ | midfielder | 9,982 | 64.4% / 65.3% | +0.9 | 61.5% / 65.3% | +3.8 | 0.5900 |
| Shots 1+ | forward | 4,074 | 83.1% / 84.8% | +1.8 | 76.5% / 84.8% | +8.4 | 0.4010 |
| Shots 2+ | defender | 8,868 | 12.7% / 12.8% | +0.2 | 20.2% / 12.8% | -7.3 | 0.3618 |
| Shots 2+ | midfielder | 9,982 | 34.0% / 35.8% | +1.8 | 37.4% / 35.8% | -1.5 | 0.5782 |
| Shots 2+ | forward | 4,074 | 58.2% / 60.2% | +2.0 | 56.8% / 60.2% | +3.3 | 0.6255 |
| Shots 3+ | defender | 8,868 | 3.6% / 3.4% | -0.2 | 12.7% / 3.4% | -9.4 | 0.1398 |
| Shots 3+ | midfielder | 9,982 | 16.0% / 16.9% | +0.9 | 23.0% / 16.9% | -6.0 | 0.3949 |
| Shots 3+ | forward | 4,074 | 33.9% / 37.0% | +3.1 | 37.9% / 37.0% | -0.9 | 0.6107 |
| Shots on target 1+ | defender | 8,858 | 14.9% / 13.9% | -1.0 | 21.9% / 13.9% | -8.0 | 0.3954 |
| Shots on target 1+ | midfielder | 9,971 | 32.1% / 32.1% | -0.1 | 35.8% / 32.1% | -3.8 | 0.5776 |
| Shots on target 1+ | forward | 4,069 | 54.3% / 55.9% | +1.6 | 53.9% / 55.9% | +2.0 | 0.6563 |
| Shots on target 2+ | defender | 8,858 | 1.6% / 1.5% | -0.1 | 11.2% / 1.5% | -9.7 | 0.0758 |
| Shots on target 2+ | midfielder | 9,971 | 8.2% / 8.4% | +0.1 | 16.7% / 8.4% | -8.4 | 0.2557 |
| Shots on target 2+ | forward | 4,069 | 22.4% / 22.4% | +0.0 | 28.3% / 22.4% | -5.9 | 0.4973 |

## 4. By minutes expectation

Average minutes over his last five appearances (all appearances, cameos included), known before kick-off.

| Leg | Group | n | fmodel said / landed | gap | tonight said / landed | gap | fmodel log loss |
|---|---|---|---|---|---|---|---|
| Anytime goalscorer | under 60 | 6,061 | 13.0% / 13.3% | +0.3 | 30.4% / 13.3% | -17.1 | 0.3526 |
| Anytime goalscorer | 60 to 74 | 6,040 | 11.8% / 12.0% | +0.2 | 27.7% / 12.0% | -15.7 | 0.3288 |
| Anytime goalscorer | 75 to 84 | 4,974 | 11.2% / 11.1% | -0.1 | 25.9% / 11.1% | -14.8 | 0.2920 |
| Anytime goalscorer | 85 plus | 8,205 | 6.8% / 6.6% | -0.2 | 22.8% / 6.6% | -16.2 | 0.1906 |
| Shots 1+ | under 60 | 6,050 | 63.2% / 64.5% | +1.3 | 60.1% / 64.5% | +4.4 | 0.5715 |
| Shots 1+ | 60 to 74 | 6,037 | 59.6% / 60.2% | +0.6 | 57.9% / 60.2% | +2.3 | 0.5747 |
| Shots 1+ | 75 to 84 | 4,970 | 56.7% / 57.2% | +0.6 | 55.5% / 57.2% | +1.8 | 0.5523 |
| Shots 1+ | 85 plus | 8,201 | 38.3% / 39.7% | +1.5 | 40.7% / 39.7% | -1.0 | 0.4473 |
| Shots 2+ | under 60 | 6,050 | 34.2% / 35.5% | +1.3 | 37.9% / 35.5% | -2.4 | 0.5570 |
| Shots 2+ | 60 to 74 | 6,037 | 31.4% / 33.0% | +1.7 | 35.3% / 33.0% | -2.3 | 0.5148 |
| Shots 2+ | 75 to 84 | 4,970 | 29.7% / 29.9% | +0.3 | 33.5% / 29.9% | -3.6 | 0.4657 |
| Shots 2+ | 85 plus | 8,201 | 17.8% / 18.8% | +1.0 | 23.9% / 18.8% | -5.2 | 0.3350 |
| Shots 3+ | under 60 | 6,050 | 16.6% / 17.1% | +0.5 | 24.4% / 17.1% | -7.3 | 0.3830 |
| Shots 3+ | 60 to 74 | 6,037 | 15.1% / 16.3% | +1.2 | 22.4% / 16.3% | -6.1 | 0.3579 |
| Shots 3+ | 75 to 84 | 4,970 | 14.4% / 15.9% | +1.4 | 21.2% / 15.9% | -5.3 | 0.3285 |
| Shots 3+ | 85 plus | 8,201 | 8.1% / 8.4% | +0.2 | 15.9% / 8.4% | -7.5 | 0.1916 |
| Shots on target 1+ | under 60 | 6,044 | 33.0% / 32.6% | -0.4 | 37.0% / 32.6% | -4.4 | 0.5612 |
| Shots on target 1+ | 60 to 74 | 6,030 | 30.6% / 31.4% | +0.8 | 34.7% / 31.4% | -3.3 | 0.5432 |
| Shots on target 1+ | 75 to 84 | 4,964 | 28.8% / 28.0% | -0.9 | 32.9% / 28.0% | -4.9 | 0.4925 |
| Shots on target 1+ | 85 plus | 8,192 | 17.9% / 17.7% | -0.2 | 24.0% / 17.7% | -6.3 | 0.3456 |
| Shots on target 2+ | under 60 | 6,044 | 9.5% / 9.4% | -0.1 | 19.0% / 9.4% | -9.5 | 0.2702 |
| Shots on target 2+ | 60 to 74 | 6,030 | 8.5% / 8.8% | +0.3 | 17.1% / 8.8% | -8.3 | 0.2491 |
| Shots on target 2+ | 75 to 84 | 4,964 | 8.1% / 8.1% | +0.1 | 16.0% / 8.1% | -7.8 | 0.2170 |
| Shots on target 2+ | 85 plus | 8,192 | 4.7% / 4.6% | -0.1 | 12.9% / 4.6% | -8.4 | 0.1275 |

## 5. By league

Leagues with 600+ starter rows since July.

| Leg | Group | n | fmodel said / landed | gap | tonight said / landed | gap | fmodel log loss |
|---|---|---|---|---|---|---|---|
| Anytime goalscorer | MLS | 4,427 | 11.1% / 10.8% | -0.3 | 24.8% / 10.8% | -14.0 | 0.2789 |
| Anytime goalscorer | Championship | 2,422 | 9.3% / 9.3% | +0.0 | 24.6% / 9.3% | -15.3 | 0.2707 |
| Anytime goalscorer | Campeonato Brasileiro Série A | 2,378 | 9.4% / 8.8% | -0.6 | 25.9% / 8.8% | -17.1 | 0.2618 |
| Anytime goalscorer | LaLiga | 1,756 | 9.3% / 9.9% | +0.5 | 23.9% / 9.9% | -14.1 | 0.2650 |
| Anytime goalscorer | UEFA Nations League | 1,476 | 9.1% / 9.1% | +0.0 | 28.2% / 9.1% | -19.0 | 0.2583 |
| Anytime goalscorer | Premier League | 1,377 | 9.8% / 9.8% | +0.0 | 22.8% / 9.8% | -13.0 | 0.2714 |
| Anytime goalscorer | Serie A | 1,350 | 9.4% / 8.7% | -0.7 | 23.8% / 8.7% | -15.1 | 0.2556 |
| Anytime goalscorer | UEFA Champions League | 1,307 | 11.8% / 12.4% | +0.6 | 27.7% / 12.4% | -15.3 | 0.3179 |
| Anytime goalscorer | Ligue 1 | 1,102 | 9.6% / 9.8% | +0.2 | 25.9% / 9.8% | -16.1 | 0.2761 |
| Anytime goalscorer | Bundesliga | 897 | 11.0% / 11.0% | -0.0 | 25.1% / 11.0% | -14.1 | 0.2912 |
| Shots 1+ | MLS | 4,427 | 51.4% / 51.2% | -0.2 | 50.8% / 51.2% | +0.5 | 0.5174 |
| Shots 1+ | Championship | 2,422 | 53.4% / 53.6% | +0.2 | 52.4% / 53.6% | +1.2 | 0.5474 |
| Shots 1+ | Campeonato Brasileiro Série A | 2,378 | 53.6% / 55.8% | +2.2 | 53.0% / 55.8% | +2.9 | 0.5376 |
| Shots 1+ | LaLiga | 1,756 | 51.1% / 50.5% | -0.7 | 50.9% / 50.5% | -0.4 | 0.5136 |
| Shots 1+ | UEFA Nations League | 1,476 | 52.0% / 53.9% | +2.0 | 52.0% / 53.9% | +1.9 | 0.5317 |
| Shots 1+ | Premier League | 1,377 | 53.5% / 55.0% | +1.5 | 53.1% / 55.0% | +1.9 | 0.5362 |
| Shots 1+ | Serie A | 1,350 | 52.4% / 54.7% | +2.3 | 52.1% / 54.7% | +2.6 | 0.5378 |
| Shots 1+ | UEFA Champions League | 1,307 | 53.6% / 55.2% | +1.5 | 54.0% / 55.2% | +1.2 | 0.5094 |
| Shots 1+ | Ligue 1 | 1,102 | 52.2% / 52.3% | +0.0 | 51.9% / 52.3% | +0.4 | 0.5425 |
| Shots 1+ | Bundesliga | 897 | 53.9% / 56.5% | +2.6 | 53.2% / 56.5% | +3.4 | 0.5390 |
| Shots on target 1+ | MLS | 4,416 | 26.6% / 26.0% | -0.6 | 30.6% / 26.0% | -4.6 | 0.4424 |
| Shots on target 1+ | Championship | 2,422 | 26.3% / 23.8% | -2.5 | 30.3% / 23.8% | -6.5 | 0.4637 |
| Shots on target 1+ | Campeonato Brasileiro Série A | 2,378 | 26.5% / 27.1% | +0.6 | 31.1% / 27.1% | -4.0 | 0.4971 |
| Shots on target 1+ | LaLiga | 1,756 | 25.5% / 25.1% | -0.4 | 29.8% / 25.1% | -4.7 | 0.4559 |
| Shots on target 1+ | UEFA Nations League | 1,476 | 25.7% / 25.6% | -0.1 | 31.6% / 25.6% | -6.0 | 0.4756 |
| Shots on target 1+ | Premier League | 1,377 | 26.7% / 25.8% | -0.9 | 30.5% / 25.8% | -4.8 | 0.4773 |
| Shots on target 1+ | Serie A | 1,350 | 25.8% / 26.7% | +1.0 | 30.2% / 26.7% | -3.4 | 0.4855 |
| Shots on target 1+ | UEFA Champions League | 1,307 | 27.6% / 28.8% | +1.1 | 33.0% / 28.8% | -4.2 | 0.5031 |
| Shots on target 1+ | Ligue 1 | 1,102 | 25.7% / 27.1% | +1.5 | 30.7% / 27.1% | -3.6 | 0.4692 |
| Shots on target 1+ | Bundesliga | 897 | 27.3% / 27.6% | +0.4 | 31.3% / 27.6% | -3.6 | 0.4753 |

## 6. Where the misses come from

### Minutes risk, after the event

Not usable before kick-off: this splits the same rows by the minutes he actually played, to show how much of the miss rate is an early substitution or injury rather than a bad read of the player.

| Leg | Played | share of starts | fmodel said / landed | gap |
|---|---|---|---|---|
| Anytime goalscorer | under 45 | 1.1% | 10.6% / 4.0% | -6.6 |
| Anytime goalscorer | 45 to 69 | 18.1% | 13.6% / 8.8% | -4.8 |
| Anytime goalscorer | 70 to 84 | 16.9% | 14.3% / 15.4% | +1.1 |
| Anytime goalscorer | 85 plus | 63.9% | 8.4% / 9.6% | +1.2 |
| Shots 1+ | under 45 | 1.1% | 56.6% / 24.2% | -32.4 |
| Shots 1+ | 45 to 69 | 18.1% | 64.6% / 56.4% | -8.2 |
| Shots 1+ | 70 to 84 | 16.9% | 65.8% / 67.2% | +1.4 |
| Shots 1+ | 85 plus | 63.9% | 46.2% / 50.3% | +4.1 |
| Shots 2+ | under 45 | 1.1% | 28.7% / 6.2% | -22.5 |
| Shots 2+ | 45 to 69 | 18.1% | 35.9% / 26.3% | -9.7 |
| Shots 2+ | 70 to 84 | 16.9% | 37.4% / 38.1% | +0.7 |
| Shots 2+ | 85 plus | 63.9% | 22.2% / 26.8% | +4.6 |
| Shots 3+ | under 45 | 1.1% | 13.4% / 1.1% | -12.3 |
| Shots 3+ | 45 to 69 | 18.1% | 17.7% / 10.7% | -7.1 |
| Shots 3+ | 70 to 84 | 16.9% | 19.1% / 19.3% | +0.2 |
| Shots 3+ | 85 plus | 63.9% | 10.2% / 13.5% | +3.4 |
| Shots on target 1+ | under 45 | 1.1% | 28.1% / 8.5% | -19.7 |
| Shots on target 1+ | 45 to 69 | 18.1% | 34.5% / 25.7% | -8.7 |
| Shots on target 1+ | 70 to 84 | 16.9% | 35.6% / 36.8% | +1.2 |
| Shots on target 1+ | 85 plus | 63.9% | 22.2% / 24.4% | +2.3 |
| Shots on target 2+ | under 45 | 1.1% | 7.4% / 1.5% | -5.9 |
| Shots on target 2+ | 45 to 69 | 18.1% | 10.1% / 5.4% | -4.7 |
| Shots on target 2+ | 70 to 84 | 16.9% | 10.9% / 11.0% | +0.1 |
| Shots on target 2+ | 85 plus | 63.9% | 5.7% / 7.2% | +1.4 |

## Rotation risk before kick-off

Share of his last ten appearances that were starts. A starter who usually comes off the bench is more likely to be taken off early.

| Leg | Group | n | fmodel said / landed | gap | tonight said / landed | gap | fmodel log loss |
|---|---|---|---|---|---|---|---|
| Anytime goalscorer | started under 70% of last ten | 5,695 | 13.0% / 12.9% | -0.1 | 31.5% / 12.9% | -18.6 | 0.3522 |
| Anytime goalscorer | started 70%+ | 19,585 | 9.6% / 9.7% | +0.1 | 24.9% / 9.7% | -15.3 | 0.2621 |
| Shots 1+ | started under 70% of last ten | 5,685 | 63.3% / 64.3% | +1.1 | 60.0% / 64.3% | +4.4 | 0.5671 |
| Shots 1+ | started 70%+ | 19,573 | 50.0% / 51.0% | +1.0 | 50.2% / 51.0% | +0.8 | 0.5169 |
| Shots 2+ | started under 70% of last ten | 5,685 | 34.3% / 35.7% | +1.4 | 38.2% / 35.7% | -2.5 | 0.5509 |
| Shots 2+ | started 70%+ | 19,573 | 25.3% / 26.2% | +1.0 | 30.1% / 26.2% | -3.8 | 0.4296 |
| Shots 3+ | started under 70% of last ten | 5,685 | 16.8% / 17.6% | +0.9 | 25.1% / 17.6% | -7.4 | 0.3916 |
| Shots 3+ | started 70%+ | 19,573 | 12.0% / 12.7% | +0.7 | 19.2% / 12.7% | -6.5 | 0.2787 |
| Shots on target 1+ | started under 70% of last ten | 5,680 | 33.2% / 33.5% | +0.3 | 37.4% / 33.5% | -3.9 | 0.5682 |
| Shots on target 1+ | started 70%+ | 19,550 | 24.8% / 24.6% | -0.3 | 29.7% / 24.6% | -5.1 | 0.4458 |
| Shots on target 2+ | started under 70% of last ten | 5,680 | 9.6% / 9.5% | -0.1 | 19.6% / 9.5% | -10.1 | 0.2739 |
| Shots on target 2+ | started 70%+ | 19,550 | 6.8% / 6.8% | +0.1 | 14.9% / 6.8% | -8.1 | 0.1893 |

## Penalties

A penalty seen in his last 38 appearances: one shot worth a penalty's xG (0.76 or 0.79). This catches only penalties taken in one-shot games, so it marks a subset of takers.

| Leg | Group | n | fmodel said / landed | gap | tonight said / landed | gap | fmodel log loss |
|---|---|---|---|---|---|---|---|
| Anytime goalscorer | penalty seen | 1,103 | 19.2% / 20.4% | +1.2 | 32.7% / 20.4% | -12.3 | 0.4643 |
| Anytime goalscorer | none seen | 24,177 | 10.0% / 9.9% | -0.0 | 26.1% / 9.9% | -16.2 | 0.2741 |
| Shots on target 1+ | penalty seen | 1,103 | 43.4% / 43.5% | +0.1 | 45.7% / 43.5% | -2.2 | 0.6046 |
| Shots on target 1+ | none seen | 24,127 | 26.0% / 25.8% | -0.2 | 30.8% / 25.8% | -5.0 | 0.4674 |

### Small samples

By the number of 45-minute appearances behind the record. fmodel needs three; tonight.html needs ten.

| Leg | Record n | rows | record said / landed | shrunk said / landed | fmodel said / landed | record LL | shrunk LL | fmodel LL |
|---|---|---|---|---|---|---|---|---|
| Anytime goalscorer | 3 to 5 | 2,511 | 9.0% / 8.0% | 40.0% / 8.0% | 9.2% / 8.0% | 0.3682 | 0.5402 | 0.2446 |
| Anytime goalscorer | 6 to 9 | 2,227 | 9.7% / 9.9% | 34.7% / 9.9% | 10.1% / 9.9% | 0.3631 | 0.4797 | 0.2766 |
| Anytime goalscorer | 10 to 19 | 5,357 | 10.6% / 10.1% | 28.5% / 10.1% | 10.9% / 10.1% | 0.3218 | 0.4132 | 0.2887 |
| Anytime goalscorer | 20 plus | 15,185 | 10.9% / 11.0% | 22.2% / 11.0% | 10.4% / 11.0% | 0.3036 | 0.3537 | 0.2873 |
| Shots 1+ | 3 to 5 | 2,517 | 49.5% / 51.4% | 49.9% / 51.4% | 49.9% / 51.4% | 0.8223 | 0.6407 | 0.5446 |
| Shots 1+ | 6 to 9 | 2,205 | 52.1% / 52.5% | 50.8% / 52.5% | 53.1% / 52.5% | 0.6324 | 0.6132 | 0.5409 |
| Shots 1+ | 10 to 19 | 5,363 | 54.8% / 56.1% | 52.6% / 56.1% | 55.7% / 56.1% | 0.5888 | 0.5932 | 0.5498 |
| Shots 1+ | 20 plus | 15,161 | 53.0% / 53.9% | 52.0% / 53.9% | 52.5% / 53.9% | 0.5297 | 0.5446 | 0.5158 |
| Shots 2+ | 3 to 5 | 2,517 | 23.6% / 24.5% | 43.6% / 24.5% | 24.1% / 24.5% | 0.6902 | 0.6031 | 0.4505 |
| Shots 2+ | 6 to 9 | 2,205 | 26.1% / 28.3% | 41.0% / 28.3% | 26.7% / 28.3% | 0.5593 | 0.5703 | 0.4639 |
| Shots 2+ | 10 to 19 | 5,363 | 27.9% / 29.2% | 37.9% / 29.2% | 28.8% / 29.2% | 0.5241 | 0.5416 | 0.4792 |
| Shots 2+ | 20 plus | 15,161 | 27.8% / 28.7% | 34.1% / 28.7% | 27.4% / 28.7% | 0.4648 | 0.4868 | 0.4489 |
| Shots 3+ | 3 to 5 | 2,517 | 11.1% / 11.6% | 40.5% / 11.6% | 10.7% / 11.6% | 0.4244 | 0.5509 | 0.2939 |
| Shots 3+ | 6 to 9 | 2,205 | 12.2% / 13.4% | 35.7% / 13.4% | 12.5% / 13.4% | 0.4032 | 0.4958 | 0.3132 |
| Shots 3+ | 10 to 19 | 5,363 | 13.2% / 14.0% | 29.9% / 14.0% | 13.9% / 14.0% | 0.3534 | 0.4344 | 0.3172 |
| Shots 3+ | 20 plus | 15,161 | 13.6% / 14.2% | 24.1% / 14.2% | 13.3% / 14.2% | 0.3171 | 0.3684 | 0.2999 |
| Shots on target 1+ | 3 to 5 | 2,508 | 24.1% / 24.2% | 43.7% / 24.2% | 24.4% / 24.2% | 0.7384 | 0.6126 | 0.4667 |
| Shots on target 1+ | 6 to 9 | 2,211 | 26.1% / 26.1% | 40.9% / 26.1% | 26.3% / 26.1% | 0.5843 | 0.5852 | 0.4817 |
| Shots on target 1+ | 10 to 19 | 5,366 | 27.4% / 27.1% | 37.7% / 27.1% | 28.1% / 27.1% | 0.5351 | 0.5536 | 0.4927 |
| Shots on target 1+ | 20 plus | 15,125 | 27.0% / 26.8% | 33.6% / 26.8% | 26.7% / 26.8% | 0.4847 | 0.5046 | 0.4664 |
| Shots on target 2+ | 3 to 5 | 2,508 | 5.6% / 6.1% | 39.2% / 6.1% | 6.1% / 6.1% | 0.2830 | 0.5216 | 0.1888 |
| Shots on target 2+ | 6 to 9 | 2,211 | 6.7% / 7.5% | 33.6% / 7.5% | 7.1% / 7.5% | 0.2843 | 0.4515 | 0.2274 |
| Shots on target 2+ | 10 to 19 | 5,366 | 7.3% / 7.2% | 26.7% / 7.2% | 7.8% / 7.2% | 0.2456 | 0.3699 | 0.2150 |
| Shots on target 2+ | 20 plus | 15,125 | 7.7% / 7.7% | 19.9% / 7.7% | 7.6% / 7.7% | 0.2178 | 0.2962 | 0.2065 |

### Substitutes

Players who came off the bench, priced on the same record tonight.html uses for any player with ten appearances (fmodel scores starters only). Paddy Power voids a non-starter's bet; a book that lets it stand is settling it at these rates.

| Leg | n | record said | shrunk said | landed | median minutes |
|---|---|---|---|---|---|
| Anytime goalscorer | 6,684 | 12.8% | 26.9% | 5.7% | 21 |
| Shots 1+ | 6,664 | 63.1% | 58.2% | 36.1% | 21 |
| Shots 2+ | 6,664 | 33.9% | 40.0% | 12.0% | 21 |
| Shots 3+ | 6,664 | 16.5% | 29.1% | 3.8% | 21 |
| Shots on target 1+ | 6,656 | 32.7% | 39.2% | 16.5% | 21 |
| Shots on target 2+ | 6,656 | 9.2% | 24.6% | 2.7% | 21 |

## 7. Calibration fixes, walk-forward

Each fix is fitted on every month before a window and scored on that window. A fix is chosen on August (fitted on July alone) and must then beat leaving fmodel alone on both September and October, on log loss and Brier, to be wired in. Fixes: Platt (logit a + b logit p), and Platt with pre-match terms for minutes and rotation, penalties, position, or all of them plus a thin record.

Log loss by window (Brier in brackets):

### Anytime goalscorer

| Fix | 2026-08 | 2026-09 | 2026-10 | chosen on 2026-08 | holds later |
|---|---|---|---|---|---|
| none | 0.2910 (0.0850) | 0.2771 (0.0807) | 0.2815 (0.0825) |  |  |
| platt | 0.2918 (0.0853) | 0.2771 (0.0807) | 0.2814 (0.0824) |  |  |
| platt+minutes | 0.2916 (0.0852) | 0.2773 (0.0807) | 0.2813 (0.0824) |  |  |
| platt+penalty | 0.2918 (0.0853) | 0.2772 (0.0807) | 0.2814 (0.0824) |  |  |
| platt+position | 0.2914 (0.0852) | 0.2774 (0.0807) | 0.2815 (0.0824) |  |  |
| platt+all | 0.2912 (0.0851) | 0.2775 (0.0807) | 0.2811 (0.0823) | picked | no |

Decision: leave fmodel as it is (nothing beat no fix on 2026-08).

### Shots 1+

| Fix | 2026-08 | 2026-09 | 2026-10 | chosen on 2026-08 | holds later |
|---|---|---|---|---|---|
| none | 0.5369 (0.1843) | 0.5228 (0.1784) | 0.5275 (0.1803) |  |  |
| platt | 0.5377 (0.1847) | 0.5228 (0.1783) | 0.5270 (0.1801) | picked | no |
| platt+minutes | 0.5394 (0.1854) | 0.5228 (0.1783) | 0.5271 (0.1802) |  |  |
| platt+penalty | 0.5386 (0.1850) | 0.5227 (0.1783) | 0.5271 (0.1802) |  |  |
| platt+position | 0.5377 (0.1847) | 0.5231 (0.1785) | 0.5268 (0.1801) |  |  |
| platt+all | 0.5409 (0.1860) | 0.5229 (0.1785) | 0.5272 (0.1802) |  |  |

Decision: leave fmodel as it is (nothing beat no fix on 2026-08).

### Shots 2+

| Fix | 2026-08 | 2026-09 | 2026-10 | chosen on 2026-08 | holds later |
|---|---|---|---|---|---|
| none | 0.4568 (0.1503) | 0.4595 (0.1519) | 0.4681 (0.1551) |  |  |
| platt | 0.4607 (0.1514) | 0.4591 (0.1517) | 0.4679 (0.1551) | picked | no |
| platt+minutes | 0.4614 (0.1517) | 0.4592 (0.1518) | 0.4680 (0.1551) |  |  |
| platt+penalty | 0.4608 (0.1514) | 0.4591 (0.1517) | 0.4680 (0.1551) |  |  |
| platt+position | 0.4619 (0.1516) | 0.4592 (0.1518) | 0.4680 (0.1551) |  |  |
| platt+all | 0.4638 (0.1522) | 0.4593 (0.1518) | 0.4683 (0.1553) |  |  |

Decision: leave fmodel as it is (nothing beat no fix on 2026-08).

### Shots 3+

| Fix | 2026-08 | 2026-09 | 2026-10 | chosen on 2026-08 | holds later |
|---|---|---|---|---|---|
| none | 0.3036 (0.0944) | 0.3034 (0.0939) | 0.3163 (0.0977) |  |  |
| platt | 0.3048 (0.0947) | 0.3032 (0.0938) | 0.3158 (0.0974) |  |  |
| platt+minutes | 0.3048 (0.0947) | 0.3032 (0.0938) | 0.3159 (0.0975) |  |  |
| platt+penalty | 0.3048 (0.0947) | 0.3032 (0.0938) | 0.3158 (0.0974) |  |  |
| platt+position | 0.3045 (0.0946) | 0.3031 (0.0938) | 0.3161 (0.0975) | picked | no |
| platt+all | 0.3049 (0.0947) | 0.3034 (0.0939) | 0.3161 (0.0975) |  |  |

Decision: leave fmodel as it is (nothing beat no fix on 2026-08).

### Shots on target 1+

| Fix | 2026-08 | 2026-09 | 2026-10 | chosen on 2026-08 | holds later |
|---|---|---|---|---|---|
| none | 0.4765 (0.1577) | 0.4729 (0.1565) | 0.4760 (0.1575) |  |  |
| platt | 0.4775 (0.1580) | 0.4729 (0.1565) | 0.4759 (0.1574) | picked | no |
| platt+minutes | 0.4776 (0.1580) | 0.4732 (0.1566) | 0.4760 (0.1575) |  |  |
| platt+penalty | 0.4776 (0.1580) | 0.4729 (0.1565) | 0.4759 (0.1574) |  |  |
| platt+position | 0.4778 (0.1580) | 0.4727 (0.1564) | 0.4760 (0.1575) |  |  |
| platt+all | 0.4789 (0.1584) | 0.4732 (0.1566) | 0.4760 (0.1575) |  |  |

Decision: leave fmodel as it is (nothing beat no fix on 2026-08).

### Shots on target 2+

| Fix | 2026-08 | 2026-09 | 2026-10 | chosen on 2026-08 | holds later |
|---|---|---|---|---|---|
| none | 0.2060 (0.0586) | 0.2052 (0.0585) | 0.2209 (0.0632) |  |  |
| platt | 0.2061 (0.0586) | 0.2052 (0.0585) | 0.2209 (0.0632) | picked | no |
| platt+minutes | 0.2064 (0.0587) | 0.2052 (0.0585) | 0.2210 (0.0632) |  |  |
| platt+penalty | 0.2061 (0.0586) | 0.2052 (0.0585) | 0.2211 (0.0633) |  |  |
| platt+position | 0.2061 (0.0586) | 0.2052 (0.0585) | 0.2209 (0.0632) |  |  |
| platt+all | 0.2074 (0.0590) | 0.2053 (0.0585) | 0.2211 (0.0633) |  |  |

Decision: leave fmodel as it is (nothing beat no fix on 2026-08).

### tonight.html's blend

tonight.html averages the shrunk record and fmodel half and half for shots and shots on target, and shows the shrunk record alone for to score. The weight on fmodel is chosen on the months before each window (grid of tenths) and scored on the window, against the page now and fmodel alone. It is wired in only if the fitted weight beats the page on every window. Log loss:

| Leg | Blend | 2026-08 | 2026-09 | 2026-10 | weight chosen |
|---|---|---|---|---|---|
| Anytime goalscorer | the page now | 0.3724 (0.1063) | 0.3646 (0.1031) | 0.3687 (0.1050) |  |
| Anytime goalscorer | fitted weight | 0.2951 (0.0863) | 0.2822 (0.0824) | 0.2915 (0.0863) | 1.0, 1.0, 1.0 |
| Anytime goalscorer | fmodel alone | 0.2951 (0.0863) | 0.2822 (0.0824) | 0.2915 (0.0863) |  |
| Shots 1+ | the page now | 0.5956 (0.2051) | 0.5799 (0.1978) | 0.5842 (0.2000) |  |
| Shots 1+ | fitted weight | 0.5947 (0.2053) | 0.5757 (0.1965) | 0.5789 (0.1983) | 1.0, 0.8, 0.9 |
| Shots 1+ | fmodel alone | 0.5947 (0.2053) | 0.5754 (0.1966) | 0.5788 (0.1984) |  |
| Shots 2+ | the page now | 0.5075 (0.1660) | 0.5213 (0.1725) | 0.5206 (0.1720) |  |
| Shots 2+ | fitted weight | 0.4990 (0.1635) | 0.5169 (0.1717) | 0.5152 (0.1708) | 1.0, 1.0, 0.9 |
| Shots 2+ | fmodel alone | 0.4990 (0.1635) | 0.5169 (0.1717) | 0.5160 (0.1712) |  |
| Shots 3+ | the page now | 0.3591 (0.1078) | 0.3597 (0.1080) | 0.3617 (0.1089) |  |
| Shots 3+ | fitted weight | 0.3325 (0.1037) | 0.3351 (0.1042) | 0.3409 (0.1057) | 1.0, 1.0, 1.0 |
| Shots 3+ | fmodel alone | 0.3325 (0.1037) | 0.3351 (0.1042) | 0.3409 (0.1057) |  |
| Shots on target 1+ | the page now | 0.5502 (0.1837) | 0.5571 (0.1870) | 0.5577 (0.1873) |  |
| Shots on target 1+ | fitted weight | 0.5420 (0.1808) | 0.5487 (0.1841) | 0.5480 (0.1837) | 1.0, 1.0, 1.0 |
| Shots on target 1+ | fmodel alone | 0.5420 (0.1808) | 0.5487 (0.1841) | 0.5480 (0.1837) |  |
| Shots on target 2+ | the page now | 0.2810 (0.0762) | 0.2806 (0.0761) | 0.2958 (0.0825) |  |
| Shots on target 2+ | fitted weight | 0.2434 (0.0703) | 0.2454 (0.0707) | 0.2682 (0.0786) | 1.0, 1.0, 1.0 |
| Shots on target 2+ | fmodel alone | 0.2434 (0.0703) | 0.2454 (0.0707) | 0.2682 (0.0786) |  |

| Leg | beats the page on every window | weight on fmodel, fitted on July to October |
|---|---|---|
| Anytime goalscorer | yes | 1.0 |
| Shots 1+ | no | 0.9 |
| Shots 2+ | yes | 0.9 |
| Shots 3+ | yes | 1.0 |
| Shots on target 1+ | yes | 1.0 |
| Shots on target 2+ | yes | 1.0 |

Scored on the same rows with the weight fitted on July to October (in sample, for the record):

| Leg | n | the page now: said / landed, log loss | fitted weight: said / landed, log loss |
|---|---|---|---|
| Anytime goalscorer | 20,371 | 23.8% / 10.7%, 0.3685 | 10.5% / 10.7%, 0.2871 |
| Shots 1+ | 15,980 | 57.3% / 59.8%, 0.5855 | 58.2% / 59.8%, 0.5815 |
| Shots 2+ | 15,980 | 33.6% / 31.5%, 0.5129 | 30.8% / 31.5%, 0.5053 |
| Shots 3+ | 15,980 | 20.4% / 15.3%, 0.3581 | 14.4% / 15.3%, 0.3325 |
| Shots on target 1+ | 14,079 | 35.1% / 31.7%, 0.5536 | 31.6% / 31.7%, 0.5446 |
| Shots on target 2+ | 14,079 | 15.9% / 9.1%, 0.2838 | 9.1% / 9.1%, 0.2486 |

### The Players tab's own chance, where fmodel has none

For a player fmodel cannot see (not in the predicted or confirmed XI, under three full games, or before any line-up is out) the Players tab prices shots and shots on target with pricePlayer and to score with scoreCase. Section 2 shows both run high on every line but shots 1+. The fix tried is a Platt map per line, fitted on starters (Paddy Power settles a player bet only if he starts), chosen on August and wired in only if it beats the page on September and October on log loss and Brier. A position term helps a little more but the page's fallback does not carry the position, so it is not offered. Log loss (Brier):

| Leg | Fix | 2026-08 | 2026-09 | 2026-10 | holds |
|---|---|---|---|---|---|
| Anytime goalscorer | none | 0.3037 (0.0867) | 0.2886 (0.0827) | 0.2973 (0.0845) |  |
| Anytime goalscorer | platt | 0.3024 (0.0878) | 0.2871 (0.0827) | 0.2940 (0.0845) | no |
| Shots 1+ | none | 0.5626 (0.1933) | 0.5568 (0.1904) | 0.5635 (0.1936) |  |
| Shots 1+ | platt | 0.5527 (0.1892) | 0.5434 (0.1848) | 0.5534 (0.1893) | yes |
| Shots 2+ | none | 0.4984 (0.1651) | 0.4967 (0.1648) | 0.5060 (0.1685) |  |
| Shots 2+ | platt | 0.4800 (0.1582) | 0.4715 (0.1562) | 0.4863 (0.1604) | yes |
| Shots 3+ | none | 0.3628 (0.1097) | 0.3616 (0.1092) | 0.3707 (0.1126) |  |
| Shots 3+ | platt | 0.3193 (0.0986) | 0.3134 (0.0958) | 0.3286 (0.1000) | yes |
| Shots on target 1+ | none | 0.5230 (0.1744) | 0.5180 (0.1730) | 0.5221 (0.1751) |  |
| Shots on target 1+ | platt | 0.5098 (0.1664) | 0.5022 (0.1659) | 0.5072 (0.1677) | yes |
| Shots on target 2+ | none | 0.2787 (0.0761) | 0.2760 (0.0754) | 0.2844 (0.0786) |  |
| Shots on target 2+ | platt | 0.2165 (0.0605) | 0.2127 (0.0599) | 0.2285 (0.0645) | yes |

| Leg | wired | a | b | said / landed before | after, same rows (in sample) |
|---|---|---|---|---|---|
| Anytime goalscorer | no | -0.6081 | 0.6368 | 10.1% / 10.3% | 10.3% / 10.3% |
| Shots 1+ | yes | +0.1306 | 1.5067 | 50.0% / 54.0% | 54.0% / 54.0% |
| Shots 2+ | yes | -0.1049 | 1.7037 | 35.0% / 28.4% | 28.4% / 28.4% |
| Shots 3+ | yes | -0.2779 | 1.7126 | 24.2% / 13.8% | 13.8% / 13.8% |
| Shots on target 1+ | yes | -0.3176 | 1.2276 | 34.1% / 26.6% | 26.6% / 26.6% |
| Shots on target 2+ | yes | -0.5068 | 1.6587 | 18.8% / 7.4% | 7.4% / 7.4% |

## 8. The live record

Settled football player legs the page picked (best_bets.json), one per player, stat and line. These are chosen legs, so the best-looking of many: expect them to land below what was said.

| Leg | n | page said | record | shrunk | landed |
|---|---|---|---|---|---|
| Goals 1+ | 7 | 71.7% | 64.5% | 59.7% | 57.1% |
| Shots 1+ | 88 | 70.4% | 79.2% | 69.9% | 78.4% |
| Shots 2+ | 40 | 70.8% | 75.8% | 68.2% | 65.0% |
| Shots 3+ | 8 | 70.4% | 71.6% | 63.9% | 75.0% |
| Shots on target 1+ | 34 | 72.6% | 76.6% | 68.7% | 64.7% |
| all | 185 | 70.7% | 76.6% | 68.4% | 70.3% |

