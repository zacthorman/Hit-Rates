# Super Sub on every market it covers

Written 2 November 2026 on the `supersub-all-markets` branch. Code: `supersub.py`, `pplog.py`, `paddypower_prices.py`, `markets_sidecar.py` and the page's `superSub()` in `report.py`. Tests: `tests/test_supersub.py`, `tests/test_paddypower_supersub.py`.

## What changed

Until now Super Sub was priced and settled on anytime goalscorer only, and in every competition. Paddy Power's terms, read off its own event page (Chelsea v Man Utd, 31 Oct), cover far more, and fewer competitions:

| Market | Lines covered |
|---|---|
| Shots | 1+ to 6+ |
| Shots on target | 1+ to 4+ |
| Fouls, Fouled | 1+ to 3+ |
| Goals | 1+ to 3+ |
| Assists, to be carded | 1+ |

Competitions: Premier League, Championship, League One, League Two, FA Cup (round 3 on), EFL Cup, Champions League and Europa League (league phase on), Community Shield, UEFA Super Cup, Irish Premier Division. **Not** LaLiga, Serie A, the Bundesliga, Ligue 1, MLS or the Brasileirão. Tackles are not covered anywhere.

On 2+ and 3+ lines the starter's own count before he goes off carries over, and his replacement (and anyone who replaces the replacement) only needs the rest.

1. **Which games.** `paddypower_prices.super_sub()` reads the game page's promotion cards: True when the Super Sub promotion is attached, False when other promotions are and it is not, None when the page lists none. Stored per game as `superSub` in `reports/paddypower.json`, passed to the page as `pp.ss` in `markets.json`, and kept on every football pplog row as `ss_ok`. When it is None the competition decides (`supersub.COMPETITIONS`).
2. **Pricing.** For k or more of a stat:

       extra = share x s x [P(Poisson(a + b) >= k) - P(Poisson(a) >= k)]

   - `share`: starts in his last 10 appearances. Super Sub covers starters only, and lines are priced before the line-ups.
   - `s`: his starts that ended before 85 minutes.
   - `a`: his own expected count in the minutes he plays when taken off. His rate is backed out of our chance over his expected minutes, so the extra always agrees with the price it is added to. His raw record would not: Nico Gonzalez had no shots in five starts against a model that gave him 53%, and the extra came out at +32 points.
   - `b`: the replacement's expected count in the minutes left, at the per-90 rate measured for replacements of his position (`supersub_fit.json` "rates").
   - His substitution minute needs 3 early-ending starts and is held to 45 to 84.
   - Anytime goalscorer 1+ keeps the original formula, which was checked out of sample (`SUPERSUB-CHECK.md`).
3. **Settling.** A lost line in a covered game is regraded a win when his own count plus his replacement chain's clears it. Goals and cards come from the incidents, the rest from the line-ups.
4. **The old goalscorer check looked at the market name only**, so it credited Super Sub wins in LaLiga, Serie A and elsewhere. It now checks the game too.

## Replacement rates (per 90, over the minutes the replacement played)

| Replacing | Shots | On target | Fouls | Fouled | Goals | Assists | Card | Starter off at |
|---|---|---|---|---|---|---|---|---|
| D | 1.08 | 0.33 | 1.37 | 1.07 | 0.08 | 0.09 | 0.30 | 64 min |
| M | 2.01 | 0.71 | 1.66 | 1.50 | 0.21 | 0.16 | 0.31 | 67 min |
| F | 2.68 | 1.05 | 1.81 | 1.59 | 0.34 | 0.16 | 0.29 | 67 min |

Counted stats: 50,806 substitution pairs in the backtest cache's 7,949 matches. Cards: the live cache's incidents, 2,952 matches (the backtest cache keeps no incidents). The forwards' goal rate gives about 8.3% for a replacement to score in 23 minutes, against the 8.0% the original goalscorer fit measured.

## What it is worth

**On the record.** `python supersub.py audit` on the pplog as of 2 Nov 2026 (read only, cached data):

- 10,717 eligible losses checked (127 with no cached incidents).
- **366 were Super Sub wins graded lost.** The biggest groups: 53 on 2+ shots, 43 on 2+ fouls, 40 each on 3+ shots and 1+ fouled, 39 on 1+ fouls.
- **28 goalscorer wins had been credited to Super Sub outside its competitions.**

