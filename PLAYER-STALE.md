# Player lines on an old record

Written 24 October 2026 on the `player-stale` branch. Reproduced by:

    python -B acceptable_check.py build --cache <cache dir>      # the football replay, now with each line's fresh share
    python -B player_stale.py replay                             # the season-start test below
    python -B player_stale.py committed --cache <cache dir>      # the committed records

## What changed

**The gap.** The page's stale-data guard used `staleDays` (`run.py` `_sample_age`): the days since the newest match in *either team's* form. It lifted once each team had played one game of a new season, while a player's last ten could still be nine of last season's games, at last season's minutes and role. NBA-CHECK.md (zacthorman/Hit-Rates#22) found this on the NBA's first two nights.

**The measure** (`freshness.py`, mirrored in `report.py`):
- **His break.** A player's break is his most recent gap of 45 days or more, either between two of his games or between his last game and this kick-off. That is the summer, or a long injury.
- **The fresh share.** The share of the games his line is priced on that come after the break.
- **Mostly stale.** A record is mostly stale when that share is under 0.5.
- **National sides are left out.** Caps come in windows months apart, so every record would read as stale.

**What it does:**
- **`run.py`** carries each player's break date in the page data (`playerBreaks`, one map per side) and marks national fixtures (`fixture.national`).
- **The page** (`freshnessOf`) counts the fresh share over the window it actually priced: his last ten under the filters. For reports built before this change, it works the break date out from his records.
- **`verdictOf`, in every sport:** a player line on a mostly-stale record is never Acceptable. It is marked **Old record**, which has its own badge and tooltip.
  - Its row says, for example, "old record: 3 of 10 games since his break (16 Aug)".
  - Each player's Paddy Power and Bet365 summary counts these lines.
  - The Value tab's "Left off" note counts them.
  - Avoid and Long shot are unchanged and take precedence, so Old record only replaces what would have been Acceptable. Player lines were already never Take (RULE-REVIEW.md).
- **`rule_review.pp_verdict`** mirrors it (`fresh=`).
- **`pplog.py`** logs each new line's fresh share (`fresh`), and `is_value` no longer counts a mostly-stale line as value. Rows logged before today carry no share and are unaffected.
- **The fixture-level warning** (`staleWarning`) is unchanged.

## The answer

- **Before the line-up is known, lines on a mostly-stale record are clearly worse calibrated, and this held out of sample.**
  - In the football cache replay, on the seasons from 2025-26 (held out), lines we made 50% or more on a mostly-stale record landed 7.8 points below what we said. Fresh records landed 3.7 points below. The difference is −4.1 points (95% −4.6 to −3.7).
  - At a price fair by our numbers, the stale lines would have lost about 13% (52.7% landed against 60.6% said); fresh ones about 6%.
  - At the two season starts in the later data it held separately: August and September 2025, −2.2 points (−3.7 to −0.7); August and September 2026, −4.1 (−5.2 to −3.0).
- **Most of that is who starts.** Players on a mostly-stale record are more often substitutes (35% of substitute lines in the later seasons, against 24% of starter lines), and a substitute's line lands about 30 points below what we said whatever his record.
  - Among **starters** the difference is small: +2.6% against +3.3% on the later seasons, so −0.7 points (−1.1 to −0.2).
  - On the earlier seasons there is no difference among starters (−0.1 points, −1.9 to +1.6).
  - So in football, once a player is confirmed in the starting XI, an old record matters little. Before the line-up, it is a strong warning, partly because it signals he may not start.
- **The earlier seasons alone were not decisive.**
  - The share was meant to be chosen on seasons before 2025-26. It picked 0.3, but 0.3 and 0.5 scored −5.6% and −5.5% with intervals that overlap almost entirely.
  - Stale minus fresh on those seasons was −1.6 points (−3.4 to +0.2), not clearly below zero.
  - Those seasons hold 18,718 lines against 457,688 later, because the cache is weighted to autumn 2024 onwards.
  - The page keeps 0.5, the brief's "mostly", and it is confirmed on the later seasons as above.
