# Pipeline safety

What can go wrong between `update.py` starting and the site going live, what
now stops each failure, and the test that proves the stop works.

Two rules run through it.

* **A page that fails a check never replaces the one that is live.** An
  empty, cut-off or malformed page stops the run before `publish.sh` pushes
  anything, says why in one line (in `update.log`, in `.last_run.json`, and in
  the macOS notification), and the last good copy of the page is put back on
  disk so the next run cannot pick up the broken one by accident either.
* **A failed fetch costs only that feed.** When one league or one sport
  cannot be fetched (refused, unreachable, or an empty answer that
  contradicts yesterday's page), nothing is written for it, so its pages stay
  as yesterday's. The run logs a `WARNING` line, every other feed is built,
  checked and published as normal, and the status and notification say which
  feed is stale. Only every feed failing at once stops the publish, because
  then there is nothing new to publish and SofaScore is refusing this machine.

Nothing here changes a model, a price, a line or a betting rule. The checks
only read the shape of a page (does it end, does its data parse, does it hold
fixtures with the fields every other script reads, does it hold any
statistics) and decide whether it may replace yesterday's.

## Running the tests

    .venv/bin/python -B tests/run_all.py

`run_all.py` runs every file in `tests/`. It exists because
`test_exchange.py` is written as plain pytest functions and pytest is not
installed, so `python -m unittest` quietly reported "NO TESTS RAN" for it and
passed. It also points `learner.py` at a scratch file, because building the
picks refits and rewrites `learned.json`, and running the tests used to change
the committed model.

The new tests are all in `tests/test_pipeline_safety.py`. None of them touches
the network or git, and none runs `publish.sh`: requests go to a fake session
and every command `update.py` would launch goes to a fake runner.

## The pipeline, end to end

`update.py`, run daily by launchd on the Mac:

1. Read `update.json`; take the lock.
2. If the last run died in git or `publish.sh`, publish the reports already on disk.
3. Check FlareSolverr is healthy (restart it if not).
4. **New:** `site_guard.snapshot()` keeps a copy of every page that passes the checks in `.last_good/`.
5. Settle tracked bets (`bettrack.py`, `besttrack.py`, `linelog.py`). Never fatal.
6. `run.py --leagues ... --status-file .build_status.json` builds each domestic league and writes what each came to: built, nothing on, or fetch failed. A league whose fetch failed keeps yesterday's page; any other failure is fatal.
7. Optional builds, each its own `run.py`: Nations League, Champions League, Europa League, NFL, darts, MLB, NBA. Exit 0 is built, exit 3 (`BAD_FETCH`) is a failed fetch that keeps yesterday's pages for that sport, anything else is "nothing on" as before.
   - **New:** `update.check_feeds` stops the run if no feed was built and at least one failed to fetch.
8. **New:** `site_guard.vet()` checks every report, with the stale-cache check for the ones this run wrote.
9. `rerender.py` rewrites every report from the data inside it.
10. **New:** `site_guard.vet()` again, since rerender rewrote them all.
11. `make_index.py --prune` writes `index.html` and deletes reports with nothing left to play.
12. **New:** `site_guard.index_problems()` checks the index.
13. `git add/commit/push`, then `publish.sh`, which refreshes prices, team news and the player models, rewrites reports in place, rebuilds the index, `tonight.html` and the record pages, stages the site and force-pushes it to `gh-pages`.
14. **New, inside publish.sh:** `site_guard.py gate "$STAGE"` checks exactly what is staged, after every step above and before the push.
15. `publish.sh` checks the live site answers and serves this build.
16. `tactics_fetch.py`. Never fatal.

Inside each `run.py` build: `sofascore_api.get_json` fetches (through the
cache), `tournament_team_ids` reads the team list, `team_next_events` each
team's next game, `hitrates.team_form` each side's record, then
`report.write_report` writes the page.

## Failure paths found, and what now guards each

| # | Failure path (before this change) | What now guards it | Test that proves it |
|---|---|---|---|
| 1 | **A fetch that gives up.** `get_json` returns `None` after a 5xx or an unexpected status on every attempt. The caller reads `None` as "no events", so `team_next_events` returns `[]`, every team has no next game, and `run.py` exits "No fixtures found", which `--leagues` and `update.py` both treat as a quiet week. The league silently drops off the site. | `get_json` records it (`note_failure`). `run.bad_fetch_reason` turns "No fixtures found" plus any noted failure into a failed fetch: exit code 3 (`BAD_FETCH`), with the league named in the status file. That feed keeps yesterday's page and is warned about (rows 23 to 27). | `FetchLayer.test_server_errors_until_the_retries_run_out_are_noted`, `RunBuild.test_leagues_with_every_fixture_list_refused_is_a_failed_fetch`, `RunBuild.test_single_league_bad_fetch_exits_bad_fetch` |
| 2 | **An empty or non-JSON response.** A 200 with an empty or HTML body returns `None` with only a printed line, same path as 1. | Noted as a failure, then as 1. | `FetchLayer.test_empty_body_that_is_not_json_is_noted` |
| 3 | **An error body dressed as a 200** (FlareSolverr's `{"error": {"code": 500}}`). Returned `None`, same path as 1. | Noted as a failure. A 404 error body is not, because SofaScore answers "no next fixture" with a 404. | `FetchLayer.test_error_body_dressed_as_200_is_noted`, control `FetchLayer.test_a_genuine_404_is_not_a_failure`, `FetchLayer.test_empty_events_list_is_a_real_answer` |
| 4 | **A missing field.** A 200 whose body lacks `events` (SofaScore changing the shape of an answer) read as an empty fixture list, same path as 1. | `team_next_events` notes it as a failure. | `FetchLayer.test_body_missing_the_events_field_is_noted` |
| 5 | **Refused outright.** `Blocked` (five 403s in a row) killed `run.py` with a traceback. In the optional steps (Nations, Champions League, Europa League, NFL, darts, MLB, NBA) every non-zero exit was ignored, so the run carried on and published with that sport's page silently stale. | `run.main` turns `Blocked` into exit code 3. `update.optional_build` records exit code 3 as a failed fetch for that sport and warns, while still ignoring the ordinary "nothing on" exit. | `FetchLayer.test_repeated_refusals_raise_blocked`, `RunBuild.test_blocked_exits_bad_fetch`, `UpdateRun.test_one_sport_refused_keeps_its_pages_and_publishes_the_rest` |
| 6 | **SofaScore unreachable.** In an optional step, "Couldn't reach SofaScore" and "Couldn't read the team list" were ignored like a quiet week; in `--leagues` they failed the whole run. | Both are a failed fetch (exit 3) everywhere, so that feed keeps yesterday's pages and is warned about. | `RunBuild.test_unreachable_schedule_exits_bad_fetch`, `RunBuild.test_empty_team_list_exits_bad_fetch` |
| 7 | **A competition renamed or renumbered at SofaScore.** Every team's next game sits under a new competition id, nothing matches the old one, and "No fixtures found" passes as a quiet week. | `run.known_upcoming` reads the reports on disk: if yesterday's page lists games in that competition still to come (within the same horizon the build used), today's "none" is a failed fetch, not a quiet week, and that page is kept. | `RunBuild.test_renamed_competition_contradicting_yesterdays_page_fails`, `RunBuild.test_single_league_within_days_contradicted_by_page_on_disk`, controls `RunBuild.test_leagues_quiet_week_still_passes`, `RunBuild.test_single_league_quiet_week_is_not_bad_fetch`, `RunBuild.test_games_beyond_the_horizon_do_not_contradict` |
| 8 | **A competition renamed in `update.json`.** Already loud ("Unknown league"), and already fatal. Now covered by a test. | Unchanged: a config mistake, not a fetch, so it still stops the run, as does a league whose fixtures produced no data at all. | `RunBuild.test_renamed_competition_in_update_json_fails`, `RunBuild.test_league_that_produced_no_data_is_still_fatal`, `UpdateRun.test_league_build_failing_for_another_reason_still_stops` |
| 9 | **A stale cache.** The cache judges age by file mtime, so anything that touches the files (unpacking `cache_backtest.tar.zst`, a restore, a copied folder) makes last week's "next fixtures" look fresh. The page is built from games already played, then `make_index --prune` deletes it and the league vanishes. | `team_next_events` throws away a cached list whose every game kicked off over 3 hours ago and asks again. `site_guard` rejects a report written this run whose every fixture kicked off over 6 hours ago. | `FetchLayer.test_stale_cached_fixture_list_is_refetched`, control `FetchLayer.test_fresh_cached_fixture_list_is_used_without_a_request`, `ReportChecks.test_fresh_report_from_stale_cache`, `KeepYesterday.test_vet_only_applies_staleness_to_this_runs_reports`, `UpdateRun.test_stale_cache_build_stops_the_publish` |
| 10 | **A half-written cache file.** Already handled (dropped and refetched). Now tested. | Unchanged, now tested. | `FetchLayer.test_half_written_cache_file_is_refetched` |
| 11 | **A page cut off part way.** `report.write_report`, `make_index` and `tonight.py` used `write_text`, which empties the file before writing. A crash, a full disk or the Mac sleeping mid-write left half a page that every later step read as real. | `site_guard.atomic_write` writes beside the page and renames over it, so a failure leaves yesterday's page whole. All three writers use it. | `AtomicWrites.test_failed_write_leaves_the_old_page_whole`, `AtomicWrites.test_write_report_is_atomic` |
| 12 | **A report that is empty, a stub, cut off, unreadable, or missing its data.** Nothing checked the reports before publishing. `rerender.py` skipped an unreadable one and still exited 0. | `site_guard.report_problems` rejects each case; `update.py` runs it after the builds and after rerender, and `publish.sh` runs it on the staged site. | `ReportChecks.test_missing_file`, `test_empty_file`, `test_stub`, `test_cut_off_part_way`, `test_cut_off_after_the_payload`, `test_no_payload`, `test_payload_does_not_parse`, `UpdateRun.test_page_cut_off_stops_the_publish` |
| 13 | **A page written with zero fixtures.** | Rejected (`holds zero fixtures`). | `ReportChecks.test_zero_fixtures`, `UpdateRun.test_empty_page_stops_the_publish_and_keeps_yesterdays` |
| 14 | **Malformed fixtures.** A fixture missing its id, teams or kick-off, or without home and away records, breaks the index and the pages that read it. | Rejected, naming the fixture and the missing field. | `ReportChecks.test_missing_fields`, `ReportChecks.test_missing_records` |
| 15 | **A page with fixtures but no statistics**, or a round where most fixtures lack one team's record (a fetch that died part way). `build_fixture` only skips a fixture when both sides are empty. | Rejected. One one-sided fixture is allowed (a club's first game in a competition has no record in it), and the cross-competition builds (darts, the Champions League, the Europa League and the Nations League), which meet unrecorded players and debutant clubs as a matter of course, are exempt. | `ReportChecks.test_no_statistics_at_all`, `ReportChecks.test_most_fixtures_one_sided`, control `ReportChecks.test_one_debutant_is_allowed` |
| 16 | **`make_index --prune` deleted unreadable reports.** `read_payload` swallowed a decode error and returned `{}`, which looked like "no upcoming fixtures", so a cut-off report was deleted and its league left the site without a word. | An unreadable report is named and never pruned. | `IndexPrune.test_unreadable_report_is_not_pruned` (which also checks prune still removes a finished report) |
| 17 | **An index that lists nothing, is cut off, still holds its template placeholder, or links to reports that are not there.** Published as is. | `site_guard.index_problems`, run by `update.py` after `make_index` (putting yesterday's index back) and by the `publish.sh` gate. | `IndexChecks.test_zero_fixtures`, `test_link_to_missing_report`, `test_cut_off`, `test_template_placeholder_left_in`, `test_missing`, `UpdateRun.test_empty_index_stops_the_publish` |
| 18 | **Pages rewritten inside `publish.sh` after `update.py` has finished.** `team_news.py`, `lineups_auto.py` and others rewrite reports, and `publish.sh` rebuilds the index and `tonight.html`; a manual or resumed publish never went through `update.py` at all. | The gate in `publish.sh` checks the staged site, after every step and before `git push`, and puts the last good copy of any bad report back on disk. `tonight.html` and the record pages must be whole if present. | `KeepYesterday.test_gate_on_staged_site`, `test_gate_catches_a_cut_off_small_page`, `test_gate_cli_exits_non_zero`, `PublishScript.test_gate_runs_after_staging_and_before_the_push`, control `KeepYesterday.test_gate_passes_a_good_site` |
| 19 | **No copy of yesterday's page to fall back on.** A bad build overwrote the only copy. | `snapshot` keeps every page that passes in `.last_good/` before each run, and never keeps a bad one. A bad page is moved to `.rejected/` for inspection and the good copy put back; a brand-new page with no good copy is left out. | `KeepYesterday.test_snapshot_keeps_only_good_pages`, `test_vet_puts_yesterdays_page_back`, `test_vet_without_a_good_copy_moves_the_page_aside`, `test_vet_with_no_reports_fails` |
| 20 | **A failed report check retried as a publish.** The next run republishes the reports on disk only after a git or `publish.sh` failure. | The report check's message does not match those, so a run stopped by the guard is never resumed as a publish. | `UpdateRun.test_report_failure_is_not_resumed_as_a_publish` |
| 21 | **The guard blocking a good run.** | A full fake run with good pages reaches `publish.sh`; the real committed `tonight.html`, `best-bets-summary.html`, `market-check.html` and `pp-results.html` pass the page check. | `UpdateRun.test_good_run_publishes`, `ReportChecks.test_good_report_passes`, `IndexChecks.test_good_index_passes`, `KeepYesterday.test_vet_passes_good_reports` |
| 22 | **A dry run reporting failure.** Found while making this change: once the runner returned exit codes, `--dry-run` returned `True` where 0 was meant and failed its first step. | Fixed before commit; a dry run launches nothing and writes no status. | `DryRun.test_dry_run_launches_nothing_and_passes` |
| 23 | **One blocked feed froze the whole site.** The first version of this change stopped the publish on any failed fetch, so SofaScore blocking one feed (the NBA, say) would have held every other sport at yesterday's pages for as long as the block lasted. | A failed fetch now costs only that feed: `update.optional_build` and the `--leagues` status file record it, `keep_yesterday` logs `WARNING: <feed>: the fetch failed. Keeping yesterday's <feed> pages`, the rest is built, checked by `site_guard` and published, and `.last_run.json` and the notification name the stale feed. | `UpdateRun.test_one_sport_refused_keeps_its_pages_and_publishes_the_rest` |
| 24 | **One league's fetch failing inside `--leagues` failed every league.** All domestic leagues are one `run.py` process, so one refused league made the step exit non-zero and nothing was published. | `run.py --leagues` carries on past a league whose fetch failed, writes `built`, `empty`, `failed` and `bad_fetch` to `--status-file`, and exits 3 when the only problems are failed fetches. `update.py` keeps yesterday's page for each league in `bad_fetch` and publishes the rest. | `RunBuild.test_one_league_refused_the_others_still_build`, `UpdateRun.test_one_league_refused_keeps_its_page_and_publishes_the_rest` |
| 25 | **The circuit breaker tripping part way through `--leagues`.** `Blocked` used to end the whole process, so leagues already built were never reported and the rest never ran. | The league that tripped it and every league after it are marked as failed fetches without another request (asking again would be the hammering the breaker exists to stop), and those built before it are published. | `RunBuild.test_blocked_marks_the_rest_without_asking_again` |
| 26 | **Every feed failing at once.** Publishing then would only re-stamp yesterday's site as today's. | `update.check_feeds` stops the run when no feed was built and at least one failed to fetch. Feeds with nothing on are counted in neither. | `UpdateRun.test_every_feed_refused_at_once_stops_the_publish` |
| 27 | **A failed feed hiding a broken page.** A partial run must not loosen the page checks. | The report and index checks run on every page whatever happened to the feeds; an empty, cut-off or malformed page still stops the publish. | `UpdateRun.test_one_sport_refused_does_not_excuse_an_empty_page` |

## Swallowed exceptions reviewed and left alone

These catch everything on purpose and cost a garnish, never the page itself.
Each prints a line, and anything they leave broken is now caught by the
report and index checks above.

| Where | What it costs when it fires |
|---|---|
| `update._flare_healthy` | Treated as unhealthy, so the container is restarted, and the run stops if that fails. Loud. |
| `update.notify` | The macOS notification only. The failure is still in the log and the status file. |
| `run.build`: line-ups, NFL injuries, team news | That extra on the page. Printed as "skipped". |
| `report._attach_team_lines` (merged from oct21-work): the team-lines gate and each fixture's team model | The team model's numbers on that page; `teamValued()` then calls no team line a take. Printed. |
| `run.build_fixture`: club form for internationals | That squad's club records. Printed. |
| `run._previous_club_records`, `run._fixture_referee` (both also catch `Blocked`) | A new signing's old-club rows and the referee's name, both display only. The feature is switched off for the run; the next core request that is refused still raises `Blocked`, because the refusal count is not reset. |
| `run.build`: reading the old Nations League file to carry fixtures forward | The carried fixtures; the new ones are still written. |
| `hitrates.club_form_for_squad` | One club's records. Printed when verbose. |
| `make_index`: picks, picker pages | The picks block and the pick pages. Printed. |
| `tonight.py`: its sections | That section of `tonight.html`. The page must still end whole to pass the gate. |
| `publish.sh`: every price, model and log step (`\|\| echo ... continuing`) | Fresher prices or records. The pages carry their last values, and the gate still checks every page staged. |
| `update.py`: settling bets, `tactics_fetch.py` | The track record or tactical data, never the page. |

## What changes for the person running it

* A feed whose fetch fails keeps yesterday's pages and the rest of the site is
  published. Look for `WARNING:` in `update.log`; `python update.py --status`
  ends its outcome line with "yesterday's pages kept for ..." and a macOS
  notification says the same. Nothing needs doing unless it persists; if one
  feed is refused for days, raise `delay_min` and `delay_max` or switch that
  sport off in `update.json` until it recovers.
* A kept page still loses its finished fixtures to `make_index --prune`, as
  every page always has, so a feed that stays blocked past its last listed
  game drops off the front page rather than advertising games already played.
* The run still stops, and publishes nothing, when a page is empty, cut off or
  malformed, when the index is, when every feed fails to fetch at once, and
  for a failure that is not a fetch (an unknown league name, a league whose
  fixtures produced no data at all). The reason is the last line of
  `update.log`.
* `.last_good/` holds the pages that are known to be good, `.rejected/` the
  ones that were refused, and `.build_status.json` what each league came to on
  the last run. All are ignored by git.
* When a "No fixtures found" happens, `run.py` reads the reports on disk to
  check the answer against yesterday's page. That costs a few seconds on a
  quiet day for the Champions League and Europa League steps, and nothing
  otherwise.