`python supersub.py resettle --apply` regrades both.

**On prices.** Lines in covered games, 2 Nov, the average extra on top of our own chance:

| Line | Extra |
|---|---|
| Shots 1+ / 2+ / 3+ | +3.6 / +3.6 / +2.7 pts |
| Fouls 1+ / 2+ | +4.3 / +3.8 pts |
| Fouled 1+ / 2+ | +3.9 / +3.3 pts |
| Shots on target 1+ | +3.0 pts |
| Goals 1+ | +1.6 pts |
| Card | +1.7 pts |

The largest single extra was +17.5 points, for a midfielder taken off in 60% of his starts at about 56 minutes.

**What it does not do: make these markets profitable on its own.** On starters in covered competitions, credited with Super Sub, at the first price logged, every line still lost:

| Market | ROI |
|---|---|
| 1+ shots | -8.9% |
| 2+ shots | -26.9% |
| 1+ fouls | -11.4% |
| 1+ fouled | -13.2% |
| 1+ shots on target | -28.0% |

Paddy Power's single-sided player props carry a large margin. Super Sub closes about 6 to 15 points of it, more on 2+ lines than 1+.

## 2+ on one player against 1+ on several

Same player, same game, starters, Super Sub credited where it applies, first price:

| Market, 2+ line priced 1.6 to 2.4 | Double of two 1+ legs | 2+ single |
|---|---|---|
| Shots (547) | -42.0% at about 1.74 | -50.9% at about 2.01 |
| Fouls (1,166) | -30.0% at about 1.59 | -37.2% at about 2.01 |
| Fouled (638) | -32.3% at about 1.65 | -45.3% at about 1.99 |

At a matched price (a treble of 1+ legs lands near 2.3), the 2+ single and the multi of 1+ legs come out about level. The record does not show 2+ as better value than spreading 1+ over several players. It shows both losing roughly the same margin.

Two cautions:

- These are every line Paddy Power offered, not our model's picks.
- The multi figure assumes the legs are independent, which holds for different players in different games.

## Bet365's Sub On Play On (added 2 Nov 2026, later the same day)

Bet365 runs the same idea under its own name. `supersub.py` now keeps a rule set per book (`BOOKS`):

| | Paddy Power Super Sub | Bet365 Sub On Play On |
|---|---|---|
| Markets | shots 1-6+, on target 1-4+, fouls and fouled 1-3+, goals 1-3+, assists, cards | the same plus tackles, every line Bet365 offers (shots to 11+, fouls to 8+, fouled to 7+, tackles to 8+, on target to 6+), assists 1-2+ |
| Competitions | English leagues and cups, Champions and Europa League, a few others | Premier League, Champions League, Europa League, LaLiga, Bundesliga, Ligue 1, Serie A |
| Which games | the game page says (`superSub`), else the list | the list only: Oddschecker does not pass Bet365's icon through |

Bet365's own terms page would not load, so its competitions are the ones betting sites list for it. Only games showing its icon qualify: check the slip before staking.

**Replacement tackles rate.** Per 90, by the position of the starter replaced: D 2.00, M 1.90, F 1.38. From the same 50,806 pairs as the rest.

**Where it applies:**
- the page's Bet365 lines;
- `b365value.py`;
- `value_books.py`, where each book's chance now includes its own cover before the better book is chosen, and settling credits it;
- `b365log.py`, a new settled record of every Bet365 line, built on pplog.py and kept in `b365log/`.

**Lines no record has tested.** Bet365 offers lines Paddy Power never did (to 11+ shots, 8+ fouls) and tackles, where the site's fallback pricing runs far too high. It made Kane 41% for 7+ shots off 1 in his last 10, and Osimhen 43% for 9+ at 17.0. The Bet365 log marks those rows `untested`, still logs and settles them, and never calls them value (`pplog._untested`). `value_books.py` and `b365value.py` only price lines the player model covers, so they were not affected.

**Dry run on 2 Nov:**
- 9,420 Bet365 lines would be logged.
- 6,403 of them are covered by Sub On Play On. The extra is about +4 pts on 1+ shots, fouls and tackles, and +3.5 on 2+.
- 1,621 are untested.
- 181 qualify as value. Some carry very large claimed edges (+100% and more), the same overconfidence seen on Paddy Power, where 15%+ edges lost 52%.

Sky Bet also runs a Super Sub; it is not modelled yet.
