# Bookie imports

Two additions to how the site reads bookmaker prices:

1. **Oddschecker drop-a-file import** (`oddschecker_import.py`). Save an Oddschecker page into a folder and the player profiles show the best price on offer next to the fair price.
2. **Paddy Power Super Sub** (`supersub.py`). Paddy Power's anytime goalscorer bets now count Super Sub, both when pricing them and when settling them.

Neither one makes a request to any website.

## 1. Oddschecker: best price per line

### How to use it

1. Open the Oddschecker page for one market in one game, in your own browser. For example, Anytime Goalscorer for Arsenal v Chelsea, or Player Shots On Target.
2. Save it into `drop/oddschecker/` in the repo folder. You can do this in either of two ways:
   - **File > Save Page As**, "Webpage, HTML only" (a `.html` file). The page keeps its own address, so the game and the market are read from that, and the file can have any name.
   - **Copy and paste** the odds table into a `.txt` file. The game and market then come from the file name, so name it like the page address ends: `arsenal-v-chelsea-anytime-goalscorer.txt` or `arsenal-v-chelsea-player-shots.txt`.
3. Check what it read: `python oddschecker_import.py --check drop/oddschecker/<file>`. This writes nothing.
4. Run `publish.sh` as usual. It runs `oddschecker_import.py` straight after the Bet365 fetch.

To see what is held, run `python oddschecker_import.py --status`.

### What it does

- It reads every file in `drop/oddschecker/`. For each player and line it keeps the best bookmaker price, matches the game to the site's fixture by team names (games not yet started, within 7 days), and writes `reports/oddschecker.json`.
- `markets_sidecar.py` merges that into `reports/markets.json` as `oc`. On a player profile each priced line gets a **Best** column next to Fair, showing the price and the bookmaker's code. Hover over it to see the bookmaker's name, how many bookmakers priced the line, the edge against our chance, and how old the saved page is.
- Best is shown only. It does not change the Take / Acceptable / Avoid verdict, which still uses your typed price, then Bet365, then Paddy Power, then Betfair.
- Markets read: anytime goalscorer, player shots, shots on target, fouls, fouled, tackles, assists and to be carded. These are the lines the site already prices (`MARKETS` in the script). Anything else is skipped.
- If the best to-score price is Paddy Power's, the hover text gives our chance with Super Sub (see below).

### Things to know

- **Optional.** If the folder is missing or empty, nothing changes on the pages. A file it cannot read is named in the run output and skipped. It never stops `publish.sh`.
- **Your files are never moved or deleted.** A file for a game that has started is ignored, so clear old ones out whenever you like. If two files cover the same market for the same game, the newer file wins.
- **Copied text cannot say which bookmaker.** The bookmaker logos do not copy, so a pasted table gives the best price with "bookmaker not known". A saved `.html` page does carry the bookmaker.
- **Exchanges are left out** (Betfair Exchange and similar). Their prices are before commission, so they are not a bookmaker's price.
- **Line markets need a count on each row**, either `2+` or `Over 1.5`. A row with only one price after the name is skipped, because a lone number is usually a shirt number.
- **Not yet tried on a real saved page.** The readers follow Oddschecker's known odds-table layout (`data-bname` rows, `data-bk` and `data-odig` cells), the JSON shape its all-odds feed returns, and plain copied text. They are tested on made-up files in `tests/fixtures/oddschecker/`. Run `--check` on the first real file you save. If it reads nothing, or the bookmaker codes look wrong, that is the place to fix (`BOOKS` and `EXCHANGES` in the script).

## 2. Paddy Power Super Sub

### The concession

A pre-match Paddy Power anytime goalscorer bet on a player who **starts** and is **substituted** moves to the player who replaces him. The bet wins if the starter scores before he goes off, or if the replacement scores after he comes on. It does not apply to a player who starts on the bench. Check Paddy Power's current terms for which markets it covers. Here it is applied to anytime goalscorer only (`APPLIES` in `supersub.py`), because that is the only goalscorer market the site prices. It is not applied to shots, cards or any other player line.

### What was wrong

- **Pricing.** `pplog.py` and the profile pages priced a Paddy Power to-score line on the player alone, over his expected minutes. That is the right chance for an ordinary bookmaker. It is too low for Paddy Power, which also pays out on the replacement, so every Paddy Power to-score edge was understated. Forwards who are often taken off were understated most.
- **Settling.** `pplog.py settle` graded the player's own goals. A bet the replacement won was recorded as lost, so the record also understated Paddy Power's to-score lines.

### What changed