- **The committed records cannot isolate staleness.**
  - Paddy Power's basketball value bets were all on old records: 635 bets, said 65%, landed 43%.
  - But football's mid-season value bets, on fresh records, did worse (46 bets, said 60%, landed 28%). Lines picked against Paddy Power's price fail whatever the record (RULE-REVIEW.md).
  - The published `best_bets.json` legs show stale minus fresh of −1.9 points (−7.6 to +6.1): no answer either way. Football leans the right way (stale −5.6%, fresh +2.8%) on only 80 stale lines.
- **NBA (NBA-CHECK.md, #22).** On opening night the site said 44% and 39% landed across all 561 Paddy Power lines on Spurs v Thunder, every record last season's. That is the case the rule is for. Whether a fresh NBA record is better calibrated cannot be measured from the repo, because no NBA box scores are committed. `nba_check.py cache` (#22) splits by how many of a player's ten games are this season's, on the Mac.

## The evidence

### 1. Committed records

#### Paddy Power value bets (pp-results.html, committed 22 Oct)

Basketball's settled value bets are all from the first two nights of the season, so every record behind them was nine or ten games of last season. Football's are from mid-season, on fresh records.

| Sport | Bets | Said | Got (95%) | Got - said |
|---|---|---|---|---|
| basketball | 635 | 65% | 43% (39% to 46%) | -23% |
| football | 46 | 60% | 28% (17% to 43%) | -31% |
| american-football | 23 | 68% | 48% (29% to 67%) | -20% |

#### Published player legs (best_bets.json)

1154 settled distinct player legs; the fresh share is known for 1054 (football and NFL rebuilt from the cache, which ends on 19 October; basketball from its dates). Intervals resample nights.

| Group | Lines | Said | Got (95%) | Got - said (95%) |
|---|---|---|---|---|
| american-football, mostly stale (share under 0.5) | 189 | 70.0% | 73.5% (66.8% to 79.3%) | +3.5% (-0.6% to +11.8%) |
| american-football, fresh (0.5 or more) | 87 | 65.9% | 71.3% (61.0% to 79.7%) | +5.4% (-21.0% to +19.6%) |
| basketball, mostly stale (share under 0.5) | 173 | 70.1% | 72.3% (65.2% to 78.4%) | +2.1% (-2.8% to +23.2%) |
| football, mostly stale (share under 0.5) | 80 | 70.6% | 65.0% (54.1% to 74.5%) | -5.6% (-11.7% to +7.8%) |
| football, fresh (0.5 or more) | 525 | 69.7% | 72.6% (68.6% to 76.2%) | +2.8% (-2.8% to +8.1%) |
| all sports, mostly stale | 442 | 70.2% | 71.5% (67.1% to 75.5%) | +1.3% (-1.7% to +7.1%) |
| all sports, fresh | 612 | 69.2% | 72.4% (68.7% to 75.8%) | +3.2% (-2.0% to +7.3%) |

Stale minus fresh, got - said: -1.9% (95% -7.6% to +6.1%).

### 2. The football cache, across season starts

476406 football player lines we made 50% or more, seasons 2020-21, 2021-22, 2022-23, 2023-24, 2024-25, 2025-26, 2026-27: 18718 choose (before 2025-26), 457688 confirm. Intervals resample matches.

#### Choosing the share, earlier seasons

| Share under | Stale lines | Said | Got | Got - said (95%) |
|---|---|---|---|---|
| 0.3 | 8713 | 61.2% | 55.6% | -5.6% (-7.1% to -4.2%) |
| 0.5 | 11841 | 61.2% | 55.7% | -5.5% (-6.7% to -4.3%) |
| 0.7 | 14572 | 61.2% | 56.1% | -5.1% (-6.1% to -4.1%) |

Chosen: 0.3.

#### Earlier seasons, at share under 0.3

| Group | Lines | Said | Got (95%) | Got - said (95%) |
|---|---|---|---|---|
| mostly stale | 8713 | 61.2% | 55.6% (54.5% to 56.6%) | -5.6% (-7.1% to -4.2%) |
| fresh | 10005 | 61.4% | 57.3% (56.4% to 58.3%) | -4.0% (-5.2% to -2.8%) |
| mostly stale, August and September | 656 | 61.5% | 58.5% (54.7% to 62.2%) | -2.9% (-8.8% to +3.1%) |
| fresh, August and September | 676 | 61.5% | 55.9% (52.2% to 59.6%) | -5.6% (-10.3% to -1.0%) |
| mostly stale, rest of the season | 8057 | 61.2% | 55.3% (54.3% to 56.4%) | -5.9% (-7.5% to -4.3%) |
| all stale: share 0 | 5281 | 61.4% | 53.5% (52.2% to 54.9%) | -7.9% (-9.9% to -5.9%) |

Stale minus fresh, got - said: -1.6% (95% -3.4% to +0.2%).

#### Later seasons (confirm), at share under 0.3

| Group | Lines | Said | Got (95%) | Got - said (95%) |
|---|---|---|---|---|
| mostly stale | 85433 | 60.5% | 51.3% (50.9% to 51.6%) | -9.3% (-9.7% to -8.8%) |
| fresh | 372255 | 60.6% | 56.9% (56.7% to 57.0%) | -3.8% (-4.0% to -3.6%) |
| mostly stale, August and September | 42588 | 60.5% | 53.4% (53.0% to 53.9%) | -7.1% (-7.7% to -6.4%) |
| fresh, August and September | 60484 | 60.8% | 58.3% (57.9% to 58.7%) | -2.5% (-3.0% to -2.0%) |
| mostly stale, rest of the season | 42845 | 60.6% | 49.1% (48.7% to 49.6%) | -11.4% (-12.2% to -10.8%) |
| all stale: share 0 | 41701 | 60.6% | 47.7% (47.2% to 48.2%) | -12.9% (-13.7% to -12.2%) |

Stale minus fresh, got - said: -5.5% (95% -6.0% to -5.0%).

#### Later seasons, at the page's share under 0.5

| Group | Lines | Said | Got (95%) | Got - said (95%) |
|---|---|---|---|---|
| mostly stale | 122873 | 60.6% | 52.7% (52.5% to 53.0%) | -7.8% (-8.2% to -7.4%) |
| fresh | 334815 | 60.6% | 57.0% (56.8% to 57.1%) | -3.7% (-3.9% to -3.5%) |

Stale minus fresh, got - said: -4.1% (95% -4.6% to -3.7%).

#### Starters and substitutes separately, at share under 0.5

Before the line-up is known the page cannot tell them apart; afterwards it can.

| Who | Seasons | Stale lines | Got - said (95%) | Fresh lines | Got - said | Stale minus fresh (95%) |
|---|---|---|---|---|---|---|
| starters | earlier | 9433 | +1.2% (-0.1% to +2.3%) | 5915 | +1.3% | -0.1% (-1.9% to +1.6%) |
| starters | later | 83844 | +2.6% (+2.2% to +3.0%) | 262551 | +3.3% | -0.7% (-1.1% to -0.2%) |
| substitutes | earlier | 2408 | -31.7% (-34.3% to -29.1%) | 962 | -32.9% | +1.2% (-3.3% to +5.4%) |
| substitutes | later | 39029 | -30.1% (-30.7% to -29.5%) | 72264 | -28.8% | -1.3% (-2.0% to -0.6%) |

#### Each season's August and September, at share under 0.5

| Season | Stale lines | Got - said | Fresh lines | Got - said | Stale minus fresh (95%) |
|---|---|---|---|---|---|
| 2024-25 | 762 | -5.0% | 570 | -3.3% | -1.6% (-8.9% to +5.4%) |
| 2025-26 | 12306 | -5.9% | 16555 | -3.7% | -2.2% (-3.7% to -0.7%) |
| 2026-27 | 49749 | -5.6% | 24462 | -1.5% | -4.1% (-5.2% to -3.0%) |

**Confirmed on the later seasons:** yes (stale got - said wholly below zero: yes; stale minus fresh wholly below zero: yes).

#### Later seasons, by fresh share

| Group | Lines | Said | Got (95%) | Got - said (95%) |
|---|---|---|---|---|
| 0 of 10 since the break | 41701 | 60.6% | 47.7% (47.2% to 48.2%) | -12.9% (-13.7% to -12.2%) |
| 1 of 10 since the break | 17889 | 60.4% | 54.9% (54.2% to 55.7%) | -5.4% (-6.5% to -4.4%) |
| 2 of 10 since the break | 24213 | 60.5% | 54.4% (53.8% to 55.0%) | -6.1% (-7.0% to -5.3%) |
| 3 of 10 since the break | 21410 | 60.6% | 55.0% (54.4% to 55.7%) | -5.6% (-6.5% to -4.7%) |
| 4 of 10 since the break | 17660 | 60.5% | 57.4% (56.7% to 58.1%) | -3.1% (-4.0% to -2.2%) |
| 5 of 10 since the break | 17651 | 60.6% | 57.1% (56.4% to 57.8%) | -3.5% (-4.4% to -2.5%) |
| 6 of 10 since the break | 17485 | 60.4% | 57.5% (56.8% to 58.3%) | -2.9% (-3.9% to -1.9%) |
| 7 of 10 since the break | 19715 | 60.7% | 55.2% (54.5% to 55.9%) | -5.5% (-6.4% to -4.5%) |
| 8 of 10 since the break | 21185 | 60.6% | 56.0% (55.3% to 56.7%) | -4.6% (-5.5% to -3.8%) |
| 9 of 10 since the break | 15368 | 60.5% | 56.4% (55.6% to 57.1%) | -4.1% (-5.1% to -3.1%) |
| 10 of 10 since the break | 243411 | 60.7% | 57.2% (57.0% to 57.4%) | -3.5% (-3.7% to -3.2%) |

## How the replay was done

- **The replay.** `acceptable_check.py build` already prices every football player line in the cache before kick-off the way `pplog.snapshot` does. That means:
  - his rows for his club in its last 38 cached matches;
  - `model.price_player` on his last ten appearances of 45 minutes or more;
  - `pplog._adjustment` for the opponent, fitted on earlier matches only;
  - to score as `pplog._score_chance`.

  It now also records, for each line, the fresh share of those ten (`freshness.py`) and the days since his previous game. This run had no fmodel replay, so every line uses the site's own record price. Overs only, as Paddy Power's football player lines are; players who did not play are left out.
- **Lines tested:** those we made 50% or more, the ones that could have been Acceptable.
- **Seasons** run from July. 2025-26 onwards confirm; earlier seasons choose. Intervals are 95% and resample whole matches.

## Limits

- **The cache does not hold every match for every team.** A "break" in the middle of a season can be cached matches missing rather than a real absence. That is why each season's August and September are shown on their own; it held in both later season starts.
- **Football only for the season-start test.** The cache has no NBA box scores, and NFL player lines are priced by the US model blend, which this replay does not reproduce. The rule applies to every sport because the problem is the same, and the NBA's opening night is where it was found.
- **Confirmed starters.** For football players confirmed in the starting XI, the evidence says an old record costs little (−0.7 points). Lifting the flag for confirmed starters would be a reasonable next step. It is not done here: the line-up is often only predicted, and the brief was that a mostly-stale record is never acceptable.
- **The share is coarse.** The by-share table shows 0 of 10 since the break is far worse than 1 to 3 of 10. A sliding discount by share would carry more information than a single cut. Not done; the cut is what the brief asked for.

## Files

| File | What it is |
|---|---|
| `freshness.py` | The break date, the fresh share and the 0.5 cut. Pure Python. |
| `run.py` | `player_breaks_for`: `playerBreaks` and `fixture.national` in the page data. |
| `report.py` | `breakDateOf`, `windowFreshness`, `freshnessOf`, `staleNoteHtml`; the "stale" verdict (Old record) in `verdictOf`, its badge, and the counts. |
| `rule_review.py` | `pp_verdict(fresh=)`, the Python mirror. |
| `pplog.py` | `fresh` on each new line; `is_value` skips mostly-stale lines. |
| `acceptable_check.py` | Two more fields per replayed line: `fresh` and `rest`. |
| `player_stale.py` | The tables above. |
| `tests/test_player_stale.py` | 13 tests on synthetic data. They include three that run the page's JavaScript in node: break dates against `freshness.py` on 400 random records, `verdictOf` against `pp_verdict` on 2,000 lines, and the label and the national-side exemption. A fourth checks that the rendered page script parses. |
