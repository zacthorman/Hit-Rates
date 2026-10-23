# Team lines: does the take tier hold?

Written 23 October 2026 on the `teamline-check` branch. Reproduced by:

    python -B teamline_check.py record                    # the published record (best_bets.json)
    python -B teamline_check.py cache --cache <cache dir>  # the walk forward (about 2 minutes; needs requirements-dev.txt)
    python teamlog.py scoreboard                          # the Paddy Power team log, on the Mac

## The answer

**The take tier is unproven against real bookmaker prices, and this check does not change that.** No settled team-line take at a real bookmaker price exists anywhere in the repo:

- `pplog/team-*.jsonl` lives only on the Mac.
- `best_bets.json` has Betfair prices only for goals legs.
- `market_prices.json` is not committed.
- `exchange_log.json` covers nine matches, and only in markets that failed the backtest.

The Paddy Power team log only started recording the team model's chance and verdict on 22 October. Until `python teamlog.py scoreboard` has 50 or more settled takes in a market, nothing real has tested it.

On the evidence that does exist, the two markets come out differently. **The gate is left as it is**: the rule for tightening, fixed in advance (below), does not trigger for either market.

- **Shots on target (one side): holds against the stand-in book on the later months.** From June onwards its 618 takes landed 68.8% of the time against 65.4% said (got minus said +3.4%, 95% interval −0.7% to +7.5%). They returned +18.5% a line at the proxy book's price (+11.1% to +26.0%). That is the right way round, but the earlier months were weaker:
  - January to May: 4.5 points short of said (−7.8% to −1.4%), and a return of +4.9% (−0.9% to +10.4%).
  - TEAM-LINES.md already notes that the large later return says more about the stand-in book than about Paddy Power.
- **Corners (one side): does not land at its stated chance, and its return is not proven.**
  - **Shortfall in both periods.** Its takes fell short of the chance shown on them by about 4 points in both periods. From June on, 65.5% said and 61.3% landed: −4.1%, interval −7.6% to −0.8%, wholly below zero.
  - **Return spans zero.** From June on the return at the proxy book's price was +3.8%, but the 95% interval runs from −2.3% to +9.7%. The backtest's 90% interval (0.0% to 7.9%) only just cleared zero.
  - **The thinnest edges look worst.** At claimed edges of 5% to 10%, which is half the corner takes, the return was −1.9% (−8.2% to +4.8%) and the shortfall −5.3% (−9.1% to −1.4%).
  - **How to read the page.** A corners take is a lean, not a proven bet. Read the edge on one as roughly 4 to 5 points smaller than the page shows.

**Every other market is right to have failed.** Corners (match total) and cards (match total) takes fell 12 and 9 points short of said from June on, with intervals wholly below zero. Cards (one side) and fouls (one side) look better from June on, but they failed on the earlier months, when the threshold was chosen. As TEAM-LINES.md says, choosing them now would be choosing on the data meant to test them.

## The evidence that exists

### 1. Real settled records

| Source | What it holds | Usable for the take tier? |
|---|---|---|
| `pplog/team-*.jsonl` (`teamlog.py`) | Every Paddy Power team line from 21 October: price first and last seen, the team model's chance and the page's verdict (from 22 October), the result | Yes, and it is the only source that is, but it lives on the Mac. `python teamlog.py scoreboard` (below) does the check there. |
| `best_bets.json` | 1,273 settled football team lines the site published (picks, accas, fixture singles), 27 September to 23 October, with the chance shown and the result | Only as calibration of the published chance: these were picks, priced mostly before the team model was wired in, and none of the gated markets carries a bookmaker or exchange price (the 18 Betfair prices are all goals). |
| `exchange_log.json` | Betfair prices for match corners and match cards on 9 October games | Nine matches, both in failed markets; scored in TEAM-LINES.md (Betfair 0.666 v model 0.674 log loss on corners, 0.564 v 0.584 on cards). Decides nothing. |
| `bets.json` | Zac's logged bets | One team shots-on-target leg. Nothing to measure. |
| `pp-results.html`, `bets.html`, `best-bets-summary.html` | Results pages | Player lines and the published picks again; no team-line takes. |
| `market_prices.json` | Betfair prices for upcoming games | Not committed (gitignored), and never kept for finished games. |

**The published team legs, one line counted once however many tickets used it.** Said is the chance the site showed. The intervals on got minus said resample whole nights.

