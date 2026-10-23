# Paddy Power "Acceptable": does it hold?

Written 23 October 2026 on branch `acceptable-check`, which builds on `rule-review`. `RULE-REVIEW.md` left
"Acceptable" (ours 50% or more, the price within 5% of fair) unproven, because the record that would test it,
`pplog/`, is not committed. This replays it on the cache instead and, separately, adds a scoreboard that
measures it directly from `pplog/` on the Mac.

## The verdict, plainly

1. **For starters, Acceptable holds.** Every football starter line we made 50% or more, replayed before
   kick-off the way pplog prices it, landed slightly *more* often than we said: +3.2 points before September
   (95% +3.0 to +3.5) and +2.9 from September (+2.3 to +3.5). Backed at the fair price that is +5.0% and
   +4.4%; at the worst price the tier allows (5% short of fair) about break-even (-0.3% and -0.8%). Read as
   "about fair", the label is honest for starters.
2. **Except on four lines, where our number runs high, and they are now long shots.** Fouls 2+, fouled 2+,
   fouled 3+ and tackles 2+ landed 7.6 points under what we said before September and 7.3 under from
   September (95% -8.6 to -5.9): a price fair by our numbers lost 13.2% (-15.6% to -10.7%) on the later
   months. Those four were picked on the earlier months only. Taking them out of Acceptable left the rest
   returning +7.6% at fair on the later months, against +4.4% for the tier as it was. `verdictOf` now calls
   them long shots (`RUNS_HIGH` in `report.py`, mirrored in `rule_review.pp_verdict`).
3. **Assists 1+ runs very high too, but on too few lines to have been picked.** Said 53%, landed 22% before
   September and 20% after (264 and 59 lines, both intervals far below zero). The fitted rule needed 500
   lines in the earlier months to judge a line, so it was not chosen, and nothing changes for it here. It
   is the next candidate, and the case is strong.
4. **For a player who comes off the bench, every tier is far too high.** Lines we made 50% or more for
   players who came on landed 31% before September and 33% after, against 60% said: about -50% at fair.
   Our chance is a starter's chance; a substitute plays a fraction of the match. Whether that costs money
   depends on Paddy Power's rule. `SCORER-AUDIT.md` says Paddy Power voids a non-starter's bet, in which case
   it costs nothing. `pplog.py` settles a substitute who came on as a live bet, so if the bet stands, these
   lines lose. Not changed: the page cannot know before kick-off who will start unless the line-up is
   confirmed, and the rule needs checking first (see "What would follow").
5. **Long shot holds as a warning.** Starter lines under 50% landed 7.4 points under what we said before
   September and 4.1 under after. A long shot is worse than our number, as the label implies.
6. **Avoid holds where it can be priced.** On the 568 starter lines with a committed Betfair back price
   that the verdict marks avoid, ours said 13.1% and 13.4% landed: our chance was right and the price was
   short, so backing them lost 44%. Only 6 starter lines with a price were acceptable (4 won), too few to
   read.

Sport by sport: this is a football check. The cache holds no basketball. NFL player lines on the page are
priced by the US model blend, not pplog's path, and `US-MODELS-AUDIT.md` covers that blend: its chance is
within two points of what landed on every NFL market, but too confident on the yards markets (calibration
slopes 0.63 to 0.87). So an NFL acceptable at 50% or more on yards is likely to land a little under what
it says. Not measured here by tier.

## How it was done

`python -B acceptable_check.py fmodel` and `build` replay the cache, and `python -B acceptable_check.py
report` prints every table below. On the Mac, `cache/` is already in place.

* **The lines.** Paddy Power's football player menu as pplog reads it (`pplog.PP_PATTERNS`): shots 1+ to 3+,
  shots on target 1+ and 2+, fouls 1+ and 2+, fouled 1+ to 3+, tackles 1+ and 2+, assists 1+, to score.
  Overs only, as Paddy Power's football player lines are. Every player who played, in every cached match.
  A player who did not play is left out, because Paddy Power voids those bets. Cards are left out: the card
  estimate is never acceptable, and the cache has no card incidents to settle it.
* **Our chance, as pplog works it out.** `model.appearances` over his rows for his club in its last 38
  matches, then `model.price_player` on the last ten (three at least), as `pplog.snapshot` does; to score is
  `pplog._score_chance`. The opponent adjustment is `pplog._adjustment` itself, on an entry rebuilt the way
  `run.py` builds one: team records from the cache, and for a league match the projection from
  `hitrates.league_ratings` and `project_fixture`, fitted each week on earlier matches only. That is the
  method `case_score_backtest.Current` uses for goals, extended to shots, shots on target, fouls and tackles.
  fmodel replaces the chance where pplog would use it: football starters, to score, shots and shots on target.
  It is replayed through `fmodel_live.features` and `scorer_audit.score_fast`. fmodel was trained to the end
  of June 2026, so a line it would have priced before July is dropped rather than scored on an in-sample
  number. The replayed fmodel chances land within about a point of what happened on every line, as in
  `SCORER-AUDIT.md`.
