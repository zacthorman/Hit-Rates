---
type: research
project: football-stats
status: active
date: 2026-11-03
tags: [project/football-stats, type/research]
---

# Confluence: only bet where the evidence stacks up

Written 3 November 2026. Code: `confluence.py`. Tests: `tests/test_confluence.py`.
Shown on the Tonight page, top of the Picks tab.

## The idea

No single number decides a bet. Every independent source the site has gets a
vote, and a source votes yes when its own chance for the line is above the
chance the price implies. A line is only put forward when enough of them agree.

| Player lines | Team lines |
|---|---|
| Player model's chance | Team-stats projection (Poisson on the expected count) |
| Hit-rate model's chance | Team model's chance |
| Learned correction | Last 10 cleared the line |
| Last 10 and last 5, shrunk towards the price | Last 5 |
| Opponent adjustment (matchup) | |
| In the confirmed XI | |
| Betfair or Pinnacle fair chance, beats the lay, sharp price moving our way | the same |

## What the record said (20 Oct to 3 Nov, prices up to 6.0, level stakes)

**More agreement is better, in every sport, in both halves of the record.**

| Sources agreeing | Football players | NBA players | NFL players |
|---|---|---|---|
| any | -44% (38,930) | -10% (26,486) | -10% (7,733) |
| 2+ | -35% | -9% | -9% |
| 3+ | -32% | -7% | -8% |
| 4+ | -24% (738) | 0% (2,625) | -5% |
| 5+ | -13% (69) | +7% (489) | +1% (346) |

Football player props lose even with strong agreement: Paddy Power's margin on
them is too wide. NFL improved in the first week and not the second.

**The sharp price is a veto.** Where Betfair or Pinnacle disagree with us,
stacking our own sources still lost 13%. Where they agree, adding two or more
of ours took the return from +6% to +13%.

**Counting beats weighting, for now.** A logistic fit on the first week,
tested on the second, did no better than a plain count for football and NBA,
and much worse for the NFL. Two weeks is too little to fit weights.

## The rules, frozen 3 Nov 2026

* **Strong:** Betfair or Pinnacle agree, and 2+ other sources do too.
  Backtest: 116 bets over 82 games, one per player or side per game, at the
  last price before kick-off: **+20%** (90% range -2% to +42%). First half
  +39%, second half +15%. Almost all team lines: corners, cards, goals.
* **On trial** (no sharp price): NBA player lines with 5+ sources agreeing,
  team lines with 4+. Backtest: 282 bets over 86 games: **+9%** (90% range
  -3% to +21%). First half +2%, second half +12%.
* **Never:** a line the sharp price disagrees with, and football player lines
  on agreement alone.

The thresholds were picked after looking at the data, so the backtest
flatters them. The live record starts on 4 November and is shown first on the
page. Judge the rules on that, in weeks, not nights.

## Next

* After 200+ live bets in a tier, fit weights on the live record and compare.
* Add game state (gamestate.json) as a source once its leans are logged with
  each line, so it can be backtested the same way.
