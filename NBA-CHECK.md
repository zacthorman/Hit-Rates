# NBA player lines: a check

Written 24 October 2026 on the `nba-check` branch. Reproduced by:

    python -B nba_check.py committed     # the basketball evidence in the repo
    python -B nba_check.py cache         # the Mac: NBA box scores in cache/, the early-season test
    python -B nba_check.py pplog         # the Mac: Paddy Power's settled basketball lines

## The answer

- **On lines picked against Paddy Power's price, the page is far too confident, and over the first two nights it lost heavily.**
  - The 112 settled Paddy Power basketball lines the log called value were said to land 64% of the time. They landed 32% (95% interval 24% to 41%) and lost 35.9 units, 32% a bet.
  - Points overs were the worst: said 65%, landed 12% (3 of 26).
  - Across all 561 Paddy Power lines on Spurs v Thunder, the site said 44% and 39% landed (Paddy Power implied 45%; `usmodel/training/results.md`).
  - All of these are from the first two nights of the season (20 and 21 October; the page was last updated 21 October 23:31), priced off last season's records.
- **The lines the site published as picks were not overconfident.** 156 settled published basketball player legs (all overs, alternative lines, said 60% to 80%) were said at 70.0% and landed 69.9% (got minus said −0.2%, 95% interval −7.8% to +7.9%). These are lines picked for a strong record at a low line, not for disagreeing with a price, and the same split shows on the team lines (TEAMLINE-CHECK.md, in zacthorman/Hit-Rates#19): picking against a price is where the model's errors gather.
- **By stat, the committed samples are too small to rank markets.** Two stand out with intervals wholly below zero, but on 9 and 10 lines:
  - Published threes landed 40% against 70% said.
  - Rebounds and assists landed 33% against 69%.
  - On Paddy Power's lines, points overs (12% of 26) is the clearest single failure.
- **Whether a season-start shrink helps could not be tested here,** because no NBA box scores are committed. The backtest cache holds one basketball line-up (a summer league game), and `pplog/` and `cache/` live on the Mac. The one split the committed data allows (fit on 20 October, score on 21 October) has 35 lines to fit on. It collapsed to the base rate and made the next night worse. It decides nothing.
- **So live pricing is not changed.** The rule fixed in advance (below) needs a shrink to beat the page's price on later games with the interval wholly below zero, both overall and on the early-season lines. That can only be checked on the Mac. `nba_check.py cache` does it in one command and prints the verdict.

**One gap in the code worth knowing about now.** The page never calls a basketball line Take on "stale" data. But `staleDays` (`run.py`, `_sample_age`) is the days since the most recent match in *either team's* form. So the guard is on for each team's first game of the season, and off from its second, while a player's last ten can still be nine of last season's games and last season's minutes.
- On each team's first game, the guard held its takes back.
- The 112 value bets above are pplog's own flag, which does not apply the page's guards.
- From each team's second game the stale guard no longer applies. The 30% edge cap and the page's other conditions for a Take still do.

This is not changed here, because there is no settled evidence on games after the guard lifts. It is the first thing the Mac run should look at: the "record: 0-2 / 3-5 this season" rows below.

## How a basketball player line is priced

1. **The record.** His last ten appearances of 12 minutes or more (`model.MIN_MINUTES_BY_SPORT`), whatever the season.
2. **The expected count.** His rate per minute times his median minutes in those ten, times the opponent adjustment from the team projection.
3. **The chance.** A count distribution around that (`model.prob_over`), then `calibrate_player()`. Basketball has no constants of its own (`PLAYER_CALIBRATION_BY_SPORT` is empty since 21 October, when an NBA fit was withdrawn), so it falls back to football's.
4. **Where the US model prices the line.** If `usmodel_live.py` has a number, the page uses the backtested NBA model instead, alone or blended with the record price (`usmodel/nba_meta.json`).
   - US-MODELS-AUDIT.md: the NBA side has never been audited, because no NBA box scores are in the repo.
   - Its single out-of-sample split was mostly play-offs.
   - On opening night the site's own price beat both the model and the blend against Paddy Power.
5. **The verdict.** `verdictOf` in `report.py`: no Take on stale data (over 60 days, as above), and none at an edge over 30%.

On opening night every record was last season's, weighted to play-off minutes. Nothing in steps 1 to 3 knows that: ten games from June count the same as ten from last week.

## The evidence in the repo

| Source | What it holds | Used |
|---|---|---|
| `pp-results.html` (committed 22 Oct) | Paddy Power value bets by market, settled, and a list of recent value bets with their records | Yes: the clearest evidence there is |
| `usmodel/training/results.md` | The opening-night check on all 561 Paddy Power lines of Spurs v Thunder | Quoted |
| `model.py` comment on `PLAYER_CALIBRATION_BY_SPORT` | At a player's median line, NBA overs landed 37% while the site said 57% (the withdrawn fit, 21 Oct) | Quoted |
| `best_bets.json` | 156 settled published basketball player legs, 20 to 21 October | Yes |
| `cache_backtest.tar.zst` | 30 NBA games in the team schedules, one line-up, no NBA box scores | No: nothing to replay |
| `pplog/`, `cache/` | Every Paddy Power line, and the NBA seasons `backfill.py` fetched | On the Mac only: `nba_check.py pplog` and `cache` |

### What the committed evidence says

#### Paddy Power value bets by market (pp-results.html)

Settled Paddy Power basketball lines the log called value (ours 50%+ and 5%+ over Paddy Power's price), page updated Wed 21 Oct 23:31. Won is rebuilt from the page's rounded hit rate.

| Market | Bets | Said | Won | Got (95%) | Profit |
|---|---|---|---|---|---|
| Points over | 26 | 65% | 3 | 12% (4% to 29%) | -18.3u |
| Rebounds over | 17 | 64% | 8 | 47% (26% to 69%) | -0.6u |
| Assists over | 15 | 67% | 7 | 47% (25% to 70%) | -0.6u |
| Rebounds and assists over | 13 | 62% | 7 | 54% (29% to 77%) | +3.0u |
| Three pointers made over | 10 | 63% | 3 | 30% (11% to 60%) | -4.1u |
| Points and rebounds over | 10 | 65% | 4 | 40% (17% to 69%) | -2.5u |
| Points rebounds and assists over | 7 | 68% | 2 | 29% (8% to 64%) | -3.3u |
| Steals over | 5 | 58% | 1 | 20% (4% to 62%) | -2.6u |
| Points and assists over | 3 | 65% | 0 | 0% (0% to 56%) | -3.0u |
| Rebounds under | 2 | 56% | 0 | 0% (0% to 66%) | -2.0u |
| Assists under | 1 | 50% | 0 | 0% (0% to 79%) | -1.0u |
| Blocks over | 1 | 51% | 1 | 100% (21% to 100%) | +1.1u |
| Rebounds and assists under | 1 | 59% | 0 | 0% (0% to 79%) | -1.0u |
| Points and rebounds under | 1 | 57% | 0 | 0% (0% to 79%) | -1.0u |
| **all basketball** | 112 | 64% | 36 | 32% (24% to 41%) | -35.9u (-32% a bet) |

#### The settled basketball value bets listed one by one (pp-results.html, Recent value bets)

Grouped by how much of his last ten the page's record rests on. These rows are a subset of the table above; the intervals resample nothing (one row each), so they are Wilson only.

| Group | Bets | Said | Got (95%) |
|---|---|---|---|
| all | 30 | 63.7% | 26.7% (14.2% to 44.4%) |
| last 5 hit 4 or 5 | 8 | 68.4% | 25.0% (7.1% to 59.1%) |
| last 5 hit 3 or fewer | 22 | 62.0% | 27.3% (13.2% to 48.2%) |

#### Published basketball player legs (best_bets.json)

156 settled lines the site published (player-line singles, parlays, doubles), all overs, each counted once, at the chance first shown.

| Group | Lines | Games | Said | Got (95%) | Got - said (95%, by game) |
|---|---|---|---|---|---|
| all | 156 | 14 | 70.0% | 69.9% (62.3% to 76.5%) | -0.2% (-7.8% to +7.9%) |
| night of 20 Oct | 35 | 3 | 68.4% | 77.1% (61.0% to 87.9%) | +8.8% (-8.0% to +33.6%) |
| night of 21 Oct | 121 | 11 | 70.5% | 67.8% (59.0% to 75.4%) | -2.8% (-11.3% to +5.3%) |
| Minutes | 38 | 14 | 70.4% | 76.3% (60.8% to 87.0%) | +6.0% (-11.0% to +20.9%) |
| Points and rebounds | 22 | 10 | 71.6% | 77.3% (56.6% to 89.9%) | +5.6% (-9.0% to +18.1%) |
| Rebounds | 19 | 11 | 68.3% | 63.2% (41.0% to 80.9%) | -5.1% (-24.1% to +9.3%) |
| Points | 17 | 11 | 70.2% | 76.5% (52.7% to 90.4%) | +6.3% (-20.4% to +30.5%) |
| Turnovers | 11 | 10 | 70.0% | 81.8% (52.3% to 94.9%) | +11.8% (-9.9% to +29.8%) |
| Steals and blocks | 10 | 8 | 71.2% | 80.0% (49.0% to 94.3%) | +8.8% (-14.4% to +27.4%) |
| Three pointers made | 10 | 9 | 69.9% | 40.0% (16.8% to 68.7%) | -29.9% (-59.3% to -2.1%) |
| Rebounds and assists | 9 | 8 | 68.6% | 33.3% (12.1% to 64.6%) | -35.2% (-67.6% to -1.6%) |
| Assists | 6 | 4 | 68.5% | 66.7% (30.0% to 90.3%) | -1.8% (-40.8% to +30.9%) |
| Points and assists | 6 | 5 | 68.8% | 83.3% (43.6% to 97.0%) | +14.6% (-28.2% to +32.4%) |
| Points rebounds and assists | 4 | 2 | 70.0% | 50.0% (15.0% to 85.0%) | -20.0% (-70.0% to +30.0%) |
| Steals | 4 | 4 | 71.2% | 75.0% (30.1% to 95.4%) | +3.8% (-42.9% to +30.3%) |
| alternative line | 156 | 14 | 70.0% | 69.9% (62.3% to 76.5%) | -0.2% (-7.8% to +7.9%) |
| said 60-70% | 73 | 14 | 67.7% | 69.9% (58.6% to 79.2%) | +2.2% (-8.9% to +11.8%) |
| said 70-80% | 83 | 13 | 72.2% | 69.9% (59.3% to 78.7%) | -2.3% (-13.2% to +8.8%) |
| record of 0 to 14 games | 16 | 9 | 71.7% | 62.5% (38.6% to 81.5%) | -9.2% (-30.1% to +27.5%) |
| record of 15 to 17 games | 35 | 10 | 70.0% | 74.3% (57.9% to 85.8%) | +4.3% (-13.6% to +22.1%) |
| record of 18 to 20 games | 105 | 13 | 69.8% | 69.5% (60.2% to 77.5%) | -0.3% (-10.3% to +12.1%) |

#### A shrink fitted on the earlier nights, scored on the last

Fitted on 35 lines from 20 Oct: b = 0.00 towards 77.1%. Scored on the 121 lines of 21 Oct: log loss 0.6228 as published, 0.6516 shrunk, difference +0.0287 (95% +0.0004 to +0.0634). Far too few lines to decide anything; shown because it is the only split the repo allows.

## The test to run on the Mac

`python -B nba_check.py cache` reads the NBA box scores in `cache/` (regular season, NBA Cup and play-offs, with summer league and pre-season left out, as the page does).

**What it prices.** Every player-game is priced as the page prices it, from his earlier games only, at three rungs around his last-ten median (75%, 100% and 125% of it, as `usmodel/training` does). The opponent adjustment is left at 1, so this tests the record price, not the team projection. Each line records:
- how many of his ten games are from this season (0-2, 3-5, 6-9 or 10);
- whether the game is in the first 21 days of a season;
- the days since his last game.

**Where it splits.** By default it fits on everything before the latest season's first game, which is all of last season including its own early weeks, when records were short. It scores this season so far. `--cut YYYY-MM-DD` moves the split.

**The page's price is reported first**, on the later games: said against got, with 95% intervals by game, overall, for the first 21 days, by record group, for players whose last game was 60 or more days before, by stat, and by band of stated chance. The same table follows for the earlier games.

**Two shrinks** are fitted on the earlier games only and scored on the later ones:
- **rate:** his rate per minute pulled towards his position's (G, F, C) with weight m / (m + K), where m is his minutes in the record and K is chosen from a fixed grid. It is then priced exactly as the page prices.
- **logit:** the page's chance pulled towards the stat's base rate, b × logit(p) + (1 − b) × logit(base), with one b per record group.

**The rule, fixed before any number was seen.** A shrink earns a change to live pricing only if all three of these hold on the later games:
- its log loss beats the page's, with the 95% interval of the difference (by game) wholly below zero, on all lines;
- the same on the early-season lines;
- no record group gets worse with an interval wholly above zero.

The script prints the verdict, and saves the fit to `cache/nba_check.json` (gitignored), never to a tracked file.

**If a shrink holds, the next step is a pull request,** not an edit on the Mac. The rate shrink is the one to prefer, because it is the honest version of the problem: stale minutes and a short record are rate problems. It would go into `model.price_player`'s basketball path and its mirror `pricePlayer` in `report.py`, with the Python and JavaScript parity checks (`verify.py`) run on it. Then `nba_check.py pplog` checks it at Paddy Power's real lines before it goes live. Until then nothing changes.

**When to run it.** Now, for a first read, then again after two or three weeks of the season, when this season's early-weeks lines number in the thousands rather than the hundreds.

## The scoreboard

`python -B nba_check.py pplog` reads the settled Paddy Power basketball lines in `pplog/`, at the chance and price first seen. It shows said against got, with 95% intervals by game:
- every line;
- pplog's value bets;
- overs and unders;
- week by week since the first line;
- by stat;
- by band of stated chance;
- the value bets' return at Paddy Power's price, with its interval.

If `nba_check.py cache` has been run, it also scores the cache's logit shrink on the Paddy Power overs with fewer than ten games behind them. That is a check at real lines, not a refit.

Read it weekly. Two things to watch:
- **Points overs among the value bets.** If they keep landing near 12% against 65% said, the market should be held at "acceptable" by hand, as US-MODELS-AUDIT.md already advises for the five blended NBA markets.
- **The weekly said-against-got rows.** If the gap closes once records are this season's, the problem was the season start and no permanent shrink is needed. If it stays, it is the model.

## Limits

- **Opening nights only.** Almost all the committed settled evidence is from 20 and 21 October. Every number above describes a season opener priced off last season, which is exactly the case in question, but not the season in general.
- **Value bets are the hardest test.** They are lines picked for disagreeing with Paddy Power, so they gather the model's errors. The 32% says the page's chance should not be trusted against Paddy Power's price on opening night. It does not say every NBA line is 30 points too high.
- **The pp-results figures are rebuilt from rounded hit rates** on a committed page, so a count can be out by one.
- **The cache test leaves out the opponent adjustment and the US model.** It tests the record price that every line starts from. The US model's own audit is US-MODELS-AUDIT.md section 8.

## Files

| File | What it is |
|---|---|
| `nba_check.py` | `committed`, `cache` and `pplog`. Pure Python (the `model`, `hitrates` and `markets` modules), so it runs on the Mac without the training packages. It writes nothing but `cache/nba_check.json`. |
| `tests/test_nba_check.py` | 14 tests on made-up data: a two-season cache in SofaScore's shape with one player whose minutes fall from 36 to 24, a pp-results page, best_bets legs and pplog rows. |

`model.py`, `report.py`, `usmodel/` and the live pipeline are unchanged.