* **Settling.** From the match's own player statistics. A stat is settled only where the players' total is
  more than half the team's, so a match whose feed left a stat out is not read as zeros (the Truffert fault
  in `hitrates._player_stat_values`).
* **Prices.** There is no Paddy Power price history in the repo. So a line is measured against its fair
  price (one over our chance): how often it landed against what we said, and what it would have returned
  at the fair price and at 5% either side, the range Acceptable allows. The only committed player prices are
  the Betfair back lists in each commit of `market_prices.json` (to score, shots on target 1+ and 2+,
  16 to 21 October). These are priced much like a bookmaker's list. Where a replayed line has one, the
  page's own verdict is applied at it (table G).
* **Which matches.** The competitions the site builds reports for (`case_score_backtest.REPORT_TIDS`), so
  the ones pplog prices; every competition is shown once in table A as a check. The cache is thin before
  mid-2025, so most lines are from August 2025 on.
* **Fit and confirm.** Every change was chosen on matches before 1 September 2026 and checked on matches
  from 1 September to 19 October 2026 (561 report-competition matches). Four kinds of change were tried, all
  fitted on the earlier months:
  - a higher floor on our chance;
  - dropping the stat-lines that ran high, with their whole interval below zero on at least 500 lines;
  - one Platt map on our chance;
  - the tier as it stands.

  The one with the best return at fair on the earlier months was tried. It would be adopted only if, on
  the later months, the lines it takes out still ran high (interval wholly below zero) and the lines it
  keeps returned at least as much as the tier as it stands.
* **Intervals.** 95% percentile bootstraps resampling whole matches, because one match's lines win and
  lose together.

**One change of method, stated.** The first version of the adoption test fired only if the whole tier lost
on the later months. It does not lose there for starters, so that test adopted nothing. That test answers
whether to scrap Acceptable, not whether to tighten it, so after the first run I replaced it with the test
above. The candidates, the fit months and the choice by earlier-month return were unchanged, and the
earlier-month choice was the same stat-line rule either way. Both versions are described here so the change
can be judged.

## What changed

- `report.py verdictOf`: football fouls, fouled and tackles at 2+ (overs, player lines) are long shots, never
  acceptable (`RUNS_HIGH`). The profile ladder now passes each rung's stat and line to the verdict so the
  rule reaches it. The long shot tooltip names the second reason. Nothing else in the verdict moved: team
  lines keep their backtested gate, and no layout changed.
- `rule_review.py`: `pp_verdict` mirrors the new rule. `python rule_review.py acceptable [--pplog DIR]` is the
  acceptable scoreboard for the Mac. It gives every settled pplog line the verdict the page gives it now,
  at the price first seen. It reports landed against said and the return with 95% intervals, by verdict, by
  earlier and later half of the record, and, for acceptable, by sport, stat, price band and source, plus how
  often the price shortened. The full `python rule_review.py` includes it whenever `pplog/` is present.
- `acceptable_check.py`: the replay and these tables. Its rows go to `cache/acceptable_rows.json.gz`
  (gitignored).
- `tests/test_acceptable_check.py`: 11 tests. They cover the replay on a small cache written in SofaScore's
  shapes (priced as pplog prices, voids and uncovered stats skipped, fmodel only out of its training years),
  the sums, the adoption test both ways, the page's `verdictOf` run in node against the Python mirror, and
  the scoreboard and its command.

## What would follow (not done here)

1. **Run `python rule_review.py acceptable` on the Mac.** It is the direct test: real Paddy Power prices, all
   sports, the NBA included. If acceptable loses there where this replay says it holds, the replay's
   population (every starter in report competitions) is not the population Paddy Power prices.
2. **Assists 1+**: on these numbers it should join the runs-high lines; it needs a few more weeks to clear
   the 500-line bar honestly, or a decision to take it on 323 lines.
3. **Substitutes**: check Paddy Power's rule for a player who starts on the bench and comes on. If the bet
   stands, the page should not give any verdict better than long shot to a player outside a confirmed XI.

## Limits

- Football only, and only lines that stood. The replay prices every player who played, but Paddy Power
  lists only some of them, and the ones it lists may differ from the average starter.
