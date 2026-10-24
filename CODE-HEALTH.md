# Code health, 22 October 2026

A health pass on the `code-health` branch, made from `oct21-work`. It was meant to change no output, and the replay below shows it does not. Nothing was published, `publish.sh` was never run, and no deployment was touched.

## In short

- **The daily page build is 44% faster**: 360 s down to 203 s on the replayed weekend. The biggest single gain is `usmodel_live.py`, at about four times faster.
- **The output is unchanged.** Of 163 output files, 153 are byte-for-byte identical. The other 10 differ only in build timestamps, and those same 10 differ between two runs of the unchanged code.
- **Duplicated helpers now live in one place.** The probability helpers are in `probability.py` and the report-reading code is in `pagedata.py`. Every old name still works.
- **Dead code is out**, and a latent crash in `run.py` is fixed.
- **Every test file passes**: 70 tests, 2 skipped. Two new test files pin the consolidations to the old code.

## How it was measured

SofaScore is unreachable from the machine this was done on, and the real build asks it for each league's next round anyway. That answer changes daily, so two real builds can never be compared. `replay_build.py` (new) replays the build from `cache/` alone:

- **Fixed window.** The clock is frozen at Saturday 17 October 2026, 06:00 UTC, using libfaketime. The fixtures are the cached matches in the following days, presented as not yet started.
- **Same reports as `update.json`.** It builds 11 reports this way: eight football leagues (106 fixtures in total), the NFL (12), MLB (3) and darts (12).
- **No network.** Every SofaScore request is answered from the cache. Every other request is pointed at a closed port.
- **Every daily step, in order.** It runs the steps `update.py` and then `publish.sh` run, minus the price fetchers, git and the push.
- **Fixed Python hash seed**, so set ordering cannot differ between runs.

The "before" tree is `git archive oct21-work`; the "after" tree is `git archive code-health`. Each was run on the same 4-core container, one after the other.

### Timings

| Step | Before (s) | After (s) |
|---|---:|---:|
| reports (`run.py` build, 11 reports) | 93.7 | 38.7 |
| `rerender.py` | 14.0 | 12.5 |
| `make_index.py --prune` | 22.4 | 17.8 |
| `team_news.py` | 4.6 | 3.2 |
| `fmodel_live.py` | 45.1 | 33.8 |
| `usmodel_live.py` | 101.5 | 25.4 |
| `make_index.py` | 21.9 | 17.1 |
| `tonight.py --hours 8` | 29.8 | 33.8 |
| `besttrack.py snapshot` | 16.1 | 11.5 |
| `linelog.py snapshot` | 8.9 | 7.9 |
| eleven other steps (settles, logs, small pages) | 1.6 | 1.5 |
| **Total** | **359.6** | **203.0** |

**Run-to-run variation.** Wall times on this container vary by about 10% from run to run:
- Two more runs of the old code took 378 s and 360 s.
- A second run of the new code, before the last fix, took 178 s.
- Steps with no code change (for example `tonight.py`, `fmodel_live.py`) moved by several seconds in both directions.

The gains on the changed steps are well outside that noise.

**`usmodel_live.py` on a real upcoming slate.** In the replay, the NFL games are already in the cache, so `usmodel_live.py` stops before scoring them, as it would in production for a finished game. To time the real path, `us_e2e.py` (a one-off in the scratch folder, not committed) dropped those 12 games from the cached history so they count as upcoming. It then ran `run_sport("nfl")` from both trees:
- **Before:** 111.5 s.
- **After:** 29.6 s.
- **Result:** both produced the same 839 KB result, 12 games and 502 players, compared with `cmp`.

### Output comparison

`python replay_build.py compare before after` walks both trees. It compares every output file and leaves out source (`*.py`, `*.sh`, `*.md`, `tests/`).

```
153 file(s) identical byte for byte
10 file(s) identical once timestamps are masked
0 file(s) equal number for number to 12 significant figures
```

**The 10 timestamp-only files:**
- `index.html`
- `tonight.html`
- `lead_log.json`
- `reports/fmodel.json`
- `reports/usmodel.json`
- `reports/campeonato-brasileiro-serie-a.html`
- `reports/ligue-1.html`
- `reports/mlb-postseason.html`
- `reports/mls.html`
- `reports/nfl.html`

**What differs in them.** Only the wall clock: a `generated` epoch, or a "fetched Sat 17 Oct 06:00" stamp that reads 06:01 when a step crosses the minute. Masking removes that difference and nothing else; no numbers had to be rounded.

**The control.** Two runs of the unchanged `oct21-work` code give exactly the same split: 153 identical, and the same 10 identical once masked. The new code is therefore indistinguishable from the old.

**The included files.** The 163 files are everything in the tree that is not source:
- **Pages:** all 22 report and pick pages, `index.html`, `tonight.html`, `best-bets-summary.html`, `market-check.html` and `pp-results.html`.
- **Sidecars:** `reports/fmodel.json`, `reports/usmodel.json` and `reports/markets.json`.
- **Files the build rewrites:** `best_bets.json`, `lead_log.json`, `learned.json`, `calibration.json` and `linelog/2026-10.jsonl`. On this weekend nothing reached `pplog/` or the team-line log, so neither was written.
- **Committed data and model files the build reads:** these came out unchanged in both runs.

