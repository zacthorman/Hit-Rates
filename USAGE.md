# Football fixture hit rates

Pick a fixture, get both teams' hit rates for every stat SofaScore tracks, split by home and away form, with a chart of the game-by-game sequence.

Output is a self-contained HTML file.

## Setup

Already done if you followed along, but from scratch:

```bash
cd "/Users/zacthorman/Vaults/Cowork Base/03 Code Projects/Football stats"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Running the tests

The suite needs a few more packages than the pipeline (pytest, numpy, scipy,
statsmodels, scikit-learn, lightgbm, and zstandard for unpacking
`cache_backtest.tar.zst`).
They are in `requirements-dev.txt`, which includes `requirements.txt`:

```bash
pip install -r requirements-dev.txt
.venv/bin/python -B -m pytest tests
.venv/bin/python -B tests/run_all.py     # the same without pytest
```

Without them, `tests/test_teamlines.py`, `tests/test_us_audit.py` and
`tests/test_teammodel_weekly.py` skip most of their tests instead of failing,
so a short skip list is the sign that everything is installed. With everything
in place, only the tests that need built reports in `reports/` or
`GAMESTATE_LIVE=1` skip (four on 23 October).

A test run never changes a tracked file. Under pytest, `tests/conftest.py`
points `learner.py`'s output at a temporary file through
`HITRATES_LEARNED_JSON`, and fails the run if the real `learned.json` changed.
The live pipeline never sets that variable, so it keeps writing `learned.json`
as before. `tests/test_tracked_files.py` runs every other test file again
without that redirect, and fails if `learned.json` or any other tracked file
differs afterwards. It doubles the run time. Set `HITRATES_SKIP_TRACKED=1` to
leave it out of a quick run.

## Use

```bash
# See it work with fake data, no network needed
python run.py --demo

# Find a team's id
python run.py --search espanyol

# List that team's next fixtures
python run.py --team 2814

# Build the report for fixture 0 in that list
python run.py --team 2814 --pick 0

# Three of that team's upcoming fixtures, one report
python run.py --team 2814 --pick 0,1,2

# Several teams, each one's next fixture, one report
python run.py --teams 2814,2833,2817 --players

# A whole division's next round
python run.py --league premier_league --players --h2h --adjust

# Every major league, one report each, all listed on the site
python run.py --leagues premier_league,championship,la_liga,serie_a,bundesliga,ligue_1 --adjust
python make_index.py
```

`--leagues` writes one report per division rather than a single enormous file, so the index reads as a list of rounds and no page has to carry a hundred fixtures. Files are named after the competition, so each league keeps its own and re-running replaces only that one.

**Darts.** No league table, so `--league` cannot find the players. `--darts` asks a seed list of PDC players (`DARTS_SEEDS` in run.py) for their next matches and builds every one in the window into one report, `reports/darts.html`, which the index lists under its own Darts tab.

```bash
./darts.sh        # next 3 days, waits for the nightly job, then indexes
./darts.sh 7      # next 7 days
python run.py --darts 3 --games 20 --h2h    # the same thing by hand
```

`darts.sh` routes every request through FlareSolverr (`SOFA_FLARESOLVERR=1`, the same as the nightly job) and refuses to start if the container is not answering on port 8191, so start Docker Desktop first.

Markets are 180s, 3-dart average, highest checkout and 100+ checkouts (`DARTS_STATS` in markets.py). Form is drawn from every competition a player has played in, because one darts event is at most a few matches a year. Modus, WDF, Challenge and Development Tour and the Women's Series are skipped by name (`DARTS_SKIP` in run.py, override with `--darts-skip`). One caveat the numbers do not show: a best-of-11-legs floor match and a sets-format major produce very different 180 counts, and the last 20 mixes both.

`--league` reads the team list off the league table, so you don't have to know twenty ids, then collapses each team's next fixture into a round. Known names: `premier_league`, `championship`, `la_liga`, `serie_a`, `bundesliga`, `ligue_1`, `champions_league`, `europa_league`. Any other competition works by passing its uniqueTournament id.

A report can hold as many fixtures as you like, with a dropdown at the top to switch between them. All the filters and edited lines are per fixture.

## What it costs in requests

Roughly, per fixture:

| | Requests | Time |
|---|---|---|
| Team stats only | about 25 | 40 seconds |
| With `--h2h` | about 35 | 55 seconds |
| With `--players` | about 45 | 75 seconds |

So five fixtures with players is around 220 requests and six minutes, which is comfortably within what SofaScore will tolerate at a 1 to 2 second delay. Two things make it cheaper than that arithmetic suggests:

- **Teams in the same league share matches.** Building every fixture in a LaLiga round means each match's statistics is fetched once and reused by both teams involved, so the marginal cost per extra fixture drops as you add more.
- **Nothing is fetched twice, ever.** Re-running is instant, and adding `--players` to a fixture you already built only fetches the lineups.

Running a full weekend's card the night before is entirely reasonable. Running it repeatedly in a tight loop is not, and would get your IP blocked.

**Only bettable markets by default.** SofaScore returns plenty that has no market attached to it (goals prevented, expected assists, duels won), and every extra row is another combination for the Standout scan to trawl and another chance for a coincidence to look like a finding. Team stats are filtered to shots, shots on target, shots off target, blocked shots, shots inside and outside the box, corners, offsides, throw-ins, fouls, cards, goal kicks, free kicks, tackles and big chances. Player props are filtered to shots, shots on target, goals, assists, tackles, fouls, fouled, offsides, clearances, interceptions, passes, crosses and saves, plus minutes, which is not a market but decides whether the rest matter. `--all-stats` turns the filter off.

**Fouls won come free.** Fouls conceded is the "For" measure and fouls won is the "Against" measure of the same stat, so the Measure control already gives you both without a separate row.

Useful flags: `--players` to include per-player stats, `--games 20` for a deeper sample, `--show 10` to list more fixtures, `--no-open` to skip launching the browser.

## In the report

**Team stats tab.** One row per stat. Every line is editable: type a number, or use the plus and minus buttons, and both teams' hit rates recompute instantly. The buttons move by a whole unit and keep the .5, so 13.5 goes to 14.5, never 14. That matters because a line ending in .5 can never be exactly matched, so there is no ambiguity about whether a match hit it. An edited line is shown in bold so you can see which are yours and which came from the data. "Reset lines" puts them all back.

**Players tab.** Present when you ran with `--players`. Pick a stat, set a line, set a minimum number of appearances, and both squads are ranked by hit rate. It respects the same last 5 / last 10 and home / away filters as the team tab, so "last 5 at home" means the same thing in both.

**Standout lines tab.** Scans every combination of fixture, team, stat, period and venue split, and ranks what comes out. Two things make it honest rather than a fruit machine:

- It ranks by the lower bound of a 95% confidence interval, not by raw percentage. That matters because 5/5 is 100% and 18/20 is 90%, yet the second is far stronger evidence. Ranking by percentage puts the flukes on top; this puts them where they belong.
- It tells you how many combinations it scanned, and roughly how many would look that consistent from chance alone. Scan 1,400 combinations at ten matches each and about 15 will reach 9/10 by luck. Without that number, a list of "strong" lines is indistinguishable from a list of coincidences.

**Fair and Need.** Each row turns its hit rate into a price two ways. **Fair** is what the hit rate implies on its own (1 divided by the rate). **Need** comes from the bottom of the confidence interval and is the one to bet off. The gap between them is the point: 8/10 reads as a fair 1.25, but ten matches cannot tell 80% from 55%, so the evidence only really justifies 2.04 or better. Type a bookmaker's price into "Your price" and the row says whether it clears, using the conservative figure. Getting a yes should be hard.

Neither number includes the bookmaker's margin. A real market is priced so the implied probabilities sum above 100%, typically 105 to 108% on these, so the available price is worse than fair by design.

Treat it as a shortlist to price up. A hit rate is not an edge: what makes a bet worth taking is the price being wrong, and there is no odds feed here to tell you that. The suggested lines are also derived from the same matches being measured, which flatters every number in the table.

**Measure.** For, Against, or Matchup.

- **For** is each team's own numbers, the default.
- **Against** is what opponents managed against them, so "corners conceded" rather than "corners won".
- **Matchup** is the one worth reaching for: the home side's own numbers on the left against the away side's conceded numbers on the right. That answers whether an attack actually meets a leak, rather than comparing two attacks that never face each other.

None of this costs extra requests. The statistics endpoint always sends both teams' figures for every match; the earlier version simply discarded the opponent's half.

**Played fixtures drop off by themselves.** The report is a static snapshot, but the browser knows the time, so a multi-fixture report hides games once they have kicked off and the button next to the dropdown brings them back. If every fixture has been played it shows them all rather than an empty page, and the index marks that report as history.

**Opponent adjustment (`--adjust`).** Fits attack and defence ratings for every club in the competition, then projects what each team should actually do *in this fixture against this opponent*. Shown as "proj 11.0 v 8.4" under each line, and turned red when the projection lands on the other side of the line from the record. That red flag is the case you care about: a true 100% that the model expects to fail.

The model is the standard multiplicative one. A team's attack rating is its own average divided by the league average, its defence rating is what it concedes divided by the same, and the expected value is `league average x attack x opponent defence`, with separate home and away baselines. It is fitted iteratively rather than in one pass, because a single pass inherits the schedule: a strong side never plays itself, so its opponents are weaker than average and its rating comes out flattered. On a synthetic league with known multipliers, one pass overstated a projection by 17% and the iterative fit recovers the truth.

Three honest limits:

- **It needs the division.** Ratings are fitted from every club's recent form, so the first `--adjust` run on a competition fetches all twenty clubs. Slow once, then cached, and a `--league` round reuses matches it was fetching anyway.
- **A promoted side comes out as exactly average.** Their sample is from another division, so there are no matches against this division's teams to fit against, and they default to a 1.0 rating. That is a guess, not a measurement, and the different-opposition warning still fires.
- **Ten matches is a thin fit.** The ratings are directionally useful and not precise. They know nothing about injuries, rotation, or a manager changing shape.

**Different opposition warning.** If a team's sample was built mostly in another competition, the team tab says so and the Standout scan leaves them out until you ask for them. This is the trap the tool is least able to solve on its own: a promoted side putting up 12 shots a game against Championship defences has a perfectly true 100% record over 2.5 shots, and it tells you almost nothing about how they'll do away at Arsenal. The hit rate carries no memory of who it was set against.

Note what this does and does not do. It flags a mismatch; it does not adjust for one. Adjusting properly means weighting every match by the opponent's strength, which is a model rather than a filter.

**Sample.** Recent form, or head to head. Head to head is the same layout over previous meetings between these two teams instead of their recent matches, with its own suggested lines, since two teams meeting each other produce different numbers from their form against everyone else. Needs `--h2h` when building.

**Team.** Both, or one side on its own. Picking a single team drops the head-to-head split and gives that team the full width, which is the easier read when you only care about one of them. The projection, the strong-row shading and the charts all follow the selection.

**Layout.** Each stat is one row with the two teams facing each other around the stat name, so the comparison is a single glance. On a phone the same row stacks into a card. **Main** shows the seven stats worth most attention; **All** shows everything the endpoint returned. **Strongest first** sorts by distance from an even split, and **Strong only** keeps just the rows where a team is at 80% or above, or 20% or below. Those rows are also shaded.

**The dots** are colour-coded against the line: a filled green dot is over, a hollow red one is under. Colour is not carrying that alone, since position relative to the dashed line and the fill state say the same thing, which keeps it readable in greyscale and for red-green colour blindness.

**Period.** Full match, first half or second half. Each period keeps its own lines, because a first-half shots line has nothing to do with a full-match one, and its own hit rates and charts. The halves come straight from SofaScore rather than being derived, since summing the halves does not reliably reproduce the full-match figure.

Player stats are full match only, since SofaScore doesn't publish per-player numbers by half. Players who have left the club are excluded automatically: the squad is read fresh, so a striker sold in July no longer shows up with last season's shot record. New signings appear once they have minutes, and the terminal reports how many squad members have none yet.

Hovering any point on a chart gives you the date, opponent and value.

It works team-first rather than date-first because SofaScore removed their date-based fixture endpoint. `check.py` is the script that established that, and it's worth keeping: if something else breaks later, add the suspect path to its list and run it.

The report lands in `reports/` and opens automatically. Inside it you can switch between last 5, last 10 and all, and between all matches, home only and away only. Hover any point on a chart for the date, opponent and value.

## Best bets

A tab that scans the whole round for fixtures where **both halves point the
same way**: the team's own record at this venue, and what their opponent
concedes at theirs. Forest have gone over 1.5 first-half corners in 10 of
their last 10 at home, and Leeds have conceded over 1.5 in 9 of their last 10
away. Two separate records agreeing is stronger than one record twice as long,
because they can fail independently.

Rules the scan follows, and why:

- **Venue is enforced on both sides.** Home record against away record, never
  the pooled one. That is the actual fixture.
- **Both halves must clear 65% on their own** before the pairing is scored, so
  a 10/10 cannot drag a 3/10 into the list.
- **The two records are pooled into one interval.** 20 observations at 85%
  supports a much shorter price than 10 at 85%, and the interval says so.
- **The line ladder is one-sided.** An over is only tried at the median line
  and above, an under at the median and below. Without this the list fills up
  with things like "Newcastle over 0.5 yellow cards, 20 from 20", which is
  true, useless, and priced at about 1.05.
- **Ties break towards the harder line.** The score depends only on how many
  went the right way, so over 0.5 and over 2.5 both score identically at
  10/10. The more demanding line wins.
- **Grouped by competition**, three per division by default.

Every card shows both sequences in full, the pooled record, the fair price,
the price the evidence actually supports, how often a scan this size throws up
something this good by chance, and whether the opponent-adjusted projection
agrees. The projection is the only figure on the card that did not come from
the same matches as the record.

None of this knows what the bookmaker is offering, and the price is the entire
bet. Treat it as a shortlist to price up.

## Goals

Goals are not in SofaScore's statistics feed at all, they live on the
scoreline, so they are bolted into the stat blocks from there. That makes
`Goals` behave like every other stat: it has a line, a hit rate, a for and
against split, and it feeds the matchup scan. Full match only, because the
half-time score is a separate call.

## The front page

`make_index.py` lists **fixtures**, not report files. A league round is one
file holding ten matches, and `premier-league-10-fixtures.html` tells you
nothing about whether Arsenal are playing tonight. So every report's payload
is read, each fixture pulled out with its kick-off time, and the lot sorted by
when they actually start and grouped under Today, Tomorrow and then by day.
Competition chips filter, and there is a search box for a club name.

Each fixture links straight to itself inside its report using the event id in
the URL hash, so `reports/premier-league.html#e16363633` opens on that match
rather than on whichever one happened to be first.

