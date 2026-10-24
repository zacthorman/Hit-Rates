# Team model check

22 October 2026, branch `team-model-check`. An audit of the two things that run every week on the Mac with nobody watching them: `teammodel_train.py --weekly` and `tactics_fetch.py` with the `teamstyle.py` parsers. Nothing here touches publishing, `gh-pages` or the live models in `teammodel/`.

## In short

1. **The weekly rule does not drift and does not lock in a bad week.** Over 46 simulated weeks its calibration and its distance from a fresh refit track the never-updated model, and a week of doubled counts in the cache cost it at most 0.0018 in any later week (0.0031 for the shipped rule), with nothing left by the end: 0.6505 with the bad week, 0.6505 without.
2. **It barely moves, so it falls behind a weekly refit.** Each Monday's 40 trees at learning rate 0.01 shift the chances by about 0.5%. Over 46 weeks the rule gains 0.0008 per match on the frozen model; refitting from scratch every week gains 0.0049 and beats the rule in 39 of 46 weeks. Over the 15 production weeks (from July) the two tie (0.6474 against 0.6473).
3. **The adoption test was fair on labels but not in what it tested.** Nothing trained on the 21 days it scores on (checked in code and by a test). But "no worse" allowed 1e-4 of slack, which adopted 26 models in scenario B that were worse on the holdout, and the halved model, the one actually saved, was never tested. Both are fixed.
4. **The halving step could never have worked.** It reused a LightGBM Dataset and raises `Cannot set predictor after freed raw data`, which would have killed the weekly run partway through (models before it saved, `meta.json` and `CHANGELOG.md` not written). It never fired in the history because no week moved more than 1.6% against the 3% threshold. Fixed, and one stat failing no longer stops the others.
5. **The parsers failed quietly.** `teamstyle.load` skipped broken or reshaped files, the four SofaScore tactics endpoints were cached with no check at all, and Understat's teamsData was skipped when missing and garbled any raw accented name. All now raise a `ShapeError` naming the file. The backtest cache holds no tactics or Understat files yet, so those checks are tested on hand-made samples of the response shapes.

## 1. The weekly rule, week by week

### How it was simulated

`teammodel_audit.py` replays the Monday job (05:34 UTC) over the backtest cache (`cache_backtest.tar.zst`, 13,576 team rows, matches up to 19 October 2026). At each Monday only matches that kicked off at least three hours earlier are known. The weekly rule runs on them exactly as the code does: the same features, parameters, recency weights, 21-day holdout, 3% halving and adoption test. The model in force after that run is then scored on the **following seven days**, which no decision has seen. That forward score is the honest one; the 21-day score the rule logs is not, because the rule chose on it.

The score is the tail log loss `teammodel_train.py` selects on (lower is better), pooled over every match in the week. Only the seven stats that use the tactics model are simulated; the linear ones are never touched by `--weekly`.

Five paths per stat:

| path | what it is |
|---|---|
| frozen | the starting full fit, never updated |
| as_run | the shipped rule as it actually ran: its halving step crashed (see 2.1), which ended that week's run for that stat and every stat after it in `meta.json` order |
| shipped | the shipped rule as intended: the crash mended, nothing else changed |
| fixed | the rule as it is now (`teammodel_train.weekly_step`) |
| refit | a full refit from scratch every week: early stopping on the last 90 days, then refitted on everything known |

Three scenarios:

| scenario | start | weekly runs |
|---|---|---|
| A | the production split: train before 1 April 2026, validate April to June | 6 July to 12 October 2026 (15 weeks) |
| B | train before 1 October 2025, validate October and November | 1 December 2025 to 12 October 2026 (46 weeks) |
| B-bad | as B, but every count in the week of 9 February 2026 doubled in the cache (a plausible feed fault), still scored on the true counts | as B |

### Results

Pooled score on the following seven days (lower is better), all seven stats:

| scenario | frozen | shipped as run | shipped | fixed | weekly refit |
|---|---|---|---|---|---|
| A, 15 weeks from July | 0.6480 | 0.6474 | 0.6474 | 0.6474 | 0.6473 |
| B, 46 weeks from December | 0.6513 | 0.6507 | 0.6507 | 0.6505 | 0.6464 |
| B-bad, B with one bad week | 0.6513 | 0.6509 | 0.6509 | 0.6505 | 0.6471 |

"Shipped as run" equals "shipped" everywhere because the crash never fired (section 2.1).

By quarter in scenario B, which shows the gap opening:

| quarter | frozen | fixed weekly rule | weekly refit |
|---|---|---|---|
| 2025 Q4 | 0.6594 | 0.6594 | 0.6574 |
| 2026 Q1 | 0.6459 | 0.6457 | 0.6415 |
| 2026 Q2 | 0.6529 | 0.6520 | 0.6472 |
| 2026 Q3 | 0.6521 | 0.6518 | 0.6476 |
| 2026 Q4 (to 19 Oct) | 0.6567 | 0.6511 | 0.6464 |

### Drift

It does not drift. Calibration (mean predicted over mean actual, next seven days) and the average gap in log chance to a fresh refit, scenario B:

| path | calibration, first 4 weeks | calibration, last 4 weeks | gap to refit, first 4 | gap to refit, last 4 | trees at the end |
|---|---|---|---|---|---|
| frozen | 1.006 | 0.980 | 0.031 | 0.059 | 209 |
| shipped | 1.006 | 0.981 | 0.031 | 0.059 | 1,358 |
| fixed | 1.006 | 0.981 | 0.031 | 0.057 | 1,249 |
| weekly refit | 1.010 | 0.985 | 0 | 0 | 227 |

The trees pile up (40 a week, six times the starting model by October) but the weekly paths sit on top of the frozen model: they neither wander off nor keep up. The gap to a refit grows at the same pace for the frozen model and the weekly rule, so what is falling behind is the starting fit, and the weekly steps are too small to pull it back. The 3% halving never fired: the median weekly move was 0.5% and the largest 1.6%.

### A bad week

In B-bad every count in the week of 9 February 2026 is doubled in the cache. Extra loss against clean B, all stats pooled (positive is worse):

| Monday | frozen | shipped | fixed | weekly refit |
|---|---|---|---|---|
| 16 Feb | 0 | 0 | -0.0003 | +0.0115 |
| 23 Feb | 0 | +0.0002 | +0.0002 | +0.0006 |
| 2 Mar | 0 | -0.0006 | -0.0002 | +0.0037 |
| 9 Mar | 0 | -0.0002 | +0.0001 | +0.0030 |
| 16 Mar | 0 | +0.0007 | +0.0004 | +0.0021 |
| 23 Mar | 0 | +0.0031 | +0.0006 | -0.0020 |
| 6 Apr | 0 | +0.0014 | +0.0018 | +0.0038 |
| whole run | 0 | +0.0002 | 0.0000 | +0.0007 |

The 21-day holdout protects the weekly rule for three weeks (the bad matches can only be scored on, never trained on). After that they enter training at full weight, but 40 small trees cannot learn much from one week, and the recency weighting fades them. Nothing is locked in. A weekly refit is the more exposed: it trained on the bad week straight away and lost 0.0115 the next week.

### Are the decisions any good?

On the next seven days (which no decision saw), scenario B, fixed rule: 95 of 182 adoptions helped (52%) and 50 of 105 rejections were right (48%). At this size of step the 21-day test is close to a coin toss: the step is too small for 21 days of matches to tell apart. It costs little because each step is small, but it also means the test is not what keeps the rule safe; the small step is.

### Recommendation (not made here)

A weekly refit from scratch scored 0.0041 a match better than the weekly rule over 46 weeks and tied over the 15 production weeks; it was hurt more by the bad week (0.0115 the week after, and small extra losses for about two months). If the Mac can afford a full fit on Mondays, a refit gated by the same 21-day comparison against the current model would keep most of that gain and keep the bad-week guard. That is a change to what the job does, so it is left for a decision; this branch only makes the existing rule sound.

Full tables, including the week-by-week score path for every scenario, are in the appendix.

## 2. Is the adoption test fair?

### 2.1 What was wrong

- **No peeking at the labels.** The candidate trains on matches before the 21 days and is only scored on them, and the old model was trained before them too (the full fit ends on 1 July; each weekly step stops 21 days before its own run, so last week's model never saw this week's holdout). The features of holdout rows are built only from earlier matches. A new test feeds the step two completely different sets of holdout labels and gets a byte-identical candidate.
- **Slack in "no worse".** The shipped test rejected only when the new score was more than 0.0001 worse, so a slightly worse model was adopted. In scenario B that happened 26 times out of 201 adoptions (5 of 52 in A, 31 of 181 in B-bad). It made a small difference overall (0.6507 against 0.6505 in B, 0.6509 against 0.6505 in B-bad), but the rule says "no worse" and should mean it.
- **The model tested was not the model adopted.** When a move was over 3%, the shipped code retrained at half the learning rate after the test and saved that model untested. The halving never fired in the history, so this did not change any result, but it would have adopted a model nobody scored.
- **The halving crashed.** The second `lgb.train` reused the first `lgb.Dataset`, whose raw data LightGBM frees after construction, so it raised `LightGBMError: Cannot set predictor after freed raw data` (reproduced with LightGBM 4.7.0). The weekly loop had no guard: stats earlier in `meta.json` would already have saved new trees, while `meta.json` (tree counts, the `weekly` stamp) and `CHANGELOG.md` were never written, and later stats were skipped. The test for halving reproduces the crash on the old code.
- **Overlapping windows (left as is).** Consecutive Monday windows share 14 of their 21 days, so the incumbent has already won a test on two thirds of the matches it is now scored on. That leans towards keeping the old model, not towards adopting a lucky one, so it cannot let a bad model in; it is noted rather than changed, since a seven-day window would make the coin toss above noisier still.

### 2.2 What changed

- `weekly_candidate(lgb, old, Xtr, ytr, wtr, Xh)` builds the candidate, halving included. It takes the holdout's features (to measure the move) but not its labels, so it cannot peek; a test checks the signature and that any holdout labels at all give a byte-identical candidate.
- `weekly_step` then scores that same candidate against the old model on the 21 days and adopts it only if `after <= before`. No slack.
- The halving fit gets a fresh `lgb.Dataset`, so it no longer crashes.
- `weekly()` catches a failure per stat, writes `update FAILED, unchanged (...)` to `CHANGELOG.md`, still runs the other stats, always writes `meta.json` and the log, and exits non-zero.