## What changed

### 1. Duplicated helpers, gathered into one module each

**`probability.py` (new).** Every function in it is the old body moved, not rewritten. On Python 3.12 and later, even swapping a `+=` loop for `sum()` changes the last bit of a float, so each loop, clamp order and edge case is kept as it was. The old names stay as aliases or one-line wrappers.

| New | Replaces |
|---|---|
| `logit(p, eps=1e-4)` | `darts_market._logit`, `exchange_eval._lg`, `market_prices._lg`, `weekend._lp`; with `eps=1e-3`: `learner._logit`, `strength._logit` |
| `sigmoid(z)` | `darts_model._p`, `exchange_eval._sig`, `learner._sig` |
| `platt(p, a, b)` | the bodies of `model.calibrate`, `model.calibrate_record`, `model.calibrate_player` |
| `wilson_low`, `wilson` | `model.wilson_low`, `review.wilson` |
| `shrink(k, n, a)` | `bettrack.adjusted`, `weekend._shrunk`, `model.smooth_rate` |
| `poisson_pmf(k, lam)` | `context._poisson`, `match_result._pois` |
| `nb_at_least(k, mu, alpha)` | `context._nb_at_least`, `usgame._nb_ge`, `gs_backtest.p_at_least` |
| `nb_alpha(y, mu)` | `gs_backtest.nb_alpha`, `teammodel_train.alpha_of` |
| `poisson_cdf`, `neg_bin_cdf`, `binom_cdf` | moved from `model.py`, which re-exports them |

`tests/test_probability.py` keeps a copy of each old body. It asserts with `==` (not almost-equal, NaN included) that every old name returns exactly what it used to, over thousands of random and edge-case inputs.

**Left alone on purpose.** These helpers look alike but are not bit-equal, so merging them would change output:

| Helper | Why it was left |
|---|---|
| `darts_model.poisson_tail` | no clamp; different guards |
| `gamestate.pois_at_least` | returns the ints 0 and 1; mirrors the page's JavaScript |
| `besttrack._tail` | log space, not `math.comb` |
| `market_prices._pois` | builds the pmf by recurrence, then `sum()` |
| `usmodel_live.calibrate` | clamps at 1e-4, not 1e-9 |
| `nba_team_train.alpha` | no 1e-9 guard |
| the four different means | different summation and empty-input handling |

The reasons are also written in `probability.py` itself.

**`pagedata.py` (new).** Twelve modules each found a report's dataset with their own copy of `re.search(r"const ALL = (\{.*?\});\n", text, re.S)`:
- `bettrack`, `enrich_derived`, `fmodel_live`, `lineups` (twice), `lineups_auto`, `make_index`, `nfl_injuries`, `picker`, `player_bets`, `rerender`, `run` and `team_news`.

That lazy `.*?` walks a page of up to 33 MB one character at a time, at about half a second per report, every time a step reads the reports. `pagedata.search` returns the same text using two `str.find` calls, and the module docstring explains why the two always agree. `tests/test_pagedata.py` checks it against the regex:
- on edge cases;
- on 5,000 random strings;
- on every built report.

### 2. Slow paths

| Where | What was slow | Fix | Effect |
|---|---|---|---|
| `usfeatures.features`, called by `usmodel_live.py` | Built a full feature row, with numpy statistics, for every historical player-game (about 39,000 for the NFL), then threw away all but the upcoming games. | New `only=` argument: rows are built only for the wanted games. Every game still feeds the histories, and the skipped branch touches the same history keys, so their order is unchanged. Training scripts call it without `only=` and get the full build as before. | 102 s to 25 s in the replay; 111 s to 30 s on a real slate. Bit-identical rows (every float compared as raw bits) on the last 40 cached NFL games: 2,514 rows. The cache holds no NBA box scores, so the NBA could not be replayed; it runs the same code. |
| The `const ALL` regex in 12 modules | About 0.5 s per report per read, in more than six steps | `pagedata.py`, above | A few seconds off each of `rerender`, `make_index` (twice), `tonight`, `besttrack`, `linelog`, `fmodel_live` and `team_news` |
| `parlay._games_by_player` | Rebuilt the same team's appearance index about 15,000 times a run, in each of `make_index` (twice) and `besttrack snapshot` | Remembered per team list. The key holds the list itself, so its id cannot be reused, plus its length. | About 35 s of profiled time per process removed |
| `hitrates._pretty` | 3.8 million calls per report build, the same few hundred keys | `functools.lru_cache` (pure function of one string) | Most of the report build's gain: 94 s to 39 s |

**Steps not made faster, and why.**
- **JSON decoding in `teamstyle.load`, `fmodel_live.history` and `hitrates`.** This is reading thousands of cached files, and in production `fmodel_live` already keeps its own history cache. A faster route would mean a second on-disk cache to keep in step, which is more risk than this pass should take.
- **`tonight.py` and `fmodel_live.py`.** They had no code change, and moved only within the noise.