Kick-off times render in the reader's own timezone. The page ships unix
timestamps and lets the device do it, because a 20:00 UTC kick-off is 21:00 in
most of Europe and being an hour out is the sort of thing that loses a bet.

## Reviewing itself after the games (`review.py`)

    python review.py reports/laliga-11-fixtures.html
    python review.py reports/*.html --history
    python review.py --history

For every fixture in a report that has now been played, this takes the bets the
Best bets tab would have shown, settles them against what actually happened,
and says why each one landed or missed. Then it appends everything to
`review_history.json`, so the picture builds week after week.

The per-bet verdict separates a good call from a lucky one:

```
Rayo Vallecano v Deportivo Alaves   10/10 landed
  OK   Alaves over 6.5 goal kicks
       said 90%  got 11   projection was right (10.3 expected, 11 actual)
  OK   Rayo over 1.5 corner kicks 1st
       said 71%  got 2    landed by 0.5, tighter than the price implied
```

Both won. Only the first was actually predicted.

### Why it does not retune itself

The obvious next step is to let it adjust the model automatically. That would
be a mistake.

A gameweek gives maybe twenty settled bets. Fitting anything to twenty
observations produces a model that explains last Saturday beautifully and knows
nothing about next Saturday. Do it every week and the model chases noise in a
circle, each week undoing the last. The failure mode is the worst kind: the
numbers keep looking better while the predictions get worse.

So it reports evidence and stops. Three rules:

1. **Nothing below 40 settled bets for a stat.** Under that a lean cannot be
   told from a run of luck. The output says `only 8, need 40` and moves on.
2. **Every figure carries an interval.** If it spans the claim, there is
   nothing there.
3. **Any suggested correction is fitted on the older half of the history and
   scored on the newer half.** If it does not survive out of sample it is
   reported as noise and explicitly not applied.

Only global corrections are ever considered: a per-stat calibration shift, or
the dispersion prior. Never a per-team or per-player adjustment, because there
is never enough data for one and it is the fastest route to a model fitted to
individual results.

Most weeks the honest answer is "nothing to change", and the script says so
rather than inventing work.

## Checked against real bookmaker prices (`market_check.py`)

    python market_check.py reports/premier-league-10-fixtures.html

Forty-eight bet365 player prices are saved in `market_prices.json`. This
reprices every one of them using the current model and reports how far off the
market it is, broken down by stat.

Every other test here checks the model against itself. `verify.py` checks the
two implementations agree; `backtest.py` checks the predictions are calibrated
against outcomes. Neither can catch the model being confidently wrong in a way
a bookmaker would spot instantly.

**It caught a real bug on its first run.** Shots on target and tackles were
both about 20% too confident. The cause: SofaScore leaves a stat out entirely
when a player records none of it. Adrien Truffert's shots on target came back
as `1, -, 1, 1, -, 2, -, -` across eight matches, and reading the gaps as
unknown rather than as zero gave 1.25 a game when the truth is 0.62. Every
shots-on-target and tackles price in the tool was built on roughly double the
real rate. Shots escaped it because zeros are recorded there, which is exactly
why eyeballing shots had suggested everything was fine.

| stat | before | after |
|------|--------|-------|
| Shots | -6.1% | -6.1% |
| Shots on target | +21.7% | +3.2% |
| Tackles | +16.0% | -4.7% |

The fix is applied both at fetch time and at render time, so reports built
before it was found are corrected by `rerender.py` without refetching.

The bookmaker's margin is a guess and the answer moves with it, so the guess
is not allowed to decide the verdict. Each stat is scored at 5%, 7% and 9%
overround, and only a lean that survives all three counts as a bias. A
difference that appears at 5% and vanishes at 9% is a statement about the
assumption, not about the model.

Run it after any change to the pricing. It exits non-zero on a real bias.

## Does it actually work? (`backtest.py`)

The one question nothing inside the model can answer: when it says 85%, do
those bets land 85% of the time? If they land 70%, every price on the site is
too short and the tool has been quietly lying to you.

    python backtest.py --league "Premier League" --games 10
    python backtest.py --leagues "Premier League,Championship" --csv bets.csv

It replays past fixtures, rebuilds what the tool would have said the day
before each one, settles every bet the Best bets scan would have produced, and
buckets the predictions against the outcomes. It runs entirely from the cache
and makes no requests, so it cannot get your IP blocked. Missing lookups are
counted rather than fetched.

**The bit that decides whether any of it means anything.** Every fixture is
built with an as-of cutoff at its own kick-off, so the model can only see
matches played earlier. Without that it reads the result of the match it is
predicting. Measured on a synthetic league:

| | bets | said | landed |
|---|---|---|---|
| with the cutoff | 511 | 81.4% | 85.1% |
| without it | 825 | 79.6% | 90.1% |

Ten points of pure fiction, and 60% more bets that only qualified because the
future was visible. That is lookahead bias, and it is the standard way a
backtest flatters itself into looking like a business.

The backtest also answers a question worth asking honestly: does the opponent
adjustment beat just using the raw hit rate? Both are scored side by side on
the same bets with a Brier score. On the synthetic league the count model came
out ahead, 0.1242 against 0.1274, and was near perfectly calibrated between
82% and 97% where the raw hit rate was seven points overconfident. On real
football it may not win, and that is worth knowing.

## The model lives in two places

`model.py` is the Python implementation, used by the backtest. The JavaScript
inside `report.py` is the same maths again, because the page reprices bets in
the browser when you drag a line. Two copies of one calculation will drift.

    python verify.py

pulls the functions straight out of `report.py`, runs them in node over 224
combinations of mean, line and sample spread, runs `model.py` over the same
grid, and fails if they disagree by more than 1e-9. Run it after touching
either one. Both were also checked against scipy.

## Player lines: minutes, and the worst bug in the tool

Saka over 1.5 shots was priced at `need 3.00`. bet365 were offering 1.22. Two
separate faults, both mine.

**Minutes were ignored.** His last eight records included a match he did not
play in at all, one where he came on for nine minutes, and one where he was
off at half time. The nil from the game he missed was counted as a losing bet.
A bookmaker voids that: it is not a loss, it is not an event. Counting it
dragged his record to 5/8 and his expectation to 1.9 shots.

Now any match under 45 minutes is dropped, the rest are converted to a rate
per 90, and that rate is multiplied by the minutes he is likely to play. Which
is how the market prices it, and the only way a 45-minute cameo and a full 90
can sit in the same average.

**The distribution was wrong in one direction.** The model switched to a
negative binomial when counts were more spread out than Poisson, but had
nothing for the other case. A regular starter's shots are *less* spread out
than Poisson: he takes two or three most weeks and almost never none. Poisson
with a mean of 2.6 assumes a 7% chance of zero shots, which for a starting
winger does not happen, and that misplaced weight below the line made every
player price too long.

There is now a binomial branch for the underdispersed case. And because the
dispersion estimate is itself noisy on six matches, it is shrunk towards
Poisson by `n / (n + 8)`.

The result, on the same six appearances:

| | fair |
|---|---|
| before | 1.75 |
| minutes fixed, Poisson | 1.37 |
| plus the binomial branch | **1.28** |
| bet365, margin removed | ~1.29 |

Worth reading the conclusion carefully. Fair is 1.28 and bet365 offer 1.22, so
that bet is **not** worth taking: the price is shorter than the odds justify.
The tool is not being timid, it is telling you the bookmaker has the edge on
that one.

Adding the binomial branch also caught a divergence between the Python and the
JavaScript, via `verify.py`: Python's `round(4.5)` is 4 and JavaScript's
`Math.round(4.5)` is 5, so the two implementations picked different numbers of
trials and quoted different prices. Exactly the drift that script exists for.

## Player lines and the strength of the opponent

A second round of the same bug. Coventry's Brandon Thomas-Asante was priced at
1.52 for over 1.5 shots when the market was 3.00, which looks like enormous
value and is not: Coventry are away at Arsenal and will barely get a shot off.

The player adjustment was clipped to between 0.7 and 1.35, on the reasoning
that an adjustment should nudge a line rather than move it a long way. That
reasoning was simply wrong. Coventry average 15.8 shots in the Championship
and are expected to manage **4.83** at the Emirates. The true adjustment is
**0.31**, and clipping it to 0.7 priced their forwards at more than double the
shots they will get. A mismatch really is a big move; that is what a mismatch
is. The bounds are now wide enough to be only a divide-by-zero guard.

That exposed a second fault underneath, and then a third.

The haircut behind `need` was an absolute standard error measured on the
player's own sample and subtracted from an adjusted expectation a third the
size. Taking 0.6 off an expectation of 0.9 leaves almost nothing, and the bet
priced at 20.0.

Fixing that proportionally was still wrong, because the whole mechanism was
wrong. It stacked two uncertainties on top of each other: the match itself is
random, which the count distribution already knows about, and then the mean
was cut again for being an estimate. On Havertz's five-match sample the cut
hit its 50% cap, halving his expectation, so a bet with a fair price of 1.43
came out needing 2.84. Nobody would ever take that.

`need` now widens the distribution instead of moving its centre, by the law of
total variance:

    var(total) = expected x dispersion  +  standard error squared

Which is the correct way to be cautious about a small sample. It converges on
the plain price as the sample grows, which is what should happen, and it stays
honest when the sample is genuinely thin. Havertz goes from 2.84 to 1.50, and
a three-match sample still shows a visible gap between fair and need.

One subtlety: extra variance usually hurts a bet, but when the expectation
sits below the line it helps, because a wider spread makes an unlikely total
more reachable. `need` takes whichever of the two views is worse, so it is
always a floor on the price you should accept.

Both fixes apply to team bets too, since they share the model.

The direction is now right: Arsenal's players price short, Coventry's price
long. The remaining gap is at team level rather than player level. The tier
estimate says Coventry manage 4.83 shots at Arsenal; the market implies nearer
7. If that team number is harsh then every Coventry player price is harsh in
proportion, and the fix is more matches behind the tier estimate rather than
anything in the player maths.

## Club colours

Each fixture is drawn in the two clubs' own colours rather than a fixed blue
and orange, so Newcastle against Liverpool looks different from Man City
against Bournemouth.

Kit colours cannot be used raw. Three things go wrong:

- **Contrast.** Newcastle's black vanishes on a dark background, Norwich's
  yellow on a light one, Wolves' gold on both.
- **Clash.** Manchester United against Liverpool is red against red. Arsenal
  against Forest, the same. You cannot tell whose line is whose.
- **Grey.** A monochrome club reads as an axis rather than as data.

So `clubcolour.py` treats the kit colour as a starting hue, not a final value.
Working in OKLab, it moves each colour into a legible lightness band for the
mode, floors its chroma so it does not read as grey, and then measures the
pair's separation under normal vision and under both red-green colour
blindnesses. If the two clubs are still too close, the away side is rotated
away in hue until they separate, so at least one team keeps its real colour.
Clubs with no usable hue get a slot from the validated palette.

The thresholds are not invented: they are the ones `dataviz`'s palette
validator enforces, and the output is checked against it. All 420 pairs from a
fifteen-club test set, across both light and dark, pass every check.

That test caught a real mistake. The first monochrome fallback was a slate
blue I picked because it looked right, and the validator failed it on the
chroma floor in both modes and on the lightness band in dark. Which is the
whole argument for running the validator instead of trusting your eye.

Colours are worked out at build time and shipped per fixture, then applied when
the fixture changes and again on a theme change, since the light and dark
values are separately chosen rather than one flipped. Reports built before this
existed keep the old defaults.

## How the Need price is worked out

`Fair` is what the record implies on its own. `Need` is the price to insist on
before staking. The first version of it was too blunt: it looked only at how
many matches went over the line and how many did not, so every 19 from 20 came
out at 1.31 regardless of the fixture. That throws away almost everything. A
team getting 4, 5, 3, 6, 4 corners and one getting 2, 2, 2, 2, 2 are both
"5 from 5 over 1.5", and one is far safer. It also never looked at the opponent.

`Need` now comes from a count model:

1. Take the opponent-adjusted expectation for this team in this fixture. That
   is the projection already on the page: league average times this team's
   attack rating times this opponent's defence rating, off the right home or
   away base. This is where the mismatch enters.
2. Fit the spread from the team's own matches. If the variance is close to the
   mean, counts behave like a Poisson process and Poisson is used. If the
   variance is larger, which is normal for shots, a negative binomial carries
   the extra spread across rather than quoting a price that is too short.
3. Read the probability off that distribution. A line of 1.5 asks for P(X >= 2).
4. Haircut for the fact the expectation is itself an estimate, by recomputing
   at the bottom of a one-sided 95% interval on the mean.

Both distributions were checked against scipy across 54 combinations of mean
and line, agreeing to machine precision.

The same record now prices very differently depending on who is playing:

| Bet, all on the same shape of 10-match record | Expected | Need |
|-----------------------------------------------|----------|------|
| Man City total shots over 9.5 v Bournemouth   | 17.2     | 1.05 |
| Arsenal first-half corners over 1.5 v Coventry| 3.4      | 1.26 |
| Arsenal first-half corners over 1.5 v Man City| 2.1      | 2.03 |
| Bournemouth total shots over 9.5 v Man City   | 9.8      | 2.59 |

Two guards sit on top of it.

The interval on the expectation is clipped to half and double the point
estimate. Ten matches of a noisy stat can produce a standard error big enough
to drag the lower bound to nothing, and a bound of nothing prices everything
at 20.0, which is not caution, it is noise wearing caution's clothes.

A pairing is dropped entirely when the model and the record contradict each
other beyond what either one's uncertainty allows, or when the projection is
less than half or more than double the team's own average. An adjustment
should move a team's average, that is its job, but it should not halve it. The
case that exposed this was an expected 0.46 second-half offsides for a side
that had gone over 0.5 in thirteen of twenty, which priced at 21.0. The number
dropped is shown on the page.

Where there is no opponent-adjusted expectation, which means one side could
not be rated, it falls back to the old record-only interval and tags the price
`record only`, because an invented expectation is worse than an honest blunt
number.

The Best bets tab can be ordered three ways. **Evidence** puts the strongest
combined records first. **Most likely** sorts by the model's probability, which
favours mismatches. **Best price** sorts the other way, surfacing the ones that
actually pay, which are the ones worth pricing up against a bookmaker.

## Standard of opposition (`--tiers`)

The opponent-adjusted projection needs a rating for both sides, and a
promoted club has none: every match on its record was played in a division
nobody else in the fit belongs to. Coventry came up with exactly one usable
match, away at Hull, who were also promoted, so the two of them were fitted
in a closed loop off a single Championship game. That is how Coventry ended
up projected for more corners at the Emirates than Arsenal.

`--tiers` reads last season's final tables for the division and the one
below, stacks them, and sorts every club into four bands:

| Band   | Where they finished                       |
|--------|-------------------------------------------|
| Top 6  | 1st to 6th                                |
| Upper  | 7th to 11th                               |
| Lower  | 12th to 17th                              |
| Bottom | 18th and below, plus every promoted club  |

Two things then become possible.

**The Opposition control** filters any team's record to matches against one
band. Arsenal's corner record against bottom-tier sides is a different and
far more relevant number from their record against everyone.

**The estimate.** When one side cannot be rated, the projection is taken
from the other side's record against bottom-tier opposition instead. Arsenal
at home to bottom-tier clubs gives both figures at once: what Arsenal
manage becomes Arsenal's number, and what those clubs manage at the Emirates
becomes Coventry's. No Coventry data is used at all, which is the point,
because their data is the part that does not carry across divisions.

Estimates are shown as `est` rather than `proj`, underlined with a dotted
rule, and hovering one lists the exact matches it came from. If there are
fewer than three usable matches even then, nothing is shown.

It wants a full season rather than ten games, otherwise there are barely any
bottom-tier matches to average:

    python run.py --league "Premier League" --games 38 --adjust --tiers --players

Last season's table is used, not this one. In August the current table is
three games old and would put whoever won on the opening weekend in the top
six.

## Team strength in the picks (`strength.py`)

The picks of the week (best bet, evens double, banker, acca) and the per-fixture singles on `tonight.html` now know how good each side is, not just what its record says.

```bash
python strength.py                  # build the ratings, print the top 40, write strength.json
python strength.py --team Arsenal   # one club
python strength.py --slopes         # refit strength_slopes.json from the built reports
python strength.py --tune           # grid-search the Elo settings on log loss
```

**The rating.** One Elo number per club, built in a single pass over every finished match in the cache (about 18,000), each one rated only on results before it, so the backtest can use it without reading the future. Settings tuned on log loss: home advantage 60, K 20 for league and cup, 30 for European ties, 5 for friendlies. Two fixes over plain Elo:

- **League offsets.** A league's own offset moves only on matches between leagues, so a league's European results reprice every club in it. Without this, Sabah rated above Liverpool by winning the Azerbaijani league every week. Log loss on cross-league matches went from 0.567 to 0.551.
- **Promotion keeps strength.** A promoted club's rating is re-based onto its new league's scale, so it does not inherit the whole Premier League offset overnight.

It is the only cross-league measure in the project, which is the point: the league projection needs shared opponents, so on a Champions League night it had nothing and every pick fell back to the raw record.

**What a team leg now carries.** Both sides' Elo as of kick-off, the chance of winning, the record against similar-strength opposition (matches weighted by how close the rating gap was to tonight's), and a strength expectation: the side's average moved by that stat's slope for the difference between tonight's gap and its usual one (shots about +11% per 100 Elo, corners +13%, yellow cards -5%). Slopes extrapolate; weighting alone could not. LASK had never been 230 points worse than anyone, so the first version took the single nearest match, a 40-shot night against Celtic, and expected 33 shots at Liverpool. The slope says 13.

**One calibrated chance.** These are blended by a logistic fit (`STACK_WITH_PROJECTION` in strength.py; Elo carries it alone where there is no projection) and the leg's `fair` becomes one over that chance. The record-only price is kept as `fairRecord`. Player legs have no strength yet; their record is shrunk towards a coin flip by phantom games fitted on how the site's own settled player picks landed (`best_bets.json`, refitted every run, 14 phantoms on 120 legs as of 13 October, against 2 before).

Picks then rank on that chance in football. Every other sport ranks exactly as before, because none of this was tested on them.

**What the backtest says, honestly.** `calib/strength_eval/` replays 1,010 fixtures across five leagues since August 2025 (48,549 headline-eligible legs), every input as of kick-off, fitted with one league held out at a time.

| | Log loss (lower is better) |
|---|---|
| Record, as the site priced it | 0.6756 |
| League projection | 0.6645 |
| Strength blend, held out | 0.6501 (Premier League) to 0.6640 (Championship) |
| Champions League, never fitted on: record / strength | 0.6818 / 0.6654 |

Its stated chances land within a point or two of what happened from 20% to 80%. The live ranking claimed 81% for picks that landed 71%.

What it does not do is pick more winners. The top three per matchday land about as often as the old ranking's (bankers 72.7% against 70.6%, best singles 45.5% against 50.8%, both inside the noise). The gain is that the numbers are true and the Champions League gets real picks. The top of the board still runs about 8 points ahead of what lands, because choosing the best of thousands of honest estimates picks the lucky ones; treat the top pick's chance as a ceiling.

Known gaps: La Liga crashed the replay in `hitrates.league_ratings` (a divide by zero), so it is not in the fit. Fixed 22 October: on a thin early-season fit a rating collapses towards zero, and once it is small enough, `base * rating` rounds to 0.0 while the rating still tests above zero, so the guard now checks the product. The cached Premier League fit for 18 January 2026 (first-half red cards) failed the same way and is the test (`tests/test_league_ratings.py`); see PROOF-2026-10-22.md. La Liga still needs the replay rerun to join the fit. The slopes are fitted on this season's reports, a mild look-ahead for one number per stat. Builders and the parlay are unchanged.

## NFL Defences tab: lines in every matchup (15 October)

The Defences tab used to suggest a line only against the softest third of defences, so a game between two good defences showed nothing. It now assesses every featured player:

- **Lead man v them.** What the best player at the position got against this defence, against his own usual. A defence can rank tough on everyone and still concede to a genuinely good player (Bijan Robinson's 100 yards against a "tough" Ravens run defence). The lead man's line is scaled by this; a tough defence only makes the list when it is 0.95 or better.
- **Usage trend.** Targets, carries or attempts over the last 3 games against the last 10, folded in at the square root and capped at 15% either way.
- **New role.** A player whose targets or carries jumped to 1.6 times what they were (every game since at 1.3 times or more bar one, the latest included, three games or more) is judged on those games only and tagged. Built for Emanuel Wilson taking Seattle's carries with Charbonnet out.
- **Without.** Defenders on the injury report as out at positions that cover the line (corners and safeties for receivers, linebackers for backs and tight ends) are named on the pick. Not modelled: the ranking was built with them.

Heuristic thresholds, not backtested yet: treat these as a shortlist to price up. The previous version is `report.py.bak-defalltiers`.

## Betfair in the picks, and the Market check (16 October)

`./publish.sh` fetches Betfair Exchange prices first (`market_prices.py`, needs
`.betfair.env`), and they now feed the picks in four ways.

1. **Strength.** Every football team leg (shots, corners, fouls, everything)
   uses a strength gap moved towards the one Betfair's match odds imply: 80%
   market when the match odds are tight and £2,000+ matched, 60% when tight,
   40% otherwise. The market knows team news the ratings cannot.
2. **The chance.** Where Betfair prices the bet itself or implies it, the
   chance is a blend of ours and Betfair's. Covered: match goals (every line,
   via the alt goal lines), first-half goals, BTTS, corners (8.5, 10.5 and the
   band edges 9.5 and 12.5), cards, team goals (from Betfair's own team lines,
   or else a Poisson goal model fitted to its match odds and goal lines),
   player to score / 2+ / shots on target 1+ and 2+ / shown a card, NFL anytime
   TD. Weight: 85% for a top market (tight, £5k+), 70% tight and traded, 50%
   tight, 35% back-only lists, 30% thin. Before blending, the model's average
   lean against Betfair across the round, per kind of bet, is taken off
   ("anchoring"), so one bias does not show as a hundred edges.
3. **Value.** Value = chance x (back - 1) x (1 - 5% commission) - (1 - chance),
   at the back price on offer. Set `BETFAIR_COMMISSION=0.02` if yours is lower.
   The **Value on Betfair** card lists up to five legs at 3%+ value, one per
   match, not against their own last five. Any headline pick whose Betfair
   price is 5%+ worse than fair is dropped from the picks.
4. **Why.** Every pick carries `why` (why.py): the evidence for and against
   (record, last five, average v line, similar opposition, what strength and
   the projection expect, the market) and, behind a fold, how the chance was
   built step by step.

**Market check** (`exchange_eval.py`, market-check.html, linked on the front
page). Each publish logs every Betfair-priced bet with four chances (model,
model with its bias off, Betfair, blend) and the back price, first sighting
and last before kick-off. It reports closing line value from day one (did
the price move our way?), then as fixtures settle: log loss and Brier for
each chance by market, calibration, and the profit from backing every value
bet at the price offered. `exchange_eval.py fit` (run by publish) refits the
blend weight per market once 30 bets have settled, and the margin inside
back-only lists, into `exchange_weights.json`.

    python exchange_eval.py report     # the scorecard in the terminal

## Darts match markets (`darts_model.py`)

Each darts page has a **Match** tab: who wins, total legs, handicap, the likely scores, match 180s and most 180s, all from one leg-level Elo over every cached PDC result since 2018 (about 3,100 matches), worked out exactly for the format. It is attached at build time by `report.write_report`, so `darts.sh` and `python rerender.py darts` both refresh it with no requests.

    python darts_model.py              # top 30 ratings
    python darts_model.py --backtest   # replay every match as of its own date
    python darts_model.py --tune

Replayed over 1,723 matches: favourite won 61%, log loss 0.657 against 0.693 for a coin flip, calibrated within a point or two up to 80%. Total legs run about 3 points high on long matches. Match 180s: 5.24 predicted, 5.29 actual over 506 matches. Two things tried and dropped: recent 3-dart average (worse on every fit), and SofaScore's `firstToServe`, which on finished matches names the winner 98% of the time and so leaks the result. The front page's darts picks open with a Match prices card.

Where the Betfair Exchange prices a match, the winner chance is a blend leaning 75% on the market (log-odds scale), and every other darts market is recomputed from it. Model, exchange and the blend are shown side by side, and a gap over 12 points is flagged as a warning. `darts.sh` fetches prices first when `.betfair.env` exists; by hand it is `python darts_market.py` then `python rerender.py darts`. Each priced match is logged to `darts_market_log.json`, and once 100 have finished the weight is refitted from results (`darts_market.fit_weight`).

A second darts model, `darts_legs.py`, prices the four stat lines from shrunk per-leg rates and the legs the match is expected to last. It is not used live: it beats the record price on the cache, but it has not yet beaten it on the settled darts bets. The evidence, and what would change the decision, are in [DARTS-MODEL.md](DARTS-MODEL.md).

## The picks correct themselves (`learner.py`)

Every settled pick in `best_bets.json` is used to fit a correction from what the site said to what landed, per sport, team or player, and market family, pulled towards "no correction" as if 100 phantom legs said so, with a ten-day half-life. It is applied only while it beats no correction on the newest fifth of settled picks, checked every run, so it cannot make the picks worse on the evidence. It learns from `chance_base` (the chance before correction, recorded by besttrack from 16 October) so it never fits its own output. On 16 October it stayed off: the latest 233 picks said 70% and landed 71%. `learned.json` holds the current fit; the picks card says which state it is in.

The player-leg shrink (`weekend.player_shrink`) learns the same way and is already on: 14 phantom games on 120 settled legs.

## Track record (`track.py`)

The tool has no evidence yet that it beats the market, and neither does anything else after a few weeks. The only way to find out is to write picks down before kickoff at the price you could actually have got, settle them from the result, and count.

```bash
python track.py add --event 14083629 --team 2814 --stat "Total shots" \
                    --line 12.5 --side over --price 1.95 \
                    --rate 0.7 --need 1.68 --proj 13.1
python track.py settle
python track.py report
```

Three things are enforced rather than suggested, because a record that can be quietly tidied is worth nothing:

- a pick cannot be logged once the match has kicked off
- settlement reads the result from the API, so a loser cannot be dropped
- the model's numbers at the time are stored, so you can later ask whether its signal predicted anything

The report gives ROI with a 95% interval, and splits results by whether the price cleared the Need figure. If those two halves perform the same, the model is not adding anything and you have learned something valuable for the price of some record-keeping.

**Expect the interval to span zero for a long time.** Simulating a genuine 10% edge over 400 bets gave +6.3% ROI with an interval of -3.3% to +15.8%, still consistent with no edge at all. It needed about 900 settled bets to separate from luck. That is not a flaw in the tracker, it is what betting variance actually looks like, and it is the single most important number to know before selling anything.

## My slip

A fourth tab. Press Add on any Standout row and it lands here, scored out of 100:

- **Value, 45 points.** How far your price beats what the evidence supports. Carries the most weight because the record tells you what happened and only the price tells you whether the bet is worth making. A 10/10 record at 1.10 is a bad bet.
- **Evidence, 25 points.** How much data sits behind it.
- **Model, 15 points.** Whether the opponent-adjusted projection agrees with the record.
- **Context, 15 points.** Whether the record was built against the right standard of opposition.

The breakdown is always shown. A score you cannot interrogate is just an opinion with a number stuck on it.

Add more than one and it shows the combined price against the fair price, and how much better each leg would need to be priced to break even. It also states plainly what multiples do: the bookmaker's margin compounds, so at 5% per market a treble carries about 16% against you and a five-fold about 28%. Singles are where value survives.

## The Line-ups tab as data (`gamestate.py`)

The Line-ups tab's player lines are worked out in the browser. `gamestate.py` works out the same things in Python from the same report data and prints them as JSON, so Jarvis (or anything else) can read them without a browser.

```bash
.venv/bin/python -B gamestate.py --event 16363888
.venv/bin/python -B gamestate.py --team "Aston Villa" --hours 168
```

`--team` matches any part of either team's name and takes kick-offs from now to `--hours` ahead (default 168). Per fixture you get where the XI came from (`confirmed`, `predicted` or `regular starters`), the game card (expected possession, projected shots, on target, goals, fouls and tackles, and the one-line script), every Fouls, Fouled, Shots, Shots on target and Tackles line the page backs with its "works against" list, the head-to-head foul pairs scoring 0.6 or more, and the positional matchup for each line, marked `thin` where the page would. `on_page` marks the rows the page itself shows; the rest it computes and cuts. It exits 1 if nothing matches.

It reads only: no fetching (`lineups_auto.py` already puts the XI in the report), no writing. The page is the reference. `tests/test_gamestate.py` lifts the tab's own JavaScript out of `report.py`, runs it in node on three saved reports and fails unless every row matches to 3 decimal places, so a change to the page's JavaScript fails the test until `gamestate.py` follows.

```bash
.venv/bin/python -B -m unittest tests.test_gamestate
GAMESTATE_LIVE=1 .venv/bin/python -B -m unittest tests.test_gamestate   # also every football fixture in reports/
```

## Weekly routine

```bash
python run.py --leagues premier_league,championship,la_liga --adjust
./publish.sh
```

That is the whole thing. No `git add`, no commit, no push for the reports.

Two reasons it stays cheap:

**Fetching is already incremental.** Finished matches never change, so their responses are cached permanently. A new gameweek only fetches that week's matches; everything before it is read off disk. The second run of a season is nearly instant regardless of how many leagues you build.

**Publishing does not grow the repo.** `publish.sh` force-pushes the built site to a `gh-pages` branch as a single commit, replacing whatever was there. `main` never carries a report, so it stays small forever. Committing a 3.5 MB file every gameweek would otherwise write the better part of a gigabyte into history over a season, for files that rebuild from cache in seconds.

One-time setup: Settings, Pages, Source "Deploy from a branch", Branch `gh-pages`, Folder `/ (root)`. The script also writes a `.nojekyll` file, which stops GitHub running the site through Jekyll, the step that failed during the outage.

Commit source changes to `main` as normal. Only generated output goes to `gh-pages`.

## What runs when

Everything scheduled runs on the Mac. Nothing here is a cloud job.

| When | What | Started by |
|---|---|---|
| Every day, 07:00 | `update.py`: settle (`bettrack.py`, `besttrack.py`, `linelog.py`), build every league in `update.json` with `run.py`, then the Nations League, Champions League, Europa League, NFL, darts, MLB and NBA steps, `rerender.py`, `make_index.py --prune`, commit, `publish.sh`, then `tactics_fetch.py` | launchd, `com.zacthorman.football.plist` |
| Every publish | `publish.sh`: `market_prices.py` (with `.betfair.env`), `paddypower_prices.py`, `bet365_prices.py`, `team_news.py`, `fmodel_live.py`, `usmodel_live.py`, `markets_sidecar.py`, `pplog.py settle` and `snapshot`, `teamlog.py settle` and `snapshot`, `pplog.py page`, `exchange_eval.py settle` and `fit` (with `.betfair.env`), `make_index.py`, `exchange_eval.py log` and `page`, `tonight.py --hours 8`, `besttrack.py snapshot`, `linelog.py snapshot`, `bets_page.py`, then the push to `gh-pages` | `update.py`, `lineups_auto.py`, `catchup.sh`, or by hand |
| Every 15 minutes | `lineups_auto.py`: confirmed line-ups about an hour before kick-off, then a republish | launchd, `com.zacthorman.lineups.plist` |
| Weekly, Mondays 05:34 | `teammodel_train.py --weekly`: small, checked update of the team model, logged to `teammodel/CHANGELOG.md` | scheduled task `football-models-weekly-mac` |
| Weekly, by hand | `gs_backtest.py build` then `gs_backtest.py test`, so `gs_fit.json` keeps up with the cache | you |
| By hand, when needed | `darts.sh`, `nfl_fit.sh`, `catchup.sh`, `backfill.py`, `cards_backfill.py`, `strength.py --slopes` or `--tune`, `nba_team_train.py`, a full `teammodel_train.py`, `match_result.py`, the probes | you |

## The files

**Build and publish**

| File | What it does |
|---|---|
| `run.py` | Command line entry point for one report or a whole round. Start here. |
| `update.py` | The daily job: settle, build, re-render, index, commit, publish, then tactical data. |
| `publish.sh` | Prices, models and logs for the site, then force-pushes it to `gh-pages`. |
| `catchup.sh` | Rebuilds only the leagues last night's job missed, then indexes and publishes. |
| `darts.sh` | The darts page: every PDC match in the next few days. |
| `nfl_fit.sh` | Fits the NFL and builds next week's slate once the football job is done. Does not publish. |
| `rerender.py` | Rebuilds every report's HTML from the data inside it, no requests. |
| `make_index.py` | The front page: every upcoming fixture, soonest first, and the four picks. |
| `tonight.py` | `tonight.html`: the small page of what is on soon. |
| `lineups_auto.py` | Confirmed line-ups an hour before kick-off, then a republish. |
| `lineup_data.py` | Predicted and confirmed line-ups attached to each fixture at build time. |
| `team_news.py` | Who is out, per fixture, for every sport. |
| `nfl_injuries.py` | NFL injury report and quarterback changes. |
| `enrich_derived.py` | Writes the derived gridiron markets into a report already on disk. |
| `replay_build.py` | Replays the whole page build from `cache/` with a frozen clock, timed, and diffs two runs (22 October). |

**Data**

| File | What it does |
|---|---|
| `sofascore_api.py` | Fetching and caching. Every response saved to `cache/` before parsing. |
| `hitrates.py` | Parses match statistics, builds each team's and player's form, works out the lines. |
| `markets.py` | Which markets exist per sport, and what they are called. |
| `tactics_fetch.py` | Average positions, shot maps, momentum and incidents, fetched gently (21 October). |
| `backfill.py` | Whole NBA and NFL seasons of box scores into the cache, for the backtests (21 October). |
| `cards_backfill.py` | Per-player card history, spread over a day. |
| `clubcolour.py` | Kit colours turned into readable chart colours. |
| `nfl_teams.py` | NFL team names to SofaScore ids. |

**Models**

| File | What it does |
|---|---|
| `model.py` | The count model in Python (Poisson, negative binomial, binomial; calibration). |
| `probability.py` | The shared probability helpers: logit, sigmoid, Platt calibration, Wilson, shrink, Poisson and negative binomial tails (22 October). |
| `strength.py` | One Elo rating per club from the cache, and the strength-aware picks. |
| `fmodel_live.py` | The backtested football player model, live: `reports/fmodel.json`. |
| `usmodel_live.py` | The backtested NBA and NFL player models, plus NBA team prices: `reports/usmodel.json` (21 October). |
| `usfeatures.py` | NBA and NFL player features, shared by training and the live scorer (21 October). |
| `usgame.py` | NBA game state: pace, ratings, expected total and margin, blowout risk, rest (21 October). |
| `nba_team_train.py` | Trains and exports the NBA team-stats models (21 October). |
| `teamstyle.py` | Team style, tactics and shape features from `cache/` (21 October). |
| `teammodel_train.py` | Trains, tests and exports the football team-stats model; `--weekly` for the Monday update (21 October). |
| `cards_model.py` | The cards model, its walk-forward backtest and `cards_fit.json` (22 October). |
| `teamlines.py` | Which team-line markets have earned a take, and the chance the page prices them at (22 October). |
| `teamline_backtest.py` | Walk-forward backtest of the team lines and the take threshold per market, `teamlines_gate.json` (22 October). |
| `gs_backtest.py` | Walk-forward backtest of the game state and the fit the pages use, `gs_fit.json` (21 October). |
| `gamestate.py` | The Line-ups tab's player lines as JSON. Reads only. |
| `context.py` | The case for each fixture on `tonight.html` (21 October). |
| `darts_model.py` | Darts match markets from a leg-level Elo. |
| `learner.py` | The picks' own correction, refitted from their results. |
| `playerlines.py` | Each player's own line, not one line per stat for the squad. |
| `fmodel/fmodel_trees.py` | Scores exported LightGBM trees without LightGBM. |

**Pages and picks**

| File | What it does |
|---|---|
| `report.py` | Generates each report's HTML and the JavaScript inside it. |
| `pagedata.py` | Finds the dataset inside a built report (22 October). |
| `value_cap.py` | How many singles one player may take, and the backtest that chose it (22 October). |
| `weekend.py` | The four picks across every built report. |
| `parlay.py` | Same-game parlays with alt lines. |
| `picker.py` | A clean bet picker built from the reports. |
| `player_bets.py` | Player props for one report, ranked. |
| `match_result.py` | Match-result accas from the goals projection and the exchange. |
| `why.py`, `explain.py` | The reasons behind a pick, and the working behind a projection. |
| `bets_page.py` | `best-bets-summary.html`. |
| `challenge.py` | The rolling 1.8 to 2.2 challenge. |

**Prices**

| File | What it does |
|---|---|
| `market_prices.py` | Betfair Exchange prices for every fixture in the reports. |
| `betfair_api.py` | The Betfair API client. |
| `markets_sidecar.py` | `reports/markets.json`, the prices the pages read in the browser. |
| `paddypower_prices.py` | Paddy Power's prices, read gently. |
| `bet365_prices.py` | Bet365 player prices via Oddschecker (21 October). |
| `oddschecker_client.py` | The Oddschecker client, with FlareSolverr as a fallback (21 October). |
| `bet365_odds.py` | Prints only Bet365's prices for given market ids (21 October). |
| `darts_market.py` | Betfair darts prices against the model. |
| `exchange_eval.py` | Scores the model against Betfair and tunes the blend. |
| `market_check.py` | The model against real bookmaker prices. |

**Records**

| File | What it does |
|---|---|
| `track.py` | Logs picks before kick-off, settles them, reports honestly. |
| `bettrack.py` | Every best bet, settled from the box score, with lessons. |
| `besttrack.py` | Every best bet the site publishes, settled. |
| `linelog.py` | Every line the model prices, settled. |
| `pplog.py` | Every Paddy Power player line, our chance and the result. |
| `teamlog.py` | The same for Paddy Power team lines (21 October). `python teamlog.py scoreboard` judges the team-line take tier against Paddy Power's real prices, with 95% intervals (TEAMLINE-CHECK.md). |
| `nba_check.py` | NBA player lines: calibration by stat and line from the committed record, and on the Mac the early-season shrink test on `cache/` and a scoreboard of Paddy Power's settled basketball lines (NBA-CHECK.md, 24 October). |
| `freshness.py` | How much of a player's record is from before his last long break; a line on a mostly-stale record is "Old record", never acceptable (PLAYER-STALE.md, 24 October). |
| `player_stale.py` | The evidence for that: the committed records and the football cache across season starts. |
| `teamline_check.py` | Whether the team-line take tier holds: the published record and the cache walk forward, with 95% intervals (TEAMLINE-CHECK.md, 23 October). |
| `review.py` | Why each of a report's bets landed or missed. |
| `backtest.py` | Every bet the model would have made, settled from the cache. |

**Checks and probes**

| File | What it does |
|---|---|
| `verify.py` | `model.py` against the JavaScript in `report.py`. |
| `check.py`, `check_sport.py`, `check_nfl.py` | What SofaScore returns, endpoint by endpoint. |
| `canary.py` | One request: is SofaScore answering? |
| `betfair_probe.py`, `oddschecker_probe.py` | Does the Betfair connection work; where Oddschecker keeps its ids. |
| `tests/` | The test suite, below. |
| `TEST.md` | The 21 questions. |
| `PLAN.md` | What this was meant to be, and what's left. |
| `CARDS-MODEL.md`, `TEAM-LINES.md`, `US-MODELS-AUDIT.md`, `PROOF-2026-10-22.md` | The 22 October write-ups: the cards model, the team lines, the NBA and NFL models audit, and the proof of the 21 October work (scripts in `proof/`). |
| `CODE-HEALTH.md` | The 22 October health pass: what changed, timings, and the output comparison. |

**Tests.** `python -B -m pytest -q tests` (or `python -B -m unittest tests.test_<name>`). Fifteen files: `test_besttrack_team_value`, `test_bettrack_team`, `test_cards_model`, `test_context`, `test_exchange`, `test_gamestate`, `test_leads`, `test_league_names`, `test_league_ratings`, `test_pagedata`, `test_probability`, `test_strength`, `test_teamlines`, `test_us_audit`, `test_value_cap`. Some read built reports or the cache and skip without them; `GAMESTATE_LIVE=1` adds every football fixture in `reports/` to the game-state parity test. None of them writes to a committed file.

## How the lines are chosen

There is no odds feed here, so the line for each stat is derived from the data: the median across both teams' matches, pushed down to the nearest .5 so there are no pushes. One line per stat, shared by both teams, so the two columns compare directly.

If you want real bookmaker lines, that's a separate feed and a separate problem.

## Things worth knowing

**Caching is permanent by design.** Finished matches never change, so their responses are cached forever. Fixture lists use a few hours. If you ever need to force a refetch, delete the relevant file in `cache/` or the whole folder. The folder grows slowly; `run.py` prints its size after each run.

**Friendlies are excluded automatically.** Matches are filtered to the same competition as the fixture, because pre-season friendlies appear in the same feed with no detailed statistics and would silently shrink your sample.

**Small samples lie.** Five matches is not evidence. A 4/5 hit rate and a 40/50 hit rate look the same in the percentage column and are not remotely the same thing. The chart is there so you can see whether a number is steady or two extremes averaged together, and the fraction is shown next to every percentage for the same reason.

**Cross-season samples are misleading.** "Last 10" can straddle a summer transfer window, which means half the sample describes a squad that no longer exists. Check the dates in the tooltips before trusting anything in August or September.

**This will break eventually.** It reads an undocumented API. If SofaScore rename a stat, `.get(name)` returns nothing and the row simply disappears rather than erroring. If rows vanish that you expect to be there, that's the first thing to check.

## Extending it

The obvious next moves:

- **Player props.** `sofascore_api.event_lineups()` is already there and returns per-player stats. Same pattern as `hitrates.team_form`, one level deeper.
- **Opponent stats.** Currently each record holds the team's own numbers. Store the opponent's too and you get "cards conceded", "shots faced" and so on.
- **Real lines.** Swap the median-derived line for a bookmaker's, and the hit rates become directly actionable rather than descriptive.
- **A watchlist.** Run it across every fixture on a Saturday and surface only the stats above some threshold.

## Match-result accas

Who wins, from each report's goals projection and the Betfair prices in `market_prices.json`.

```bash
python match_result.py --league mls              # safest 2-leg win acca, next 24 hours
python match_result.py --league mls --legs 3 --log   # 3 legs, logged to match_results.json
python match_result.py                           # every football report at once
python match_result.py settle                    # settle logged picks once games finish
python match_result.py report                    # win rate, profit, model v market Brier score
```

"Safe" legs need the model and the market to agree on the favourite, ranked by the average of the two. "Value" legs are where the model beats the market by 10 points or more (`--edge`). The goals model has never been tested on match results, so treat value legs as disagreements until `report` has 100+ settled legs behind it.

## Player lines and the full line log (18 October)

**Player lines** (`playerlines.py`). Every other player leg is priced against the report's one line per stat for the whole squad. This picks each player's own line instead: the highest whole-number rung he has cleared in 7 of his last 10, with his last-10 average at least 10% over it. The same rule as the NFL Defences tab, now in Python for every sport. Only markets bookmakers list (shots, tackles, fouls, passes, saves; NFL yards, receptions, attempts, tackles, kicking; MLB hits, total bases, H+R+RBI, and pitcher props for starters only). Players ruled out on the NFL injury report are dropped, and once a line-up is confirmed only the XI (or the NFL actives) count. Priced through `model.price` and `weekend.calibrate`, so the chance carries the same shrink as every settled player pick. Shown as a **Player lines** table per fixture on tonight.html and recorded by besttrack as category `Player line`.

    python playerlines.py --hours 24 --top 20

Heuristic thresholds (7 of 10, 10% clear, 60% chance floor), not backtested yet. That is what the log below is for.

**Line log** (`linelog.py`). besttrack records what the site chose. This records everything: every leg tonight.py can price plus every player-line candidate, first sighting before kick-off, settled the same way (a DNP voids). Run by publish.sh (snapshot) and update.py (settle).

    python linelog.py report    # calibration by chance band, kind, sport and market; value bets at the Betfair price

One JSON-lines file a month in `linelog/`, around 2 MB on a busy day, so it is gitignored and lives on this Mac with `cache/`. Back it up if the raw rows matter.

## Players tab: squads, player profiles and match odds (19 October)

The Players tab now opens on the two sides, each with its predicted or confirmed XI as tappable names. Tap a side for the squad (XI first, then the rest by position, each with a role and any line cleared 7 of the last 10), then a player for his profile. The old by-stat table is still there under **Compare by stat**.

- **Role.** Worked out from what he does per 90, not SofaScore's G/D/M/F: tackles plus fouls plus interceptions against shots plus key passes plus three times xG. Midfielders split into holding, box-to-box and attacking, so two "midfielders" in the same XI read differently.
- **Profile.** Every stat with a record: the last ten as chips, avg and per 90, and up to three lines. Each line shows the last-ten record and the full record, **Ours** (pricePlayer on his last ten under the filters, matchup-adjusted and calibrated), **Fair**, **Betfair** where the exchange lists it, **Est. bookie**, a box to type the real price, and the **Edge** (ours times price, minus one) against the typed price, else Betfair's back, else the estimate. Add puts it on the slip.
- **Est. bookie** is not a scraped price. It is the calibrated chance over every match on file, unadjusted, with `BOOK_MARGIN` (12%) on the implied chance, which is roughly how a bookmaker prices a player line. The margin is a judgement call; set it from real prices once a few have been typed in.
- **To be booked** (football): fouls per 90 times the side's yellow cards per foul over its filtered window, over his expected minutes, times the side's projected fouls here against its usual (`playerAdjustment("Fouls")`), times a factor for the men he is up against on the line-up (their fouled per 90 against the report average, square-rooted, held to 0.85 to 1.2). Half last ten, half the full filtered record. **Heuristic and not backtested.** Per-player card history is not fetched (it needs SofaScore's incidents endpoint per match), so this works from fouls. Where `reports/fmodel.json` carries a Card chance (the cards model, 22 October, below) that is shown instead.
- **To score** (football): 60% xG and 40% goals per 90, over expected minutes, times the side's projected goals here against its usual. Half last ten, half full record. **Heuristic and not backtested.**
- **Match odds.** A strip above the tabs on every fixture shows Betfair's price and chance for home, draw and away. `markets_sidecar.py` writes `reports/markets.json` from `market_prices.json` (match odds plus the player markets Betfair lists: to score, shots on target 1+ and 2+, shown a card), run by `publish.sh` straight after `market_prices.py`, and each page fetches it on open. Opened as a local file the strip and Betfair columns are simply absent.

Previous version kept as `report.py.bak-profiles` and `publish.sh.bak-profiles`.

**Team stats as one chart (19 October, evening).** The Team stats tab opens on **Chart**: the stat list down the side, always open, each stat with each side's last-N count at its line; tap one and the chart beside it switches. Above the chart: the line stepper and projection, then Both / home / away, Full / 1st half / 2nd half, and Last 5 / 10 / 20. The side and period buttons press the Filters panel's own buttons, so the whole page moves together. Each side gets a ring (thick green segment a hit, thin red a miss) and a line in its own colour on one shared chart, the line dashed across, filled dot over and hollow under, opponent initials along the bottom when one side is shown. Same look as Jarvis's pick cards (`jChart`, `jChart2`, `jRing`). The old board is under **Table**. Player profiles use the same chart in place of the number chips.

`besttrack._tail` now sums the binomial tail in log space: `math.comb` overflowed a float once the best bets record passed about a thousand legs, and `bets_page.py` crashed on 19 Oct. Old version in `besttrack.py.bak-tail`.

**Strongest lines, every sport (19 October, late).** `playerBestLines()` prices every line a player has a record in through `pricePlayer` on his last ten under the filters and keeps those between 55% and 92%, ordered by that chance, then the full record, then sample size. It feeds three places: a **Strongest player lines** list on the Players tab's front page (one line per player, XI only once a line-up is known, with stat chips to rank one market at a time; Passes is left out of "All" and has its own chip), the top three chips on each squad row with a **Strongest** order beside Line-up or Position, and a "His strongest lines" strip on each profile. Profile lines are now centred on the player's own numbers (`rungsFor`), so a quarterback's passing yards and a back's rushing yards both get readable lines. The Team stats list shows each count as a % too, with Standard or Strongest order (the Filters panel's own Strongest first). The NFL record-only branch tops out at 91% for a perfect ten, which is why its list ties at the top; the full record breaks the tie. Backup before this: `report.py.bak-strongest`.

## Paddy Power prices (`paddypower_prices.py`, 20 October)

Real Paddy Power prices on the Players tab: a **Best value at Paddy Power** list on the front page (our chance 50%+ and beating the price, players ruled out left off, questionable ones marked), a **Paddy Power lines** card on each profile with our chance worked out at exactly Paddy Power's line, over or under, and the Paddy Power price used for the edge on the site's own lines wherever the line matches.

It reads the feed Paddy Power's own event page uses (`apisms.paddypower.com/smspp/event-page/v5`), one GET per game, logged out, no cookies. **That is a private feed, not a public API, and reading it is against Paddy Power's terms**; it runs from the home connection, so it is built to stay well below one person browsing:

- `touch .paddypower_off` switches it off; delete the file to switch it back on.
- Any refusal (403, 429, 5xx, timeout, a non-JSON reply) locks it out for 24 hours. It never retries.
- 15 to 30 seconds between games, randomised; at most 15 games a run and 60 a day; only games kicking off within 30 hours; never once started; nothing refetched within 4 hours (1 hour in the last 3 before kick-off); a lock file so two publishes cannot overlap.
- Paddy Power's event id is tried as Betfair's (`bfEvent`, now saved by `market_prices.py`). The team names on the reply must match; a mismatch or a 400 records that the mapping does not hold and it stops asking.

`python paddypower_prices.py --status` shows the caps, any lockout, the id mapping and what is held. `--event <id>` prints one game's lines. Run from `publish.sh` after the Betfair fetch; `markets_sidecar.py` merges `reports/paddypower.json` into `reports/markets.json`. NFL market names are mapped to the site's stats (`PP_STAT` in report.py); football markets are shown once their names have been seen. Unders are priced as one minus the over, so both sides of a line add to 100%; lines under 50% are shown as long shots and never count as value.

## Player model (`fmodel_live.py`, 20 October)

The football player chances on the site now come from a model built and tested
on 6,788 matches, not from the player's own record alone. For each starter it
looks at his form, how his team and the opponent play, what the opponent
concedes to his position, the two opposition players nearest him in the
formation, his team-mates on the same line, head to head and league strength.

Lines covered: shots 1+, 2+, 3+; shots on target 1+, 2+; fouls 1+, 2+;
fouled 1+, 2+, 3+; tackles 1+, 2+, 3+; to score; to assist. Everything else
(passes, saves, higher lines, other sports) still uses the old chance.

How good it is, out of sample (July to October 2026, matches it never saw):
it beat the old chance on all 15 lines, including after fixing the old one's
calibration, and when it says 65% the line hits about 65% of the time (within
about a point at every level). The old chance was 5 to 13 points out, mostly
too close to 50%. Full numbers: `fmodel/training/results_auto.csv`.

How it runs: `publish.sh` runs `fmodel_live.py` before the prices and the
Paddy Power log. It reads `cache/` only (no requests) and writes
`reports/fmodel.json`. The line-ups job republishes when a confirmed XI
lands, so chances move from the predicted XI to the real one about an hour
before kick-off. First run takes a couple of minutes; after that it keeps a
cache in `fmodel/` and takes about a minute.

Things to know:

- It assumes the player starts. A player not in the predicted or confirmed XI
  keeps the old chance, so before line-ups are out treat non-starters' lines
  with care.
- Value rows priced by it say "model", and "predicted XI" until the
  confirmed one is in. An edge over 40% says "check team news": a gap that
  big is more often the bookie knowing something than the bookie being wrong.
- To score now counts as value when the model priced it (it is calibrated).
  Cards still do not.
- The Paddy Power log records the model's chance and the old one side by side
  (`source`, `site_chance`), so the two can be compared on real results.
- How it was built and how to retrain: `fmodel/training/README.md`.
- To switch it off, delete or rename `reports/fmodel.json` and comment out the
  `fmodel_live.py` line in `publish.sh`. The pages fall back on their own.

## The case for each fixture (`context.py`, 21 October)

Modelled on the detail a good tipster preview gives (a saved Upper90 Tips Champions League reel): every pick argued, not just priced. Each fixture on `tonight.html` now opens with **The case**:

- **Call.** A predicted score with home, draw and away chances. Where the report has a goals projection it is used; for cross-league ties Elo decides the result and recent xG only the number of goals, and the line says which. Untested against results.
- **Lead.** The top single on the page, with its fair and need prices.
- **The argument.** One paragraph in the order a preview makes it: how each side comes in, what the opponent concedes in the lead bet's stat, then the facts that bear on that kind of bet (a cards bet gets the referee, not clean sheets). "Nothing for us here" when no leg qualified.
- **Facts.** Only the unusual ones: conceded in 9 of 10, 1 point from 2 games, plays again in 3 days, without a player who started 8 of the last 10, referee well above or below 4 yellows a game.
- **Each side.** The last five results with date, competition, opponent, score and W/D/L; the last ten as counts (won, scored in, conceded in, clean sheets, BTTS, 3+ goals); xG for and against over the last five; points and table position in this competition (from a cached standings table when fresh, since the records cannot tell qualifiers from the league phase); the next three fixtures; who is missing and how often they started.

Every team single also gets an **opponent allows** line: what the opposition concedes in that stat at the matching venue, in this competition when there are 4+ games and otherwise in all, with how many of those games beat the line. "Bodo allow 25.0 total shots a game away in this competition (last 9): 9 of 9 went over 14.5" is the shape.

Nothing here changes a chance or a ranking: it is the argument, not the model. It reads only what is on disk (the report payloads and `cache/`), so it adds no fetching. Tests: `python -B -m unittest tests.test_context`.

## Game state, backtested (`gs_backtest.py`, 21 October)

The game state now prices bets rather than describing them. `gs_backtest.py build` gathers every cached match with statistics and line-ups (7,177 and 6,777 on 21 October); `gs_backtest.py test` replays them in date order with only pre-match information and fits, per stat, how much four things move the count: the side's or player's own last-10 average, what tonight's opponent allows over its last 10, home or away, and tonight's predicted share of the ball against the share this side usually has. Each version is scored on later matches it was not fitted on, and the fit goes to `gs_fit.json` with the table in `GS_BACKTEST.md`.

What it found: what the opponent allows is the big signal for every stat; possession adds a measurable amount only for player shots, shots on target and tackles, and team corners, tackles, clearances and saves, so its term is off for the rest (fouls, cards, team shots); and the old unfitted possession factor made fouls and tackles worse than ignoring the game state. Player chances land within about two points at 1+ and run a little cautious at 2+ and 3+.

On `tonight.html` every team and player single the model reaches shows "Backtested model X% (opponent ×a, game state ×b; Y% before the game state). With the record: Z%", the singles are ranked on Z, the lead is the top of that list, and each fixture's Game state box lists **Tonight leans to** (model at 60%+ and 8+ points above the player's record, the bets a record filter throws away) and **Tonight works against** (good records the model marks down). Re-run `build` and `test` weekly so the fit keeps up with the cache.

Also new on the page: current streaks of eight or more (e.g. under 3.5 goals in 9 straight), a minutes note on player legs (share of minutes, record in 60+ minute games, whether the misses came in short games), the opponent's league rank when it is in the top or bottom five for the stat it allows, and **Last night's leads**: each fixture's lead is written to `lead_log.json` before kick-off and ticked or crossed from `best_bets.json`, with how many the page expected to land.

## How the game will go, tactics and the team model (21 October, late)

**How the game will go** is the last section of every football fixture on `tonight.html`: the likeliest score, each side's shape from the line-up (double or single pivot, who plays behind the striker, back three), each side's style in words, and a numbered **Why** list in the form "X plays a double pivot against three attacking midfielders, so the pivot has more ground to cover: expect tackles and fouls (Rice: 2+ tackles 67%)". Style words (press hard, sit off, go long, build short, attack wide, camp in the final third, bodies in the box, run with the ball, foul a lot) are used only when a side is in the top or bottom quarter of every team on the site. Player numbers in the reasons are fmodel's.

**The team model** (`teamstyle.py`, `teammodel_train.py`, `teammodel/`). Team bets (shots on target, corners, fouls, tackles, cards, big chances, saves, and the linear fallback for shots, clearances, offsides) are priced by a model trained on every cached match with tactical features: pressing (opposition passes per defensive action), directness, crossing and crosses allowed, territory, box touches for and against, dribbling, fouling, xG, tonight's formation and shape, the clashes between the two styles, predicted possession and Elo. Per stat, LightGBM with all of that only replaced the linear model where it won on April to June validation; out of sample from July it improved shots on target 2.2%, tackles 1.3%, big chances 1.0%, cards 0.6%, corners 0.3%, fouls 0.2%. `teamstyle.py` is the one feature module for training, the weekly update and the page, so they cannot drift; the page scores the exported trees with `fmodel/fmodel_trees.py`, checked equal to LightGBM to 1e-14.

**Player bets** use fmodel's backtested chance (`reports/fmodel.json`) where it covers the player. Adding the same tactical group to fmodel was tested on every line and changed nothing measurable (all within 0.1%), so fmodel is unchanged until the new data below is in.

**Weekly, in small steps.** The scheduled task `football-models-weekly-mac` (Mondays 05:34) runs `teammodel_train.py --weekly`: each kept model continues from last week's with 40 trees at a low learning rate on recency-weighted data (half-life 120 days), has any change of more than 3% on average halved, is then scored against last week's on the latest 21 days it did not train on (so the model scored is the model adopted), and is adopted only if no worse there, with no slack. Every week is written to `teammodel/CHANGELOG.md`; a stat that fails is logged as FAILED, the other stats still run, and the job exits non-zero. `TEAM-MODEL-CHECK.md` has the week-by-week audit of this rule (`teammodel_audit.py`). A full refit (`teammodel_train.py` without `--weekly`) needs lightgbm, statsmodels and scipy and is for when the data changes shape, e.g. once the tactical backfill lands.

**New tactical data** (`tactics_fetch.py`, run by `update.py` after publishing, never fatal): SofaScore average positions, shot maps (with fast-break, set-piece, open-play situations), attack momentum and incidents for every finished match, teams with upcoming fixtures first, budget 1,500 requests a day (`tactics_budget` in update.json); and, only if you create `.understat_on`, Understat's league pages (PPDA and deep completions); off by default since its robots rules disallow automated access. `tactics_fetch.py --status` shows progress. Every response is checked against the shape its endpoint is known to have (and Understat's teamsData likewise); an unknown shape stops the run with `SHAPE ERROR` and exit code 2 instead of being cached or skipped, and `tactics_fetch.py --check` runs every parser over the files already held. Once enough is held, line height, team length and width, full-back height, pivot dropping, counter-attack threat and chasing behaviour go into teamstyle.py and both models are re-tested.

## NBA game state and team model (21 October, late)

`usgame.py` computes each NBA side's game state strictly from earlier games: pace (possessions = FGA + 0.44 FTA - offensive rebounds + turnovers, from the player box scores), offensive and defensive rating, expected points for and against, total and margin, blowout rate (games ending 15+ apart), each player's minutes in blowouts against close games, games in the last four days, the rest gap and altitude. One module for training and live; a finished game replayed as upcoming gives identical features.

Backtested on fmodel-style splits (train to January 2026, validation February to March, out of sample from April):
- **Player markets:** adding the game state to usmodel changed nothing measurable (all within 0.5%, mostly slightly worse); usmodel already carries each opponent's points for and against, Elo and missing team-mates. usmodel is unchanged.
- **Team markets** (`nba_team_train.py`, `usmodel/nba_team.json`): each side's last-10 average and the opponent's last-10 conceded, home, priced as negative binomial. The game-state LightGBM did not beat that on validation for any stat once a leak in the first version was fixed (the live parity test caught the away side's "opponent concedes" including the same game), so every stat uses the simple model, with pace added for assists only.

`usmodel_live.py` now also writes, per NBA game, each side's game state and team prices into `reports/usmodel.json`; `tonight.html` re-prices NBA team legs from them ("Backtested NBA team model") and ends each NBA game with **How the game will go**: the model score and total, the pace clash, likely margin and blowout risk (starters sitting the fourth), third game in four nights, rest gap, altitude, and who is out with who gains (usmodel's expected points against each player's usual). These lines explain the game; they do not move the chances beyond the team model.

## Cards model and one bet per player (`cards_model.py`, `value_cap.py`, 22 October)

Team yellow cards on `tonight.html` are priced by a cards model: own and provoked cards over 10 and 38 games, the competition's card rate, both sides' fouls and the Elo gap, with SofaScore's missing 0-0 rows counted as 0-0s. Walk-forward it beat the team model on all four held-out windows, and the page's fouls heuristic summed over the XI by more. `fmodel_live.py` writes each starter's To be booked from it into `reports/fmodel.json`: the side's expected cards, the starters' 86% share, split by fouls per 90 over expected minutes. The split is not backtested, because the cache has no per-player cards, and card lines are still never value. Value lists, "Best singles here", the recorded fixture singles and the Paddy Power value record now take one line per player per game, because legs on one player land together.

    python -B cards_model.py test     # the backtest tables
    python -B cards_model.py fit      # refit cards_fit.json (delete the file to switch the model off)
    python -B value_cap.py            # the cap's backtest, from pplog/ when it is on this machine

Full results and the honest verdict: `CARDS-MODEL.md`.

## Code health (22 October)

A pass that changes no output, written up in `CODE-HEALTH.md`.

- **`probability.py`.** The probability helpers that had been copied between modules (logit, sigmoid, Platt calibration, Wilson, the pseudo-count shrink, Poisson and negative binomial tails, method-of-moments overdispersion) live here once. Every old name (`model.wilson_low`, `context._nb_at_least`, `weekend._lp` and the rest) still works, as an alias or a one-line wrapper. `tests/test_probability.py` checks each against its old body with `==`, not almost-equal. Look-alikes that are not bit-equal (`darts_model.poisson_tail`, `gamestate.pois_at_least`, `besttrack._tail`, `market_prices._pois`, `usmodel_live.calibrate`) were left where they are, with the reason in `probability.py`.
- **`pagedata.py`.** Twelve modules found a report's dataset with the same lazy regular expression, which crawled through a multi-megabyte page for half a second each time. One `str.find` version now, pinned to the old regex by `tests/test_pagedata.py`.
- **`replay_build.py`.** Replays the daily build from `cache/` alone: a fixed weekend presented as upcoming, every SofaScore request answered from the cache, every other request refused, the clock frozen (`pip install libfaketime`). Two runs can then be compared file by file. It never publishes and writes only inside the folder it is given.

```bash
git archive oct21-work | tar -x -C /tmp/before
git archive code-health | tar -x -C /tmp/after
python replay_build.py run /tmp/before
python replay_build.py run /tmp/after
python replay_build.py compare /tmp/before /tmp/after
python replay_build.py run /tmp/after --profile   # a cProfile per step
```

## Scorer audit (`scorer_audit.py`, 22 October)

A walk-forward audit of the player legs the pages lean on most: to score, shots and shots on target. Every starter since 1 July 2026 (when fmodel's training ended) is replayed with only what was known before kick-off, and each chance the pages can show is scored against the result: the record, the shrunk record, the Players tab's own chance, the game-state model, fmodel, and tonight.html's blend. Full tables and the verdict: [SCORER-AUDIT.md](SCORER-AUDIT.md).

    python -B scorer_audit.py build   # about 20 minutes, reads cache/ only
    python -B scorer_audit.py test    # a minute: tables, and refits the two files below

What it found: fmodel is calibrated and was left alone. tonight.html's chance and the Players tab's fallback both ran high on the low lines (to score on tonight.html said 24% where 11% landed), because both pull towards 50%. Two fixes, each kept only where a version chosen on earlier months beat the page on every later month:

- `fmodel/tonight_blend.json`: the weight `context.py` gives fmodel against the shrunk record, per line (1.0 for to score, shots 3+ and shots on target; 0.9 for shots 2+; shots 1+ stays half and half). To score now gets fmodel on tonight.html.
- `fmodel/site_calib.json`: a Platt map per line on the Players tab's own shots and shots on target chance where fmodel has none, injected by `report.py` at render.

Delete either file to go back to the old numbers. The `test` step rewrites both and drops any line whose fix stops holding, so rerun it when the cache has grown. Tests: `python -B -m unittest tests.test_scorer_audit`.

## NFL game script (22 Oct 2026)
`nflgame.py` builds pre-game script features (expected margin, plays, pass-rate shift when ahead or behind, short week, bye); `nflgame.upcoming()` gives the same for live games.
`usmodel/training/nfl_gs_eval.py` tests them against the live NFL model with a bootstrap by game and Holm correction.
Result: no market significant, so the NFL model is unchanged. See NFL_GS_BACKTEST.md. Re-run after the 2026 season.
NFL games on the tonight page now have a "How the game will go" section built from that script: points form, expected plays, how much each side's passing follows the scoreboard, and short weeks or byes. It is display only and does not change any chance.

## Bookie value bets, boost check, Conference League (22 Oct 2026)
- **Bookie value bets** (top of tonight.html, `boostcheck.value_box`): Paddy Power player bets where the player model beats the price, one per game, priced at 8.0 or shorter, chances cut by how far that market's hits have fallen short of the model in pplog. It shows a market only while its settled record is about break-even or better (−5% per bet), and calls it "Proven" only when it is still in profit without its two biggest winners. The budget box splits stakes by Kelly share (50p steps).
- **Boost check** (third tab on each football game, `boostcheck.boost_tab`): result, most shots on target, most corners, goals line, both teams to score, against a typed price. Result chances are the site's score model; goals come from its Poisson projection, rescaled to the result; the shots-on-target and corners winners come from `boost_table.json` (5,017 matches, given result × pre-game favourite from last-5 xG). Ties lose. Rebuild the table with `boost_table.py` (reads the backtest's teams.parquet).
- **Conference League**: tournament 17015, cross-league form like the Champions League and Europa League. Built by update.py whenever a matchday is within `conference_league_days` (3).
- When building tonight.html anywhere other than the Mac, set `TZ=Europe/London`, or kick-off times come out in UTC.
- **Tonight layout (22 Oct, later)**: two big tabs, Team lines and Player lines. Each game is a collapsed row showing its best bet; open it for the case, game state and boost check (team) or the player bets and each player's own line (player). Bookie value bets sit at the top of Player lines and drop players who aren't in the XI the player model is using (confirmed once line-ups land). `tonight.legs_of` now drops players listed out (line-up missing lists, injury report) and, once an XI is confirmed, anyone not starting.

## Game state tab, style model, flank tests (22 Oct 2026, evening)
- **Style model for the score** (`teammodel/open_goals.json.gz`, `open_meta.json`; trained by `research/open_eval.py`): goals per side from a Poisson GLM on recent xG for/against, home and Elo, times trees on every teamstyle feature plus clashes (counter-attack threat v a high line, press v build-up, both sides' openness). Out of sample it beat the GLM on the result (1X2 log loss −0.54%, Holm p<0.001). Where it lifted an underdog by 1–4 points, underdogs won 35% (it said 31%, the GLM 29%); where it cut one, they won 10–20%. Totals and both-to-score: no worse, not significantly better. `context.score` uses it for **same-league games only**; European ties keep Elo + xG, because each side's profile is built from its own league (it made Beşiktaş 67% v Palace).
- **Game state tab** on every football report page: `gamestate_live.py` → `reports/gamestate.json` (run by publish.sh). Result and goals with fair prices, open or tight, how the game will go, the game state's leans, and lines to target (lines the game state rates above their record, with the exchange price and edge where Betfair has it).
- **Flank and involvement features** (`research/flank.py`, `flank_eval.py`): each team's attacking volume by side, what it concedes down each side, the player's side against the opponent's weaker side, and each player's share of team touches, shots, key passes and fouls won. None passed against the player model (45 lines × variants, best tackles +0.1%, Holm 0.29): its direct-opponent and team-style features already carry most of it. Sides come from formation slots, which is crude; re-test once the average-position backfill (tactics_fetch.py) has a season of data.
- **Style model v the market (22 Oct, late):** on the 85 domestic games in exchange_log.json (team goals, match goals, both-to-score; 386 lines) Betfair's price near kick-off beat the style model clearly (log loss 0.609 v 0.660). Where the style model was 10+ points higher than the market, the line landed 24% (market said 47%); 10+ lower, it landed 76% (market said 54%). Do not bet goals markets off the model where the exchange disagrees. The result (1X2) improvement is untested against the market: no match-odds history yet. To test it, download free closing odds into research/odds/ (football-data.co.uk, see research/README) and re-run.
- **Result v closing odds (22 Oct, late; research/vs_market.py, odds from football-data.co.uk in research/odds/):** 2,579 league games matched. Log loss per match, out of sample (456 games): closing average odds 0.981, style model 1.008, GLM 1.013. Adding the style model to the market did not help (−0.001, CI −0.006 to +0.004). Backing outcomes where the style model saw a 5%+ edge at the best closing price: −11% (validation), −3% (out of sample). Conclusion: the market's result prices are better than ours; the style model is a read of the game, not a source of value on results or goals.
- **Paper bankroll and price movement (22 Oct, late; `papertrade.py`):** £1,000 replayed over 7,423 settled priced lines. Backing everything the model rated 5%+ value busts (old record-based chances, NBA props and shots worst); the player model's Paddy Power value bets lose 16%; anytime scorers at 8.0 or shorter +5% (26 bets). Price movement (pplog first v last price): lines the player model rated 5%+ value at the first price shortened 3.6% on average before kick-off (control +0.7%) and broke even (−1.6%, 78 bets) where all other lines lost 42%. Lines with model value after the confirmed line-up: +18.6% over 29 bets (too few to trust yet). The value box now shows when a price has moved since first logged.
- **Paper trade page** (`papertrade.py --page` → `papertrade.html`, run and published by publish.sh): every player bet the site put forward (best_bets.json) matched to the Paddy Power price logged for the same line, £1,000 at 1% a bet, by type, latest 40. First run (22 Oct): 79 settled, 72% won (site said 59%), flat return −5.0%. `python3 papertrade.py` (no flag) still prints the strategy comparison.

## Paddy Power v Betfair (sharp.py, 23 Oct 2026)

The value-bot check on the site. After every pplog / teamlog snapshot, `python sharp.py stamp`
(publish.sh) looks up each unstarted Paddy Power line in Betfair Exchange's prices
(market_prices.json) and writes `sharp_first` / `sharp_last` into the row: Betfair's fair chance
(mid of back and lay on player markets, margin-free two-way on corners/cards), the back and lay,
and the edge = PP price x Betfair chance - 1. Covered: to score, shots on target 1+/2+, shown a
card, anytime TD, match corners 8.5/9.5/10.5/12.5, match cards 2.5/3.5. pplog now also logs
Paddy Power's player shots-on-target lines so they can be checked.

* Tonight page: "Paddy Power v Betfair" box at the top of both tabs, lines 2%+ longer than
  Betfair, tagged by the other signals that agree (beats Betfair's lay, our model, confirmed
  starter, Betfair moving our way), with a budget split.
* papertrade.html: the settled record of those bets by number of signals agreeing, plus the
  site's picks split by price and by claimed edge (where it goes wrong).
* `python sharp.py report` prints what is live and the record.

## Rules on trial, and the NBA / NFL model in pplog (23 Oct 2026)
- **pplog now logs the NBA and NFL player models.** Until 23 Oct it logged the old last-10 chance
  (`model.price_player`) for both, so its NBA and NFL record, and the -33% "model value" in
  papertrade, was the old formula, not `usmodel/`. From now each NBA / NFL row carries
  `source: usmodel`, `chance` (the page's blend), `model_chance` (the model alone) and
  `site_chance` (the old one). Rows logged before then are not rewritten.
- **`research/uscheck.py nba|nfl`** rebuilds what the live model would have said before tip-off for
  every logged game and writes `research/uscheck_<sport>.csv`. On 13 NBA games: log loss 0.533
  against 0.594 for the old chance, well calibrated, but Paddy Power's own price is better still
  (0.522), and blending the model with the price did not help on later games. See
  `research/RULES_RESEARCH.md`.
- **`ruletrack.py`** scores fixed rules, frozen 23 Oct 13:00 BST, on every game after. `report`
  writes `RULES_TRACK.md` (run by publish.sh after the pplog page); `tonight` prints the bets.
  History is the games the rules were chosen on and proves nothing; judge on Live after about 40
  games. The tonight page shows a Rules on trial box above the bookie value bets: one bet per
  player, ordered by model edge (the edge only orders the list).
- Backups: `pplog.py.bak-usmodel`, `publish.sh.bak-ruletrack`, `tonight.py.bak-ruletrack`.

## Bet365 further ahead, and Bet365 value (23 Oct 2026)
- `bet365_prices.py --window 60` fetches games up to 60 hours out (default 30), e.g. on a Friday
  for Sunday. Prices that early move a lot; the normal runs refresh them nearer kick-off.
- `python b365value.py` lists Bet365 football player lines where the player model (shrunk by its
  settled Paddy Power record per market) beats the price, with Paddy Power's price for the same
  line beside it. Edges over 15% are marked CHECK. Predicted XI until line-ups: re-run after.
- Each Bet365 line now also keeps the other bookmakers' prices from the same Oddschecker reply
  (`mkt_n`, `mkt_median`, `mkt_best`). b365value.py shows Bet365 against that median and tags
  BOTH where the model is ahead (15% or less) and Bet365 is at least the market median.
  `bet365_prices.py --force` refetches held games before their usual refresh.
- Backups: `bet365_prices.py.bak-window`, `bet365_prices.py.bak-market`.

## Picks priced at the books, Bet365 team lines (23 Oct 2026)

* **Every pick is priced at a book.** The best bet already was; the banker, evens double and acca now are too (`weekend._book_ok`, `_price`). A leg counts when Paddy Power or Bet365 offers it at our fair price or longer, and no more than 30% over it. Bands and targets (banker 1.30 to 1.75, double near evens, acca 3.0) are read off the book price. Only when nothing priced qualifies does a pick fall back to fair prices, and the card says "fair, not priced". Each leg on the front page shows its book (PP or B365) and price, with fair beside it. Publish prints the banker, double and acca under the pick of the week.
* **Paddy Power fetches Bet365's games first** (`paddypower_prices.candidates`). Soonest-first spent the 23 Oct afternoon run on Brazil, the NBA and Friday night while nine of ten Premier League and Clasico games had no Paddy Power price. Caps unchanged.
* **Bet365 team lines** (`bet365_prices.TEAM_MARKETS`): home, away and match corners, cards and goals from the same Oddschecker pages, in Paddy Power's team-line shape (`team`, `ppHome`), so `attach_books` and `markets.json` read them alike. Bet365 prices only its main line on corners and cards (e.g. home corners 6.5, total 9.5, home cards 1.5, total 3.5) and a full ladder on team goals. Team shots and shots on target are requested too, but on the 23 Oct sample Oddschecker had other books and no Bet365 price for them; they are kept whenever Bet365 appears. 22 markets a game in batches of 10, so three requests per game; the daily cap is 150.
* `python bet365_prices.py --markets` lists every market name on the saved pages (no requests); `--markets "Total Corners" ...` fetches one upcoming game's bets for those names (one request).

## Pinnacle (`pinnacle_prices.py`, 23 Oct 2026)

Pinnacle's prices as margin-free chances, from the guest API its own site uses (`guest.api.arcadia.pinnacle.com/0.1`, logged out, the site's public key in `cache/pinnacle_key.json`, which is git-ignored). Two requests a league plus one for the league list: `/leagues/{id}/matchups` and `/leagues/{id}/markets/straight`. Corners and bookings come back in the same calls as their own matchups (units `Corners` / `Bookings`) hanging off the game by `parentId`, so no per-game calls. 11 leagues, 78 games, 28 requests on the first run. Each league at most every 90 minutes, 150 a day, a day's lockout on any refusal, `touch .pinnacle_off` to stop. Run by publish.sh after Bet365. Writes `reports/pinnacle.json` keyed by the site's fixture id: result, goals (match and team), corners and bookings, each with price and fair chance `p`.

* `--probe` (Premier League only, prints what came back), `--leagues`, `--status`.
* Not yet read by sharp.py or the picks; first comparison (23 Oct): 409 Paddy Power and Bet365 team lines matched to Pinnacle. Corners compare like for like. Cards are not settled yet: Pinnacle's "Bookings" may count a red differently from the soft books' card markets, so treat card edges against Pinnacle as unconfirmed until checked against settled games.

## Game state tab on NBA and NFL reports (25 Oct 2026)
- gamestate_live.py now writes NBA and NFL games into reports/gamestate.json too (the same How the
  game will go as the tonight page, plus the backtest note), and report.py's Game state tab loads it
  for basketball and american-football as well as football. Display only, as before.
- Backups: report.py.bak-usgamestate, gamestate_live.py.bak-us.

## Learning from results (added 26 Oct 2026)

Everything below only changes once it has beaten the current version on the newest games it was not fitted on. Full write-up in `LEARNING.md`.

**`learn.py` (every publish, after `pplog.py settle`).** Refits a correction for each sport × side (over/under), and each stat inside it, from every settled Paddy line in `pplog`: the corrected chance is a recency-weighted blend of the model's chance and Paddy's margin-free price, pulled toward "no change". It is fitted on the older 70% of games and adopted only if it beats the raw model on the newest 30% in at least 80% of resamples. Results go to `learn/learned.json` and `LEARNING.md`. `pplog.py` logs the corrected chance as `learned_chance` on every new snapshot; `b365value.py` uses it for football when one is adopted. `python learn.py report` prints the table.

**`learned_value` rule (`ruletrack.py`).** Any Paddy line where the corrected chance is 3 to 15% above Paddy's price, at 3.0 or shorter. Tracked live from 26 Oct 12:00 alongside the other rules in `RULES_TRACK.md`.

**`usmodel_weekly.py` (Mondays, from `update.py`).** The NBA/NFL equivalent of the football weekly step: 40 small Poisson trees on top of the current model, recency-weighted, scored on the latest 21 days, adopted only if no worse, halved if they move numbers by more than 3%. Adopted steps are saved in `usmodel/delta/` and listed in `usmodel/{nba,nfl}_meta.json` under `deltas`; `usmodel_live.py` applies them in order. Log in `usmodel/CHANGELOG.md`. Run by hand with `python usmodel_weekly.py nba points rebounds` (a sport, then optional targets). **Needs lightgbm in the venv:** `.venv/bin/pip install lightgbm` (the football weekly needs it too). To undo a week, remove its file name from `deltas` in the meta.

**Other fixes the same day.** `b365value.py` only shrinks the model chance on prices of 2.0 and longer (it was wrongly shrinking short-priced lines). `sofascore_api.py` restarts the FlareSolverr container (opening Docker Desktop first if needed) when it stops answering mid-run, instead of stopping the run; `update.py` already did this at the start of a run.

## Best selections (added 26 Oct 2026)

`selections.py` builds the short list at the top of the Tonight page: NBA and NFL player lines at Paddy Power priced 1.60 to 2.30, where the model's chance beats the price by 3%+ and the player has cleared that line in 7+ of his last 10 and 3+ of his last 5. One per player, two per game, eight a day per sport. Every publish logs the list before kick-off (`selections/log.jsonl`) and settles earlier ones; `python selections.py` prints tonight's list, `python selections.py report` the live record. How it was tested: `research/SELECTIONS_RESEARCH.md`.

Each selection also carries team news (`selections.annotate`): if he is questionable, and any key team-mate (usual Paddy points line 10+ in the NBA, 30+ yards in the NFL) ruled out in the last 48 hours on ESPN's report, with a red warning when that works against an under. `python selections.py` re-reads ESPN if the copy is over 20 minutes old, so run it just before betting.

Signals research (`research/signals.py`, write-up `research/SIGNALS.md`): every extra piece of data is tested on Paddy's real prices and on the long back-test, and only kept if it helps in both. So far that added one rule to the selections: no under when the player's side is missing regulars (the model's `miss_key`, now passed through `reports/usmodel.json` as `ctx`), no over when fewer than usual are missing. Re-run it as the real-price record grows: `python research/signals.py > research/SIGNALS.md`.

Football was tested for the same missing-regulars effect on 26 Oct (`research/FOOTBALL_MISSING_RESEARCH.md`) and left out: no gain in the player model (it is scored from the confirmed XI, which already carries it) and gains too small to matter in the team model. Bet football player lines on confirmed line-ups only, as b365value already flags.

## Real slips (added 27 Oct 2026)

`slips.py` keeps every bet Zac actually placed (book, stake, price, return, each leg with the price taken and how it settled) in `slips/slips.jsonl`. `python slips.py report` gives profit by book and bet shape, and each leg's hit rate against the price it needed, split by the player's last-10 record at that line (from pplog) and price band. Slips are entered from screenshots: `python slips.py add file.json` (format in the file's docstring).

## Automatic price refresh and selection alerts (added 27 Oct 2026)

`lineups_auto.py` (launchd, every 15 minutes) now also refreshes prices: between 11:00 and 23:00, every 2 hours, if Paddy Power has games to fetch and is not locked out, it runs `publish.sh` (next 15 games' Paddy lines, pplog, best selections logged and settled, tonight.html, site pushed). Any best selection not announced before triggers a Mac notification ("3 new best selections: ..."), including after the morning build. Settings at the top of the prices section: `PRICE_EVERY`, `PRICE_HOURS`. Log lines go to `lineups_auto.log`.