| Market | Passed | Lines | Nights | Said | Got (95%) | Got - said (95%, by night) | With a Betfair price |
|---|---|---|---|---|---|---|---|
| shots on target (one side) | yes | 277 | 24 | 68.5% | 75.5% (70.1% to 80.1%) | +6.9% (+2.5% to +14.4%) | 0 |
| cards (one side) | no | 277 | 23 | 68.7% | 70.8% (65.1% to 75.8%) | +2.1% (-2.8% to +7.2%) | 0 |
| shots (one side) | no | 238 | 23 | 69.3% | 73.1% (67.1% to 78.3%) | +3.8% (-2.5% to +11.8%) | 0 |
| corners (one side) | yes | 211 | 23 | 69.3% | 72.0% (65.6% to 77.7%) | +2.7% (-4.0% to +10.1%) | 0 |
| fouls (one side) | no | 42 | 9 | 70.7% | 66.7% (51.6% to 79.0%) | -4.1% (-15.1% to +7.6%) | 0 |

The site's published team legs landed at or above the chance shown. In the two passed markets: shots on target +6.9 points (+2.5 to +14.4), corners +2.7 points (−4.0 to +10.1). That is reassuring about the published picks, but **it is not a test of the take tier**:

- **Different selection.** These were lines picked for a high chance on the record, not lines picked for beating a price. Picking against a price is what gathers the model's errors.
- **Different pricer.** Most were priced before the team model priced team lines.
- **No price.** None has a bookmaker's price, so no return can be worked out.

### 2. The cache, out of sample

This uses the same walk forward as `teamline_backtest.py`. The team model is refitted every month from January 2026 on earlier matches only. Every side and match total is priced at five lines around its own average, and each line is priced against the proxy book: the linear game state fit with a 9% overround.

The take band is the page's: our chance 50% or more, and an edge from the market's threshold to the 30% cap. The passed markets use their gate threshold (5% for both). The failed markets are shown at 5%, to show what a take there would have done. This reproduces TEAM-LINES.md's take counts and returns exactly (corners 1,249 takes at +3.8%, shots on target 618 at +18.5%, June on). What it adds:

- 95% intervals rather than 90%.
- Got minus said, and got divided by said.
- The take band split by claimed edge.
- The book-free calibration of every likely line.

All intervals resample whole matches, 2,000 draws.

**Which months are held out.** The thresholds were chosen on January to May. June to 19 October (the end of the cache) is out of sample for the model and for the threshold. It did, however, decide which markets passed, because the gate required the threshold to hold there. So it is not untouched for the pass or fail choice. There is no newer cached data; the team log is the only fresh evidence.

#### The take band, market by market

Against the proxy book at a 9% overround. Passed markets at their gate threshold; failed markets at 5%, to show what a take there would have done. Said is the model's chance on the takes; got is how often they landed. 95% intervals resample whole matches.

| Market | Gate | Months | Takes | Matches | Said | Got (95%) | Got - said (95%) | Got / said (95%) | Claimed edge | Return (95%) |
|---|---|---|---|---|---|---|---|---|---|---|
| corners (one side) | take from 5.0% | Jan to May | 3122 | 1230 | 69.4% | 65.8% (64.1% to 67.4%) | -3.6% (-5.9% to -1.3%) | 0.948 (0.915 to 0.982) | +12.2% | +6.7% (+2.8% to +10.5%) |
| corners (one side) | take from 5.0% | Jun on | 1249 | 601 | 65.5% | 61.3% (58.6% to 64.0%) | -4.1% (-7.6% to -0.8%) | 0.937 (0.884 to 0.987) | +11.3% | +3.8% (-2.3% to +9.7%) |
| corners (match total) | failed (5% shown) | Jan to May | 1367 | 667 | 66.3% | 60.6% (58.0% to 63.2%) | -5.6% (-9.2% to -2.2%) | 0.915 (0.862 to 0.967) | +12.5% | +2.6% (-3.5% to +8.8%) |
| corners (match total) | failed (5% shown) | Jun on | 672 | 324 | 65.5% | 53.7% (49.9% to 57.5%) | -11.8% (-17.1% to -6.6%) | 0.820 (0.739 to 0.900) | +11.6% | -8.6% (-18.1% to +0.5%) |
| cards (one side) | failed (5% shown) | Jan to May | 645 | 536 | 64.7% | 61.4% (57.6% to 65.1%) | -3.3% (-7.4% to +0.6%) | 0.949 (0.886 to 1.009) | +10.3% | +4.3% (-3.0% to +11.4%) |
| cards (one side) | failed (5% shown) | Jun on | 448 | 364 | 63.7% | 64.3% (59.7% to 68.6%) | +0.5% (-4.0% to +5.1%) | 1.009 (0.937 to 1.080) | +10.8% | +11.3% (+3.3% to +19.7%) |
| cards (match total) | failed (5% shown) | Jan to May | 626 | 443 | 63.4% | 62.8% (58.9% to 66.5%) | -0.6% (-5.3% to +3.8%) | 0.990 (0.916 to 1.059) | +11.0% | +10.5% (+2.1% to +18.5%) |
| cards (match total) | failed (5% shown) | Jun on | 398 | 285 | 64.6% | 55.5% (50.6% to 60.3%) | -9.1% (-14.9% to -3.5%) | 0.859 (0.769 to 0.946) | +11.1% | -4.7% (-15.1% to +5.3%) |
| fouls (one side) | failed (5% shown) | Jan to May | 982 | 477 | 64.1% | 56.8% (53.7% to 59.9%) | -7.2% (-11.6% to -2.9%) | 0.887 (0.818 to 0.954) | +11.7% | -1.3% (-9.2% to +6.5%) |
| fouls (one side) | failed (5% shown) | Jun on | 613 | 320 | 62.6% | 61.8% (57.9% to 65.6%) | -0.8% (-5.8% to +4.7%) | 0.987 (0.907 to 1.074) | +10.6% | +9.4% (+0.2% to +19.4%) |
| shots on target (one side) | take from 5.0% | Jan to May | 1304 | 785 | 66.9% | 62.4% (59.8% to 65.0%) | -4.5% (-7.8% to -1.4%) | 0.933 (0.884 to 0.979) | +12.8% | +4.9% (-0.9% to +10.4%) |
| shots on target (one side) | take from 5.0% | Jun on | 618 | 384 | 65.4% | 68.8% (65.0% to 72.3%) | +3.4% (-0.7% to +7.5%) | 1.052 (0.989 to 1.115) | +11.9% | +18.5% (+11.1% to +26.0%) |
| shots (one side) | failed | Jan to May | 0 | - | - | - | - | - | - | - |
| shots (one side) | failed | Jun on | 0 | - | - | - | - | - | - | - |

