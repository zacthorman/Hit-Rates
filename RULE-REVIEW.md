# Betting-rule review: which flags have earned their place?

Written 23 October 2026, following the exchange-log audit (`EXCHANGE-LOG.md`, branch `exchange-log`), which
found that the bets the page called value against Betfair were worth -3.9% at the closing price (95% -6.7%
to -1.7%). This review finds every rule on the site that calls a bet value, take, acceptable or a pick,
measures each one against what has settled, and changes the ones the evidence says lose money.

`python rule_review.py` prints every table below. It reads only.

## What changed

1. **The Betfair value claim is off.** The page no longer prints "value +n%" beside a pick, the "Value on
   Betfair" list stays empty, and `tonight.py` prints "no value" instead of a value figure
   (`weekend.VALUE_SHOW = None`, `make_index.py valueClaimed`, `tonight.py leg_row`). The figure is still
   worked out and logged, because the bad-price guard uses it and `exchange_eval.py` keeps tracking it. Setting
   `VALUE_SHOW` back to a number turns the claim on again, with every other filter unchanged.
2. **Paddy Power "Take" is gone.** `report.py verdictOf` no longer returns take. A price that beats our chance
   by 5% or more is now marked avoid, the same as a price 5% worse. The card estimate is never acceptable.
   "Best value at Paddy Power" lists only edges under 5%, so it no longer leads with lines the verdict marks
   avoid.
3. **Kept as they were:** the 15-point disagreement flag, the -5% bad-price guard, Paddy Power "Acceptable"
   and the headline picks. The first two hold up; the last two are not shown to lose (details below).

Page layout is unchanged: the same cards, badges and tooltips, fed different verdicts. The one visible
text change is the tooltip on avoid, which now gives the second reason, and the note under "Best value at
Paddy Power".

## Every rule that flags a bet

| Rule | Where | What it claims | Record it can be tested on | Verdict |
|---|---|---|---|---|
| "value +n%" beside a pick | `weekend.py:531` (`_exchange`), `make_index.py:816` (`exchangeLine`, `legRow`) | Blended chance at Betfair's back price, after 5% commission, worth over 0.5% | `exchange_log.json`, first and last sighting | **Loses at the close. Removed.** |
| "Value on Betfair" list | `weekend.py:1288` (`best_value`, `VALUE_MIN` 3%) | As above, 3% or more, with filters | `exchange_log.json` | **Loses at the close. Removed** (follows the claim). |
| tonight.py value figure | `tonight.py:129` | Prints the same figure, signed | as above | **Removed**, as on the index. |
| Disagreement flag | `weekend.py:376`, `:531` (`EXCHANGE_DISAGREE` 0.15) | Model 15+ points from Betfair: not value, flagged instead | `exchange_log.json` | **Holds. Kept.** |
| Bad-price guard | `weekend.py:1185` (`BAD_PRICE` -5%) | Out of the headline picks | `exchange_log.json` | **Holds. Kept.** |
| Paddy Power "Take" | `report.py:6340` (`verdictOf`); scored by `pplog.is_value` | Ours 50%+, beats the price by 5%+, five games+ | `pp-results.html`, every committed copy; `pplog/` where kept | **Loses, outside the noise. Removed.** |
| Paddy Power "Acceptable" | `report.py:6340` | Ours 50%+, price within 5% of fair | Only indirectly (calibration) | **Unproven. Kept.** |
| "Best value at Paddy Power" | `report.py:6602` (`ppBestHtml`) | Ours 50%+, beats the price | As take, for edges of 5%+ | **Capped below 5%** to match the verdict. |
| Headline picks (best bet, banker, double, acca, builder, parlay, fixture singles, player lines) | `weekend.py` `best_*`, `parlay.py` | Most likely to land at a fair price; no bookmaker price claimed | `best_bets.json`, results only | **Not shown to lose at their own price. Kept.** |

