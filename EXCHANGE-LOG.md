# Exchange log: who has been right, the site or Betfair?

Written 22 October 2026 from `exchange_log.json` as committed on `oct21-work` (last written 21 Oct 22:31 UTC).
Analysis and tests only: nothing here changes a live price, a blend weight, a margin or a betting rule.

## The verdict, plainly

1. **Betfair has been at least as right as the site, and by kick-off clearly more right.** On 307 settled
   lines from 102 fixtures, priced when the site first saw them, Betfair's own chance scored better than
   the site's model on log loss and Brier, though the gap is inside the noise (model minus Betfair log loss
   +0.011, 95% interval -0.013 to +0.037). Against Betfair's last price before kick-off the model loses
   by a margin the noise does not cover (+0.036, 95% +0.010 to +0.063). The market sharpens towards the
   start; the model does not.
2. **The blend the site actually uses is about as good as Betfair alone, no better.** Its log loss is
   0.0017 lower than Betfair's, with a 95% interval of -0.016 to +0.012. That is a tie.
3. **The value the page shows against Betfair has not been real so far.** The 23 settled bets the page
   showed as value (over 0.5%) won 9, lost 4.91 units, ROI -21% (95% -63% to +30%). The 12 that cleared
   the 3% value-list bar won 3, ROI -53% (95% -100% to +3%). The site said those bets were worth +3.6%
   and +5.2%; Betfair's own chance said -5.3% and -6.2%. The sample is far too small for results alone
   to settle it, but the closing price, which needs no results, gives the same answer: at Betfair's last
   price before kick-off the bets shown as value were worth **-3.9%** (95% -6.7% to -1.7%). That interval
   excludes zero. The market did not come round to the site's view; it stayed where it was.
4. **No rule for trusting the site against the exchange is supported.** Every rule tried, fitted out of
   sample on held-out fixtures, failed to beat simply taking Betfair's chance. Where the site disagreed
   by 15 points or more, the result landed on the site's side 29% of the time. The evidence is
   consistent with the site adding nothing measurable to Betfair's price; it cannot yet rule out a small
   contribution in either direction.
5. **The log's own results for player lines are partly wrong, and the fitted numbers built on them are
   too.** 19 player lines the log graded as losses at 0 were wins (13) or voids (6) in SofaScore's
   post-match line-ups (Haaland scored twice and had 2 shots on target, graded 0 and lost). This is the pre-match
   line-up hazard described in `besttrack._player_value`. The back-only margin `exchange_eval.py fit`
   wrote for shots on target (28.4%, from a raw 40%) and the shots-on-target blend weight (0.114, from a
   raw 0) were fitted on these results. On verified results only, the margin fits at 17% (95% -7% to
   42%) and the weight at 0.60 (95% 0 to 1). Separately, `fit` counts both sides of every line, so a
   family it treats as 33 bets is 17 lines. Neither is changed here; see "What would follow" below.

Sample sizes throughout are small: 307 lines, 102 fixtures, six days (16 to 21 October), almost all
football. Read every interval before reading any point estimate.

## How it was done

`python exchange_audit.py` reproduces every table below. It reads only.

* **Results.** Every logged record was matched to every result the repo holds: the log's own settled
  result; `best_bets.json` legs on the same stat (any line on the same event, player or team and stat
  settles every other line on it, so an over at 0.5 settles the under at 0.5); `pplog/*.jsonl` where present
  (it is gitignored and absent in this checkout; `pp-results.html` holds only a page of recent, mostly
  basketball rows, with no usable overlap); and SofaScore's own match statistics and line-ups from `cache/`
  and `cache_backtest.tar.zst`, recomputed with the same `besttrack` functions the settler uses. A line-up
  copy counts only if somebody in it has minutes, so a pre-match copy is never read as a result. Where
  sources disagree the post-match copy wins and the conflict is listed. Team results the log alone saw are
  kept: they come from the final score, not a line-up, and 308 team results seen by a second source agreed
  with the log every time. **Player** results the log alone saw are set aside, wins as well as losses:
  dropping only the suspect zeros would have tilted every player market towards winning.