## 3. The tactics parsers

Checked against every file in the backtest cache: 1,375 team event lists, 7,949 line-ups, 9,182 statistics files, 870 event files and 363 team files. It holds **no** tactics files (average-positions, shotmap, graph, incidents) and **no** Understat files, because the tactical backfill started after the archive was made. Those parsers are therefore tested on small hand-made samples in the shape the SofaScore and Understat responses take. If a real response differs in a field the checks require, the first run stops with `SHAPE ERROR` naming the file and field, which is the failure this asked for; `tactics_fetch.py --check` runs every parser over whatever the Mac already holds.

| parser | before | now |
|---|---|---|
| `teamstyle.load`, team event lists | broken JSON skipped (`except Exception: pass`); a renamed `events` key gave no matches | `ShapeError` naming the file; events must have id, kick-off, both teams and status; files present but no events at all raises |
| `teamstyle.load`, statistics | broken JSON skipped; no `ALL` period skipped; items read with no checks | `parse_statistics`: broken JSON, missing `statistics` list, no `ALL` period, groups or items in another shape all raise. The 7 cached `{"error": ...}` bodies and an empty list mean "no statistics" and are skipped, as before |
| `teamstyle.load`, line-ups | broken JSON skipped | `parse_lineups`: home and away must be objects, formation a string or null (889 files have null, read as no shape, as before) |
| page side (`context._team_model`) | any error stored and never shown, team legs quietly on the simple model | one line in the run log saying the team model is off and why |
| SofaScore average-positions, shotmap, graph, incidents | cached as returned, never parsed or checked | each response checked (players with numeric average x and y; shots with side, type and situation, xG a number when present; momentum points with minute and value; incidents with a type). An unknown shape stops the run, exit code 2, and the file is deleted so it is fetched again once the parser is fixed. The `{"incidents": [], "missing": true}` placeholder `cards_backfill.py` writes is accepted |
| Understat teamsData | a page without teamsData printed a note only with `-v` and the league was skipped; any other error was swallowed; `.encode().decode("unicode_escape")` turned a raw accented name into mojibake (Köln became KÃ¶ln) | `parse_understat_league` raises when teamsData is missing, is not JSON, or teams lack title, history, ppda att/def, deep, xG or xGA; decoding keeps accents whether escaped or raw. Still off by default (`.understat_on`); nothing was fetched from Understat for this check |
| `tactics_missing.json` | a broken file read as empty, so every known 404 was asked again and the record overwritten | a missing file is empty; a broken one raises |
| `finished_events` | an empty parse of the event lists meant "0 fetched, 0 left" | raises when there are event files but no finished match |
| `teamstyle.load` on the whole cache | 6,788 matches | the same 6,788, identical field for field |

`update.py` runs `tactics_fetch.py` with `allow_fail`, so a shape error does not stop the gameweek; the `SHAPE ERROR` line goes into the log. `update.py`'s `run()` does not itself report a non-zero exit for such steps; that file belongs to the publishing run, so it was left alone.

## 4. Tests

- `tests/test_teammodel_weekly.py` (9 tests, skipped where LightGBM is not installed): the candidate takes no holdout labels; different holdout labels give an identical candidate; the reported score is the adopted (halved) model's; no slack; halving moves between 35% and 65% of the full step; `weekly()` writes the log and `meta.json`, leaves the model alone when it rejects, and handles too few new matches; the audit's Monday timing.
- `tests/test_tactics_parsers.py` (26 tests, 32 subtests): every parser on the cache shape and on the shapes it must refuse, including the Understat teamsData case with escaped and raw accents, a page without teamsData, the fetch loop stopping and dropping a bad file, `--check`, and the missing-404 record.
- The whole suite: `OMP_NUM_THREADS=1 python -B -m unittest discover -s tests` runs 91 tests, all passing (3 skipped, the same as before: they need built reports). `OMP_NUM_THREADS=1` only matters when another LightGBM job is running at the same time.
- Unrelated, found while testing: `tests/test_strength.py` rewrites `learned.json` in the repository each time it runs. Not changed here; the rewritten file was not committed.

## Reproducing

```
python - <<'PY'   # unpack the backtest cache somewhere outside the repo
import tarfile, zstandard
with open("cache_backtest.tar.zst", "rb") as f:
    tarfile.open(fileobj=zstandard.ZstdDecompressor().stream_reader(f), mode="r|").extractall("/tmp/cache", filter="data")
PY
OMP_NUM_THREADS=1 python teammodel_audit.py --cache /tmp/cache --out /tmp/audit.json --jobs 3   # about two and a half hours
python teammodel_audit_report.py /tmp/audit.json
python tactics_fetch.py --check                    # on the Mac, against cache/
OMP_NUM_THREADS=1 python -B -m unittest discover -s tests
```

## Appendix: full tables from teammodel_audit_report.py

Scores are the tail log loss on the seven days after each Monday run, pooled over matches. "adopt_helped" counts adoptions that scored better than keeping the old model on those seven days, "reject_helped" rejections that were right, "slack_used" adoptions that were worse on the 21 days.

#### Scenario A: pooled score on the next seven days, per stat