- No real prices outside table G. "Return at fair" is what the tier would make if Paddy Power priced at our
  fair price; their real prices carry a margin and know things we do not, and the take record
  (`RULE-REVIEW.md`) shows they win where they disagree with us by 5% or more. This check says our chance
  is honest for starters at 50% to 75% on most lines. It cannot say Paddy Power's price will be within 5%
  of it.
- The page's football shots and shots on target chance for a player fmodel does not cover goes through the
  scorer audit's map (`siteCalibrated`); pplog and this replay use the raw `price_player`. Starters are
  covered by fmodel from July, so this touches mainly substitutes and earlier months. The page also scales a
  player's line by the match odds in cross-league games (`crossLeagueModel`), which pplog does not; those
  games are priced with no adjustment here.
- The projection is refitted weekly rather than daily, and a player's record is his rows for his current
  club only, as on the page.

## Reproducing

```
pip install -r requirements.txt zstandard
python -B acceptable_check.py fmodel      # fmodel over cache/, about 12 minutes
python -B acceptable_check.py build       # about 5 minutes
python -B acceptable_check.py report
python rule_review.py acceptable          # on the Mac, against pplog/
python -m unittest tests.test_acceptable_check
```

The `fmodel` command runs `fmodel_live.history()`, `fmodel_live.features(M, T, P, set(), emit=set(M.match))`
and `scorer_audit.score_fast`, as `scorer_audit.build` does. Here the cache was `cache_backtest.tar.zst`,
extracted outside the repo and passed with `--cache`, with `--fmodel` and `--rows` pointing outside it too.

## The tables

1,367,966 replayed lines from 6,223 matches, 13 Jun 2021 to 19 Oct 2026. 1,075,765 lines from 4,373 matches are in the competitions the site reports on, 737,416 of them for starters; the tables use those unless they say otherwise. Fit: matches before 01 Sep 2026; confirm: from that date.

### A. Each tier, starters and substitutes who came on

| Competitions | Player | Tier | Period | Lines | Matches | Said | Landed | Landed minus said | 95% | Return at fair | 95% | At fair -5% / +5% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Report competitions | started | acceptable band (ours 50%+) | fit | 183,203 | 3,812 | 60.8% | 64.1% | +3.2% | +3.0% to +3.5% | +5.0% | +4.5% to +5.5% | -0.3% / +10.2% |
| Report competitions | started | acceptable band (ours 50%+) | confirm | 34,537 | 561 | 62.4% | 65.3% | +2.9% | +2.3% to +3.5% | +4.4% | +3.4% to +5.5% | -0.8% / +9.7% |
| Report competitions | started | long shot (under 50%) | fit | 416,454 | 3,812 | 26.7% | 19.4% | -7.4% | -7.5% to -7.2% | -30.1% | -31.0% to -29.2% | -33.6% / -26.6% |
| Report competitions | started | long shot (under 50%) | confirm | 103,222 | 561 | 22.8% | 18.8% | -4.1% | -4.4% to -3.7% | -16.9% | -19.3% to -14.4% | -21.0% / -12.7% |
| Report competitions | came on | acceptable band (ours 50%+) | fit | 78,668 | 3,694 | 60.3% | 30.5% | -29.8% | -30.2% to -29.4% | -50.3% | -51.0% to -49.6% | -52.8% / -47.8% |
| Report competitions | came on | acceptable band (ours 50%+) | confirm | 12,140 | 558 | 60.2% | 32.6% | -27.6% | -28.6% to -26.6% | -46.7% | -48.4% to -45.1% | -49.4% / -44.1% |
| Report competitions | came on | long shot (under 50%) | fit | 214,496 | 3,698 | 27.5% | 6.8% | -20.7% | -20.8% to -20.5% | -72.6% | -73.5% to -71.6% | -73.9% / -71.2% |
| Report competitions | came on | long shot (under 50%) | confirm | 33,045 | 558 | 27.8% | 7.4% | -20.5% | -20.9% to -20.1% | -70.9% | -73.2% to -68.6% | -72.3% / -69.4% |
| Every competition | started | acceptable band (ours 50%+) | fit | 233,274 | 5,437 | 60.9% | 64.0% | +3.2% | +2.9% to +3.4% | +4.9% | +4.5% to +5.3% | -0.3% / +10.2% |
| Every competition | started | acceptable band (ours 50%+) | confirm | 43,411 | 768 | 62.4% | 65.3% | +2.9% | +2.4% to +3.4% | +4.4% | +3.6% to +5.3% | -0.8% / +9.6% |
| Every competition | started | long shot (under 50%) | fit | 537,395 | 5,450 | 26.7% | 19.5% | -7.2% | -7.4% to -7.1% | -29.3% | -30.0% to -28.6% | -32.8% / -25.7% |
| Every competition | started | long shot (under 50%) | confirm | 129,356 | 770 | 22.9% | 18.9% | -4.0% | -4.3% to -3.7% | -16.4% | -18.7% to -14.2% | -20.6% / -12.2% |
| Every competition | came on | acceptable band (ours 50%+) | fit | 99,208 | 5,191 | 60.4% | 30.7% | -29.6% | -30.0% to -29.3% | -50.0% | -50.5% to -49.4% | -52.5% / -47.5% |
| Every competition | came on | acceptable band (ours 50%+) | confirm | 15,455 | 764 | 60.3% | 32.7% | -27.6% | -28.5% to -26.7% | -46.8% | -48.2% to -45.3% | -49.4% / -44.1% |
| Every competition | came on | long shot (under 50%) | fit | 268,288 | 5,205 | 27.6% | 7.0% | -20.6% | -20.7% to -20.4% | -71.7% | -72.5% to -70.8% | -73.1% / -70.2% |
| Every competition | came on | long shot (under 50%) | confirm | 41,579 | 766 | 28.0% | 7.5% | -20.5% | -20.9% to -20.2% | -70.2% | -72.4% to -68.2% | -71.7% / -68.7% |