* **Scoring.** Four chances, all as logged at first sighting: the site's model, the model with its usual
  lean against the market taken off ("lean off", `pAnchored`), Betfair's chance with the margin off, and
  the blend the site priced with. Over and under on one line are the same bet seen twice (their log
  losses are nearly identical), so each line is scored once, the over where both were logged.
  All intervals are 95% percentile bootstraps resampling **whole fixtures**, because lines in one match
  win and lose together.
* **Commission and the spread.** Betfair's chance comes from the mid price with the margin off. A back
  bet at price b pays (b - 1) x 0.95 after 5% commission, so it breaks even at a chance of
  1 / (1 + 0.95 (b - 1)), which is above 1/back, which is in turn above the mid-price chance and 1/lay.
  Value is backed only at the back price on offer then (never the mid, never the lay), and every return
  is after commission. Table 3d checks that each logged Betfair chance sits inside its own spread, and
  3e shows what reading the price the wrong way does to the score. For back-only lists (shots on target,
  anytime scorer) there is no lay, so Betfair's chance is the back price with an estimated margin off;
  3f checks that margin against verified results.
* **Trust rules.** Eight rules for combining the two chances, each fitted on four-fifths of the fixtures
  and scored on the fifth, five times over, so no fixture is scored by a rule that saw it.

## 1. Matching every logged price to its result

916 records: 553 scored (one side per line leaves 307 lines), 233 still open, 45 void, 85 player lines set
aside as unverifiable. Every open record is a fixture that kicked off on or after 22 Oct 16:45, after the
log was last written, so none can be settled from the repo. Four Cincinnati v DC United lines the log
still had open were settled from `best_bets.json`.

#### 1a. What happened to every logged price
| Status | Records |
|---|---:|
| verified | 365 |
| open | 233 |
| log only | 188 |
| unverified player zero | 60 |
| void | 45 |
| unverified player line | 25 |
| Total | 916 |

#### 1b. Where the scored results came from
| Market side | Sources that saw the result | Records |
|---|---:|---:|
| team | log | 188 |
| team | cache + log | 175 |
| team | best_bets + log | 95 |
| player | cache + log | 39 |
| team | best_bets + cache + log | 38 |
| player | best_bets + log | 11 |
| team | best_bets | 4 |
| player | best_bets + cache + log | 3 |


Every conflict is a player line, and in every one the log said 0. Where SofaScore's post-match line-up
had the player with minutes and a positive count, the bet was a win; where it had the player without
minutes, the bet was void. One went the other way (Solanke: the log voided it, the line-up shows he played and
had no shot on target, so it was a loss).

#### 1c. Conflicts between sources
| Record | What each source said (value, result) |
|---|---:|
| 16363887 / Rayan Cherki / Shots on target / ALL / 0.5 / True | log: 0.0 lose; cache: void void |
| 16363887 / Erling Haaland / Goals / ALL / 0.5 / True | log: 0.0 lose; cache: 2.0 win |
| 16363887 / Erling Haaland / Shots on target / ALL / 0.5 / True | log: 0.0 lose; cache: 2.0 win; best_bets: 2.0 win |
| 16363883 / Ismaïla Sarr / Shots on target / ALL / 0.5 / True | log: 0.0 lose; cache: void void |
| 16363881 / Chemsdine Talbi / Shots on target / ALL / 0.5 / True | log: 0.0 lose; cache: void void |
| 16310981 / Esteban Lepaul / Goals / ALL / 0.5 / True | log: 0.0 lose; cache: 3.0 win |
| 16421068 / Antony / Shots on target / ALL / 0.5 / True | log: 0.0 lose; cache: void void |
| 16421068 / Abdessamad Ezzalzouli / Shots on target / ALL / 0.5 / True | log: 0.0 lose; cache: 1.0 win |
| 16421068 / Cucho Hernández / Shots on target / ALL / 0.5 / True | log: 0.0 lose; cache: 1.0 win |
| 16421068 / Lamine Yamal / Shots on target / ALL / 0.5 / True | log: 0.0 lose; cache: 2.0 win; best_bets: 2.0 win |
| 16421068 / Fermín López / Shots on target / ALL / 0.5 / True | log: 0.0 lose; cache: 1.0 win |
| 16421071 / Julián Alvarez / Shots on target / ALL / 0.5 / True | log: 0.0 lose; cache: 1.0 win |
| 16421073 / Mikel Oyarzabal / Shots on target / ALL / 0.5 / True | log: 0.0 lose; cache: 3.0 win |
| 16421073 / Luka Sučić / Shots on target / ALL / 0.5 / True | log: 0.0 lose; cache: void void |
| 16363889 / Noni Madueke / Shots on target / ALL / 0.5 / True | log: 0.0 lose; cache: 1.0 win |
| 16421073 / Orri Óskarsson / Goals / ALL / 0.5 / True | log: 0.0 lose; cache: 1.0 win |
| 16421068 / Lamine Yamal / Goals / ALL / 0.5 / True | log: 0.0 lose; cache: 1.0 win |
| 16421071 / Alexander Sørloth / Shots on target / ALL / 1.5 / True | log: 0.0 lose; cache: void void |
| 16363890 / Dominic Solanke / Shots on target / ALL / 0.5 / True | log: void void; cache: 0.0 lose |
| 16421072 / Martín Satriano / Shots on target / ALL / 0.5 / True | log: 0.0 lose; cache: 3.0 win |