#### Inside the take band, by claimed edge (passed markets, June on)

| Market | Claimed edge | Takes | Said | Got | Got - said (95%) | Return (95%) |
|---|---|---|---|---|---|---|
| corners (one side) | 5% to 10% | 642 | 67.3% | 62.0% | -5.3% (-9.1% to -1.4%) | -1.9% (-8.2% to +4.8%) |
| corners (one side) | 10% to 20% | 488 | 63.9% | 62.5% | -1.4% (-6.2% to +3.2%) | +11.3% (+2.7% to +19.6%) |
| corners (one side) | 20% to 30% | 119 | 62.0% | 52.9% | -9.0% (-17.9% to -0.6%) | +4.2% (-14.3% to +21.7%) |
| shots on target (one side) | 5% to 10% | 296 | 67.5% | 70.6% | +3.1% (-2.1% to +8.1%) | +12.5% (+3.5% to +20.7%) |
| shots on target (one side) | 10% to 20% | 242 | 63.7% | 68.6% | +4.9% (-0.9% to +10.9%) | +24.1% (+13.2% to +35.1%) |
| shots on target (one side) | 20% to 30% | 80 | 62.8% | 62.5% | -0.3% (-10.6% to +9.9%) | +23.8% (+2.8% to +44.5%) |

#### Other proxy books (passed markets, June on)

A sharper book (5%) or a softer one (12%) picks different takes from the same chances.

| Market | Overround | Takes | Said | Got | Got - said (95%) | Return (95%) |
|---|---|---|---|---|---|---|
| corners (one side) | 5% | 2132 | 67.4% | 62.9% | -4.6% (-7.3% to -1.8%) | +3.9% (-0.8% to +8.7%) |
| corners (one side) | 9% | 1249 | 65.5% | 61.3% | -4.1% (-7.6% to -0.8%) | +3.8% (-2.3% to +9.7%) |
| corners (one side) | 12% | 835 | 64.2% | 60.1% | -4.1% (-8.3% to -0.0%) | +3.7% (-3.5% to +11.0%) |
| shots on target (one side) | 5% | 969 | 67.3% | 71.3% | +4.0% (+0.3% to +7.5%) | +20.0% (+13.6% to +26.2%) |
| shots on target (one side) | 9% | 618 | 65.4% | 68.8% | +3.4% (-0.7% to +7.5%) | +18.5% (+11.1% to +26.0%) |
| shots on target (one side) | 12% | 445 | 64.1% | 67.2% | +3.1% (-1.7% to +8.2%) | +18.5% (+9.8% to +27.7%) |

#### Every line the model called 50% or more (no book), June on

The same months without picking against a price: how the model's chance runs on the likely side of a line in general.

