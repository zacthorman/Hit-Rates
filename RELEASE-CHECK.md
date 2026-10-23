# Release check: oct21-work and its branches, against main

Written 23 October 2026 on branch `release-check`. Read-only: nothing was pushed except this branch, nothing was
published, `publish.sh` and `update.py` were never run, and nothing reached the network during the builds.
`release_check.py` reproduces every number here (see "Reproducing").

## The short version

1. **The 14 branches merge cleanly onto `oct21-work`, in the order given.**
2. **Merging that into `main` does not.** `main` has moved on by four commits since 21 October:
   - the Game state tab;
   - the tonight page split into Team lines and Player lines;
   - "Bookie value bets";
   - `sharp.py` and `papertrade`;
   - the Conference League.

   Git stops on three files: `tonight.py` (two places), `USAGE.md` and `best_bets.json`. It also merges four
   things silently that need a decision, listed under "What the merge into main needs".
3. **Built offline, every page works on all three versions.** The three are `main`, the stack on `oct21-work`,
   and `main` with the stack merged. On each: no JavaScript errors in a browser, every inline script parses in
   node, no broken links, no empty tabs, every build step finishes, and the stack's own `site_guard.py` checks
   pass. One caveat: the merged version only got that far once the hidden `tonight_chance` clash was fixed;
   before that, the tonight step crashed.
4. **What a visitor would see change** (main against main with the stack):
   - the "Value on Betfair" list goes (five football legs and one NFL leg here);
   - "Take" disappears from player lines (2 on this weekend become avoid);
   - tonight.html says "no value" instead of a negative value figure;
   - The case's predicted score switches model on every same-league match;
   - one darts lead changes;
   - player legs on tonight.html are capped at one per player.

   Picks, accumulators, tabs and table columns are otherwise unchanged.
5. **Zac must install `scipy`, `lightgbm` and `statsmodels` on the Mac.** Only `scipy` is in `requirements.txt`.
   Without them the build does not fail: The case's backtested score and the "to be booked" chances drop
   out quietly.
6. **Two tests fail on the merged tree.** Both are clashes between `main`'s changes and the stack's tests, not
   broken behaviour, and both are small fixes; see below.
7. **The build is quicker:** 233 s merged against 294 s for `main`, on one run each.

## What was built, and how

| | Ref | What it is |
|---|---|---|
| main | `origin/main` 0b5ce71 | what is live |
| stack | `oct21-work` d529fef + the 14 branches | what was asked for: the branches on top of oct21-work |
| release | main + stack | what main becomes; conflicts resolved for this check only (below) |

**The merge order:** case-score, team-model-check, exchange-log, code-health, scorer-audit, pipeline-tests,
acca-correlation, darts-model, bookie-imports, rule-review, parlay-check, test-hygiene, acceptable-check,
supersub-check. Every merge is clean, `--no-ff`, into a scratch worktree on a local branch
(`release-merge-scratch`) that is never pushed.

**The build** uses `replay_build.py` (from code-health) as the harness:
- The clock is frozen at Saturday 17 October 2026, 06:00 UTC, using libfaketime.
- Every SofaScore request is answered from the cache (`cache_backtest.tar.zst`, extracted).
- Every other request goes to a closed port. ESPN's injury fetch failing in every log shows the cut-off works.
- Each version runs its own steps, those of its `update.py` followed by those of its `publish.sh`:
  - main: settle, reports, rerender, index, team news, fmodel, usmodel, markets, gamestate, pplog, teamlog,
    sharp, papertrade, index, market check, tonight, best-bets snapshot, line log, bets page;
  - stack: the same without gamestate, sharp and papertrade, and with the Oddschecker import;
  - release: main's steps plus the Oddschecker import.
- Price fetchers, Betfair settling and fitting, the tactics fetch, git and the push are left out.
- All three get the same committed Betfair snapshot (`market_prices.json` as of 16 October), so the value and
  verdict code has prices for the weekend.
- The window holds 99 fixtures in 11 reports: 8 football leagues, the NFL, MLB and darts. The Champions,
  Europa and Conference Leagues and the NBA had no fixtures in it.

**The checks:**
- Each site is staged the way `publish.sh` stages it.
- `node --check` runs on every inline script.
- Every page loads in headless Chromium over a local server, with every visible tab clicked. The check
  records console errors, uncaught exceptions and failed requests.