Not treated as flags, and left alone: the green colour on an edge of +3% or more (`report.py:6114 edgeHtml`,
`:6756 teamRowHtml`), which colours a number rather than recommending a bet; the "value" sort on the stat table
(`report.py:4230 valueEdge`), which orders rows by how far the projection moves the record; the strongest
lines (`report.py:6182`), which rank on chance with no price; and the blend weights and back-only margin in
`exchange_weights.json`, which the exchange-log audit already showed were fitted on false zeros and should be
refitted on verified results separately.

## How it was measured

* **The record.** `exchange_log.json` as committed on `oct21-work` (last written 21 Oct 22:31 UTC): every
  bet the site priced against Betfair with a back price, both sides, 16 to 21 October. Results are the
  audit's verified results (`exchange_audit.resolve`, which needs a post-match source for every player
  line). Paddy Power: every committed copy of `pp-results.html`. `pplog/` itself is gitignored and not in
  this checkout; where it exists, `rule_review.py` scores take and acceptable from it directly, before and
  after this change. Picks: `best_bets.json`.
* **Two measures.** The return: each flagged bet backed for one unit at the back price shown at first
  sighting, after 5% commission. And the closing value: what that price was worth at Betfair's chance at the
  last sighting before kick-off (median 34 minutes before, 90% within 84 minutes). The second needs no
  results, so it uses every flagged bet seen twice, settled or not, and it is the measure that can give a
  verdict on six days of data. A bet flagged as worth +4% that is really worth +4% shows as about +4% at the
  close, on average.
* **Intervals.** 95% percentile bootstraps resampling whole fixtures, as in the audit.
* **Held out.** Every choice about how to tighten a rule was made on fixtures that kicked off before
  19 October (252 bets, 30 fixtures) and is reported on 19 to 21 October (171 bets, 26 fixtures). The rule
  for adopting a tighter version was set before looking at the test fixtures: adopt it only if, on the
  training fixtures, it flags at least 10 bets seen at the close and the lower end of their closing-value
  interval is above zero; otherwise claim nothing.

## 1. Betfair value: the rules as they stood

| Rule | Bets | Site said | Betfair said | Seen at close | Worth at close | 95% | Won | ROI | 95% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Page: "value +n%" (blend over 0.5% at the back price) | 40 | +3.9% | -6.9% | 31 | -5.1% | -8.9% to -2.3% | 9/23 | -21.3% | -62.9% to +29.6% |
| Value on Betfair list (3%+, filters) | 24 | +5.3% | -7.7% | 18 | -6.9% | -12.4% to -2.5% | 3/12 | -53.0% | -100.0% to +3.4% |
| Held back by the 15-point disagreement flag | 27 | +21.3% | -13.7% | 26 | -12.0% | -17.3% to -7.0% | 4/13 | -24.8% | -83.5% to +44.0% |
| Every bet with a value figure | 297 | -8.9% | -8.9% | 265 | -9.7% | -11.9% to -7.7% | 87/162 | -4.5% | -11.9% to +3.5% |
| Bad-price guard: value below -5% (kept out of headline picks) | 180 | -14.4% | -10.9% | 166 | -12.3% | -14.7% to -9.7% | 45/78 | -3.6% | -26.3% to +23.8% |
| Let through by the bad-price guard (-5% or better) | 117 | -0.3% | -5.9% | 99 | -5.3% | -7.3% to -3.6% | 42/84 | -5.4% | -25.2% to +13.7% |

"Site said" is the blend's value figure; "Betfair said" is the same bet valued at Betfair's own chance at the
time. The "list" row applies every filter the log can see (3%+, no disagreement, ten games of record, back
price 1.25 to 6.0, not a count stat); the last-five check and one-per-fixture rule are not applied, and would
only shorten it.