These are the player zeros no post-match source could confirm or contradict, set aside rather than
scored. Twelve are NFL anytime touchdowns, which leaves only two verified NFL lines in the whole audit.

#### 1d. Player zeros nothing else could confirm (set aside)
| Market | Records |
|---|---:|
| player / Shots on target / back | 41 |
| player / Anytime touchdown / back | 12 |
| player / Goals / back | 4 |
| player / Shots on target / exchange | 3 |


## 2. Who has been right

### Overall

#### 2a. Overall, one side per line, chance at first sighting
| Group | Lines | Fixtures | Landed | LL Site model | LL Site, lean off | LL Betfair | LL Blend (used) | Brier model | Brier Betfair | Brier blend | Model minus Betfair LL (95%) | Best |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| All verified lines | 307 | 102 | 61.9% | 0.6343 | 0.6347 | 0.6233 | 0.6216 | 0.2206 | 0.2153 | 0.2148 | +0.0109 (-0.0132 to +0.0369) | Blend (used) |
| Same, chance at last sighting | 307 | 102 | 61.9% | 0.6448 | 0.6444 | 0.6092 | 0.6185 | 0.2236 | 0.2096 | 0.2124 | +0.0356 (+0.0101 to +0.0634) | Betfair |
| Both sides of every line (double counts) | 553 | 102 | 51.2% | 0.6305 | 0.6294 | 0.6144 | 0.6157 | 0.2191 | 0.2118 | 0.2123 | +0.0161 (-0.0075 to +0.0420) | Betfair |


Read across the first row: Betfair beat the model (0.6233 against 0.6343); the blend edged Betfair
(0.6216); none of the differences is outside the noise. The second row is the important one. By the last
sighting before kick-off Betfair has improved (0.6233 to 0.6092) and the model has got slightly worse
(0.6343 to 0.6448), and the gap is now clear of zero.

### By sport

#### 2b. By sport
| Group | Lines | Fixtures | Landed | LL Site model | LL Site, lean off | LL Betfair | LL Blend (used) | Brier model | Brier Betfair | Brier blend | Model minus Betfair LL (95%) | Best |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| american-football | 2 | 2 | 100.0% | 0.4132 | 0.4971 | 0.4282 | 0.4695 | 0.1180 | 0.1213 | 0.1416 | -0.0150 (-0.1301 to +0.1001) | Site model |
| football | 305 | 100 | 61.6% | 0.6357 | 0.6356 | 0.6246 | 0.6226 | 0.2212 | 0.2160 | 0.2153 | +0.0111 (-0.0127 to +0.0366) | Blend (used) |


There is nothing to say about American football: two verified lines. This is a football audit.

### By market