- On each report, every player profile in every fixture is opened (8,934 profiles, 106 fixtures) and the
  verdict badges counted.
- Every local link is followed.
- The stack's `site_guard.py gate` runs on the staged site, and its report and index checks on the build.

## 1. Merging

| Step | Result |
|---|---|
| 14 branches onto oct21-work | all clean |
| that into main | conflicts in `tonight.py` (2 hunks), `USAGE.md` (1), `best_bets.json` (29) |

For the release build only, the conflicts were resolved like this:
- **`tonight.py`:** main's split into team and player pools, each ranked the stack's way (sport-aware chance,
  one leg per player); main's folding warning with the stack's evidence on multiples.
- **`USAGE.md`:** both sections kept.
- **`best_bets.json`:** main's copy.

None of this is committed. The real merge needs its own PR.

## 2. What the merge into main needs (beyond the three conflicts)

These merge without a conflict and are wrong or need a decision:

1. **`tonight_chance` is defined twice, and the old one wins.**
   - The stack moved `tonight_chance(l, sport)` to module level with the darts fix (darts legs use the
     shrunk record rather than 0).
   - `main` still defines its own `tonight_chance(l)` inside `build()`, which shadows it.
   - With the conflicts resolved the stack's way, the tonight step crashed (`takes 1 positional argument but 2
     were given`). Resolved the other way, it would silently drop the darts fix.
   - **Fix:** delete main's inner function.
2. **Which score model The case uses.**
   - main added a style model for same-league scores on 23 October.
   - The case-score branch made its team attack and defence ratings the first choice and kept the older route
     as `legacy_score`. Main's style model lands inside that older route.
   - Merged, the ratings win wherever they know both sides, and the style model only runs for sides they
     don't know. On this weekend that changed the call on all 22 same-league football matches on tonight.html.
     For example, Everton v Chelsea goes from 2-1, 42% home, to 0-1, 41% away.
   - Neither branch compared its model with the other's. **Zac to decide**, ideally by adding the style model
     to `case_score_backtest.py`'s comparison.
3. **Cards chance.** main labels team cards legs "Backtested tactics model". The release shows "Backtested cards
   model" (cards_model.py). That needs `lightgbm` and `statsmodels`; without them it quietly falls back to main's.
4. **A new value claim on main that no review has looked at.** "Bookie value bets" (`boostcheck.value_box`, top
   of tonight.html):
   - Paddy Power player bets where fmodel beats the price, with Kelly stakes.
   - It shows a market only while that market's own pplog record is near break-even or better.
   - It is self-gated, but it is separate from the verdict and the value list, which RULE-REVIEW.md and
     ACCEPTABLE-CHECK.md changed, and it survives the merge untouched.
   - It could not be exercised here, because there is no pplog offline. Worth adding to
     `rule_review.py acceptable` before it is relied on.
5. **Two tests to fix** (see section 6).

## 3. What a visitor would see change

Release against main, same data, same frozen weekend.

**Index (index.html)**

| | main | release |
|---|---:|---:|
| Fixtures listed | 106 | 106 |
| "Value on Betfair" list, football | 5 legs | none |
| "Value on Betfair" list, NFL | 1 leg | none |
| Best bet, banker, evens double, accumulator, bet builder, parlay (every sport) | | identical |

The stack built on oct21-work alone also shows different NFL and baseball fair prices on the same legs
(banker 1.40 against 1.35). That is data, not code. The shrink on the record is refitted from `best_bets.json`:
605 settled legs on main give 8, and 431 on oct21-work give 6. After the merge, main's file stands, so the
release matches main.

**Paddy Power verdicts** on every player profile (8,934 profiles, 106 fixtures). Offline there are no Paddy
Power prices, so these are the rungs priced off Betfair's back price:

| Verdict | main | release |
|---|---:|---:|
| Take | 2 | 0 |
| Acceptable | 1 | 1 |
| Long shot | 0 | 0 |
| Avoid | 5 | 7 |

The two takes on main are the rule-review change: an edge of 5% or more is now avoid. The team-lines gate
also arrives with the stack. It allows Take on team corners and shots on target past each market's backtested
threshold, and the release's reports now carry that gate and the team model's expectations. It needs Paddy
Power team prices, so it could not show here.

**tonight.html** (same 25 games, same layout):
- The value figure on Betfair-priced legs changes from "−4.5% value" to "no value" (4 places).
- The Call on all 22 same-league football games switches score model (65 lines; section 2, item 2).
- 4 of the 26 team legs priced by main's tactics model are now priced by the cards model (the yellow-cards
  legs), with a different chance and label.
- One lead changes: Schindler v Sedláček is now led by Sedláček over 92.5 highest checkout, from the darts fix.
- About 320 other lines change because the legs offered under each game reorder or drop out: one leg per
  player, the darts chance, and the cards model.

**Reports:**
- No tab, table column or heading changes.
- Each grows by about 10 KB of script: the verdict rules, the value gate and the scorer calibration map.
- The data changes only by the team-lines gate and, on football pages, each fixture's team model.

**Other pages:** best-bets-summary, bets, market-check and papertrade are byte-for-byte identical.
pp-results.html changes one line: its value scoreboard now counts only each player's biggest edge in a game
(supersub-check / value_cap), so its totals will move when pplog is present.

## 4. Errors, links, empty sections, crashes

| Check | main | stack | release |
|---|---|---|---|
| Build steps that failed or printed a traceback | none | none | none (after the `tonight_chance` fix) |
| Inline scripts that node cannot parse | 0 of 26 | 0 of 24 | 0 of 26 |
| Pages with console errors or uncaught exceptions | 0 of 29 | 0 of 28 | 0 of 29 |
| Failed requests (404) | none | none | none |
| Broken local links | 0 | 0 | 0 |
| Empty tabs | none | none | none |
| Profiles that threw while the verdicts were counted | 0 | 0 | 0 |
| `site_guard.py gate` on the staged site | passed | passed | passed |
| `site_guard` report and index checks on the build | passed | passed | passed |
| Writes into the shared cache during the build | none | none | none |

The stack has 28 pages to main's 29: it has no `papertrade.html`, which only main builds. The darts report's
Players tab is hidden by design. The two that cannot be checked offline: fmodel and the US model score
nothing in this replay, because every cached match is already finished and both skip matches already in their
history. The Players tab's fmodel chances and the US model's NFL chances are therefore not exercised on any
version.

## 5. Build time

Each version built once, in a row, on a warm disk cache. One run each, so read differences under 10 seconds
as noise.

| Step | main | stack | release |
|---|---:|---:|---:|
| reports (run.py) | 39.8 | 50.0 | 45.4 |
| rerender | 13.3 | 27.4 | 23.4 |
| make_index --prune | 20.5 | 14.1 | 12.8 |
| fmodel_live | 25.5 | 24.1 | 22.6 |
| usmodel_live | 81.3 | 16.8 | 15.7 |
| gamestate_live | 35.1 | - | 42.9 |
| make_index | 20.5 | 13.6 | 11.7 |
| tonight --hours 8 | 28.8 | 40.1 | 37.9 |
| besttrack snapshot | 14.8 | 10.0 | 9.5 |
| linelog snapshot | 8.4 | 7.4 | 6.9 |
| everything else | 5.5 | 3.9 | 4.0 |
| **Total (seconds)** | **293.5** | **207.3** | **232.8** |

**Where the time changes:**
- **Faster:** most of the saving is `usmodel_live`, and `make_index` is a little faster too (code-health).
- **Slower:** rerender, tonight and gamestate_live are a little slower in the release.
- **Not measured:** these offline times leave out the network fetches, so the Mac's real run will be longer on
  every version.

## 6. Tests

`python release_check.py tests WORK release` runs every `tests/test_*.py` one file at a time, because all
at once ran out of memory with the built reports present. The cache was linked in, as on the Mac.

| Version | Files | Passed | Failed |
|---|---:|---:|---:|
| main | 6 | 60 | 0 |
| release | 31 | 454 | 2 |

The two failures, both from main and the stack meeting:

- **`test_pipeline_safety.py::test_every_feed_refused_at_once_stops_the_publish`.**
  - **Cause:** its fake `update.json` turns off the Champions League and Europa League builds, but knows
    nothing of main's Conference League, so that build runs and the fake answers success.
  - **What still happens:** the publish is still stopped, but by the later report check rather than with
    "every feed failed".
  - **Live behaviour:** fine, because in a real outage `run.py` would report the failed fetch for the
    Conference League too.
  - **Fix:** add `"conference_league_days": 0` to the test's config.
- **`test_context.py::ScoreModel::test_no_model_falls_back`.**
  - **Cause:** it expects the fallback route to give the goals projection. In the merged `context.py` that
    route now tries main's style model first, which reads team profiles from `cache/`.
  - **When it fails:** only with a cache present, which on the Mac is always.
  - **Fix:** stub `open_mu` out in that test (or decide item 2 of section 2 first).

Both pass on the stack alone, with or without the cache.

## 7. Dependencies and new steps

**What to install on the Mac**, into the project's `.venv`:

```
.venv/bin/pip install "scipy>=1.10" lightgbm statsmodels
```

| Package | In requirements.txt | Needed by the daily build? | Without it |
|---|---|---|---|
| scipy | yes (new) | yes: `scoremodels.py`, The case's score | The case quietly uses the older score route |
| lightgbm | **no** | yes: `cards_model.py`, via `fmodel_live` and `context` | no "to be booked" chances; cards legs fall back to the tactics model |
| statsmodels | **no** | yes: `teammodel_train.py`, via the cards model | as for lightgbm |
| numpy, pandas | pandas yes (numpy comes with it) | yes, as on main | |
| zstandard | no | no: `exchange_audit.py` reading `cache_backtest.tar.zst` | the audit reads `cache/` only |
| scikit-learn | no | no: `usmodel/training/audit_us.py` | that audit and one test skip |
| pytest | no | no: `tests/test_tracked_files.py`, `test_exchange*.py` | run those with pytest |

`lightgbm` and `statsmodels` should be added to `requirements.txt`. On macOS, `lightgbm` may also need
`brew install libomp`.

**New steps in publish.sh:**
- `oddschecker_import.py`, after the Bet365 fetch. It reads pages Zac saves by hand into
  `drop/oddschecker/` (gitignored), makes no requests, and does nothing when the folder is empty.
- `site_guard.py gate "$STAGE"`, the last thing before the push. A staged report that is empty, cut off or
  unreadable, or an index that lists nothing or links to missing pages, stops the publish. When that happens
  the live site keeps yesterday's pages.

**New steps in update.py:**
- `site_guard.snapshot()` before anything is rebuilt. It keeps the last good copy of every report in
  `.last_good/` (gitignored). At 15 to 33 MB a report that is about 250 MB more disk.
- `check_reports` after the league build and again after rerender, and `index_problems` after the index. Any
  failure stops the run before publishing and puts back the last good copy. These checks passed on every
  version here; their job is to stop a bad day, so on a real bad day the site stays on yesterday's pages
  rather than publishing a broken one.
- Each optional build (Nations League, European competitions, NFL, darts, MLB, NBA) now goes through
  `optional_build`. A failed fetch keeps that sport's pages from yesterday with a warning; only every feed
  failing at once stops the run. `run.py` gains `--status-file` (written to `.build_status.json`).
- The merge keeps main's Conference League step (`conference_league_days`); the stack had removed it only
  because it branched before main added it.

**New gitignored files:**
- `drop/`, `.last_good/` and `.rejected/`;
- `*.html.tmp`, `*.json.tmp` and `.build_status.json`;
- `case_score_results.json`.

## 8. Before merging into main

1. Merge `main` into `oct21-work` (or the stack) first, in its own PR:
   - resolve the three conflicts;
   - delete main's inner `tonight_chance` (section 2, item 1);
   - fix the two tests (section 6);
   - re-run `python release_check.py`.
2. Decide which score model The case leads with (section 2, item 2).
3. Install `scipy`, `lightgbm` and `statsmodels` on the Mac, and add the last two to `requirements.txt`.
4. Expect a little over 250 MB more disk for `.last_good/`.
5. Put "Bookie value bets" through the same review as the verdict tiers once `pplog/` has a few weeks of it.

## Reproducing

```
pip install zstandard libfaketime playwright pytest scipy lightgbm statsmodels
mkdir -p ~/release-work/cache && tar --zstd -xf cache_backtest.tar.zst -C ~/release-work/cache   # or link the Mac's cache/
python release_check.py prepare ~/release-work          # merge, unpack main, stack and release
for s in main stack release; do python release_check.py build ~/release-work $s; done
for s in main stack release; do python release_check.py check ~/release-work $s; done
python release_check.py tests ~/release-work release
python release_check.py compare ~/release-work          # writes compare.json
```

`prepare` uses git worktrees under the work folder and a local branch `release-merge-scratch`, and never
pushes. `check` needs node and Chromium (Playwright). The builds take about four minutes each, the checks a few
minutes each.