| stat | frozen | as_run | shipped | fixed | refit |
|---|---|---|---|---|---|
| Big chances | 0.6412 | 0.6401 | 0.6401 | 0.6401 | 0.6384 |
| Corner kicks | 0.6378 | 0.6375 | 0.6375 | 0.6377 | 0.6376 |
| Fouls | 0.6611 | 0.6618 | 0.6618 | 0.6618 | 0.6602 |
| Goalkeeper saves | 0.6445 | 0.6440 | 0.6440 | 0.6439 | 0.6450 |
| Shots on target | 0.6467 | 0.6445 | 0.6445 | 0.6446 | 0.6466 |
| Total tackles | 0.6571 | 0.6569 | 0.6569 | 0.6569 | 0.6560 |
| Yellow cards | 0.6470 | 0.6466 | 0.6466 | 0.6467 | 0.6469 |
| all stats | 0.6480 | 0.6474 | 0.6474 | 0.6474 | 0.6473 |

#### Scenario A: score path, all stats pooled, week by week

| Monday | frozen | as_run | shipped | fixed | refit | n | fixed - refit | fixed - frozen |
|---|---|---|---|---|---|---|---|---|
| 2026-07-06 | 0.4680 | 0.4680 | 0.4680 | 0.4680 | 0.4663 | 56 | 0.0017 | 0.0000 |
| 2026-07-13 | 0.6600 | 0.6600 | 0.6600 | 0.6600 | 0.6569 | 190 | 0.0031 | 0.0000 |
| 2026-07-20 | 0.6528 | 0.6528 | 0.6528 | 0.6528 | 0.6540 | 676 | -0.0013 | 0.0000 |
| 2026-07-27 | 0.6172 | 0.6170 | 0.6170 | 0.6170 | 0.6195 | 392 | -0.0024 | -0.0001 |
| 2026-08-03 | 0.6161 | 0.6154 | 0.6154 | 0.6155 | 0.6102 | 386 | 0.0053 | -0.0006 |
| 2026-08-10 | 0.6375 | 0.6376 | 0.6376 | 0.6375 | 0.6390 | 822 | -0.0015 | 0.0000 |
| 2026-08-17 | 0.6572 | 0.6575 | 0.6575 | 0.6576 | 0.6573 | 1442 | 0.0003 | 0.0004 |
| 2026-08-24 | 0.6410 | 0.6403 | 0.6403 | 0.6404 | 0.6427 | 1606 | -0.0023 | -0.0006 |
| 2026-08-31 | 0.6641 | 0.6636 | 0.6636 | 0.6637 | 0.6636 | 1624 | 0.0001 | -0.0004 |
| 2026-09-07 | 0.6475 | 0.6481 | 0.6481 | 0.6480 | 0.6470 | 1988 | 0.0010 | 0.0005 |
| 2026-09-14 | 0.6377 | 0.6371 | 0.6371 | 0.6373 | 0.6367 | 1986 | 0.0006 | -0.0004 |
| 2026-09-21 | 0.6663 | 0.6666 | 0.6666 | 0.6666 | 0.6648 | 674 | 0.0018 | 0.0003 |
| 2026-09-28 | 0.6720 | 0.6709 | 0.6709 | 0.6710 | 0.6707 | 668 | 0.0003 | -0.0010 |
| 2026-10-05 | 0.6562 | 0.6543 | 0.6543 | 0.6544 | 0.6573 | 1414 | -0.0029 | -0.0017 |
| 2026-10-12 | 0.6436 | 0.6417 | 0.6417 | 0.6417 | 0.6395 | 2238 | 0.0022 | -0.0019 |

#### Scenario A: drift checks (mean over stats)

| path | calibration first 4 weeks | calibration last 4 weeks | gap to refit first 4 weeks | gap to refit last 4 weeks | trees at the end |
|---|---|---|---|---|---|
| frozen | 1.0265 | 0.9808 | 0.0173 | 0.0324 | 192.8571 |
| as_run | 1.0267 | 0.9813 | 0.0175 | 0.0323 | 490.0000 |
| shipped | 1.0267 | 0.9813 | 0.0175 | 0.0323 | 490.0000 |
| fixed | 1.0267 | 0.9816 | 0.0175 | 0.0317 | 467.1429 |
| refit | 1.0269 | 0.9854 | 0.0000 | 0.0000 | 227.4286 |

#### Scenario B: pooled score on the next seven days, per stat

| stat | frozen | as_run | shipped | fixed | refit |
|---|---|---|---|---|---|
| Big chances | 0.6477 | 0.6478 | 0.6478 | 0.6478 | 0.6421 |
| Corner kicks | 0.6407 | 0.6419 | 0.6419 | 0.6412 | 0.6374 |
| Fouls | 0.6606 | 0.6610 | 0.6610 | 0.6609 | 0.6566 |
| Goalkeeper saves | 0.6458 | 0.6456 | 0.6456 | 0.6453 | 0.6423 |
| Shots on target | 0.6481 | 0.6464 | 0.6464 | 0.6461 | 0.6415 |
| Total tackles | 0.6670 | 0.6628 | 0.6628 | 0.6628 | 0.6574 |
| Yellow cards | 0.6493 | 0.6496 | 0.6496 | 0.6493 | 0.6475 |
| all stats | 0.6513 | 0.6507 | 0.6507 | 0.6505 | 0.6464 |

