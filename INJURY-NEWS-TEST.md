# Injury news test: is Paddy Power slow to reprice team-mates?

Spec written 1 November 2026. Nothing here is built yet. This is a test that bets nothing: it watches, logs and scores.

## The question

When an NBA player is ruled out (or ruled back in), his team-mates' minutes and usage change. Sharp books reprice within minutes. Does Paddy Power leave team-mates' player props at the old price long enough to take them, and does that stale price beat the close?

If yes, this is an edge that does not depend on our model beating the market, only on being faster than Paddy Power. If no, we find out without risking a penny and drop it.

## What already exists

| Piece | Where | What it gives |
|---|---|---|
| ESPN NBA injury feed | `team_news.py`, `usmodel_live.py` (`cache/espn_nba_injuries.json`) | Every listed player, status, and a `date` timestamp per update. About 22 updates in the 24 hours to 1 Nov. Currently cached for 3 hours, far too slow for this |
| Paddy Power game feed | `paddypower_prices.py` | One GET returns every market on a game. Each runner carries `previousWinRunnerOdds` (the price before the last change, no timestamp) and each market a `marketStatus` (OPEN or SUSPENDED) |
| Price log | `pplog.py`, `pplog/*.jsonl` | First and last price per line, k5/k10 records, results. Gives the pre-news price and the near-close price for free |
| Who gains when a team-mate sits | `nba_stats.py withwithout` | Minutes, points, rebounds, assists with and without a team-mate, with ranges. Not yet run live |
| 5-minute launchd job | `com.zacthorman.lineups.plist`, `lineups_auto.py` | A tick to hang the watcher on |
| Rule scoring | `ruletrack.py` | Freeze, live record, closing line value (CLV) |

## The constraint that shapes the design

Paddy Power's feed is private and runs from the connection Zac bets from. `paddypower_prices.py` caps it at 60 games a day, 15 to 30 seconds between requests, and locks out for 24 hours on any refusal. On 1 Nov the 60 were already used by 14:00.

So this test must not poll Paddy Power every minute. It polls the free feeds (ESPN, the NBA's official report) often, and spends Paddy Power requests **only when news has just landed**, on the one game it affects.

**Budget:** carve a `NEWS_RESERVE` of 20 out of the existing 60, not on top of it. Same spacing, same lockout, same lock file, same off switch. The footprint on Paddy Power does not grow. If the test looks promising, raising the total is a separate decision.

## How it works

### 1. Watch for news (`news_watch.py`, every 3 minutes, 16:00 to 03:30 UK)

- Fetch ESPN's NBA injuries JSON fresh (its own cache entry with a 3-minute life, so the existing 3-hour cache used by the build is untouched). About 230 requests a day to a public feed.
- Optional second source, phase 2: the NBA's official injury report, a PDF the league republishes every 15 minutes at `ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_HH_MMAM.pdf`. Gives an official timestamp to compare ESPN against.
- Diff against the last snapshot. A **news event** is a player on a team playing within the next 14 hours whose status changes to Out or Doubtful, or from Out/Doubtful back to available (returns move team-mates the other way).
- Ignore players who don't matter: under 15 minutes a game over his last 10 (SofaScore box scores already in the cache), or already Out for the previous 3 games (long-term absences are already priced).
- Write the event to `news/events.jsonl`: player, team, game, status before and after, ESPN `date`, our `seen_at`, the gap between them.

### 2. Snapshot Paddy Power (only on an event)

For the affected game, within the reserve:

| Snapshot | When | Why |
|---|---|---|
| `pre` | already in `pplog` (the last price logged before ESPN's `date`) | the price before the news |
| `t0` | as soon as the event is seen (still respecting the 15 to 30 second gap) | what we could actually have bet |
| `t20` | 20 minutes later, if before tip-off | how fast Paddy Power moves |
| `close` | already in `pplog` (`last`) | the yardstick |

That is 2 Paddy Power requests an event. Two events on the same game inside 20 minutes share snapshots. With 20 a day that covers about 10 events a night, which is roughly the number that matter.

Store **parsed lines only** (player, stat, line, side, price, `previousWinRunnerOdds`, `marketStatus`) in `news/snapshots.jsonl`, not the 500 KB raw page.

### 3. Classify every team-mate line

For each team-mate prop on the side the news should push (overs when a team-mate is ruled out, unders when one returns):

- **Already moved:** `t0` differs from `pre` by 3%+ in the expected direction, or the market is SUSPENDED at `t0`. Paddy Power beat us to it.
- **Stale, then moved:** `t0` equals `pre`, and `t20` or `close` is 3%+ shorter. This is the edge.
- **Never moved:** `t0`, `t20` and `close` all within 3% of `pre`. Either Paddy Power thinks the news doesn't matter or it misses it entirely; results decide which.

Same treatment for opponents' lines is optional (smaller effect, phase 2).

### 4. The control

Prices drift towards tip-off anyway. For every news game, take one game the same night with no news, snapshot it at the same clock times inside the reserve if there's room, and otherwise use its `pplog` first and last. The edge is news-game drift **minus** control drift, never the raw drift.

## Scoring (`news_eval.py`)

For the stale lines, and separately for all expected-side team-mate lines:

- **CLV at t0:** `t0` price over `close` price, minus one. Averaged, with a 90% range bootstrapped **by event** (lines in one game are not independent).
- **Paper ROI at t0:** £1 a line at the `t0` price, settled by `pplog`. One line per player per stat (the one nearest evens), like `ruletrack.py`.
- **Speed:** median minutes from ESPN `date` to our `seen_at`, and the share of events where Paddy Power had already moved by `t0`.
- **Model check:** does `nba_stats.py withwithout` predict which team-mates move most? If it does, the rule can target those lines and skip the rest.

## When to call it

After **30 news events** (about 3 to 4 weeks of an NBA season):

- **Pursue** if stale team-mate lines show CLV at t0 of +3% or more over the control, with the 90% range clear of zero. Then freeze it as a rule in `ruletrack.py` (`nba_news_stale`) and keep scoring it live before any money goes on.
- **Drop** if Paddy Power had already moved on most events by `t0`, or the CLV range sits on zero. Write the result into `FINDINGS.md` either way.
- Results alone (win/lose) are not the verdict at this sample size. CLV is.

## Build order

1. `news_watch.py`: ESPN fetch, diff, event filter, `news/events.jsonl`. Tests with ESPN fixtures saved by hand, no network (follow `tests/test_paddypower_lockout.py`).
2. `NEWS_RESERVE` in `paddypower_prices.py`: a `--event` call that draws from the reserve and records which budget it used. Test that the reserve can never push the day past 60 and that a lockout stops it like any other run.
3. Snapshot writer and the `t20` follow-up (a pending list the 3-minute tick checks).
4. Hook into launchd: either `lineups_auto.py` calls `news_watch.py` on each tick in the NBA window, or a new plist at 180 seconds. It must never block line-ups or the nightly build, same as the price jobs (see `PIPELINE-SAFETY.md`).
5. `news_eval.py` and a section in `RULES_TRACK.md`.
6. Phase 2: the official NBA PDF, opponents' lines, Pinnacle NBA player props as a sharp reference (`pinnacle_prices.py` is football only today).

## Off switch and safety

- `touch .news_off` stops the watcher.
- Never fatal: any failure logs one line and leaves everything else running.
- Never places a bet, never logs in, never touches the account.

## Later: football

The same test fits football at 60 minutes before kick-off, when `lineups_auto.py` already pulls confirmed XIs. A surprise benching or a striker dropped should move team-mates' shots and opponents' tackles/fouls lines. Build only if the NBA test passes.