#### 2c. By market
| Group | Lines | Fixtures | Landed | LL Site model | LL Site, lean off | LL Betfair | LL Blend (used) | Brier model | Brier Betfair | Brier blend | Model minus Betfair LL (95%) | Best |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| team / Goals / derived | 142 | 76 | 69.7% | 0.6066 | 0.5969 | 0.5789 | 0.5836 | 0.2077 | 0.1947 | 0.1964 | +0.0277 (-0.0060 to +0.0602) | Betfair |
| team / Goals / exchange | 44 | 24 | 56.8% | 0.6470 | 0.6545 | 0.6153 | 0.6254 | 0.2227 | 0.2137 | 0.2153 | +0.0317 (-0.0200 to +0.0845) | Betfair |
| player / Shots on target / back | 36 | 15 | 52.8% | 0.6633 | 0.6658 | 0.6554 | 0.6485 | 0.2355 | 0.2275 | 0.2286 | +0.0079 (-0.1054 to +0.0972) | Blend (used) |
| team / Both teams to score / exchange | 17 | 10 | 35.3% | 0.6802 | 0.7180 | 0.7356 | 0.7306 | 0.2432 | 0.2710 | 0.2681 | -0.0554 (-0.1785 to +0.0782) | Site model |
| team / Match goals / exchange | 17 | 10 | 41.2% | 0.7252 | 0.7437 | 0.6829 | 0.7017 | 0.2651 | 0.2456 | 0.2544 | +0.0423 (-0.0460 to +0.1357) | Betfair |
| team / Match corners / exchange | 17 | 10 | 58.8% | 0.6824 | 0.6828 | 0.6976 | 0.6864 | 0.2448 | 0.2521 | 0.2467 | -0.0151 (-0.0965 to +0.0589) | Site model |
| team / Match cards / exchange | 17 | 10 | 64.7% | 0.5938 | 0.5868 | 0.5819 | 0.5832 | 0.2016 | 0.1954 | 0.1961 | +0.0119 (-0.1128 to +0.1336) | Betfair |
| player / Goals / back | 13 | 12 | 69.2% | 0.6719 | 0.6802 | 0.8238 | 0.7071 | 0.2396 | 0.3000 | 0.2562 | -0.1518 (-0.4586 to +0.1106) | Site model |
| player / Anytime touchdown / back | 2 | 2 | 100.0% | 0.4132 | 0.4971 | 0.4282 | 0.4695 | 0.1180 | 0.1213 | 0.1416 | -0.0150 (-0.1301 to +0.1001) | Site model |
| player / Goals / exchange | 1 | 1 | 100.0% | 0.6118 | 0.6057 | 0.4917 | 0.5465 | 0.2094 | 0.1509 | 0.1772 | +0.1201 (-) | Betfair |
| player / Shots on target / exchange | 1 | 1 | 100.0% | 0.4806 | 0.4608 | 0.5738 | 0.4927 | 0.1456 | 0.1906 | 0.1513 | -0.0931 (-) | Site, lean off |


No market shows the site clearly ahead. The largest single families, team goals derived from Betfair's
goal model (142 lines) and team goals priced directly (44), both favour Betfair. The site's best showings
(both teams to score, corners, player anytime scorer) rest on 13 to 17 lines each, with intervals several
times wider than the gaps. Player anytime scorer is the one place Betfair's number looks poor, and that
number is not really Betfair's: it is a back price with a 10% margin estimate taken off, on 13 lines.

### By how far apart they were

The gap is the site's chance with its usual lean off, minus Betfair's, at first sighting: the same
comparison the page makes before it calls value or flags a disagreement.

#### 2d. By how far apart the site and Betfair were (site lean off, at first sighting)
| Group | Lines | Fixtures | Landed | LL Site model | LL Site, lean off | LL Betfair | LL Blend (used) | Brier model | Brier Betfair | Brier blend | Model minus Betfair LL (95%) | Best |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0-3 pts | 79 | 49 | 63.3% | 0.6381 | 0.6377 | 0.6334 | 0.6357 | 0.2231 | 0.2216 | 0.2219 | +0.0047 (-0.0151 to +0.0257) | Betfair |
| 3-6 pts | 77 | 53 | 58.4% | 0.6396 | 0.6477 | 0.6241 | 0.6361 | 0.2211 | 0.2145 | 0.2189 | +0.0154 (-0.0113 to +0.0431) | Betfair |
| 6-10 pts | 69 | 43 | 63.8% | 0.5956 | 0.5998 | 0.5936 | 0.5955 | 0.2025 | 0.2035 | 0.2038 | +0.0020 (-0.0446 to +0.0547) | Betfair |
| 10-15 pts | 48 | 37 | 64.6% | 0.6780 | 0.6676 | 0.6894 | 0.6651 | 0.2415 | 0.2459 | 0.2355 | -0.0114 (-0.1012 to +0.0665) | Blend (used) |
| 15+ pts | 34 | 24 | 58.8% | 0.6303 | 0.6227 | 0.5654 | 0.5478 | 0.2203 | 0.1835 | 0.1820 | +0.0649 (-0.0809 to +0.2066) | Blend (used) |