#### Scenario B: score path, all stats pooled, week by week

| Monday | frozen | as_run | shipped | fixed | refit | n | fixed - refit | fixed - frozen |
|---|---|---|---|---|---|---|---|---|
| 2025-12-01 | 0.6588 | 0.6587 | 0.6587 | 0.6588 | 0.6584 | 1252 | 0.0004 | 0.0000 |
| 2025-12-08 | 0.6490 | 0.6491 | 0.6491 | 0.6490 | 0.6459 | 1030 | 0.0031 | 0.0000 |
| 2025-12-15 | 0.6634 | 0.6635 | 0.6635 | 0.6633 | 0.6633 | 790 | -0.0000 | -0.0000 |
| 2025-12-22 | 0.6607 | 0.6609 | 0.6609 | 0.6611 | 0.6595 | 474 | 0.0016 | 0.0004 |
| 2025-12-29 | 0.6662 | 0.6653 | 0.6653 | 0.6663 | 0.6619 | 1128 | 0.0045 | 0.0001 |
| 2026-01-05 | 0.6784 | 0.6780 | 0.6780 | 0.6784 | 0.6687 | 752 | 0.0097 | -0.0000 |
| 2026-01-12 | 0.6574 | 0.6565 | 0.6565 | 0.6568 | 0.6573 | 1068 | -0.0005 | -0.0007 |
| 2026-01-19 | 0.6341 | 0.6350 | 0.6350 | 0.6349 | 0.6295 | 1158 | 0.0053 | 0.0007 |
| 2026-01-26 | 0.6472 | 0.6465 | 0.6465 | 0.6469 | 0.6473 | 1180 | -0.0004 | -0.0002 |
| 2026-02-02 | 0.6330 | 0.6336 | 0.6336 | 0.6337 | 0.6300 | 1182 | 0.0037 | 0.0007 |
| 2026-02-09 | 0.6456 | 0.6466 | 0.6466 | 0.6461 | 0.6450 | 1096 | 0.0011 | 0.0005 |
| 2026-02-16 | 0.6383 | 0.6337 | 0.6337 | 0.6344 | 0.6351 | 1348 | -0.0007 | -0.0038 |
| 2026-02-23 | 0.6437 | 0.6428 | 0.6428 | 0.6416 | 0.6388 | 1490 | 0.0027 | -0.0021 |
| 2026-03-02 | 0.6317 | 0.6318 | 0.6318 | 0.6311 | 0.6294 | 1348 | 0.0017 | -0.0006 |
| 2026-03-09 | 0.6471 | 0.6453 | 0.6453 | 0.6454 | 0.6373 | 1672 | 0.0081 | -0.0017 |
| 2026-03-16 | 0.6593 | 0.6603 | 0.6603 | 0.6604 | 0.6506 | 1726 | 0.0098 | 0.0011 |
| 2026-03-23 | 0.6704 | 0.6723 | 0.6723 | 0.6739 | 0.6687 | 126 | 0.0052 | 0.0035 |
| 2026-03-30 | 0.6421 | 0.6472 | 0.6472 | 0.6462 | 0.6389 | 1310 | 0.0072 | 0.0041 |
| 2026-04-06 | 0.6489 | 0.6461 | 0.6461 | 0.6459 | 0.6442 | 1602 | 0.0017 | -0.0031 |
| 2026-04-13 | 0.6505 | 0.6474 | 0.6474 | 0.6479 | 0.6408 | 1376 | 0.0071 | -0.0026 |
| 2026-04-20 | 0.6530 | 0.6538 | 0.6538 | 0.6537 | 0.6450 | 1896 | 0.0087 | 0.0007 |
| 2026-04-27 | 0.6499 | 0.6474 | 0.6474 | 0.6472 | 0.6470 | 1376 | 0.0002 | -0.0028 |
| 2026-05-04 | 0.6618 | 0.6641 | 0.6641 | 0.6633 | 0.6579 | 1276 | 0.0054 | 0.0015 |
| 2026-05-11 | 0.6621 | 0.6617 | 0.6617 | 0.6615 | 0.6565 | 1698 | 0.0050 | -0.0006 |
| 2026-05-18 | 0.6534 | 0.6541 | 0.6541 | 0.6531 | 0.6478 | 1014 | 0.0053 | -0.0003 |
| 2026-05-25 | 0.6341 | 0.6320 | 0.6320 | 0.6326 | 0.6352 | 236 | -0.0025 | -0.0014 |
| 2026-06-01 | 0.5012 | 0.4932 | 0.4932 | 0.4996 | 0.4846 | 14 | 0.0150 | -0.0016 |
| 2026-06-08 | 0.5452 | 0.5021 | 0.5021 | 0.5019 | 0.5282 | 24 | -0.0264 | -0.0433 |
| 2026-06-15 | 0.6341 | 0.6341 | 0.6341 | 0.6344 | 0.6307 | 52 | 0.0036 | 0.0003 |
| 2026-06-22 | 0.4868 | 0.4643 | 0.4643 | 0.4585 | 0.4525 | 12 | 0.0060 | -0.0284 |
| 2026-06-29 | 0.6229 | 0.6582 | 0.6582 | 0.6575 | 0.6401 | 40 | 0.0174 | 0.0346 |
| 2026-07-06 | 0.4893 | 0.4899 | 0.4899 | 0.4912 | 0.4663 | 56 | 0.0249 | 0.0020 |
| 2026-07-13 | 0.6681 | 0.6705 | 0.6705 | 0.6709 | 0.6569 | 190 | 0.0141 | 0.0028 |
| 2026-07-20 | 0.6648 | 0.6698 | 0.6698 | 0.6695 | 0.6540 | 676 | 0.0154 | 0.0047 |
| 2026-07-27 | 0.6230 | 0.6241 | 0.6241 | 0.6237 | 0.6195 | 392 | 0.0043 | 0.0008 |
| 2026-08-03 | 0.6191 | 0.6111 | 0.6111 | 0.6120 | 0.6102 | 386 | 0.0018 | -0.0071 |
| 2026-08-10 | 0.6457 | 0.6467 | 0.6467 | 0.6445 | 0.6390 | 822 | 0.0055 | -0.0012 |
| 2026-08-17 | 0.6602 | 0.6600 | 0.6600 | 0.6600 | 0.6573 | 1442 | 0.0027 | -0.0002 |
| 2026-08-24 | 0.6396 | 0.6398 | 0.6398 | 0.6393 | 0.6427 | 1606 | -0.0034 | -0.0003 |
| 2026-08-31 | 0.6711 | 0.6678 | 0.6678 | 0.6672 | 0.6636 | 1624 | 0.0036 | -0.0039 |
| 2026-09-07 | 0.6509 | 0.6533 | 0.6533 | 0.6533 | 0.6470 | 1988 | 0.0063 | 0.0024 |
| 2026-09-14 | 0.6419 | 0.6403 | 0.6403 | 0.6402 | 0.6367 | 1986 | 0.0035 | -0.0017 |
| 2026-09-21 | 0.6696 | 0.6698 | 0.6698 | 0.6688 | 0.6648 | 674 | 0.0040 | -0.0008 |
| 2026-09-28 | 0.6750 | 0.6796 | 0.6796 | 0.6770 | 0.6707 | 668 | 0.0063 | 0.0020 |
| 2026-10-05 | 0.6617 | 0.6598 | 0.6598 | 0.6596 | 0.6573 | 1414 | 0.0023 | -0.0021 |
| 2026-10-12 | 0.6536 | 0.6463 | 0.6463 | 0.6458 | 0.6395 | 2238 | 0.0063 | -0.0078 |

