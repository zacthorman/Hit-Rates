# NBA.com stats: minutes, starters and line-ups

Written 28 October 2026 on the `nba-stats` branch. The code is `nba_stats.py`, the tests `tests/test_nba_stats.py`.

## Not run live yet

stats.nba.com does not answer from the cloud machine this was written on (curl gets no answer at all), so **nothing here has seen a real answer**. The parsers were written against the response shapes stats.nba.com documents and tested on fixtures built by hand in those shapes (`tests/fixtures/nba_stats/`, each marked `_fixture`). There are no results yet. The first live run has to happen on the Mac, and it is the test of whether the endpoints and parameters below are right.

## What it is for

SofaScore, which everything else reads, gives a box score per player but not who started, and nothing about who was on the floor together. Two questions need that.

1. **Small ball.** Do backup big men (and others) lose minutes and output when the opponent plays small? An earlier test on 20 games a team was inconclusive: two reasonable definitions of "big" gave opposite signs. Part of the trouble is SofaScore's positions (it lists Karl-Anthony Towns as F). NBA.com's listed position is reliable, and its line-up tables say how long each five-man group played, so "how small did the opponent play" can be counted.
2. **Injury boosts.** When a team-mate is out, how do a player's minutes, points, rebounds and assists change? The player game log lists everyone who got on the floor in every game, so with and without can be split exactly.

## How to run it on the Mac

```bash
cd "/Users/zacthorman/Vaults/Cowork Base/03 Code Projects/Football stats"
.venv/bin/python -B nba_stats.py fetch --season 2025-26 --max 40   # first: does it answer?
.venv/bin/python -B nba_stats.py status --season 2025-26
.venv/bin/python -B nba_stats.py fetch --season 2025-26           # 300 requests a run; repeat until "up to date"
.venv/bin/python -B nba_stats.py withwithout "Mitchell Robinson" --teammate "Karl-Anthony Towns"
.venv/bin/python -B nba_stats.py smallball --season 2025-26 --who backup-bigs
```

- `--season 2026-27` for this season so far; `--playoffs` for the play-offs (cached separately).
- A whole regular season is about 1,230 box scores and 165 line-up days, roughly 1,400 requests, so about five runs at the default cap of 300. At 1.5 to 3 seconds a request, each run takes 10 to 15 minutes.
- If the first run prints `STOPPED`, read the reason. A 403 or a timeout on the very first request means NBA.com is refusing this machine or the headers; wait a few hours rather than trying again straight away. A `KeyError` about a result set means the response shape differs from the one assumed; save the raw answer from `cache/nba_stats/` and fix the parser.
- Things to check by eye on the first real run: `status` shows box scores and line-up days rising; `cache/nba_stats/box_<id>.json` has players under `boxScoreTraditional`; a `lineups_*.json` day has rows for every team that played, about 48 minutes in total a team.

## Being polite, and never fatal

- Every request carries the headers NBA.com's own site sends (a browser User-Agent, `Referer: https://www.nba.com/`, `Origin: https://www.nba.com`, JSON Accept) and a 10 second connect, 30 second read timeout.
- At least 1.5 seconds plus up to 1.5 seconds of jitter between real requests. Cache hits never wait.
- A cap per run (`--max`, default 300).
- **Any answer but a clean JSON 200 stops the run at once**: a 403, 429, 5xx, timeout, dropped connection or non-JSON body. No retries, because retrying is how a slow-down turns into a ban. The exit code is 2, and everything fetched before the stop is kept.
- Nothing in `update.py` or `publish.sh` calls it, so it cannot stop the daily build. It writes only under `cache/nba_stats/` (gitignored).

## Where the data comes from