### B. The acceptable band by stat and line (starters)

| Stat | Line | Period | Lines | Matches | Said | Landed | Landed minus said | 95% | Return at fair | 95% | At fair -5% / +5% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Tackles | 1+ | fit | 52,254 | 3,809 | 64.0% | 72.8% | +8.8% | +8.4% to +9.2% | +14.1% | +13.5% to +14.8% | +8.4% / +19.8% |
| Tackles | 1+ | confirm | 7,511 | 561 | 63.4% | 71.9% | +8.6% | +7.5% to +9.7% | +13.9% | +12.1% to +15.6% | +8.2% / +19.6% |
| Fouls | 1+ | fit | 45,517 | 3,805 | 60.0% | 65.5% | +5.5% | +5.0% to +5.9% | +9.4% | +8.6% to +10.1% | +3.9% / +14.8% |
| Fouls | 1+ | confirm | 6,364 | 561 | 59.6% | 64.3% | +4.7% | +3.6% to +5.8% | +7.9% | +6.1% to +9.8% | +2.5% / +13.3% |
| Fouled | 1+ | fit | 39,920 | 3,800 | 60.7% | 65.5% | +4.8% | +4.3% to +5.2% | +7.6% | +6.8% to +8.4% | +2.2% / +13.0% |
| Fouled | 1+ | confirm | 5,775 | 561 | 60.6% | 65.9% | +5.3% | +4.1% to +6.5% | +8.6% | +6.5% to +10.6% | +3.2% / +14.1% |
| Tackles | 2+ | fit | 20,938 | 3,763 | 57.4% | 52.5% | -4.9% | -5.6% to -4.2% | -8.6% | -9.9% to -7.4% | -13.1% / -4.0% |
| Tackles | 2+ | confirm | 2,760 | 558 | 57.1% | 52.1% | -5.0% | -6.8% to -3.1% | -8.9% | -12.0% to -5.5% | -13.5% / -4.4% |
| Fouled | 2+ | fit | 9,053 | 3,437 | 56.3% | 48.6% | -7.7% | -8.8% to -6.7% | -14.3% | -16.1% to -12.4% | -18.6% / -10.0% |
| Fouled | 2+ | confirm | 1,276 | 523 | 56.2% | 48.8% | -7.4% | -10.1% to -4.9% | -13.9% | -18.6% to -9.2% | -18.2% / -9.6% |
| Fouls | 2+ | fit | 8,256 | 3,230 | 55.1% | 41.5% | -13.6% | -14.7% to -12.6% | -24.7% | -26.7% to -22.9% | -28.5% / -20.9% |
| Fouls | 2+ | confirm | 1,044 | 466 | 55.1% | 42.0% | -13.1% | -15.9% to -9.8% | -23.7% | -28.9% to -17.9% | -27.5% / -19.9% |
| Shots | 1+ | fit | 3,257 | 375 | 72.9% | 72.1% | -0.8% | -2.3% to +0.8% | -1.5% | -3.8% to +0.9% | -6.4% / +3.4% |
| Shots | 1+ | confirm | 5,401 | 561 | 73.0% | 74.2% | +1.3% | +0.1% to +2.4% | +1.7% | -0.1% to +3.3% | -3.4% / +6.8% |
| Shots | 2+ | fit | 1,245 | 360 | 63.6% | 66.0% | +2.5% | -0.2% to +5.0% | +3.9% | -0.4% to +8.1% | -1.3% / +9.1% |
| Shots | 2+ | confirm | 2,107 | 555 | 63.4% | 65.2% | +1.8% | -0.3% to +3.7% | +2.6% | -0.8% to +6.0% | -2.5% / +7.8% |
| Shots on target | 1+ | fit | 1,026 | 354 | 59.9% | 58.7% | -1.2% | -4.2% to +1.8% | -2.0% | -7.3% to +3.2% | -6.9% / +2.9% |
| Shots on target | 1+ | confirm | 1,626 | 542 | 59.7% | 62.2% | +2.5% | +0.3% to +4.7% | +4.2% | +0.5% to +8.1% | -1.0% / +9.4% |
| Fouled | 3+ | fit | 1,222 | 1,040 | 55.6% | 43.8% | -11.9% | -14.4% to -9.0% | -21.9% | -26.4% to -16.7% | -25.8% / -18.0% |
| Fouled | 3+ | confirm | 192 | 168 | 55.0% | 47.4% | -7.6% | -14.4% to -1.2% | -13.5% | -26.0% to -1.7% | -17.8% / -9.2% |
| Shots | 3+ | fit | 201 | 152 | 57.3% | 62.2% | +4.8% | -1.5% to +11.4% | +8.2% | -2.9% to +19.8% | +2.8% / +13.6% |
| Shots | 3+ | confirm | 327 | 240 | 57.5% | 57.8% | +0.3% | -5.0% to +5.8% | -0.1% | -9.6% to +9.7% | -5.1% / +4.9% |
| Assists | 1+ | fit | 264 | 249 | 52.9% | 22.3% | -30.6% | -35.5% to -25.9% | -58.1% | -67.4% to -49.4% | -60.2% / -56.1% |
| Assists | 1+ | confirm | 59 | 56 | 53.2% | 20.3% | -32.9% | -41.9% to -23.4% | -62.9% | -79.8% to -45.1% | -64.7% / -61.0% |
| Shots on target | 2+ | fit | 32 | 32 | 58.6% | 56.2% | -2.3% | -19.0% to +14.1% | -3.3% | -30.9% to +25.0% | -8.1% / +1.5% |
| Shots on target | 2+ | confirm | 63 | 55 | 57.5% | 61.9% | +4.4% | -7.1% to +16.0% | +7.3% | -13.8% to +27.7% | +1.9% / +12.6% |
| Goals | 1+ | fit | 18 | 18 | 57.1% | 55.6% | -1.5% | -25.4% to +23.5% | +3.1% | -38.3% to +44.3% | -2.1% / +8.2% |
| Goals | 1+ | confirm | 32 | 32 | 52.3% | 65.6% | +13.3% | -2.8% to +29.3% | +25.0% | -6.9% to +56.2% | +18.8% / +31.3% |