#### Scenario B: drift checks (mean over stats)

| path | calibration first 4 weeks | calibration last 4 weeks | gap to refit first 4 weeks | gap to refit last 4 weeks | trees at the end |
|---|---|---|---|---|---|
| frozen | 1.0059 | 0.9798 | 0.0313 | 0.0591 | 209.1429 |
| as_run | 1.0061 | 0.9809 | 0.0314 | 0.0591 | 1357.7143 |
| shipped | 1.0061 | 0.9809 | 0.0314 | 0.0591 | 1357.7143 |
| fixed | 1.0058 | 0.9808 | 0.0314 | 0.0573 | 1249.1429 |
| refit | 1.0101 | 0.9854 | 0.0000 | 0.0000 | 227.4286 |

#### Scenario B-bad: pooled score on the next seven days, per stat

| stat | frozen | as_run | shipped | fixed | refit |
|---|---|---|---|---|---|
| Big chances | 0.6477 | 0.6474 | 0.6474 | 0.6474 | 0.6415 |
| Corner kicks | 0.6407 | 0.6423 | 0.6423 | 0.6414 | 0.6371 |
| Fouls | 0.6606 | 0.6629 | 0.6629 | 0.6618 | 0.6593 |
| Goalkeeper saves | 0.6458 | 0.6454 | 0.6454 | 0.6456 | 0.6430 |
| Shots on target | 0.6481 | 0.6453 | 0.6453 | 0.6450 | 0.6423 |
| Total tackles | 0.6670 | 0.6631 | 0.6631 | 0.6626 | 0.6585 |
| Yellow cards | 0.6493 | 0.6497 | 0.6497 | 0.6497 | 0.6479 |
| all stats | 0.6513 | 0.6509 | 0.6509 | 0.6505 | 0.6471 |

#### Scenario B-bad: score path, all stats pooled, week by week