- `pplog.py snapshot`: for a Paddy Power anytime goalscorer line, the chance is now **his own chance + (1 − his own chance) × how often he is taken off × how often a replacement for his position scores**. The extra is logged on the snapshot as `supersub`.
- `pplog.py settle`: a lost Paddy Power to-score line is checked against SofaScore's match incidents. If he started, was substituted, and the man who came on for him scored (own goals do not count), the line is graded a win and the replacement's name is recorded as `supersub`.
- The page: Paddy Power to-score rows on a profile use the same chance, and the row's note reads "Super Sub +x pts".
- To-score is still on the `UNCALIBRATED` list in `pplog.py`. A Paddy Power to-score line is still never counted as a value bet unless the backtested model priced it. Super Sub makes the chance more accurate. It does not lift that gate.

### The evidence

"How often he is taken off" is the share of his own starts that ended before 85 minutes, once he has five starts on file. "How often a replacement scores" is measured by `python supersub.py fit` on the line-ups in `cache_backtest.tar.zst`: 6,765 football matches. The results are saved in `supersub_fit.json`.

| Starter's position | Starts | Scored himself | Taken off | Replacement scored (when he went off without scoring) | Extra wins from Super Sub, per start |
|---|---:|---:|---:|---:|---:|
| Forward | 25,110 | 24.0% | 56.8% | 8.0% | 3.64% |
| Midfielder | 58,892 | 10.2% | 45.4% | 5.2% | 2.16% |
| Defender | 51,197 | 4.0% | 19.2% | 2.4% | 0.44% |
| Goalkeeper | 13,517 | 0.0% | 1.2% | 0.0% | 0.00% |

The formula was also checked out of sample. The replacement rates were fitted on the first 70% of matches by date. Each starter's chance of being taken off came only from his earlier starts. The remaining 30% of matches were then scored, counting starters who did not score themselves:

| Predicted Super Sub win | Starters | Predicted | Actually paid |
|---|---:|---:|---:|
| under 2% | 21,677 | 0.61% | 0.73% |
| 2 to 4% | 6,943 | 2.91% | 2.98% |
| 4 to 6% | 2,847 | 4.76% | 4.88% |
| 6% and over | 904 | 6.87% | 8.19% |

It is close, and slightly low at the top. The likely reason is the pairing (next paragraph), so the adjustment errs on the cautious side.

What this means for a typical forward who scores 30% of the time on his own and is taken off in 60% of his starts: 0.30 + 0.70 × 0.60 × 0.080 = 33.4%. At Paddy Power's 3.50 that is an edge of +17%, not +5%. For a centre-back it hardly matters.

**Limits of the evidence**

- **Pairing in the fit.** The cached line-ups do not record who replaced whom, so `fit` pairs them by time: the first starter off goes with the substitute who played longest. A red card can mis-pair. Settling does not use this pairing. It uses the real substitution incidents.
- **The Paddy Power record is not in the repo.** `pplog/` stays on Zac's machine, so it could not be checked from here. The committed `pp-results.html` shows 3,904 settled lines. Only one of them is a to-score value bet: Tresoldi, Club Brugge v Lens on 21 October, lost. To see how many past to-score losses were really Super Sub wins, run this on the machine that holds `pplog/`:

      python supersub.py audit

  It reads `pplog/` and the cached incidents, prints each loss that Super Sub would have won and the hit rate both ways, and changes nothing. Settled rows are never rewritten. Only lines settled from now on use Super Sub.
- **Refreshing the fit.** To refit on a fuller cache, run `python supersub.py fit cache` (or any folder of SofaScore `event_*_lineups.json` files). If the figures move, update `DEFAULT_REP` in `supersub.py` and `SUPER_SUB_REP` in `report.py` to match. A test checks that the first agrees with `supersub_fit.json`.

## Files

| File | What it is |
|---|---|
| `oddschecker_import.py` | Reads `drop/oddschecker/` and writes `reports/oddschecker.json` |
| `supersub.py` | Super Sub chance, settling check, `fit` and `audit` |
| `supersub_fit.json` | The fit above |
| `markets_sidecar.py` | Now also merges `oc` (best price and bookmaker) |
| `pplog.py` | Super Sub in snapshot and settle |
| `report.py` | Best column on profiles; Super Sub on Paddy Power to-score rows |
| `publish.sh` | Runs `oddschecker_import.py` after `bet365_prices.py` |
| `tests/test_oddschecker_import.py`, `tests/test_supersub.py` | Unit tests on made-up fixtures |

`drop/` is gitignored, so saved pages are never committed.