**The value claim.** The 40 bets the page called value were worth -5.1% at the close (95% -8.9% to -2.3%),
not the +3.9% claimed. The list's stricter bar did no better (-6.9%). Results alone cannot separate these from
zero (ROI -21%, 95% -63% to +30%, on 23 settled), but the closing price can, and it excludes zero.

Raising the bar does not rescue it. Across the 265 bets with a value figure seen at the close, a bigger
claimed value does go with a better closing value (slope +0.46 per point, 95% +0.35 to +0.57; some of that
is mechanical, since both are worked out at the same back price), but the line through them reaches zero only
at a claimed value of about +11.5%. The largest claimed value in the log is +10.2%: the disagreement flag stops
anything bigger being priced, and section 1 shows it is right to.

**The disagreement flag holds.** The 27 bets it held back were the ones the blend rated highest (+21.3% on
average) and were worth -12.0% at the close (95% -17.3% to -7.0%), worse than anything the page did show.

**The bad-price guard holds.** The bets it keeps out of the headline picks were worth -12.3% at the close
against -5.3% for the ones it lets through; the intervals do not overlap. By results the two groups cannot
be told apart, which is expected on 78 and 84 settled bets.

## 2. Tightening the value flag, held out

| Rule | Period | Bets | Site said | Betfair said | Seen at close | Worth at close | 95% | Won | ROI | 95% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| As now: over 0.5% | train | 23 | +3.8% | -5.6% | 23 | -3.0% | -5.3% to -0.8% | 7/19 | -30.3% | -71.7% to +20.1% |
| As now: over 0.5% | test | 17 | +4.1% | -8.7% | 8 | -11.3% | -20.1% to -2.2% | 2/4 | +21.2% | -100.0% to +142.5% |
| Bar raised to 3% | train | 13 | +5.4% | -6.4% | 13 | -3.6% | -6.8% to -0.2% | 2/10 | -65.9% | -100.0% to -10.5% |
| Bar raised to 3% | test | 11 | +5.3% | -9.3% | 5 | -15.5% | -28.0% to -5.2% | 1/2 | +11.7% | -100.0% to +123.5% |
| Bar raised to 6% | train | 4 | +7.8% | -10.0% | 4 | -8.3% | -11.6% to -4.7% | 0/2 | -100.0% | -100.0% to -100.0% |
| Bar raised to 6% | test | 3 | +7.6% | -9.2% | 2 | -9.7% | -10.9% to -8.4% | 1/2 | +11.7% | -100.0% to +123.5% |
| Bar raised to 10% | train | 1 | +10.2% | -8.1% | 1 | -11.5% | - | 0/0 | - | - |
| Bar raised to 10% | test | 0 | - | - | 0 | - | - | 0/0 | - | - |
| Blend 1.00 on Betfair (fitted on train), over 0.5% | train | 0 | - | - | 0 | - | - | 0/0 | - | - |
| Blend 1.00 on Betfair (fitted on train), over 0.5% | test | 0 | - | - | 0 | - | - | 0/0 | - | - |
| Betfair's chance alone (claims nothing) | train | 0 | - | - | 0 | - | - | 0/0 | - | - |
| Betfair's chance alone (claims nothing) | test | 0 | - | - | 0 | - | - | 0/0 | - | - |

On the training fixtures no version of the flag had a closing value above zero, so the adoption rule picks
"claim nothing". The weight on Betfair that fits the training fixtures' results best is 1.00, which is the same
answer by another route: a blend that is all Betfair can never find value at the back price, because the chance a
back bet needs to break even after commission always sits above Betfair's own chance.

Before and after, test fixtures only (19 to 21 October):

| Value flag | Bets called value | Worth at close | 95% | Won | Profit |
|---|---:|---:|---:|---:|---:|
| Before | 17 | -11.3% | -20.1% to -2.2% | 2/4 | +0.85u |
| After | 0 | - | - | 0/0 | +0.00u |

The test period confirms the training result: the bets the old rule would have flagged were worth -11.3% at
the close. Its interval is wide (8 bets seen twice, one of them at -37%), and four settled bets happened to make
+0.85u, which is noise either way. The training result alone already excluded zero.