| Monday | frozen | as_run | shipped | fixed | refit | n | fixed - refit | fixed - frozen |
|---|---|---|---|---|---|---|---|---|
| 2025-12-01 | 0.6588 | 0.6587 | 0.6587 | 0.6588 | 0.6584 | 1252 | 0.0004 | 0.0000 |
| 2025-12-08 | 0.6490 | 0.6491 | 0.6491 | 0.6490 | 0.6459 | 1030 | 0.0031 | 0.0000 |
| 2025-12-15 | 0.6634 | 0.6635 | 0.6635 | 0.6633 | 0.6633 | 790 | -0.0000 | -0.0000 |
| 2025-12-22 | 0.6607 | 0.6609 | 0.6609 | 0.6611 | 0.6595 | 474 | 0.0016 | 0.0004 |
| 2025-12-29 | 0.6662 | 0.6653 | 0.6653 | 0.6663 | 0.6619 | 1128 | 0.0045 | 0.0001 |
| 2026-01-05 | 0.6784 | 0.6780 | 0.6780 | 0.6784 | 0.6687 | 752 | 0.0097 | -0.0000 |
| 2026-01-12 | 0.6574 | 0.6565 | 0.6565 | 0.6568 | 0.6573 | 1068 | -0.0005 | -0.0007 |
| 2026-01-19 | 0.6341 | 0.6350 | 0.6350 | 0.6349 | 0.6295 | 1158 | 0.0053 | 0.0007 |
| 2026-01-26 | 0.6472 | 0.6465 | 0.6465 | 0.6469 | 0.6473 | 1180 | -0.0004 | -0.0002 |
| 2026-02-02 | 0.6330 | 0.6336 | 0.6336 | 0.6337 | 0.6300 | 1182 | 0.0037 | 0.0007 |
| 2026-02-09 | 0.6456 | 0.6466 | 0.6466 | 0.6461 | 0.6450 | 1096 | 0.0011 | 0.0005 |
| 2026-02-16 | 0.6383 | 0.6337 | 0.6337 | 0.6342 | 0.6467 | 1348 | -0.0125 | -0.0041 |
| 2026-02-23 | 0.6437 | 0.6429 | 0.6429 | 0.6418 | 0.6394 | 1490 | 0.0024 | -0.0019 |
| 2026-03-02 | 0.6317 | 0.6312 | 0.6312 | 0.6309 | 0.6330 | 1348 | -0.0021 | -0.0008 |
| 2026-03-09 | 0.6471 | 0.6451 | 0.6451 | 0.6455 | 0.6403 | 1672 | 0.0052 | -0.0016 |
| 2026-03-16 | 0.6593 | 0.6609 | 0.6609 | 0.6608 | 0.6527 | 1726 | 0.0081 | 0.0015 |
| 2026-03-23 | 0.6704 | 0.6754 | 0.6754 | 0.6745 | 0.6667 | 126 | 0.0078 | 0.0041 |
| 2026-03-30 | 0.6421 | 0.6472 | 0.6472 | 0.6455 | 0.6403 | 1310 | 0.0053 | 0.0034 |
| 2026-04-06 | 0.6489 | 0.6476 | 0.6476 | 0.6477 | 0.6480 | 1602 | -0.0003 | -0.0012 |
| 2026-04-13 | 0.6505 | 0.6471 | 0.6471 | 0.6475 | 0.6407 | 1376 | 0.0067 | -0.0030 |
| 2026-04-20 | 0.6530 | 0.6554 | 0.6554 | 0.6547 | 0.6457 | 1896 | 0.0090 | 0.0017 |
| 2026-04-27 | 0.6499 | 0.6481 | 0.6481 | 0.6479 | 0.6479 | 1376 | -0.0001 | -0.0021 |
| 2026-05-04 | 0.6618 | 0.6656 | 0.6656 | 0.6641 | 0.6587 | 1276 | 0.0054 | 0.0023 |
| 2026-05-11 | 0.6621 | 0.6644 | 0.6644 | 0.6637 | 0.6579 | 1698 | 0.0058 | 0.0016 |
| 2026-05-18 | 0.6534 | 0.6560 | 0.6560 | 0.6561 | 0.6478 | 1014 | 0.0084 | 0.0027 |
| 2026-05-25 | 0.6341 | 0.6296 | 0.6296 | 0.6303 | 0.6325 | 236 | -0.0022 | -0.0038 |
| 2026-06-01 | 0.5012 | 0.4910 | 0.4910 | 0.5000 | 0.5169 | 14 | -0.0169 | -0.0012 |
| 2026-06-08 | 0.5452 | 0.5132 | 0.5132 | 0.5192 | 0.5515 | 24 | -0.0323 | -0.0260 |
| 2026-06-15 | 0.6341 | 0.6196 | 0.6196 | 0.6163 | 0.6181 | 52 | -0.0018 | -0.0178 |
| 2026-06-22 | 0.4868 | 0.4450 | 0.4450 | 0.4424 | 0.4453 | 12 | -0.0029 | -0.0444 |
| 2026-06-29 | 0.6229 | 0.6493 | 0.6493 | 0.6497 | 0.6310 | 40 | 0.0187 | 0.0268 |
| 2026-07-06 | 0.4893 | 0.4711 | 0.4711 | 0.4735 | 0.4662 | 56 | 0.0073 | -0.0158 |
| 2026-07-13 | 0.6681 | 0.6641 | 0.6641 | 0.6647 | 0.6487 | 190 | 0.0160 | -0.0034 |
| 2026-07-20 | 0.6648 | 0.6710 | 0.6710 | 0.6702 | 0.6549 | 676 | 0.0153 | 0.0054 |
| 2026-07-27 | 0.6230 | 0.6274 | 0.6274 | 0.6251 | 0.6220 | 392 | 0.0032 | 0.0022 |
| 2026-08-03 | 0.6191 | 0.6155 | 0.6155 | 0.6134 | 0.6128 | 386 | 0.0006 | -0.0057 |
| 2026-08-10 | 0.6457 | 0.6487 | 0.6487 | 0.6465 | 0.6353 | 822 | 0.0112 | 0.0008 |
| 2026-08-17 | 0.6602 | 0.6619 | 0.6619 | 0.6622 | 0.6561 | 1442 | 0.0061 | 0.0020 |
| 2026-08-24 | 0.6396 | 0.6376 | 0.6376 | 0.6377 | 0.6419 | 1606 | -0.0041 | -0.0019 |
| 2026-08-31 | 0.6711 | 0.6659 | 0.6659 | 0.6652 | 0.6627 | 1624 | 0.0026 | -0.0058 |
| 2026-09-07 | 0.6509 | 0.6523 | 0.6523 | 0.6511 | 0.6474 | 1988 | 0.0037 | 0.0001 |
| 2026-09-14 | 0.6419 | 0.6402 | 0.6402 | 0.6399 | 0.6380 | 1986 | 0.0019 | -0.0020 |
| 2026-09-21 | 0.6696 | 0.6691 | 0.6691 | 0.6677 | 0.6615 | 674 | 0.0062 | -0.0020 |
| 2026-09-28 | 0.6750 | 0.6810 | 0.6810 | 0.6804 | 0.6690 | 668 | 0.0114 | 0.0054 |
| 2026-10-05 | 0.6617 | 0.6586 | 0.6586 | 0.6568 | 0.6546 | 1414 | 0.0023 | -0.0049 |
| 2026-10-12 | 0.6536 | 0.6454 | 0.6454 | 0.6446 | 0.6396 | 2238 | 0.0050 | -0.0090 |