### C. Every starter line by fair price (one over our chance)

| Fair price | Period | Lines | Matches | Said | Landed | Landed minus said | 95% | Return at fair | 95% | At fair -5% / +5% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1.00-1.25 | fit | 4,307 | 2,143 | 84.5% | 86.8% | +2.3% | +1.2% to +3.3% | +2.8% | +1.5% to +4.0% | -2.3% / +7.9% |
| 1.00-1.25 | confirm | 2,503 | 557 | 86.0% | 88.0% | +2.0% | +0.8% to +3.2% | +2.3% | +0.9% to +3.7% | -2.8% / +7.4% |
| 1.25-1.50 | fit | 35,783 | 3,787 | 71.4% | 77.2% | +5.8% | +5.4% to +6.3% | +8.2% | +7.6% to +8.8% | +2.8% / +13.6% |
| 1.25-1.50 | confirm | 6,958 | 561 | 71.9% | 77.0% | +5.1% | +4.0% to +6.1% | +7.2% | +5.7% to +8.6% | +1.8% / +12.5% |
| 1.50-1.75 | fit | 71,344 | 3,809 | 61.5% | 66.2% | +4.8% | +4.4% to +5.1% | +7.7% | +7.1% to +8.3% | +2.3% / +13.1% |
| 1.50-1.75 | confirm | 12,377 | 561 | 61.4% | 65.5% | +4.1% | +3.1% to +5.0% | +6.6% | +5.0% to +8.1% | +1.3% / +11.9% |
| 1.75-2.00 | fit | 71,760 | 3,808 | 53.5% | 54.0% | +0.5% | +0.1% to +0.9% | +0.8% | +0.1% to +1.6% | -4.2% / +5.9% |
| 1.75-2.00 | confirm | 12,698 | 561 | 53.4% | 54.2% | +0.7% | -0.3% to +1.6% | +1.3% | -0.6% to +3.0% | -3.8% / +6.3% |
| 2.00-3.00 | fit | 173,299 | 3,812 | 41.7% | 33.6% | -8.1% | -8.4% to -7.9% | -20.7% | -21.4% to -20.1% | -24.7% / -16.7% |
| 2.00-3.00 | confirm | 32,605 | 561 | 41.5% | 35.3% | -6.2% | -6.8% to -5.6% | -16.0% | -17.4% to -14.5% | -20.2% / -11.8% |
| 3.00-5.00 | fit | 96,339 | 3,809 | 27.4% | 14.7% | -12.7% | -13.0% to -12.4% | -46.8% | -47.7% to -45.8% | -49.4% / -44.1% |
| 3.00-5.00 | confirm | 21,980 | 561 | 27.0% | 19.4% | -7.6% | -8.2% to -7.1% | -28.1% | -30.2% to -26.0% | -31.7% / -24.5% |
| 5.00+ | fit | 146,825 | 3,812 | 8.6% | 5.7% | -3.0% | -3.1% to -2.8% | -30.3% | -32.4% to -28.3% | -33.8% / -26.8% |
| 5.00+ | confirm | 48,638 | 561 | 8.4% | 7.4% | -1.0% | -1.3% to -0.7% | -12.4% | -17.1% to -7.8% | -16.8% / -8.0% |