## 3. Paddy Power: take and acceptable

`pplog/` is not in this checkout, so take is measured from the scoreboard `pplog.py page` writes into
`pp-results.html`, which is committed on every update. Its "value bets" are the old take rule (ours 50%+, the
price beating it by 5%+, five games+), except that it leaves out football to-score and cards, which take
never called either, and that it predates the stale-data and basketball guards added on 21 October (those
turned take into acceptable, not into avoid). The totals are cumulative, so each row below is the bets settled
since the copy before. The copy of 21 Oct 00:41 is skipped: it graded players 0 from a pre-match line-up, and
a later settle revised those results (its 1,080 voids fell to 558), so it cannot be differenced against.

| Settled by | New bets | Won | Said | Hit (95%) | Profit | ROI | ROI 95% (approx.) |
|---|---:|---:|---:|---:|---:|---:|---:|
| 9678948 (Tue 20 Oct 10:06) | 23 | 11 | 68.0% | 47.8% (29.2% to 67.0%) | -4.3u | -18.7% | -50.3% to +14.0% |
| 7351df6 (Wed 21 Oct 23:31) | 154 | 46 | 62.3% | 29.9% (23.2% to 37.5%) | -56.4u | -36.6% | -50.8% to -20.4% |

The ROI interval is approximate: the page keeps totals, not each bet, so it is the Wilson interval on the hit
rate at the slice's average winning price. Not clustered by fixture, so somewhat too narrow.

By sport, everything settled by 21 Oct 23:31:

| Sport | Bets | Won | Said | Hit 95% | Profit | ROI |
|---|---:|---:|---:|---:|---:|---:|
| basketball | 112 | 36 | 63.9% | 24.2% to 41.3% | -35.9u | -32.1% |
| football | 42 | 10 | 57.9% | 13.5% to 38.5% | -20.5u | -48.8% |
| american-football | 23 | 11 | 67.6% | 29.2% to 67.0% | -4.3u | -18.7% |

**Take loses, outside the noise.** Bets called take won 57 of 177 against 63% said, ROI -34%. The first 23
alone could not show it (-19%, interval -50% to +14%); the 154 settled after them, which played no part in
the first look, made -37% (about -51% to -20%). It is not one sport: basketball and football both lose
heavily. Nor is it the line-up hazard: if every football loss among them had really been a win, they would
still have landed 89 of 177, 50% (95% 43% to 58%) against 63% said. An edge of 5% or more against Paddy
Power has, so far, meant our number was wrong.

Before and after, the 154 bets settled after the first copy: before, all 154 were called take, 46 won,
-56.4u. After, none is called take or acceptable; all 154 are marked avoid. No parameter was fitted to get
there (take was removed, not re-tuned), so there is nothing for the second slice to have been fitted on.

**Acceptable is unproven.** The page's totals do not split out acceptable bets, so they cannot be measured
here. The nearest evidence is how well ours is calibrated on every Paddy Power line, 50% and up:

| Settled by | Ours said | Lines | Hit | 95% |
|---|---:|---:|---:|---:|
| 9678948 (Tue 20 Oct 10:06) | 50-60% | 26 | 54% | 35% to 71% |
| 9678948 (Tue 20 Oct 10:06) | 60-70% | 25 | 76% | 57% to 89% |
| 9678948 (Tue 20 Oct 10:06) | 70-80% | 30 | 60% | 42% to 75% |
| 9678948 (Tue 20 Oct 10:06) | 80-90% | 15 | 100% | 80% to 100% |
| 9678948 (Tue 20 Oct 10:06) | 90-100% | 3 | 100% | 44% to 100% |
| 7351df6 (Wed 21 Oct 23:31) | 50-60% | 448 | 47% | 42% to 51% |
| 7351df6 (Wed 21 Oct 23:31) | 60-70% | 266 | 52% | 46% to 58% |
| 7351df6 (Wed 21 Oct 23:31) | 70-80% | 170 | 66% | 58% to 73% |
| 7351df6 (Wed 21 Oct 23:31) | 80-90% | 73 | 73% | 61% to 82% |
| 7351df6 (Wed 21 Oct 23:31) | 90-100% | 22 | 82% | 61% to 93% |