| Market | Lines | Said | Got (95%) | Got - said (95%) |
|---|---|---|---|---|
| corners (one side) | 11839 | 71.2% | 69.5% (68.7% to 70.3%) | -1.7% (-2.6% to -0.8%) |
| corners (match total) | 5925 | 69.8% | 66.3% (65.1% to 67.5%) | -3.5% (-5.0% to -2.0%) |
| cards (one side) | 10470 | 76.7% | 77.8% (77.0% to 78.6%) | +1.1% (+0.4% to +1.8%) |
| cards (match total) | 5879 | 73.2% | 72.3% (71.1% to 73.4%) | -0.9% (-2.0% to +0.1%) |
| fouls (one side) | 5499 | 66.2% | 66.2% (64.9% to 67.4%) | -0.0% (-2.1% to +1.9%) |
| shots on target (one side) | 4968 | 71.2% | 71.4% (70.1% to 72.6%) | +0.2% (-1.3% to +1.9%) |
| shots (one side) | 4831 | 65.1% | 66.5% (65.2% to 67.9%) | +1.4% (-0.5% to +3.5%) |

#### The rule for tightening, applied (the rule is set out below)

- **corners (one side)**: no reason to tighten under the rule (neither interval lies wholly on the wrong side).
- **shots on target (one side)**: no reason to tighten under the rule (neither interval lies wholly on the wrong side).

## The rule for tightening

This was fixed before the numbers above were looked at, and written into `teamline_check.py`. A passed market's take tier is cut back only if, on the June-onwards takes:

- **(a)** the 95% interval of the return against the proxy book lies wholly below zero; or
- **(b)** the 95% interval of got divided by said lies wholly below 1 / (1 + threshold). A take at the threshold edge would then lose even at the proxy's price.

Applied:

- **Corners:** neither triggers.
  - Return: −2.3% to +9.7%.
  - Got / said: 0.884 to 0.987, against a bar of 0.952 at 5%. The upper end clears the bar, though not by much.
- **Shots on target:** clearly neither.

**So `teamlines_gate.json` is not changed.** Raising the corners threshold to avoid the weak 5% to 10% band would mean choosing it on the June-onwards months, the data meant to test it. That is the mistake TEAM-LINES.md warns against.

## What would settle it: the team log on the Mac

`python teamlog.py scoreboard` reads `pplog/team-*.jsonl` and, for each market and each of the page's verdicts, shows:

- **lines:** how many settled.
- **said and got:** the team model's chance, and how often the lines landed (Wilson 95% interval).
- **got minus said:** with a 95% interval resampling whole matches.
- **return at Paddy Power's price:** with a 95% interval.
- **price move:** first price seen against last, where positive means Paddy Power shortened it after we saw it.

It shows these at the last price seen before kick-off (the one the record settles on) and again at the first price.

It then gives one line per market, applying the same rule as above:

| Verdict shown | What it means | What to do |
|---|---|---|
| **too few settled takes to judge** | Fewer than 50 | Wait. |
| **losing** | (a) or (b) above holds on the real prices | Set that market's `"pass"` to `false` in `teamlines_gate.json` by hand, and revisit the backtest. |
| **holding** | The return's interval lies wholly above zero | The take tier has earned its place at Paddy Power's prices. |
| **no clear answer yet** | The interval spans zero | Keep logging. |

It also flags any line called take in a market that failed the backtest; there should be none.

Run it weekly. How soon a market reaches 50 settled takes depends on how many takes the page makes, which could not be counted from here; the scoreboard prints the count each time. In the cache, corners made about twice as many takes as shots on target, so it is likely to get there first.

## Limits

- **The proxy book is not Paddy Power.** Paddy Power knows the team news, the referee and its own traders' views. A take against the stand-in is easier to make than a take against them, so every cache return here is an upper bound on what the real takes will do.
- **The cache months are not fully fresh.** June onwards decided which markets passed. It is clean for the model and the threshold, not for the pass or fail choice.
- **The lines are the backtest's ladder** around each side's own average, close to Paddy Power's main lines but not their alternative lines further out.
- **The published record is picks, not takes.** It says the site's published team chances were, if anything, cautious. It says nothing about lines chosen for disagreeing with a price.

## Files

| File | What it is |
|---|---|
| `teamline_check.py` | `record` and `cache`. Reads `best_bets.json`, `teamlines_gate.json` and a cache folder (or a saved walk); writes nothing. Its interval helpers are pure Python so `teamlog.py` can use them on the Mac. |
| `teamlog.py scoreboard` | The real-price check. |
| `tests/test_teamline_check.py` | Synthetic data only. |

`teamline_backtest.py`, `teamlines_gate.json` and `TEAM-LINES.md` are unchanged. The walk was run through the backtest's own `build()` and `walk()`, and its `write()` was never called.