| Endpoint | Requests | What it gives | Cached |
|---|---|---|---|
| `leaguegamelog`, `PlayerOrTeam=T` | 1 | every finished game, both teams | 6 hours |
| `leaguegamelog`, `PlayerOrTeam=P` | 1 | every player who got on the floor, with minutes, points, rebounds, assists | 6 hours |
| `playerindex` | 1 | listed position (C, C-F, F-C, F, G...) and height | 7 days |
| `boxscoretraditionalv3` | 1 a game | who started (a starter has a position slot, the bench has none), DNP comments | for good |
| `leaguedashlineups`, `GroupQuantity=5`, one day | 1 a game day | each five-man group's minutes that day | for good, once the day is over |

A team plays at most once a day, so a one-day line-up table is that team's line-ups in that one game. That is why the line-ups are fetched by day, not by team over the season. A box score with no players (a game not yet filled in) is not cached, and a line-up day is only fetched once it is at least a day old, so nothing half-finished is ever cached as final.

## The two analyses

**`withwithout PLAYER --teammate NAME`.** His games for every team the team-mate also played for this season, split by whether the team-mate got on the floor that game. A team-mate on the roster who did not play (injured, rested, DNP) counts as without, which is the point. Prints minutes, points, rebounds and assists with and without, and without minus with, with a 90% bootstrap range resampling each side's games.
- A team-mate who arrived mid-season counts the games before he arrived as without. `--since-joined` starts the split at his first game for the team.
- A team-mate who left mid-season counts the games after as without. There is no flag for that yet.
- Names match with accents and punctuation ignored (`jokic` finds Jokić); an ambiguous name lists the matches.

**`smallball [--who backup-bigs|bigs|all] [--cut X] [--min-games N]`.**
- **Big** is NBA.com's listed position C, C-F or F-C. A line-up player missing from the index counts as not big.
- For every team-game, the **small-ball share** is the share of its line-up minutes with one big or fewer on the floor.
- An opponent is **small** in that game when its share is above the cut, the league median of all team-games unless `--cut` is given, and **big** otherwise.
- **Backup bigs** are listed bigs who started under half of their box-scored games. `--who bigs` takes every listed big, `--who all` everyone. Each needs `--min-games` (default 5) on each side and 8 minutes a game on average.
- **Within player.** For each player, small-opponent games minus big-opponent games for minutes, points and rebounds, each with a 90% range resampling his games. So a player who simply plays more against bad teams does not drive the answer.
- **Pooled.** The mean of the players' differences with a 90% range resampling players, and the same for points and rebounds per 36 minutes, which says whether a change is minutes or rate.

## Limits

- **Untested live,** as above.
- **The opponent's whole game, not his minutes.** The share counts the opponent's line-ups across the whole game, not only while the player was on the floor. Matching the two needs stints (who was on when), which `gamerotation` (in and out times per player) or `playbyplayv3` (substitutions) could give. That is the natural next step if the game-level split shows something.
- **Small ball is partly a response.** A team that goes small against a small opponent pushes its own bigs' minutes down for a reason that is not the opponent. Within-player comparison does not remove that.
- **Garbage time** line-ups count the same as the rest.
- **Listed positions are one label a season.** A player listed F who plays centre for one team is still not big here; `--who all` shows everyone so such cases can be seen.

## Parameters worth checking on the first live run

These follow the parameter names `nba_api` uses, but they have not been seen working from here:
- `leaguegamelog` with `Counter=0`, `Direction=ASC`, `Sorter=DATE`, and empty `DateFrom`/`DateTo`.
- `boxscoretraditionalv3` with lower-case `startPeriod`, `endPeriod`, `startRange`, `endRange`, `rangeType` all 0. v2 is parsed too, but NBA.com stopped filling v2 for new games, so v3 is what is asked for.
- `leaguedashlineups` with `DateFrom` and `DateTo` as `MM/DD/YYYY`, `TeamID=0` for every team at once, `PerMode=Totals`. Whether a one-day league-wide table returns every team's line-ups, with no row limit, is the main thing to check.
- `playerindex` with `Historical=1`, so a player waived mid-season still has a position.