On the later and larger slice ours ran 8 to 13 points high from 50% to 90%, which would make a line that is
fair by our numbers lose 12 to 20% at Paddy Power's price. The earlier slice leaned the other way. That later
slice includes NBA opening night, when every record was last season's, which the stale-data warning now
flags. This points towards acceptable losing, but it is not a measurement of acceptable bets, and a
calibration fitted on one slice would have pointed the wrong way on the other. So acceptable is kept, and
`python rule_review.py` scores it directly, before and after, on the machine that keeps `pplog/`. That is the
next thing to run.

## 4. Headline picks

| Category | Settled | Said | Landed | Landed minus said | 95% | Return at fair price |
|---|---:|---:|---:|---:|---:|---:|
| Fixture single | 1668 | 70.2% | 71.8% | +1.6% | -0.8% to +4.0% | +2.8% |
| Player line | 315 | 69.4% | 76.5% | +7.2% | +3.0% to +11.4% | +10.7% |
| Pick: parlay | 128 | 30.9% | 29.7% | -1.2% | -16.0% to +15.3% | -3.8% |
| Pick: evens double | 126 | 50.4% | 53.2% | +2.7% | -6.6% to +12.5% | +5.5% |
| Pick: acca | 117 | 32.9% | 44.4% | +11.5% | +0.2% to +23.1% | +36.7% |
| Pick: single | 84 | 49.3% | 53.6% | +4.2% | -7.6% to +16.1% | +8.2% |
| Pick: banker | 77 | 72.0% | 68.8% | -3.1% | -15.3% to +8.3% | -3.7% |
| Pick: builder | 63 | 49.4% | 54.0% | +4.6% | -8.0% to +16.4% | +10.7% |

Settled tickets from 27 September to 21 October. "Said" is one over the ticket's fair price. No bookmaker
price is recorded with these, so neither profit nor closing value can be measured; the last column is the
return at the page's own fair price, which is break-even if the chance was right. No category lands less
often than it says by more than the noise; two (player lines, accas) land more often. A pick that lands
exactly as often as it says still loses the bookmaker's margin, so these show the chances are honest, not
that the picks make money. Kept as they are. The bootstrap clusters on each ticket's first fixture, which
understates the spread for multi-fixture accas.

## Limitations

* Six days of Betfair prices (16 to 21 October), 56 fixtures with a Betfair back price, almost all football. The held-out period is three days and 26 fixtures; its interval is wide.
* "Close" is the last sighting before kick-off, not a true closing price; the log keeps nothing later.
* The closing-value measure uses unsettled and unverified bets too, since it needs no result. The return
  uses verified results only.
* The Paddy Power evidence is from the scoreboard's totals, not each bet, and a slice of it may still hold
  results the pre-match line-up hazard got wrong; the worst-case line above allows for that in football.
* Turning the value claim off removes a signal that was wrong on average. It does not show that the model has
  no information: claimed value and closing value do move together. If the closing value of what the blend
  would flag turns positive on a few hundred more bets (`exchange_eval.py` keeps tracking it on the Market
  check page), set `weekend.VALUE_SHOW` back to a number and rerun this review.
* `exchange_audit.py` is copied unchanged from the `exchange-log` branch, for its settlement code. If that
  branch merges first the file is identical.

## Reproducing

```
pip install zstandard      # to read cache_backtest.tar.zst, as the audit does
python rule_review.py      # every table above
python -m pytest tests     # or: python -m unittest tests.test_rule_review
```