### D. The acceptable band by where the chance came from

| Chance from | Player | Period | Lines | Matches | Said | Landed | Landed minus said | 95% | Return at fair | 95% | At fair -5% / +5% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| fmodel | started | fit | 5,657 | 344 | 68.0% | 68.4% | +0.4% | -1.3% to +1.8% | +0.5% | -2.2% to +2.8% | -4.5% / +5.5% |
| fmodel | started | confirm | 9,556 | 561 | 67.9% | 69.5% | +1.6% | +0.5% to +2.8% | +2.4% | +0.6% to +4.2% | -2.7% / +7.5% |
| site | started | fit | 177,546 | 3,812 | 60.6% | 63.9% | +3.3% | +3.1% to +3.6% | +5.1% | +4.7% to +5.6% | -0.1% / +10.4% |
| site | started | confirm | 24,981 | 561 | 60.3% | 63.7% | +3.4% | +2.7% to +4.1% | +5.2% | +4.0% to +6.4% | -0.0% / +10.5% |
| site | came on | fit | 78,668 | 3,694 | 60.3% | 30.5% | -29.8% | -30.2% to -29.4% | -50.3% | -51.0% to -49.6% | -52.8% / -47.8% |
| site | came on | confirm | 12,140 | 558 | 60.2% | 32.6% | -27.6% | -28.6% to -26.6% | -46.7% | -48.4% to -45.1% | -49.4% / -44.1% |

### E. The acceptable band by month (starters)

