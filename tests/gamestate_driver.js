/* Driver for test_gamestate.py. Run by the test, never by hand.

   The test writes one file: a line reading ALL from process.argv[2], then the
   page's own declarations lifted out of report.py's rendered <script>, then
   this file. Everything below only calls the page's functions and arranges
   what they return into gamestate.py's JSON shape. No number is worked out
   here: if the page changes, the page's answer changes with it. */

const PAGE_ROWS = 6, PAGE_AGAINST = 5, PAGE_PAIRS = 5;
const PROJECTED = [["shots", "Total shots"], ["on_target", "Shots on target"],
                   ["goals", "Goals"], ["fouls", "Fouls"], ["tackles", "Tackles"]];

function strip(html) {
  return html.replace(/<[^>]*>/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/\s+/g, " ").trim();
}

// gamestate.py's choice of matchup arguments, made with the page's helpers.
function matchupFor(t, name, stat, L) {
  const recs = luRecords(t, name);
  const pos = recs.length ? (recs[recs.length - 1].position || "") : "";
  const window = ((DATA.records || [])[1 - t] || []).slice(-10);
  const m = matchupProfile(DATA, 1 - t, pos, stat, L - 0.5, window, "gamestate|10");
  return { pos, matchup: m && {
    against: m.posName, mode: m.mode, stat: m.stat, n: m.n, hits: m.hits,
    matches: m.matches, share: m.share, rate: m.per90, unit: m.unit,
    covered: m.covered, window: m.windowMatches, thin: m.thin } };
}

function factorOf(x) {
  return { avg: x.avg, adjusted_avg: x.mu, factor: x.g.f, factor_fitted: x.g.mf,
           factor_ball: x.g.pf, team_usual: x.g.usual, team_projected: x.g.projTeam };
}

const out = [];
ALL.fixtures.forEach((fx, i) => {
  if (((fx.fixture || {}).sport || "football") !== "football") return;
  DATA = ALL.fixtures[i];
  const st = gsState();
  const squads = gsSquads();
  const hasBall = !!(st.teams[0].poss && st.teams[1].poss);

  const projected = {};
  PROJECTED.forEach(([k, stat]) => { if (st.proj[stat]) projected[k] = [st.proj[stat][0], st.proj[stat][1]]; });
  const script = strip((gsCardHtml().match(/<p class="gs-script">([\s\S]*?)<\/p>/) || ["", ""])[1]);

  const markets = {};
  Object.values(GS_MARKETS).flat().forEach(([stat, lines]) => {
    const { out: rows, against } = gsRows(stat, lines);
    markets[stat] = {
      lines: rows.map((x, j) => {
        const mu = matchupFor(x.t, x.name, stat, x.best.L);
        return { player: x.name, side: x.t, team: DATA.teams[x.t].name, position: mu.pos,
                 line: x.best.L, k: x.best.k, n: x.best.n, chance: x.best.p, record: x.best.rec,
                 ...factorOf(x), on_page: j < PAGE_ROWS, matchup: mu.matchup };
      }),
      works_against: against.map((x, j) => {
        const mu = matchupFor(x.t, x.name, stat, x.L);
        return { player: x.name, side: x.t, team: DATA.teams[x.t].name, position: mu.pos,
                 line: x.L, k: x.k, n: x.n, chance: x.p,
                 ...factorOf(x), on_page: j < PAGE_AGAINST, matchup: mu.matchup };
      }),
    };
  });

  // What lineupView hands luPairs: the confirmed XI if there is one, else
  // the predicted, and no pairs at all without a line-up.
  const store = DATA.lineups || {};
  let pairs = null;
  const lu = store.confirmed || store.predicted;
  if (lu) {
    const shapes = [luShape(lu.home), luShape(lu.away)];
    pairs = luPairs(shapes).filter(x => x.score >= 0.6).map((x, j) => {
      const a = luRate(luRecords(x.t, x.p), "Fouled", 1);
      const b = luRate(luRecords(1 - x.t, x.o), "Fouls", 1);
      return { score: x.score, side: x.t, player: x.p, opponent: x.o,
               player_fouled: { k: a.k, n: a.n, p: a.p, avg: a.avg },
               opponent_fouls: { k: b.k, n: b.n, p: b.p, avg: b.avg },
               on_page: j < PAGE_PAIRS };
    });
  }

  out.push({
    event: DATA.fixture.id,
    xi_label: squads.source,
    squads: squads.sides,
    card: {
      teams: [0, 1].map(t => ({ name: DATA.teams[t].name, tier: st.tiers[t], n: st.teams[t].n,
                               possession: st.teams[t].poss, xg: st.teams[t].xg, xga: st.teams[t].xga })),
      possession: hasBall ? st.poss : null,
      projected,
      script,
    },
    markets,
    foul_pairs: pairs,
  });
});
process.stdout.write(JSON.stringify(out));