#### Scenario B-bad: drift checks (mean over stats)

| path | calibration first 4 weeks | calibration last 4 weeks | gap to refit first 4 weeks | gap to refit last 4 weeks | trees at the end |
|---|---|---|---|---|---|
| frozen | 1.0059 | 0.9798 | 0.0313 | 0.0619 | 209.1429 |
| as_run | 1.0061 | 0.9966 | 0.0314 | 0.0591 | 1243.4286 |
| shipped | 1.0061 | 0.9966 | 0.0314 | 0.0591 | 1243.4286 |
| fixed | 1.0058 | 0.9974 | 0.0314 | 0.0569 | 1117.7143 |
| refit | 1.0101 | 0.9993 | 0.0000 | 0.0000 | 238.2857 |

#### Decisions over all weeks (summed over stats)

| scenario, path | adopted | rejected | too few | adopt_helped | reject_helped | slack_used | halved_worse_than_old |
|---|---|---|---|---|---|---|---|
| A as_run | 52 | 32 | 21 | n/a | n/a | 5 | 0 |
| A fixed | 48 | 36 | 21 | 27 | 14 | 0 | 0 |
| A shipped | 52 | 32 | 21 | 28 | 13 | 5 | 0 |
| B as_run | 201 | 86 | 35 | n/a | n/a | 26 | 0 |
| B fixed | 182 | 105 | 35 | 95 | 50 | 0 | 0 |
| B shipped | 201 | 86 | 35 | 112 | 38 | 26 | 0 |
| B-bad as_run | 181 | 106 | 35 | n/a | n/a | 31 | 0 |
| B-bad fixed | 159 | 128 | 35 | 91 | 70 | 0 | 0 |
| B-bad shipped | 181 | 106 | 35 | 108 | 61 | 31 | 0 |

#### Size of the weekly move

| scenario | weeks with a candidate | median move | largest move | over 3% (halved) |
|---|---|---|---|---|
| A | 84.0000 | 0.0047 | 0.0067 | 0.0000 |
| B | 287.0000 | 0.0050 | 0.0094 | 0.0000 |
| B-bad | 287.0000 | 0.0053 | 0.0156 | 0.0000 |

#### Bad week (B-bad minus B, all stats pooled; positive is worse)

| Monday | frozen | as_run | shipped | fixed | refit |
|---|---|---|---|---|---|
| 2026-02-02 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| 2026-02-09 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| 2026-02-16 | +0.0000 | +0.0000 | +0.0000 | -0.0003 | +0.0115 |
| 2026-02-23 | +0.0000 | +0.0002 | +0.0002 | +0.0002 | +0.0006 |
| 2026-03-02 | +0.0000 | -0.0006 | -0.0006 | -0.0002 | +0.0037 |
| 2026-03-09 | +0.0000 | -0.0002 | -0.0002 | +0.0001 | +0.0030 |
| 2026-03-16 | +0.0000 | +0.0007 | +0.0007 | +0.0004 | +0.0021 |
| 2026-03-23 | +0.0000 | +0.0031 | +0.0031 | +0.0006 | -0.0020 |
| 2026-03-30 | +0.0000 | -0.0000 | -0.0000 | -0.0006 | +0.0013 |
| 2026-04-06 | +0.0000 | +0.0014 | +0.0014 | +0.0018 | +0.0038 |
| 2026-04-13 | +0.0000 | -0.0004 | -0.0004 | -0.0004 | -0.0001 |
| 2026-04-20 | +0.0000 | +0.0016 | +0.0016 | +0.0010 | +0.0007 |
| 2026-04-27 | +0.0000 | +0.0007 | +0.0007 | +0.0007 | +0.0009 |