| Month | Lines | Matches | Said | Landed | Landed minus said | 95% | Return at fair | 95% | At fair -5% / +5% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022-06 | 13 | 2 | 60.9% | 76.9% | +16.0% | +5.3% to +40.1% | +25.7% | +6.6% to +68.7% | +19.4% / +32.0% |
| 2023-06 | 5 | 1 | 60.2% | 80.0% | +19.8% | - | +33.0% | - | +26.4% / +39.7% |
| 2024-04 | 16 | 1 | 63.0% | 43.8% | -19.2% | - | -27.4% | - | -31.0% / -23.8% |
| 2024-05 | 164 | 10 | 61.8% | 57.9% | -3.8% | -10.4% to +5.0% | -6.3% | -16.6% to +8.3% | -11.0% / -1.6% |
| 2024-06 | 210 | 12 | 61.5% | 61.4% | -0.1% | -7.1% to +6.6% | +0.4% | -10.9% to +11.5% | -4.6% / +5.5% |
| 2024-07 | 459 | 17 | 61.0% | 61.0% | +0.0% | -6.3% to +5.7% | -0.1% | -11.1% to +9.5% | -5.1% / +4.9% |
| 2024-08 | 182 | 5 | 61.8% | 69.8% | +8.0% | -1.2% to +16.6% | +14.2% | -2.5% to +29.1% | +8.5% / +19.9% |
| 2024-09 | 505 | 18 | 60.9% | 60.4% | -0.5% | -5.8% to +5.2% | -1.0% | -9.9% to +8.5% | -5.9% / +4.0% |
| 2024-10 | 592 | 18 | 60.4% | 62.3% | +1.9% | -2.9% to +6.5% | +3.1% | -5.0% to +10.8% | -2.1% / +8.2% |
| 2024-11 | 273 | 10 | 60.3% | 64.8% | +4.6% | -0.3% to +9.0% | +6.9% | -1.2% to +14.4% | +1.6% / +12.3% |
| 2024-12 | 94 | 9 | 61.9% | 67.0% | +5.1% | -1.2% to +15.5% | +7.9% | -2.0% to +24.0% | +2.5% / +13.3% |
| 2025-01 | 253 | 19 | 61.7% | 65.2% | +3.5% | -1.9% to +9.8% | +5.5% | -4.1% to +16.2% | +0.2% / +10.8% |
| 2025-02 | 810 | 35 | 61.5% | 67.7% | +6.2% | +2.5% to +10.0% | +9.8% | +3.6% to +16.1% | +4.3% / +15.3% |
| 2025-03 | 940 | 33 | 60.5% | 63.3% | +2.8% | -1.7% to +7.0% | +4.7% | -3.1% to +11.7% | -0.6% / +9.9% |
| 2025-04 | 1,535 | 55 | 61.4% | 61.3% | -0.1% | -2.7% to +2.4% | -0.1% | -4.3% to +4.1% | -5.0% / +4.9% |
| 2025-05 | 2,991 | 93 | 60.9% | 62.8% | +1.9% | +0.1% to +4.0% | +3.0% | -0.2% to +6.4% | -2.2% / +8.1% |
| 2025-06 | 1,252 | 31 | 60.4% | 62.8% | +2.4% | -1.0% to +6.3% | +3.7% | -2.3% to +10.6% | -1.5% / +8.9% |
| 2025-07 | 3,706 | 74 | 60.5% | 63.5% | +3.0% | +1.2% to +4.8% | +4.5% | +1.5% to +7.6% | -0.7% / +9.8% |
| 2025-08 | 6,238 | 180 | 61.0% | 62.8% | +1.8% | +0.5% to +3.2% | +2.6% | +0.4% to +5.0% | -2.5% / +7.8% |
| 2025-09 | 9,014 | 217 | 60.9% | 63.2% | +2.3% | +1.2% to +3.4% | +3.4% | +1.4% to +5.3% | -1.8% / +8.6% |
| 2025-10 | 12,273 | 269 | 60.9% | 63.8% | +2.9% | +1.9% to +3.9% | +4.5% | +2.8% to +6.2% | -0.8% / +9.7% |
| 2025-11 | 17,125 | 348 | 60.7% | 64.1% | +3.4% | +2.4% to +4.2% | +5.2% | +3.6% to +6.6% | -0.1% / +10.4% |
| 2025-12 | 13,853 | 275 | 60.4% | 64.6% | +4.2% | +3.2% to +5.2% | +6.5% | +4.7% to +8.2% | +1.2% / +11.9% |
| 2026-01 | 17,466 | 347 | 60.5% | 64.7% | +4.1% | +3.2% to +4.9% | +6.4% | +4.9% to +7.8% | +1.1% / +11.7% |
| 2026-02 | 16,263 | 325 | 60.6% | 63.9% | +3.3% | +2.5% to +4.2% | +5.1% | +3.6% to +6.6% | -0.2% / +10.3% |
| 2026-03 | 17,671 | 343 | 60.5% | 63.4% | +2.9% | +1.9% to +3.8% | +4.3% | +2.7% to +5.8% | -0.9% / +9.5% |
| 2026-04 | 20,315 | 389 | 60.4% | 64.4% | +4.0% | +3.2% to +4.9% | +6.3% | +4.9% to +7.8% | +1.0% / +11.7% |
| 2026-05 | 17,855 | 332 | 60.4% | 63.7% | +3.3% | +2.4% to +4.2% | +5.1% | +3.5% to +6.5% | -0.1% / +10.4% |
| 2026-07 | 4,715 | 72 | 62.6% | 63.8% | +1.2% | -0.4% to +2.7% | +1.2% | -1.4% to +3.8% | -3.8% / +6.3% |
| 2026-08 | 16,415 | 272 | 62.3% | 65.7% | +3.3% | +2.5% to +4.2% | +5.3% | +3.9% to +6.7% | +0.0% / +10.5% |
| 2026-09 | 24,580 | 406 | 62.4% | 65.5% | +3.1% | +2.4% to +3.8% | +4.8% | +3.6% to +6.1% | -0.4% / +10.0% |
| 2026-10 | 9,957 | 155 | 62.4% | 64.8% | +2.4% | +1.2% to +3.4% | +3.6% | +1.5% to +5.3% | -1.6% / +8.8% |

### F. Tightening acceptable (starters): fitted before the confirm months, checked on them