#### 2e. When they disagreed, which way did the result go?
| Gap | Lines | Average gap | Share of gap realised | 95% | Landed on site's side |
|---|---:|---:|---:|---:|---:|
| 0-3 pts | 79 | 1.4% | 0.44 | -6.60 to 7.41 | 49% |
| 3-6 pts | 77 | 4.3% | -2.07 | -4.61 to 0.10 | 36% |
| 6-10 pts | 69 | 7.9% | 0.47 | -1.02 to 1.84 | 45% |
| 10-15 pts | 48 | 12.4% | 0.79 | -0.25 to 1.91 | 44% |
| 15+ pts | 34 | 21.2% | -0.01 | -0.59 to 0.59 | 29% |
| All | 307 | 7.5% | 0.04 | -0.75 to 0.75 | 42% |

Share of gap realised: 1 means results moved the full distance from Betfair's chance to the site's, 0 means they stayed at Betfair's, below 0 means they moved the other way.


When the two were 15 points or more apart (the page's disagreement flag), the result went the site's
way 29% of the time and realised none of the gap (-0.01, 95% -0.59 to +0.59). In the 3 to 6 point band
results moved away from the site (-2.07, 95% -4.61 to +0.10). The 6 to 10 and 10 to 15 point bands lean
the site's way (0.47 and 0.79), but their intervals run from about -1 to nearly +2. Across all 307 lines the
share of the gap realised is 0.04 (95% -0.75 to +0.75): on average the results stayed at Betfair's
chance.

### Calibration

#### 2f. Calibration
| Chance | Calibration slope | 95% | Landed minus said |
|---|---:|---:|---:|
| Site model | 0.96 | 0.47 to 1.65 | +3.0% |
| Site, lean off | 0.87 | 0.43 to 1.53 | +0.0% |
| Betfair | 0.82 | 0.47 to 1.22 | -1.0% |
| Blend (used) | 0.97 | 0.55 to 1.51 | -0.4% |

Slope 1 is perfect; below 1 the chances are too spread out (overconfident), above 1 too timid.


Site model, by band:

| Said | Lines | Average said | Landed |
|---|---:|---:|---:|
| 20%-30% | 3 | 24.0% | 0.0% |
| 30%-40% | 12 | 35.7% | 33.3% |
| 40%-50% | 57 | 46.0% | 50.9% |
| 50%-60% | 100 | 54.2% | 56.0% |
| 60%-70% | 73 | 64.4% | 74.0% |
| 70%-80% | 40 | 74.0% | 75.0% |
| 80%-90% | 20 | 84.5% | 85.0% |
| 90%-100% | 2 | 90.8% | 0.0% |

Betfair, by band:

| Said | Lines | Average said | Landed |
|---|---:|---:|---:|
| 10%-20% | 3 | 15.4% | 0.0% |
| 20%-30% | 7 | 23.9% | 14.3% |
| 30%-40% | 17 | 35.4% | 58.8% |
| 40%-50% | 31 | 45.2% | 32.3% |
| 50%-60% | 70 | 56.0% | 54.3% |
| 60%-70% | 79 | 64.2% | 64.6% |
| 70%-80% | 44 | 75.4% | 84.1% |
| 80%-90% | 46 | 83.9% | 80.4% |
| 90%-100% | 10 | 91.0% | 60.0% |

Blend (used), by band:

| Said | Lines | Average said | Landed |
|---|---:|---:|---:|
| 10%-20% | 2 | 17.2% | 0.0% |
| 20%-30% | 4 | 26.4% | 0.0% |
| 30%-40% | 9 | 34.7% | 44.4% |
| 40%-50% | 35 | 46.1% | 42.9% |
| 50%-60% | 94 | 55.4% | 55.3% |
| 60%-70% | 71 | 64.4% | 67.6% |
| 70%-80% | 55 | 75.4% | 74.5% |
| 80%-90% | 31 | 84.0% | 83.9% |
| 90%-100% | 6 | 91.1% | 66.7% |


All four are roughly calibrated in the large (landed within three points of said). All slopes below 1
point to chances slightly too spread out, but every interval includes 1. The bands are thin above 80%
and below 30%.

## 3. Has the value against Betfair been real?

#### 3a. Bets the page called value, backed at the price shown, 5% commission
| Bets | n | Fixtures | Won | Needed to break even | Site said | Betfair said | Profit | ROI | ROI 95% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Every bet with a value figure | 162 | 33 | 87 (54%) | 58% | -5.7% | -5.1% | -7.33u | -4.5% | -11.9% to +3.5% |
| Value below 0 (not shown as value) | 139 | 31 | 78 (56%) | 59% | -7.3% | -5.1% | -2.42u | -1.7% | -11.5% to +9.4% |
| Shown as value on the page (over 0.5%) | 23 | 15 | 9 (39%) | 50% | +3.6% | -5.3% | -4.91u | -21.3% | -62.9% to +29.6% |
| Value list bar (3%+) | 12 | 10 | 3 (25%) | 49% | +5.2% | -6.2% | -6.36u | -53.0% | -100.0% to +3.4% |
| Value 6%+ | 4 | 4 | 1 (25%) | 45% | +7.5% | -10.8% | -1.77u | -44.1% | -100.0% to +67.6% |
| Shown, two-way exchange markets | 18 | 10 | 8 (44%) | 51% | +2.7% | -3.9% | -2.14u | -11.9% | -59.2% to +52.1% |
| Shown, back-only player lists | 5 | 5 | 1 (20%) | 45% | +6.9% | -10.3% | -2.77u | -55.3% | -100.0% to +34.1% |


The page prints value when the blend's expected return at the back price, after commission, is above
0.5% (`make_index.py`); the value list needs 3% (`weekend.VALUE_MIN`). Bets the page did not call value
lost less than the ones it did, though nothing here separates them statistically. Of the 23 shown, both
the per-market split below and the three-way split above are too small to read: 4 shots-on-target value
bets lost all 4, and 4 both-teams-to-score bets won 2.

How many bets would results alone need? A back bet near evens returns +0.9 or -1, a standard deviation of
about 1 unit. To pin ROI down to within 3 points either side takes about (1.96 / 0.03)^2, roughly 4,300
settled value bets; the log has 23. That is why the closing price matters:

#### 3b. The same bets against Betfair's closing chance (no results needed)
| Bets | Seen twice | Worth at close | 95% | Shortened | Drifted |
|---|---:|---:|---:|---:|---:|
| Shown as value (over 0.5%) | 23 | -3.9% | -6.7% to -1.7% | 52% | 26% |
| Value list bar (3%+) | 12 | -5.0% | -8.0% to -2.0% | 50% | 25% |
| Not shown as value | 138 | -5.8% | -7.1% to -4.7% | 45% | 49% |
| Every bet with a value figure | 161 | -5.5% | -6.8% to -4.7% | 46% | 45% |


Closing line value needs no results. Every bet here, valued at Betfair's last chance before kick-off,
was worth less than nothing, as it must be once the spread and commission are paid. The question is
whether the bets the site called value did better than that floor by more than the site claimed. They
did slightly better (-3.9% against -5.8% for bets not shown as value), and slightly more of their prices
shortened (52% against 45%), but the site said +3.6% and the close says -3.9%. A real edge of +3.6% would
show as a positive number at the close. It did not.

#### 3c. Value by market
| Market | Value bets | Won | Site said | ROI | 95% |
|---|---:|---:|---:|---:|---:|
| player / Goals / back | 1 | 1 | +7.4% | +123.5% | - |
| player / Shots on target / back | 4 | 0 | +6.8% | -100.0% | -100.0% to -100.0% |
| team / Both teams to score / exchange | 4 | 2 | +2.4% | +15.6% | -100.0% to +131.1% |
| team / Goals / exchange | 8 | 5 | +2.3% | +13.7% | -48.8% to +87.3% |
| team / Match goals / exchange | 6 | 1 | +3.3% | -64.3% | -100.0% to +28.4% |

#### 3d. Is Betfair's chance where its spread says? (two-way markets, first sighting)
| Quotes with back and lay | Chance inside [1/lay, 1/back] | Within 2 pts more | Median spread width |
|---|---:|---:|---:|
| 210 | 210 | 0 | 1.7% |


Every two-way Betfair chance in the log sits inside its own spread, as it should. The margin-off chance
and the mid-price chance agree to a tenth of a point:

#### 3e. Reading Betfair's chance different ways (two-way markets with both prices)
| Betfair's chance read as | Lines | Said | Landed | Log loss | Brier |
|---|---:|---:|---:|---:|---:|
| 1 / back | 91 | 62.8% | 52.7% | 0.6534 | 0.2314 |
| 1 / lay | 91 | 59.9% | 52.7% | 0.6501 | 0.2301 |
| 1 / mid price | 91 | 61.3% | 52.7% | 0.6506 | 0.2303 |
| Back break-even after commission | 91 | 63.9% | 52.7% | 0.6588 | 0.2339 |
| Margin off, as logged | 91 | 61.4% | 52.7% | 0.6506 | 0.2302 |


Reading the back price as Betfair's chance, or worse the break-even after commission, scores worse than
the mid. 1/lay happens to score a fraction better than the mid here (0.0005), only because on these 91
lines the overs landed less often than any reading of the price said; that is noise. The mid with the
margin off is the right number to compare the site with, and it is the one the site uses. Value is then priced at the back price after commission, which is also right: `weekend.ev_at` and
this audit's `ev` agree to machine precision (tested). The commission and spread are handled correctly
in the site's sums. The problem is not the arithmetic; it is that the chance going into it has not been
better than Betfair's.

#### 3f. Back-only lists: what margin the results say is in the price
| Results used | Lines | Fitted margin | 95% |
|---|---:|---:|---:|
| Verified only | 51 | 17.0% | -7.0% to 42.0% |
| The log as settled (includes unverified zeros) | 138 | 94.0% | - |


On verified results the margin left in back-only shots-on-target prices fits at about 17%, with a very
wide interval. On the log as settled, false zeros included, it fits at 94%: the false losses make the
back prices look far too short. `exchange_weights.json` currently holds 28.4% for `SHOTS_ON_TARGET_P1`,
fitted on those results.

## 4. A rule for trusting the site against the exchange?

#### 4. Trust rules, out of sample (5 folds by fixture)
| Rule | Lines | Log loss | Minus Betfair | 95% |
|---|---:|---:|---:|---:|
| Betfair only | 307 | 0.6233 | +0.0000 | +0.0000 to +0.0000 |
| Site model only | 307 | 0.6343 | +0.0109 | -0.0132 to +0.0378 |
| Site, lean off | 307 | 0.6347 | +0.0114 | -0.0123 to +0.0352 |
| Blend as used | 307 | 0.6216 | -0.0017 | -0.0160 to +0.0117 |
| Fixed 50/50 | 307 | 0.6231 | -0.0002 | -0.0122 to +0.0115 |
| One fitted weight | 307 | 0.6270 | +0.0037 | -0.0033 to +0.0111 |
| Weight by gap band | 307 | 0.6254 | +0.0020 | -0.0066 to +0.0112 |
| Weight by market | 307 | 0.6291 | +0.0058 | -0.0001 to +0.0127 |

Weight on Betfair that fits all verified lines best: 0.72 (95% 0.20 to 1.00).

| Gap | Lines | Best weight on Betfair | 95% |
|---|---:|---:|---:|
| 0-3 pts | 79 | 1.00 | 0.00 to 1.00 |
| 3-6 pts | 77 | 1.00 | 0.80 to 1.00 |
| 6-10 pts | 69 | 0.70 | 0.00 to 1.00 |
| 10-15 pts | 48 | 0.20 | 0.00 to 1.00 |
| 15+ pts | 34 | 0.72 | 0.20 to 1.00 |

| Market | Lines | Weight the site used | Best weight on Betfair | 95% |
|---|---:|---:|---:|---:|
| team / Goals / derived | 142 | 0.48 | 0.97 | 0.20 to 1.00 |
| team / Goals / exchange | 44 | 0.58 | 1.00 | 0.25 to 1.00 |
| player / Shots on target / back | 36 | 0.32 | 0.60 | 0.00 to 1.00 |
| team / Both teams to score / exchange | 17 | 0.64 | 0.00 | 0.00 to 1.00 |
| team / Match goals / exchange | 17 | 0.69 | 1.00 | 0.00 to 1.00 |
| team / Match corners / exchange | 17 | 0.30 | 0.00 | 0.00 to 1.00 |
| team / Match cards / exchange | 17 | 0.34 | 0.62 | 0.00 to 1.00 |
| player / Goals / back | 13 | 0.35 | 0.00 | 0.00 to 1.00 |


**The evidence does not support one.** Out of sample, no rule beats Betfair's chance alone by more than
its own noise. The two that come out marginally ahead are the blend as used (-0.0017) and a fixed 50/50
log-odds blend (-0.0002); both intervals straddle zero comfortably. Every rule that fits weights from the
data (one weight, a weight by gap band, a weight by market) does **worse** out of sample than those fixed
rules, which is what overfitting on 307 lines looks like. The fitted weights tell the same story: every
interval for a market or a gap band spans most of 0 to 1. The single pooled weight that fits best puts
0.72 on Betfair (95% 0.20 to 1.00).

What the evidence does support, short of a rule:

* **When the site and Betfair are 15 points or more apart, Betfair has been right.** The page already
  refuses to call these value and flags them instead (`EXCHANGE_DISAGREE`). On 34 lines that choice looks
  correct.
* **Nothing supports trusting the site more than the current blend does anywhere.** No market, no gap
  band and no sport shows the site beating Betfair outside the noise.
* **Per-market weights are not yet estimable.** With 13 to 44 lines in every family but one, and
  intervals spanning 0 to 1, a per-family weight is noise. `exchange_eval.py fit` has already fitted
  weights of 0.0 and 1.0 (raw) for families with 17 lines, which it counted as 33 or 34 because it scores
  both sides of each line.

A rule could become supportable when there are several hundred verified lines per market and, for value,
a few thousand settled value bets or a long enough run of closing prices to show that flagged prices
shorten by more than the site's claimed edge.

## What would follow (not done here)

These are recommendations only. This branch changes no live behaviour.

1. Refit `exchange_weights.json` only on results confirmed by a post-match line-up, or re-settle the
   player lines in the log first. The current `SHOTS_ON_TARGET_P1` margin (0.284) and shots-on-target
   weight (0.114) are fitted on false zeros.
2. In `exchange_eval.py fit`, count each line once (over and under are the same bet), so `FIT_MIN = 30`
   means 30 lines, not 15.
3. Until the closing-line numbers turn positive, treat the page's value against Betfair as unproven.
   The simplest honest step would be to say so beside the figure; a stricter one would be to lean the
   blend further towards Betfair, which the pooled fit (0.72) points to without proving.
4. Keep logging. The closing-line test in 3b is the one to watch: it will give a verdict on value long
   before results do.

## Limitations

* Six days and 102 fixtures. Every family has one or two rounds in it, so a single odd weekend moves a
  family's numbers a long way.
* Chances are compared at first sighting (what the page showed) and, in 2a, at last sighting. The log
  keeps nothing in between and no true closing price, so "close" here is the last sighting before
  kick-off.
* The anchored chance takes off a lean measured on the same round's legs, so it is not fully
  out of sample. It scored no better than the raw model, so this does not flatter the site.
* Back-only Betfair chances depend on an estimated margin; derived team-goal chances depend on a
  Poisson model fitted to Betfair's match odds and goal lines. Both are Betfair's information, but not
  Betfair's own number. On the derived lines, the market's chance beat the site's anyway.
* `cache_backtest.tar.zst` needs the `zstandard` package to read; without it the audit reads only
  `cache/`, which on the machine that publishes holds more post-match line-ups than this checkout, so
  some set-aside player lines may become verifiable there.

## Reproducing

```
pip install zstandard        # only to read cache_backtest.tar.zst
python exchange_audit.py     # prints every table above
python -m pytest tests/test_exchange_audit.py
```