### 3. Dead code removed

- **`apply_pool_fix.py` and `widen_guard.py`.** One-off scripts that patched `hitrates.py` and `verify.py` in place. Both patches are long applied, and nothing refers to either script.
- **`exchange_eval._fmt` and `why._bet`.** Private helpers with no callers.
- **Unused imports** in:
  - `backtest`, `bets_page`, `darts_model`, `make_index`, `market_check` (three), `parlay`, `review`, `run`, `sofascore_api`, `strength` and `teammodel_train` (two);
  - two test files;
  - the `re` imports left unused by `pagedata`.
- **Unused locals:**
  - `model.price`: `record_p`, `se` and the variance that fed only `se`;
  - `strength`: `neff` and `sw2`;
  - `market_prices`: `targets` and `names`;
  - `bettrack.report`: `cal`.

### 4. Fixed on the way

- **`run.py` crash.** `main_for` called `parser.print_help()` with no `parser` in scope. So `python run.py` with no arguments died with a `NameError` instead of printing the help. The parser is now passed in.
- **Test writing a committed file.** `tests/test_strength.py` rewrote the committed `learned.json` on every run, because `weekend.calibrate` refits the learner and saves it. The test now points `learner.OUT` at a temporary file.
- **`replay_build.py` caught a real slip in this pass** before it shipped. With `only=`, a slate with no games to score returned a frame with no columns, and `usmodel_live` would have dropped its NFL block. It now returns early, exactly as the old full build did.

## Tests

`python -B -m pytest -q tests`: **70 passed, 2 skipped**, with the replayed reports in `reports/`.

- **New tests:** `test_probability.py` (6 tests) and `test_pagedata.py` (4 tests).
- **Skips:** one needs a built Champions League report, and none was in the replayed weekend. The other is the opt-in live game-state test.
- **Live game-state test:** run separately with `GAMESTATE_LIVE=1`, it passed too, with 5 tests and 8 subtests.
- **Without built reports**, the suite gives 68 passed and 4 skipped.

## After merging oct21-work (22 October, later)

`oct21-work` moved on while this was in review. It added the cards model, the team lines, the US models audit and the 22 October proof, along with seven new test files. It was merged into `code-health`, and the only conflict was in USAGE.md, where both sides had added a section; both sections were kept. The USAGE files table and test list now include the new modules (`cards_model.py`, `value_cap.py`, `teamlines.py`, `teamline_backtest.py`) and the new write-ups.

**Replay after the merge.** The replay was run again, with the new `oct21-work` as "before" and the merged `code-health` as "after":
- 158 output files are byte-for-byte identical.
- 8 differ only in build timestamps.
- None needed numbers rounded to match.

So the health changes still change no output on top of the new work. The container was busier for this pair of runs, and the totals were 507 s before and 312 s after (`usmodel_live`: 152 s down to 30 s).

**Tests after the merge.** All 15 test files were run with built reports present, including a Champions League report replayed from the 13 to 14 October matchday, with `GAMESTATE_LIVE=1`, and with statsmodels and scikit-learn installed for the team-lines and audit tests. The result was **173 passed, 0 skipped** (plus 9 subtests), and no test wrote to a committed file.

## Found, not changed

These need a decision from you rather than a health pass:

- **Backups in git.** 137 `*.bak-*` files, plus `_backup/` and `_to_delete/` (50 files), are still tracked, even though `.gitignore` lists them. Together they are about 200 MB of the working tree. `git rm --cached` would stop tracking them without deleting your copies. Removing them in a commit, however, would delete them from your Mac on the next pull, so they were left alone.
- **Unused public functions.** Nothing calls these, but a notebook or a later script might, so they were kept:
  - `darts_model.upcoming_format`
  - `hitrates.pool_of`
  - `parlay.ladder_for`
  - `sofascore_api.h2h_events`
  - `usgame.player_features`
  - `model.Z_95` and `model.STAT_TO_TEAM_BY_SPORT`
  - `markets.BASKETBALL_UNCONFIRMED` and `markets.BASEBALL_UNCONFIRMED`
- **Dead assignment in `usgame.player_features`.** It assigns `T_margin` twice and never reads it.
- **`learned.json` rewrites itself.** `learner.model()` rewrites `learned.json` whenever anything calibrates. That is by design in the daily build, but it means any script that imports `weekend` and prices a leg changes a committed file.

## Reproducing

```bash
# once: the cache the replay reads, and the frozen clock
python -c "import zstandard, tarfile; tarfile.open(fileobj=zstandard.ZstdDecompressor().stream_reader(open('cache_backtest.tar.zst','rb')), mode='r|').extractall('cache', filter='data')"
pip install libfaketime

git archive oct21-work  | (mkdir -p /tmp/before && tar -x -C /tmp/before)
git archive code-health | (mkdir -p /tmp/after  && tar -x -C /tmp/after)
python replay_build.py run /tmp/before
python replay_build.py run /tmp/after
python replay_build.py compare /tmp/before /tmp/after
```