| Rule | Lines | Period | Lines | Matches | Said | Landed | Landed minus said | 95% | Return at fair | 95% | At fair -5% / +5% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| As now: ours 50%+ | kept | fit | 183,203 | 3,812 | 60.8% | 64.1% | +3.2% | +3.0% to +3.5% | +5.0% | +4.5% to +5.5% | -0.3% / +10.2% |
| As now: ours 50%+ | kept | confirm | 34,537 | 561 | 62.4% | 65.3% | +2.9% | +2.3% to +3.5% | +4.4% | +3.4% to +5.5% | -0.8% / +9.7% |
| Ours 55%+ (floor fitted) | kept | fit | 131,778 | 3,811 | 64.1% | 68.7% | +4.6% | +4.3% to +4.9% | +7.1% | +6.7% to +7.6% | +1.8% / +12.5% |
| Ours 55%+ (floor fitted) | kept | confirm | 25,354 | 561 | 66.0% | 69.8% | +3.8% | +3.1% to +4.4% | +5.7% | +4.6% to +6.8% | +0.5% / +11.0% |
| Ours 55%+ (floor fitted) | taken out | fit | 51,425 | 3,799 | 52.4% | 52.2% | -0.2% | -0.7% to +0.2% | -0.5% | -1.4% to +0.4% | -5.4% / +4.5% |
| Ours 55%+ (floor fitted) | taken out | confirm | 9,183 | 561 | 52.4% | 52.9% | +0.5% | -0.6% to +1.5% | +0.9% | -1.2% to +2.9% | -4.2% / +5.9% |
| Without the 4 stat-line(s) that ran high (fitted) | kept | fit | 143,734 | 3,812 | 62.0% | 68.2% | +6.2% | +5.9% to +6.5% | +10.1% | +9.7% to +10.6% | +4.6% / +15.6% |
| Without the 4 stat-line(s) that ran high (fitted) | kept | confirm | 29,265 | 561 | 63.5% | 68.2% | +4.7% | +4.1% to +5.3% | +7.6% | +6.5% to +8.6% | +2.2% / +13.0% |
| Without the 4 stat-line(s) that ran high (fitted) | taken out | fit | 39,469 | 3,793 | 56.6% | 49.0% | -7.6% | -8.1% to -7.1% | -13.7% | -14.6% to -12.7% | -18.0% / -9.3% |
| Without the 4 stat-line(s) that ran high (fitted) | taken out | confirm | 5,272 | 561 | 56.4% | 49.1% | -7.3% | -8.6% to -5.9% | -13.2% | -15.6% to -10.7% | -17.5% / -8.9% |
| Recalibrated chance 50%+ (Platt a -0.13, b 1.37, fitted) | kept | fit | 157,959 | 3,812 | 62.4% | 66.3% | +3.9% | +3.6% to +4.2% | +6.1% | +5.7% to +6.6% | +0.8% / +11.4% |
| Recalibrated chance 50%+ (Platt a -0.13, b 1.37, fitted) | kept | confirm | 30,050 | 561 | 64.1% | 67.4% | +3.3% | +2.7% to +4.0% | +5.1% | +4.0% to +6.2% | -0.2% / +10.4% |
| Recalibrated chance 50%+ (Platt a -0.13, b 1.37, fitted) | taken out | fit | 25,244 | 3,767 | 51.2% | 50.1% | -1.1% | -1.7% to -0.5% | -2.1% | -3.4% to -1.0% | -7.0% / +2.7% |
| Recalibrated chance 50%+ (Platt a -0.13, b 1.37, fitted) | taken out | confirm | 4,487 | 560 | 51.1% | 51.2% | +0.0% | -1.4% to +1.5% | +0.1% | -2.8% to +2.9% | -4.9% / +5.1% |

Tried (best return on the fit months): Without the 4 stat-line(s) that ran high (fitted).

Stat-lines dropped by the per-stat rule: Fouled 2+, Fouled 3+, Fouls 2+, Tackles 2+.

Adopted: Without the 4 stat-line(s) that ran high (fitted).

### G. Lines with a committed Betfair back price (every competition)

| Player | Verdict | Lines | Won | Said | Landed | 95% | Profit | ROI |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| started | acceptable | 6 | 4 | 63.0% | 66.7% | 30.0% to 90.3% | +0.47u | +7.8% |
| started | long shot | 87 | 19 | 21.5% | 21.8% | 14.5% to 31.6% | +1.64u | +1.9% |
| started | avoid | 568 | 76 | 13.1% | 13.4% | 10.8% to 16.4% | -251.00u | -44.2% |
| came on | acceptable | 2 | 0 | 59.5% | 0.0% | 0.0% to 65.8% | -2.00u | -100.0% |
| came on | long shot | 57 | 4 | 23.0% | 7.0% | 2.8% to 16.7% | -28.88u | -50.7% |
| came on | avoid | 130 | 18 | 18.8% | 13.8% | 8.9% to 20.8% | -79.43u | -61.1% |
