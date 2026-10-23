"""
Render a fixture's hit-rate data as a single self-contained HTML file.

Everything is inlined, so the file works offline, opens anywhere, and can be
emailed. The match data is embedded as JSON and the filtering happens in the
browser, so switching fixture, period, venue or sample size is instant.

Layout is head to head: each stat is one row with the two teams facing each
other around the stat name, so the comparison you actually care about is a
single glance rather than a scan across two distant columns. On a narrow
screen the same row stacks into a card.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import hitrates
import markets
import model
import parlay

CSS = """
:root {
  color-scheme: light;
  --surface-1: #fcfcfb;
  --page: #f9f9f7;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --muted: #898781;
  --grid: #e1e0d9;
  --baseline: #c3c2b7;
  --border: rgba(11,11,11,0.10);
  --tint: rgba(11,11,11,0.035);
  --track: #e8e7e1;
  --team-1: #2a78d6;
  --team-2: #eb6834;
  --control-bg: #ffffff;
  --control-active: #0b0b0b;
  --control-active-text: #ffffff;
  /* Status pair, fixed in both modes. Both clear 3:1 on either surface. */
  --hit: #0ca30c;
  --miss: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface-1: #1a1a19;
    --page: #0d0d0d;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --muted: #898781;
    --grid: #2c2c2a;
    --baseline: #383835;
    --border: rgba(255,255,255,0.10);
    --tint: rgba(255,255,255,0.045);
    --track: #2c2c2a;
    --team-1: #3987e5;
    --team-2: #d95926;
    --control-bg: #222220;
    --control-active: #ffffff;
    --control-active-text: #0b0b0b;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-1: #1a1a19;
  --page: #0d0d0d;
  --text-primary: #ffffff;
  --text-secondary: #c3c2b7;
  --muted: #898781;
  --grid: #2c2c2a;
  --baseline: #383835;
  --border: rgba(255,255,255,0.10);
  --tint: rgba(255,255,255,0.045);
  --track: #2c2c2a;
  --team-1: #3987e5;
  --team-2: #d95926;
  --control-bg: #222220;
  --control-active: #ffffff;
  --control-active-text: #0b0b0b;
}

* { box-sizing: border-box; }

/* The hidden attribute must always win. Without this, any element that also
   has an author display rule (a .control-group is display:flex) ignores
   hidden entirely: the Opposition group showed on reports with no tier data
   behind it, which is a filter that acts on nothing. */
[hidden] { display: none !important; }

body {
  margin: 0;
  padding: 28px 18px 72px;
  background: var(--page);
  color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 15px;
  line-height: 1.5;
  -webkit-text-size-adjust: 100%;
}

.wrap { max-width: 1180px; margin: 0 auto; }

/* ------------------------------------------------------------- header */

header { margin-bottom: 18px; }

.competition {
  font-size: 12px; letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--muted); margin-bottom: 6px;
}
h1 { font-size: 30px; font-weight: 680; margin: 0 0 5px; letter-spacing: -0.015em; }
.kickoff { color: var(--text-secondary); font-size: 14px; }
.referee { color: var(--text-secondary); font-size: 13px; margin-top: 2px; }
/* Sticky, not just placed at the top. A report runs to thousands of rows, so
   a back link that scrolls away is a back link you do not have. On a phone
   that meant reaching for the browser's own back button every time.

   It sits as a direct child of .wrap rather than inside <header>, because a
   sticky element only sticks while its own parent is still on screen. Inside
   the header it unstuck the instant the title scrolled past, which looked
   exactly like sticky not working at all. */
.back-bar {
  position: sticky; top: 0; z-index: 20;
  background: var(--page); padding: 10px 0 10px;
  margin: -10px 0 12px;
}
.back {
  display: inline-flex; align-items: center; gap: 7px;
  color: var(--text-primary); text-decoration: none;
  font-size: 15px; font-weight: 640;
  border: 1px solid var(--border); background: var(--surface-1);
  border-radius: 9px; padding: 9px 15px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.07);
}
.back:hover { background: var(--tint); }
.back:active { transform: translateY(1px); }

/* ----------------------------------------------------------- controls */

.controls {
  display: flex; flex-wrap: wrap; gap: 14px 22px; align-items: center;
  padding: 13px 16px; margin-bottom: 8px;
  background: var(--surface-1);
  border: 1px solid var(--border); border-radius: 12px;
}
.controls + .controls { margin-bottom: 20px; }

/* min-width and wrapping matter more than they look. A flex item will not
   shrink below its own content, so the fixture picker, sized to its longest
   team name, held this bar at 503px and pushed 142px of every panel off the
   side of a 390px phone. One dropdown made the whole site scroll sideways. */
.control-group { display: flex; align-items: center; gap: 8px;
                 min-width: 0; flex-wrap: wrap; }

.control-label {
  font-size: 11px; letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--muted); white-space: nowrap;
}

.seg { display: flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.seg button {
  border: 0; background: var(--control-bg); color: var(--text-secondary);
  font: inherit; font-size: 13px; padding: 6px 13px; cursor: pointer;
  white-space: nowrap;
}
.seg button + button { border-left: 1px solid var(--border); }
.seg button:disabled { opacity: 0.4; cursor: not-allowed; }
.seg button[aria-pressed="true"] {
  background: var(--control-active); color: var(--control-active-text); font-weight: 620;
}

.legend { display: flex; gap: 18px; margin-left: auto; align-items: center; }
.legend-item {
  display: flex; align-items: center; gap: 7px;
  font-size: 14px; font-weight: 600; color: var(--text-primary);
}
.swatch { width: 12px; height: 12px; border-radius: 3px; flex: none; }

select, .num-input {
  height: 32px; border: 1px solid var(--border);
  background: var(--control-bg); color: var(--text-primary);
  border-radius: 8px; font: inherit; font-size: 14px; padding: 0 8px;
}
select { max-width: 100%; min-width: 0; text-overflow: ellipsis; }

.num-input {
  width: 60px; text-align: center; font-variant-numeric: tabular-nums;
}

/* -------------------------------------------------------------- line-ups */
.lu-head { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 12px; }
.lu-seg button[disabled] { opacity: .4; cursor: not-allowed; }
.lu-badge { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em;
  padding: 2px 8px; border-radius: 99px; border: 1px solid var(--muted); color: var(--muted); }
.lu-badge.lu-conf { border-color: var(--hit); color: var(--hit); }
.lu-muted { color: var(--muted); font-size: 13px; }
.lu-warn { color: var(--miss); }
.lu-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 18px; align-items: start; }
@media (max-width: 820px) { .lu-grid { grid-template-columns: 1fr; } }
.lu-pitch { background: var(--tint); border: 1px solid var(--border); border-radius: 12px; padding: 10px 6px;
  display: flex; flex-direction: column; gap: 8px; }
.lu-row { display: flex; justify-content: space-around; gap: 4px; }
.lu-half { border-top: 1px dashed var(--baseline); margin: 4px 0; }
.lu-chip { display: inline-flex; align-items: center; gap: 4px; max-width: 110px; overflow: hidden;
  white-space: nowrap; text-overflow: ellipsis; font: inherit; font-size: 12.5px; padding: 4px 8px;
  border-radius: 99px; border: 1px solid var(--border); background: var(--control-bg); color: var(--text-primary); cursor: pointer; }
.lu-chip .lu-shirt { font-weight: 700; font-size: 11px; color: #fff; border-radius: 99px; padding: 0 5px; }
.lu-t0 .lu-shirt { background: var(--team-1); }
.lu-t1 .lu-shirt { background: var(--team-2); }
.lu-chip.lu-on { outline: 2px solid var(--text-primary); }
.lu-h { font-size: 15px; margin: 14px 0 6px; }
.lu-table { border-collapse: collapse; width: 100%; font-size: 13.5px; margin: 4px 0 8px; }
.lu-table td, .lu-table th { text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--grid); }
.lu-table th { color: var(--muted); font-weight: 600; font-size: 12px; }
.lu-hi { color: var(--hit); } .lu-lo { color: var(--miss); } .lu-mid { color: var(--text-primary); }
.lu-list { margin: 6px 0; padding-left: 18px; font-size: 13.5px; } .lu-list li { margin: 3px 0; }
.lu-opp { border-top: 1px solid var(--grid); padding-top: 8px; margin-top: 8px; }
.lu-link { font: inherit; font-weight: 600; background: none; border: 0; padding: 0; color: var(--text-primary);
  text-decoration: underline; cursor: pointer; }
.lu-card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; }
.lu-who { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; font-size: 15px; }
.lu-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.lu-dot0 { background: var(--team-1); } .lu-dot1 { background: var(--team-2); }
.lu-tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
@media (max-width: 480px) { .lu-tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.lu-tile { background: var(--tint); border-radius: 8px; padding: 7px 9px; }
.lu-tile span { display: block; font-size: 11.5px; color: var(--muted); }
.lu-tile b { display: block; font-size: 18px; line-height: 1.25; font-variant-numeric: tabular-nums; }
.lu-tile small { font-size: 11px; color: var(--muted); }
.lu-vs { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 10px; padding: 7px 0; border-top: 1px solid var(--grid); }
.lu-vs:first-of-type { border-top: 0; }
.lu-vs-side span { display: block; font-size: 12px; color: var(--muted); }
.lu-vs-side b { font-size: 16px; font-variant-numeric: tabular-nums; }
.lu-r { text-align: right; }
.lu-vs-mid { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }
.lu-strong .lu-vs-mid { color: var(--hit); font-weight: 700; }
.lu-bar { display: block; height: 4px; background: var(--track); border-radius: 99px; margin-top: 4px; overflow: hidden; font-style: normal; }
.lu-bar em { display: block; height: 100%; background: var(--team-2); border-radius: 99px; }
.lu-bar-l em { background: var(--team-1); margin-left: auto; }
.lu-strong .lu-bar em { background: var(--hit); }
.lu-more { margin-top: 8px; } .lu-more summary { cursor: pointer; color: var(--muted); font-size: 13px; margin-bottom: 6px; }
.lu-empty { color: var(--muted); font-size: 14px; padding: 18px 4px; }
.lu-best .lu-vs { padding: 8px 0; }
.lu-pitch { background: linear-gradient(180deg, var(--tint), transparent 50%, var(--tint)); }
#lineups { min-width: 0; max-width: 100%; overflow-x: hidden; }
.lu-row > .lu-chip { flex: 0 1 auto; min-width: 0; }
@media (max-width: 520px) {
  .lu-chip { font-size: 11.5px; padding: 3px 6px; max-width: 84px; gap: 3px; }
  .lu-chip .lu-shirt { font-size: 10px; padding: 0 4px; }
  .lu-pitch { padding: 8px 2px; }
}
/* ------------------------------------------------------- defence ranks */
.def-table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
.def-table th, .def-table td { text-align: left; padding: 8px; border-bottom: 1px solid var(--grid); vertical-align: top; }
.def-table th { font-weight: 600; color: var(--text-secondary); font-size: 13px; }
.def-table small { color: var(--muted); }
.def-sub { font-size: 12px; color: var(--muted); margin-top: 2px; }
.def-soft b { color: var(--hit); } .def-tough b { color: var(--miss); }
.def-up { color: var(--hit); font-weight: 600; } .def-down { color: var(--miss); font-weight: 600; }
.def-spot { padding: 6px 0; border-top: 1px solid var(--grid); font-size: 14px; }
.def-spot:first-child { border-top: 0; }
.tablewrap { overflow-x: auto; }
.def-grid { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap: 12px; margin-top: 14px; }
@media (max-width: 760px) { .def-grid { grid-template-columns: 1fr; } }
.def-row { padding: 8px 0; border-top: 1px solid var(--grid); }
.def-row:first-of-type { border-top: 0; }
.def-row-top { display: flex; justify-content: space-between; gap: 8px; font-size: 13.5px; }
.def-row-top span { color: var(--text-secondary); }
.def-row.def-soft .def-row-top b { color: var(--hit); } .def-row.def-tough .def-row-top b { color: var(--miss); }
.def-bar { display: block; height: 5px; background: var(--track); border-radius: 99px; margin: 5px 0 3px; overflow: hidden; }
.def-bar em { display: block; height: 100%; background: var(--muted); border-radius: 99px; }
.def-soft .def-bar em { background: var(--hit); } .def-tough .def-bar em { background: var(--miss); }
.def-pick { padding: 9px 0; border-top: 1px solid var(--grid); }
.gs-card { padding: 14px 16px; }
.gs-teams { display: flex; justify-content: space-between; gap: 12px; }
.gs-side { display: flex; flex-direction: column; gap: 1px; font-size: 15px; min-width: 0; }
.gs-name { display: inline-flex; align-items: center; gap: 7px; }
.gs-r { align-items: flex-end; text-align: right; }
.gs-poss { display: flex; align-items: center; gap: 10px; margin-top: 12px; font-variant-numeric: tabular-nums; }
.gs-bar { flex: 1; height: 10px; border-radius: 99px; background: var(--team-2); overflow: hidden; font-style: normal; }
.gs-bar em { display: block; height: 100%; background: var(--team-1); border-right: 2px solid var(--surface-1); }
.gs-caption { text-align: center; font-size: 11.5px; color: var(--muted); margin-top: 2px; text-transform: uppercase; letter-spacing: .05em; }
.gs-vols { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 6px; margin-top: 12px; }
@media (max-width: 560px) { .gs-vols { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
.gs-vol { background: var(--tint); border-radius: 8px; padding: 6px 8px; text-align: center; }
.gs-vol span { display: block; font-size: 11px; color: var(--muted); }
.gs-vol b { font-size: 14px; font-variant-numeric: tabular-nums; }
.gs-script { margin: 10px 0 0; font-size: 13.5px; color: var(--text-secondary); }
.gs-head { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin: 18px 0 4px; }
.gs-h { margin: 0; }
.gs-p { margin-left: auto; font-weight: 700; font-variant-numeric: tabular-nums; }
.gs-up { color: var(--hit); font-weight: 600; } .gs-down { color: var(--miss); font-weight: 600; }
.gs-missing { margin: 0 0 10px; }
.nfl-qb { display: flex; gap: 10px; align-items: flex-start; border: 1px solid var(--miss); border-left-width: 4px;
          border-radius: 10px; padding: 10px 13px; margin: 0 0 10px; font-size: 14px; line-height: 1.45; }
.nfl-qb .lu-dot { margin-top: 6px; flex: 0 0 auto; }
.nfl-inj { display: flex; gap: 8px; align-items: baseline; font-size: 13.5px; padding: 4px 0; line-height: 1.5; }
.nfl-inj .lu-dot { flex: 0 0 auto; }
.nfl-injcard .lu-who { margin-bottom: 4px; }
.nfl-tag { font-size: 11px; font-weight: 600; border: 1px solid var(--border); border-radius: 5px;
           padding: 0 5px; color: var(--muted); margin-left: 4px; }
.def-pick:first-child { border-top: 0; }
.def-pick-main { display: flex; align-items: center; gap: 8px; font-size: 15px; }
.def-line { font-weight: 700; padding: 1px 8px; border-radius: 99px; border: 1px solid var(--hit); color: var(--hit); font-size: 13px; }
.def-pick-why { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 12.5px; color: var(--muted); margin-top: 4px; padding-left: 17px; }
.def-fade { padding: 7px 0; border-top: 1px solid var(--grid); font-size: 13.5px; display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
.def-fade:first-child { border-top: 0; }
/* --------------------------------------------------------------- tabs */

.tabs { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 16px; }
.tabs button {
  border: 1px solid var(--border); background: var(--control-bg);
  color: var(--text-secondary);
  font: inherit; font-size: 15px; font-weight: 600;
  padding: 9px 20px; border-radius: 9px; cursor: pointer;
}
.tabs button[aria-selected="true"] {
  background: var(--control-active); color: var(--control-active-text);
  border-color: var(--control-active);
}
.panel[hidden] { display: none; }

/* ----------------------------------------------------- head to head */

.board {
  background: var(--surface-1);
  border: 1px solid var(--border); border-radius: 12px; overflow: hidden;
}

.stat-row {
  display: grid;
  grid-template-columns: 1fr 210px 1fr;
  gap: 20px;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--grid);
}
.stat-row:last-child { border-bottom: 0; }
.stat-row.strong { background: var(--tint); }

/* One team at a time: the middle column leads, the single side gets the rest
   of the width, and everything reads left to right like a normal table. */
.stat-row.solo { grid-template-columns: 230px 1fr; }
.stat-row.solo .middle { order: 1; text-align: left; }
.stat-row.solo .stepper { justify-content: flex-start; }
.stat-row.solo .side { order: 2; flex-direction: row; }
.stat-row.solo .side.a .figure { text-align: left; }
.stat-row.solo .side.a .bar { justify-content: flex-start; }

.middle { text-align: center; order: 2; }
.stat-label {
  font-size: 15px; font-weight: 620; margin-bottom: 6px; line-height: 1.25;
}
.stepper { display: flex; align-items: center; justify-content: center; gap: 4px; }
.stepper button {
  width: 28px; height: 28px;
  border: 1px solid var(--border); background: var(--control-bg);
  color: var(--text-secondary); border-radius: 7px;
  font: inherit; font-size: 16px; line-height: 1; cursor: pointer; padding: 0;
}
.stepper button:hover { color: var(--text-primary); }
.stepper input {
  width: 62px; height: 28px;
  border: 1px solid var(--border); background: var(--control-bg);
  color: var(--text-primary); border-radius: 7px;
  font: inherit; font-size: 14px; font-variant-numeric: tabular-nums;
  text-align: center; padding: 0 2px;
}
.stepper input.edited { border-color: var(--text-primary); font-weight: 660; }
.stepper input::-webkit-outer-spin-button,
.stepper input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.stepper input[type=number] { -moz-appearance: textfield; }

.side { display: flex; align-items: center; gap: 14px; min-width: 0; }
.side.a { order: 1; flex-direction: row-reverse; }
.side.b { order: 3; }

.team-tag {
  display: none;
  align-items: center; gap: 7px;
  font-size: 13px; font-weight: 620; color: var(--text-secondary);
}

.figure { flex: none; min-width: 96px; }
.side.a .figure { text-align: right; }

.pct {
  font-size: 24px; font-weight: 700; letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums; line-height: 1.1;
}
.stat-row.strong .pct { font-size: 26px; }
.frac { font-size: 13px; color: var(--muted); font-variant-numeric: tabular-nums; }

.bar { height: 7px; border-radius: 4px; background: var(--track);
       margin-top: 7px; overflow: hidden; display: flex; }
.side.a .bar { justify-content: flex-end; }
.fill { height: 100%; border-radius: 4px; }

.spark { flex: none; }
.seq {
  font-size: 12.5px; color: var(--text-secondary);
  font-variant-numeric: tabular-nums; white-space: nowrap; min-width: 0;
  overflow: hidden; text-overflow: ellipsis;
}

.empty { color: var(--muted); font-size: 14px; }

/* ------------------------------------------------------------ players */

.team-block { margin-bottom: 26px; min-width: 0; }

/* Home above away meant scrolling the length of a squad to compare a player
   with the man marking him.

   Side by side is not free: a squad table wants 1034px and the wrap is capped
   at 1180px, so two of them inside the normal column would each lose 457px,
   taking the fair and need prices off the edge. So two-up widens the page and
   drops the sparkline and the raw sequence, which brings a table to 785px.
   Applied from JS against the real window width rather than a media query,
   because the decision depends on the table, not the viewport alone. */
#players { display: grid; gap: 22px; grid-template-columns: 1fr; }
#players.two-up { grid-template-columns: 1fr 1fr; }
#players.two-up .team-block { margin-bottom: 0; }
#players.two-up .pcell svg,
#players.two-up .seq { display: none; }
#players .board { overflow-x: auto; }
.wrap.wide { max-width: min(1680px, calc(100vw - 40px)); }
.team-title {
  display: flex; align-items: center; gap: 9px;
  font-size: 17px; font-weight: 680; margin: 0 0 10px;
}

.ptable { width: 100%; border-collapse: collapse; }
.ptable thead th {
  text-align: left; font-size: 11px; letter-spacing: 0.07em;
  text-transform: uppercase; color: var(--muted); font-weight: 620;
  padding: 12px 16px; border-bottom: 1px solid var(--grid); white-space: nowrap;
}
.ptable tbody td {
  padding: 13px 16px; border-bottom: 1px solid var(--grid); vertical-align: middle;
}
.ptable tbody tr:last-child td { border-bottom: 0; }
.ptable tbody tr.strong { background: var(--tint); }
.player-name { font-weight: 620; white-space: nowrap; font-size: 15px; }
.pos { color: var(--muted); font-size: 12px; margin-left: 7px; font-weight: 500; }
.num { font-variant-numeric: tabular-nums; white-space: nowrap; color: var(--text-secondary); }
.pcell { display: flex; align-items: center; gap: 14px; }

.note { color: var(--muted); font-size: 13.5px; margin: 0 0 14px; }
.caution {
  border: 1px solid var(--border); border-left: 3px solid var(--miss);
  background: var(--surface-1); border-radius: 10px;
  padding: 13px 16px; margin: 0 0 16px;
  font-size: 13.5px; color: var(--text-secondary);
}
.caution strong { color: var(--text-primary); }
.warn {
  border: 1px solid var(--border); border-left: 3px solid var(--miss);
  background: var(--surface-1); border-radius: 10px;
  padding: 12px 15px; margin: 0 0 14px;
  font-size: 13.5px; color: var(--text-secondary);
}
.warn strong { color: var(--text-primary); }
.pill {
  display: inline-block; padding: 2px 8px; border-radius: 999px;
  font-size: 11.5px; font-weight: 620; letter-spacing: 0.02em;
  border: 1px solid var(--border); color: var(--text-secondary);
  white-space: nowrap;
}
.dir { font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
.odds { font-variant-numeric: tabular-nums; font-weight: 620; white-space: nowrap; }
.odds-min { font-size: 17px; }
.price-input {
  width: 72px; height: 30px; text-align: center;
  border: 1px solid var(--border); background: var(--control-bg);
  color: var(--text-primary); border-radius: 7px;
  font: inherit; font-size: 14px; font-variant-numeric: tabular-nums;
}
.price-input::-webkit-outer-spin-button,
.price-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.verdict { font-weight: 660; white-space: nowrap; font-size: 14px; }
.verdict.yes { color: var(--hit); }
.verdict.thin { color: var(--text-secondary); }
.verdict.no { color: var(--miss); }
.sub-line { color: var(--muted); font-size: 12px; font-weight: 500; display: block; }
.score { font-size: 26px; font-weight: 720; font-variant-numeric: tabular-nums; line-height: 1; }
.score.good { color: var(--hit); }
.score.poor { color: var(--miss); }
.breakdown { font-size: 12px; color: var(--muted); margin-top: 5px; }
.breakdown span { white-space: nowrap; margin-right: 10px; }
/* Usage: what feeds the bet, and whether it is drying up. */
.usage {
  font-size: 11.5px; font-weight: 600; letter-spacing: .01em;
  padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border);
  white-space: nowrap;
}
.usage-flat { color: var(--muted); }
.usage-up { color: var(--hit); border-color: color-mix(in srgb, var(--hit) 40%, transparent); }
.usage-down { color: var(--miss); border-color: color-mix(in srgb, var(--miss) 45%, transparent); }
.usage b { font-weight: 700; }

/* How soft or tough this defence is to the position, at a glance. */
.mu-rank {
  display: inline-block; font-size: 11px; font-weight: 700;
  letter-spacing: .02em; padding: 2px 7px; border-radius: 999px;
  border: 1px solid var(--border); white-space: nowrap; vertical-align: middle;
}
.mu-soft { color: var(--hit); border-color: color-mix(in srgb, var(--hit) 45%, transparent); }
.mu-tough { color: var(--miss); border-color: color-mix(in srgb, var(--miss) 45%, transparent); }
.mu-middling { color: var(--muted); }
.half-num .mu-rank { margin-left: 6px; font-size: 10.5px; }


/* ---- the bar: one number that says whether a bet earns a slip place ---- */
.order-note {
  font-size: 13px; color: var(--text-secondary);
  border-left: 2px solid var(--border); padding: 2px 0 2px 12px;
  margin: 0 0 16px;
}
.order-note code {
  font-size: 12px; background: var(--surface-1);
  border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px;
}
.pick-score {
  font-variant-numeric: tabular-nums; font-weight: 600;
  border-radius: 999px; padding: 2px 9px; font-size: 12px;
  border: 1px solid var(--border);
}
.pick-score.pass { color: var(--hit); border-color: color-mix(in srgb, var(--hit) 40%, transparent); }
.pick-score.fail { color: var(--muted); }
.bar-chip {
  margin-top: 6px; font-size: 11.5px; font-weight: 600;
  letter-spacing: 0.02em; text-transform: lowercase;
}
.bar-chip.pass { color: var(--hit); }
.bar-chip.fail { color: var(--miss); }
.breakdown .unscored { color: var(--miss); }
.score sup { font-size: 13px; color: var(--muted); font-weight: 500; }

.slip-bar-summary {
  border: 1px solid var(--border); border-radius: 10px;
  padding: 12px 15px; margin: 0 0 14px;
  font-size: 13.5px; color: var(--text-secondary);
}
.slip-bar-summary.is-warn { border-left: 3px solid var(--miss); }
.slip-bar-summary.is-ok { border-left: 3px solid var(--hit); }
.slip-bar-summary strong { color: var(--text-primary); }
.slip-bar-summary .pos { display: block; margin: 5px 0 0; }

.rec-bar { font-size: 12.5px; margin: 10px 0 12px; }
.rec-bar.is-ok { color: var(--muted); }
.rec-bar.is-warn { color: var(--miss); }

tr.swap-row > td { padding-top: 0; border-top: 0; }
tr.swap-row[hidden] { display: none; }
.swap-none { font-size: 13px; color: var(--muted); padding: 2px 0 10px; }
.swap-has {
  border-left: 2px solid var(--miss); padding: 4px 0 8px 12px;
  margin-bottom: 8px;
}
.swap-head { font-size: 13px; color: var(--text-secondary); margin-bottom: 8px; }
.swap-list { list-style: none; margin: 0; padding: 0; }
.swap-list li {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 6px 0; border-top: 1px solid var(--border);
}
.swap-leg { font-weight: 600; color: var(--text-primary); font-size: 13.5px; }
.swap-meta { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.swap-score {
  margin-left: auto; font-variant-numeric: tabular-nums;
  font-weight: 700; color: var(--hit);
}
.swap-list .add-btn { flex: 0 0 auto; }

.add-btn {
  border: 1px solid var(--border); background: var(--control-bg);
  color: var(--text-secondary); border-radius: 7px;
  font: inherit; font-size: 12.5px; padding: 5px 10px; cursor: pointer;
  white-space: nowrap;
}
.add-btn:hover { color: var(--text-primary); }
.add-btn[data-in="1"] { background: var(--control-active); color: var(--control-active-text); }
.totals {
  display: flex; flex-wrap: wrap; gap: 26px;
  padding: 16px 18px; margin-bottom: 16px;
  background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px;
}
.total-item .k {
  font-size: 11px; letter-spacing: 0.07em; text-transform: uppercase; color: var(--muted);
}
.total-item .v { font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }
.proj {
  margin-top: 7px; font-size: 12.5px; color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}
.proj b { font-weight: 680; color: var(--text-primary); }
.proj.conflict { color: var(--miss); }
/* Dotted underline on an estimate, so it never reads as the fitted number.
   Hover gives the matches it came from. */
.proj.est { border-bottom: 1px dotted var(--border); display: inline-block; }
.proj.est b { font-weight: 600; }
.chance { font-variant-numeric: tabular-nums; color: var(--muted); white-space: nowrap; }

/* ---------------------------------------------------------- best bets */
.comp-head {
  margin: 20px 0 10px; font-size: 13px; font-weight: 640;
  letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-secondary);
}
.comp-head .pos { text-transform: none; letter-spacing: 0; }

.pick {
  background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 12px; padding: 14px 16px; margin-bottom: 10px;
}
.pick-line { font-size: 17px; font-weight: 640; letter-spacing: -0.01em; }
.pick-fixture { color: var(--muted); font-size: 13px; margin-top: 1px; }

.pick-halves {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 12px 0 10px;
}
@media (max-width: 620px) { .pick-halves { grid-template-columns: 1fr; } }

.half {
  background: var(--tint); border-radius: 9px; padding: 9px 11px;
  display: grid; grid-template-columns: 1fr auto; gap: 2px 8px; align-items: baseline;
}
.half-label { font-size: 12.5px; color: var(--text-secondary); }
.half-num {
  font-variant-numeric: tabular-nums; font-weight: 660; font-size: 15px;
  justify-self: end;
}
.half .bar { grid-column: 1 / -1; margin: 3px 0 1px; }
.half .seq {
  grid-column: 1 / -1; font-size: 11.5px; color: var(--muted);
  font-variant-numeric: tabular-nums; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap;
}

.pick-foot {
  display: flex; flex-wrap: wrap; gap: 6px 16px; align-items: center;
  font-size: 13px; color: var(--text-secondary);
  border-top: 1px solid var(--grid); padding-top: 10px;
}
.pick-foot b { color: var(--text-primary); font-variant-numeric: tabular-nums; }
.pick-foot .add-btn { margin-left: auto; }

/* Positional matchup: the opponent's side of a player bet. A cell on the
   Players tab and a third block on a player pick. */
.mu { min-width: 0; }
.mu-fig { white-space: nowrap; font-variant-numeric: tabular-nums; color: var(--text-secondary); }
.mu-fig b { color: var(--text-primary); }
.mu-rate { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
.mu-note {
  font-size: 11.5px; color: var(--muted); margin-top: 2px;
  font-variant-numeric: tabular-nums; width: 165px;
}
/* The sample statement on a pick. Not .seq: that class is hidden on a phone
   and ellipsised on a card, and this line is the one that must always be
   read in full. */
.mu-seq {
  grid-column: 1 / -1; font-size: 11.5px; color: var(--muted);
  font-variant-numeric: tabular-nums; white-space: normal;
}
.mu-thin .mu-fig, .mu-thin .mu-rate, .half.mu-thin .half-num { opacity: 0.7; }
.mu-none { font-size: 12px; color: var(--muted); }
.pick-halves.three { grid-template-columns: 1fr 1fr 1fr; }
@media (max-width: 900px) { .pick-halves.three { grid-template-columns: 1fr 1fr; } }
@media (max-width: 660px) {
  .pick-halves.three { grid-template-columns: 1fr; }
  .ptable .mu::before { content: attr(data-label) ": "; color: var(--muted); }
  .ptable .mu .mu-fig, .ptable .mu .mu-rate { display: inline; margin-right: 6px; }
  .ptable .mu .mu-note { width: auto; }
}

/* A player with barely any appearances. Shown rather than hidden, because a
   missing player reads as missing data, but marked so a 100% record off one
   match is never mistaken for a strong one. */
tr.thin { opacity: 0.78; }
.tag-thin {
  display: inline-block;
  margin-left: 0.4rem;
  padding: 0.05rem 0.35rem;
  border-radius: 4px;
  border: 1px solid var(--border);
  font-size: 0.68rem;
  color: var(--text-secondary);
  white-space: nowrap;
}

.rec-legs { margin: 0.5rem 0 0.6rem 1.1rem; padding: 0; }
.rec-legs li { margin: 0.2rem 0; }
#rec-controls { margin-top: 0.4rem; }

/* The custom bet builder. A grid so it wraps sensibly on a phone rather than
   forcing a horizontal scroll, which is where this would be used most. */
#custom-wrap {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0.6rem 0.9rem;
  margin-bottom: 1rem;
  background: var(--surface-raised);
}
#custom-wrap summary {
  cursor: pointer;
  font-weight: 600;
  padding: 0.2rem 0;
}
.custom-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  align-items: flex-end;
  margin: 0.6rem 0;
}
.custom-row label {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  font-size: 0.78rem;
  color: var(--text-secondary);
}
.custom-row select, .custom-row input {
  font: inherit;
  padding: 0.3rem 0.4rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text-primary);
  min-width: 7rem;
}
.custom-row input { width: 6.5rem; min-width: 0; }
#c-preview:not(:empty) {
  border-top: 1px solid var(--border);
  padding-top: 0.5rem;
  margin-top: 0.2rem;
}
.need-cell { display: inline-flex; align-items: baseline; gap: 5px; }
.src {
  font-size: 10.5px; font-weight: 600; color: var(--muted);
  border: 1px solid var(--border); border-radius: 5px; padding: 0 5px;
  white-space: nowrap;
}
.src.warnsrc { color: var(--miss); border-color: var(--miss); }
.agree { font-size: 12.5px; }
.agree.yes { color: var(--hit); }
.agree.no  { color: var(--miss); }

.tooltip {
  position: fixed; pointer-events: none;
  background: var(--text-primary); color: var(--surface-1);
  padding: 7px 10px; border-radius: 7px;
  font-size: 12.5px; line-height: 1.4;
  opacity: 0; transition: opacity 0.1s; z-index: 10; white-space: nowrap;
}

footer { margin-top: 22px; color: var(--muted); font-size: 13px; }

/* --------------------------------------------------- filter drawer */

/* The resting state of the whole control area: one line that says, in plain
   words, what the numbers on screen have been filtered by, and one button
   that opens the panel. The line is the button, so the tap target is the
   full width of the page rather than a small chevron. */
.filter-bar {
  display: flex; align-items: center; gap: 14px;
  margin-bottom: 12px;
}
#filter-toggle {
  display: flex; align-items: center; gap: 9px;
  flex: 1 1 auto; min-width: 0; text-align: left;
  border: 1px solid var(--border); background: var(--surface-1);
  color: var(--text-primary); border-radius: 12px;
  font: inherit; font-size: 13.5px; padding: 10px 14px; cursor: pointer;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
#filter-toggle:hover { background: var(--tint); }
#filter-toggle .chev {
  flex: none; color: var(--muted); font-size: 11px;
  transition: transform 0.12s ease;
}
#filter-toggle[aria-expanded="true"] .chev { transform: rotate(90deg); }
#filter-toggle .fword {
  flex: none; font-weight: 640;
  display: inline-flex; align-items: center; gap: 6px;
}
.fcount {
  background: var(--control-active); color: var(--control-active-text);
  border-radius: 999px; font-size: 10.5px; font-weight: 700;
  min-width: 16px; height: 16px; line-height: 16px; text-align: center;
  padding: 0 4px;
}
.fcount[hidden] { display: none; }
#filter-summary {
  color: var(--text-secondary); min-width: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
#filter-summary .on { color: var(--team-1); font-weight: 640; }

.filter-panel {
  display: flex; flex-direction: column; gap: 14px;
  border: 1px solid var(--border); border-radius: 12px;
  background: var(--surface-1);
  padding: 15px 16px; margin: -4px 0 16px;
  box-shadow: 0 12px 28px rgba(0,0,0,0.08);
}
/* display:flex on the class would silently defeat the hidden attribute. */
.filter-panel[hidden] { display: none; }
.fgroup { display: flex; gap: 8px 20px; }
.fgroup + .fgroup { border-top: 1px solid var(--grid); padding-top: 14px; }
.fgroup-title {
  flex: none; width: 62px; padding-top: 7px;
  font-size: 11px; letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--muted); font-weight: 620;
}
.fgroup-body {
  display: flex; flex-wrap: wrap; gap: 12px 22px;
  align-items: center; flex: 1 1 auto; min-width: 0;
}

/* ------------------------------------------------------ header actions */

.header-line {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 10px 16px; flex-wrap: wrap;
}
.header-actions { display: flex; gap: 7px; flex: none; padding-top: 4px; }
.header-actions button {
  border: 1px solid var(--border); background: var(--control-bg);
  color: var(--text-secondary); border-radius: 8px;
  font: inherit; font-size: 13px; padding: 6px 12px; cursor: pointer;
  white-space: nowrap;
}
.header-actions button:hover { color: var(--text-primary); background: var(--tint); }
#fixture-group { margin-top: 12px; }

/* ------------------------------------------------------ player picks */

.pick-player { border-left: 3px solid var(--team-1); }
.tag-player {
  display: inline-block; vertical-align: 2px;
  margin-left: 0.45rem; padding: 0.1rem 0.45rem;
  border-radius: 5px; border: 1px solid var(--border);
  background: var(--tint);
  font-size: 0.66rem; font-weight: 600; letter-spacing: 0.05em;
  text-transform: uppercase; color: var(--text-secondary);
  white-space: nowrap;
}

/* -------------------------------------------------------------- narrow */

@media (max-width: 900px) {
  .seq { display: none; }
  .stat-row { grid-template-columns: 1fr 170px 1fr; gap: 12px; padding: 14px; }
  .figure { min-width: 78px; }
}

@media (max-width: 660px) {
  /* Full width beats a squeezed dropdown you cannot read the end of. */
  #fixture-group { width: 100%; }
  #fixture-group select { flex: 1 1 auto; }

  /* The panel reads as a sheet: group names above their controls, not
     beside them, and the summary keeps to its single line. */
  .fgroup { flex-direction: column; gap: 8px; }
  .fgroup-title { width: auto; padding-top: 0; }

  /* A phone cannot fit the whole sentence. When any filter is off its
     default, the defaults give way and the active ones keep the room,
     wrapping if they must: nothing may filter the numbers invisibly. */
  #filter-summary.has-active .defaults { display: none; }
  #filter-summary.has-active { white-space: normal; }
  .header-actions { padding-top: 0; }

  /* Five tabs measure 494px and the phone is 390px. Wrapping onto two rows
     keeps every tab visible and tappable; a sideways scroller would hide
     "My slip" off the edge with nothing to say it was there. */
  .tabs button { flex: 1 1 auto; padding: 10px 12px; font-size: 14px; }
  body { padding: 20px 12px 60px; font-size: 16px; }
  h1 { font-size: 24px; }
  .legend { display: none; }

  .stat-row { grid-template-columns: 1fr; gap: 12px; padding: 16px 14px; }
  .middle {
    order: 0; text-align: left;
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
  }
  .stat-label { margin-bottom: 0; font-size: 16px; }

  .side.a, .side.b { order: 1; flex-direction: row; gap: 12px; }
  .side.a .figure { text-align: left; }
  .side.a .bar { justify-content: flex-start; }

  .team-tag { display: flex; flex: none; min-width: 84px; }
  .figure { min-width: 74px; }
  .pct { font-size: 22px; }

  .ptable thead { display: none; }
  .ptable tbody td { display: block; padding: 4px 14px; border: 0; }
  .ptable tbody td:first-child { padding-top: 14px; }
  .ptable tbody td:last-child { padding-bottom: 14px; border-bottom: 1px solid var(--grid); }
  .ptable .num::before { content: attr(data-label) ": "; color: var(--muted); }
}

.ladder { margin: 10px 14px 12px; }
.ladder summary { cursor: pointer; font-size: 12px; color: var(--muted);
  padding: 4px 0; }
.ladder summary:hover { color: var(--fg); }
.ladder-table { width: 100%; border-collapse: collapse; margin-top: 6px;
  font-variant-numeric: tabular-nums; font-size: 12px; }
.ladder-table th { text-align: left; font-weight: 500; color: var(--muted);
  padding: 3px 8px 3px 0; border-bottom: 1px solid var(--border); }
.ladder-table td { padding: 3px 8px 3px 0; border-bottom: 1px solid var(--border); }
.ladder-table td.rung { font-weight: 600; }
.ladder-table td.rung-need { color: var(--muted); }
.ladder-table tr.rung-here { background: var(--raised); }
.ladder-table tr.rung-here td { border-bottom-color: var(--accent); }
.ladder-note { font-size: 11px; color: var(--muted); margin: 8px 0 0;
  line-height: 1.5; }


/* ---------------------------------------------------------------- restyle
   A quieter shell around exactly the same information.

   Appended rather than edited in, so every rule above still says what it said
   and this can be deleted in one block if it turns out worse. Nothing here
   changes markup or behaviour: it is spacing, weight and contrast only.

   The charts are deliberately untouched. Their red and green are not
   decoration -- a hit is a filled dot above the line and a miss a hollow one
   below, so the pair survives greyscale and red-green colour blindness, and
   the contrast was chosen to clear 3:1 on both surfaces. Calming those would
   be undoing work that was done for a reason. */

/* Tabs: one segmented control rather than five separate buttons. */
.tabs {
  display: inline-flex; flex-wrap: wrap; gap: 2px; margin-bottom: 18px;
  background: var(--tint); border-radius: 10px; padding: 3px;
}
.tabs button {
  border: 0; background: none; color: var(--text-secondary);
  font-size: 14px; font-weight: 500; padding: 7px 15px; border-radius: 8px;
}
.tabs button:hover { color: var(--text-primary); }
.tabs button[aria-selected="true"] {
  background: var(--surface-1); color: var(--text-primary); font-weight: 600;
  border-color: transparent; box-shadow: 0 1px 2px rgba(11,11,11,.08);
}

/* Header furniture: present, not shouting. */
.back {
  font-size: 13.5px; font-weight: 500; padding: 7px 13px 7px 11px;
  border-radius: 99px; box-shadow: none; color: var(--text-secondary);
}
.back:hover { color: var(--text-primary); }
.back-bar { padding: 12px 0 8px; margin: -12px 0 6px; }
h1 { letter-spacing: -0.025em; }
.controls {
  gap: 10px 18px; padding: 10px 14px; border-radius: 10px;
  background: none; border-color: var(--grid);
}
.controls + .controls { margin-top: 6px; }
.control-label { font-size: 11px; letter-spacing: .06em; text-transform: uppercase; }

/* Rows: the market is the anchor, the percentage supports it. Both were
   competing at 24px against a 15px label. */
.stat-row { padding: 13px 18px; gap: 18px; }
.stat-label { font-size: 15px; font-weight: 600; letter-spacing: -0.01em; }
.pct { font-size: 19px; font-weight: 650; }
.stat-row.strong .pct { font-size: 19px; }
.frac { font-size: 12px; }
.bar { height: 5px; margin-top: 6px; }
.seq { font-size: 12px; color: var(--muted); }

/* The long explanations sit under everything and are read once. */
.note { font-size: 12.5px; line-height: 1.6; }


/* The collapsed explanations. Quiet when shut, readable when open. */
.caution { padding: 0; border: 0; background: none; }
details.tuck { border: 1px solid var(--grid); border-radius: 10px;
  background: var(--tint); margin: 0 0 14px; }
details.tuck > summary { cursor: pointer; list-style: none; padding: 10px 14px;
  font-size: 13px; font-weight: 600; color: var(--text-secondary);
  display: flex; align-items: center; gap: 8px; }
details.tuck > summary::-webkit-details-marker { display: none; }
details.tuck > summary::before { content: "?"; display: inline-flex;
  align-items: center; justify-content: center; width: 17px; height: 17px;
  border-radius: 50%; border: 1px solid var(--baseline); font-size: 11px;
  font-weight: 600; flex: none; }
details.tuck > summary:hover { color: var(--text-primary); }
details.tuck[open] > summary { border-bottom: 1px solid var(--grid); }
details.tuck > div { padding: 12px 14px 14px; font-size: 13px; line-height: 1.65;
  color: var(--text-secondary); }

/* Steppers you can actually hit. 28px was a target for a mouse on a good day
   and nothing at all on a phone; 34px with a real hover state is a control. */
.stepper { gap: 6px; }
.stepper button {
  width: 34px; height: 34px; border-radius: 9px; font-size: 18px;
  color: var(--text-primary); border-color: var(--grid);
  transition: background .12s, border-color .12s, transform .06s;
}
.stepper button:hover { background: var(--tint); border-color: var(--baseline); }
.stepper button:active { transform: scale(.94); }
.stepper input {
  height: 34px; width: 74px; font-size: 15px; font-weight: 600;
  border-radius: 9px; border-color: var(--grid);
}
.stepper input:focus { outline: none; border-color: var(--text-primary); }

/* Selects: one caret, drawn, so every browser shows the same control. */
select, .num-input {
  height: 38px; border-radius: 10px; border-color: var(--grid);
  padding: 0 34px 0 12px; font-size: 14px;
  appearance: none; -webkit-appearance: none;
  background-image:
    linear-gradient(45deg, transparent 50%, currentColor 50%),
    linear-gradient(135deg, currentColor 50%, transparent 50%);
  background-position: calc(100% - 18px) 52%, calc(100% - 13px) 52%;
  background-size: 5px 5px, 5px 5px;
  background-repeat: no-repeat;
  transition: border-color .12s;
}
select:hover, .num-input:hover { border-color: var(--baseline); }
select:focus, .num-input:focus { outline: none; border-color: var(--text-primary); }
.num-input { background-image: none; padding-right: 12px; }

/* The board reads as cards, like the picks do, rather than one ruled sheet. */
.board { border: 0; background: none; padding: 0; }
.stat-row {
  background: var(--surface-1); border: 1px solid var(--grid);
  border-radius: 12px; margin-bottom: 6px;
  transition: border-color .12s, box-shadow .12s;
}
.stat-row:hover { border-color: var(--baseline);
  box-shadow: 0 1px 2px rgba(11,11,11,.05); }
.stat-row.strong { background: var(--tint); }


/* The dropdown that replaces the operating system's. */
.combo { position: relative; display: inline-block; min-width: 0; max-width: 100%; }
.combo > select { position: absolute; opacity: 0; pointer-events: none;
  width: 100%; height: 100%; left: 0; top: 0; }
.combo-btn {
  display: inline-flex; align-items: center; gap: 10px; width: 100%;
  height: 38px; padding: 0 12px; border-radius: 10px;
  border: 1px solid var(--grid); background: var(--control-bg);
  color: var(--text-primary); font: inherit; font-size: 14px; cursor: pointer;
  transition: border-color .12s, background .12s;
}
.combo-btn:hover { border-color: var(--baseline); }
.combo-btn[aria-expanded="true"] { border-color: var(--text-primary); }
.combo-btn:disabled { opacity: .5; cursor: default; }
.combo-val { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.combo-caret { margin-left: auto; flex: none; width: 0; height: 0;
  border-left: 4px solid transparent; border-right: 4px solid transparent;
  border-top: 5px solid var(--muted); }
.combo-pop {
  position: absolute; z-index: 60; left: 0; min-width: 100%; top: calc(100% + 5px);
  background: var(--surface-1); border: 1px solid var(--grid); border-radius: 11px;
  box-shadow: 0 2px 6px rgba(11,11,11,.08), 0 16px 40px -20px rgba(11,11,11,.4);
  overflow: hidden; max-width: 90vw;
}
.combo-search { width: 100%; border: 0; border-bottom: 1px solid var(--grid);
  background: none; color: var(--text-primary); font: inherit; font-size: 14px;
  padding: 10px 12px; }
.combo-search:focus { outline: none; }
.combo-list { max-height: 300px; overflow: auto; padding: 5px; }
.combo-item { display: block; width: 100%; text-align: left; border: 0;
  background: none; color: inherit; font: inherit; font-size: 14px;
  padding: 8px 10px; border-radius: 7px; cursor: pointer;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.combo-item:hover { background: var(--tint); }
.combo-item.on { background: var(--tint); font-weight: 600; }
.combo-none { color: var(--muted); font-size: 13px; padding: 12px; }


/* Number fields with buttons you can hit, and no operating-system spinner
   anywhere on the page. */
input[type=number] { -moz-appearance: textfield; }
input[type=number]::-webkit-outer-spin-button,
input[type=number]::-webkit-inner-spin-button {
  -webkit-appearance: none; margin: 0;
}
.numwrap { display: inline-flex; align-items: center; gap: 4px; }
.numwrap input {
  text-align: center; border-radius: 9px; border-color: var(--grid);
  height: 34px; font-weight: 600; font-size: 15px;
  padding: 0 6px; min-width: 62px; width: 62px;
}
.numwrap input:focus { outline: none; border-color: var(--text-primary); }
.numbtn {
  width: 34px; height: 34px; flex: none; padding: 0;
  border: 1px solid var(--grid); background: var(--control-bg);
  color: var(--text-primary); border-radius: 9px;
  font: inherit; font-size: 18px; line-height: 1; cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
  transition: background .12s, border-color .12s, transform .06s;
  user-select: none; -webkit-user-select: none; touch-action: manipulation;
}
.numbtn:hover { background: var(--tint); border-color: var(--baseline); }
.numbtn:active { transform: scale(.94); }
.price-input { width: 74px; min-width: 74px; }
/* ---- Players tab: squads and profiles */
.pp-mode { margin: 0 0 14px; }
#odds-strip { margin: 0 0 12px; }
.mo-strip { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; padding: 9px 12px;
  background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; font-size: 13.5px; }
.mo-label { font-size: 11px; letter-spacing: 0.07em; text-transform: uppercase; color: var(--muted); font-weight: 620; }
.mo-cell { display: inline-flex; align-items: baseline; gap: 6px; }
.mo-cell b { font-variant-numeric: tabular-nums; }
.mo-cell small, .mo-muted { color: var(--muted); font-size: 12px; }
.mo-muted { margin-left: auto; }
.pp-wrap .mo-strip { margin-bottom: 14px; }
.pp-teams { display: grid; gap: 14px; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
.pp-teamcard { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; }
.pp-team { all: unset; cursor: pointer; display: flex; flex-wrap: wrap; align-items: center; gap: 4px 9px; width: 100%; }
.pp-team b { font-size: 18px; font-weight: 680; }
.pp-team .pp-sub { flex-basis: 100%; }
.pp-go { margin-left: auto; color: var(--muted); font-size: 13px; }
.pp-team .pp-go { position: relative; top: -2px; }
.pp-sub { color: var(--text-secondary); font-size: 13px; font-weight: 400; }
.pp-xilabel { font-size: 11px; letter-spacing: 0.07em; text-transform: uppercase; color: var(--muted); font-weight: 620; margin: 12px 0 7px; }
.pp-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.pp-chip { border: 1px solid var(--border); background: var(--tint); color: var(--text-primary); border-radius: 999px;
  padding: 5px 10px; font: inherit; font-size: 13px; cursor: pointer; display: inline-flex; gap: 6px; align-items: center; }
.pp-chip:hover, .pp-row:hover { border-color: var(--baseline); }
.pp-crumbs { display: flex; gap: 8px; flex-wrap: wrap; margin: 0 0 12px; }
.pp-back { border: 1px solid var(--border); background: var(--control-bg); color: var(--text-primary); border-radius: 8px;
  padding: 6px 11px; font: inherit; font-size: 13px; cursor: pointer; }
.pp-section { font-size: 11px; letter-spacing: 0.07em; text-transform: uppercase; color: var(--muted); font-weight: 620; margin: 18px 0 8px; }
.pp-row { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; font: inherit; color: var(--text-primary);
  background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 9px 12px; margin-bottom: 6px; cursor: pointer; }
.pp-row .lu-shirt { min-width: 22px; text-align: center; }
.pp-name { display: flex; flex-direction: column; min-width: 150px; }
.pp-name small { color: var(--muted); font-size: 12px; }
.pp-tags { display: flex; flex-wrap: wrap; gap: 5px; flex: 1; justify-content: flex-end; }
.pp-tag { font-size: 11.5px; background: var(--tint); border-radius: 6px; padding: 3px 7px; color: var(--text-secondary); white-space: nowrap; }
.pp-tag b { color: var(--hit); }
.pp-tag.pp-card { color: var(--text-primary); background: rgba(232, 185, 35, 0.22); }
.vd { font-size: 11px; font-weight: 680; letter-spacing: 0.04em; text-transform: uppercase; border-radius: 6px; padding: 3px 7px; white-space: nowrap; }
.vd-take { background: rgba(12, 163, 12, 0.18); color: var(--hit); }
.vd-ok { background: rgba(232, 185, 35, 0.22); color: var(--text-primary); }
.vd-avoid { background: rgba(220, 60, 60, 0.16); color: var(--miss); }
.vd-long { background: var(--tint); color: var(--muted); }
.pp-hero { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 14px; }
.pp-hero .swatch { margin-right: 6px; }
.pp-big { font-size: 22px; font-weight: 700; }
.pp-hero .pp-sub { margin: 4px 0 12px; }
.pp-hero .mo-strip { margin: 0; }
.lu-badge.pp-out { color: var(--miss); }
.pp-grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(440px, 1fr)); }
.pp-stat { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; }
.pp-stat-head { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; margin-bottom: 8px; }
.pp-stat-head b { font-size: 15px; }
.pp-stat-head span { color: var(--muted); font-size: 12px; text-align: right; }
.pp-why { font-size: 12.5px; color: var(--text-secondary); margin: 0 0 8px; line-height: 1.45; }
.pp-seq { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 8px; }
.pp-seq span { min-width: 24px; text-align: center; border-radius: 6px; padding: 2px 4px; font-size: 12px; font-variant-numeric: tabular-nums; }
.pp-hit { background: rgba(12, 163, 12, 0.16); }
.pp-miss { background: var(--tint); color: var(--muted); }
.pp-rung { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; padding: 8px 0; border-top: 1px solid var(--grid); }
.pp-line { font-weight: 680; min-width: 54px; }
.pp-rec { color: var(--text-secondary); font-size: 12.5px; min-width: 120px; flex: 1; }
.pp-kv { display: inline-flex; flex-direction: column; font-variant-numeric: tabular-nums; min-width: 46px; }
.pp-kv small { font-size: 10.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.pp-bf b { color: var(--team-1); }
.pp-in input { width: 64px; font: inherit; font-size: 13px; padding: 2px 5px; border: 1px solid var(--border);
  border-radius: 6px; background: var(--control-bg); color: var(--text-primary); }
.pp-edge { font-weight: 680; }
.pp-pos { color: var(--hit); }
.pp-neg { color: var(--miss); }
@media (max-width: 560px) {
  .pp-grid { grid-template-columns: 1fr; }
  .pp-row { flex-wrap: wrap; }
  .pp-tags { justify-content: flex-start; flex-basis: 100%; }
  .mo-muted { margin-left: 0; flex-basis: 100%; }
}

/* ---- Jarvis-style charts and the Team stats cards */
.jchart { width: 100%; height: auto; display: block; }
.jchart .jg { stroke: var(--grid); }
.jchart .jt, .jchart .jx { fill: var(--muted); font-size: 9px; }
.jchart .jline { stroke: var(--text-secondary); stroke-dasharray: 3 4; }
.jchart .jll { fill: var(--text-primary); font-size: 10px; font-weight: 650; }
.jchart .jv { fill: var(--text-primary); font-size: 10px; font-weight: 650; }
.jchart .jhit { fill: var(--hit); stroke: var(--surface-1); stroke-width: 2; }
.jchart .jmiss { fill: var(--surface-1); stroke: var(--miss); stroke-width: 2; }
.jring { width: 100%; height: auto; display: block; }
.jring .jseg-hit { stroke: var(--hit); stroke-width: 7; stroke-linecap: round; }
.jring .jseg-miss { stroke: var(--miss); stroke-width: 2.5; stroke-linecap: round; opacity: 0.85; }
.jring .jr1 { fill: var(--text-primary); font-size: 20px; font-weight: 650; }
.jring .jr2 { fill: var(--muted); font-size: 10px; }
.tmode { margin: 0 0 14px; }
.tc-card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; }
.tc-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; margin-bottom: 6px; }
.tc-head b { font-size: 15px; }
.tc-head .proj { margin: 0; }
.tc-step { display: inline-flex; align-items: center; gap: 4px; }
.tc-step button { border: 1px solid var(--border); background: var(--control-bg); color: var(--text-primary);
  border-radius: 7px; width: 28px; height: 26px; font: inherit; cursor: pointer; }
.tc-line { min-width: 48px; text-align: center; font-weight: 650; font-variant-numeric: tabular-nums; }
.tc-side { border-top: 1px solid var(--grid); padding-top: 8px; margin-top: 6px; }
.tc-sidehead { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }
.tc-meta { color: var(--muted); font-size: 12px; }
.tc-team { display: inline-flex; align-items: center; gap: 7px; font-weight: 620; font-size: 13.5px; }
.tc-body { display: grid; grid-template-columns: 92px 1fr; gap: 10px; align-items: center; }
.pp-chartwrap { margin: 2px 0 6px; }
@media (max-width: 560px) {
  .tc-body { grid-template-columns: 70px 1fr; gap: 6px; }
}

/* ---- Team stats: list down the side, one chart */
#tcards { display: block; }
.tv { display: grid; grid-template-columns: 250px 1fr; gap: 14px; align-items: start; }
.tv-list { display: flex; flex-direction: column; gap: 3px; position: sticky; top: 10px;
  max-height: calc(100vh - 20px); overflow-y: auto; background: var(--surface-1);
  border: 1px solid var(--border); border-radius: 12px; padding: 6px; }
.tl-item { display: flex; justify-content: space-between; align-items: center; gap: 8px; width: 100%;
  border: 0; background: transparent; color: var(--text-primary); font: inherit; font-size: 13.5px;
  text-align: left; padding: 8px 9px; border-radius: 8px; cursor: pointer; }
.tl-item:hover { background: var(--tint); }
.tl-item.tl-on { background: var(--control-active); color: var(--control-active-text); }
.tl-name { display: flex; flex-direction: column; }
.tl-name small { font-size: 11px; opacity: 0.65; }
.tl-badges { display: flex; gap: 4px; flex: none; }
.tl-badge { display: inline-flex; align-items: center; gap: 4px; font-size: 11.5px; font-variant-numeric: tabular-nums;
  padding: 2px 6px; border-radius: 6px; background: var(--tint); }
.tl-on .tl-badge { background: rgba(255,255,255,0.14); }
.tl-badge i { width: 7px; height: 7px; border-radius: 2px; display: inline-block; }
.tl-badge.tl-hi { font-weight: 700; }
.tv-main { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; min-width: 0; }
.tv-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; }
.tv-head h3 { margin: 0; font-size: 20px; }
.tv-head .proj { margin: 0; }
.tv-controls { display: flex; flex-wrap: wrap; gap: 8px 12px; margin: 12px 0; }
.tv-seg button { font-size: 12.5px; }
.tv-rings { display: flex; flex-wrap: wrap; gap: 10px 26px; margin-bottom: 6px; }
.tv-ring { display: flex; align-items: center; gap: 10px; }
.tv-ringsvg { width: 78px; }
.tv-ringtxt { display: flex; flex-direction: column; gap: 3px; }
.tv-ringtxt small { color: var(--muted); font-size: 12px; }
.tv-chart .jbig .jx, .tv-chart .jbig .jt { font-size: 12px; }
.tv-chart .jbig .jv, .tv-chart .jbig .jll { font-size: 13px; }
.tv-note { margin: 4px 0 0; }
@media (max-width: 760px) {
  .tv { grid-template-columns: 1fr; }
  .tv-list { position: static; flex-direction: row; overflow-x: auto; max-height: none; padding: 5px; }
  .tl-item { flex: none; width: auto; flex-direction: column; align-items: flex-start; gap: 4px; }
  .tv-main { padding: 12px; }
}

/* ---- strongest lines */
.pp-tag.pp-hi { background: rgba(12, 163, 12, 0.16); color: var(--text-primary); }
.pp-tag.pp-mid { background: rgba(12, 163, 12, 0.08); color: var(--text-primary); }
.pp-tag b { color: inherit; }
.pp-strong { display: flex; flex-direction: column; gap: 4px; background: var(--surface-1);
  border: 1px solid var(--border); border-radius: 12px; padding: 6px; }
.pp-srow { display: grid; grid-template-columns: 22px 10px 1fr 44px 44px 110px; align-items: center; gap: 10px;
  border: 0; background: transparent; color: var(--text-primary); font: inherit; text-align: left;
  padding: 7px 8px; border-radius: 8px; cursor: pointer; }
.pp-srow:hover { background: var(--tint); }
.pp-rank { color: var(--muted); font-variant-numeric: tabular-nums; font-size: 12px; }
.pp-sname { display: flex; flex-direction: column; min-width: 0; }
.pp-sname small { color: var(--text-secondary); font-size: 12px; }
.pp-srec { color: var(--text-secondary); font-size: 12.5px; font-variant-numeric: tabular-nums; }
.pp-spct { font-weight: 700; font-variant-numeric: tabular-nums; }
.pp-sbar { height: 6px; background: var(--track); border-radius: 3px; overflow: hidden; }
.pp-sbar i { display: block; height: 100%; background: var(--hit); }
.pp-order { margin: 4px 0 8px; }
.pp-schips { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 8px; }
.pp-schip { border: 1px solid var(--border); background: var(--control-bg); color: var(--text-primary);
  border-radius: 999px; padding: 4px 11px; font: inherit; font-size: 12.5px; cursor: pointer; }
.pp-schip[aria-pressed="true"] { background: var(--control-active); color: var(--control-active-text); border-color: transparent; }
.tl-order { display: flex; gap: 4px; padding: 2px 2px 6px; }
.tl-order button { flex: 1; font-size: 12px; }
.tl-pct { font-size: 10.5px; opacity: 0.7; margin-left: 2px; }
@media (max-width: 560px) {
  .pp-srow { grid-template-columns: 18px 8px 1fr 38px 40px; }
  .pp-sbar { display: none; }
}

.pp-ppp b { color: #0b8a4a; }
.pp-ppcard .pp-line { min-width: 170px; font-weight: 600; }

.pp-edge.pp-long { color: var(--muted); font-weight: 500; }

"""

JS = """
const ALL = __PAYLOAD__;

let DATA = ALL.fixtures[0];
let SUGGESTED = {};
let SUGGESTED_H2H = {};

/* The whole record, not the last ten.
   Ten appearances cannot tell 70% from 45%, so the Wilson bound stays wide
   and `need` lands around 2.2 on bets a book prices at 1.4 -- which is to say
   nothing in the file was backable. Doubling the sample moves the median
   `need` from 2.21 to 1.91 and the tightest from 1.68 to 1.31. Recency still
   matters, and the 5 / 10 buttons are there for it. */
let games = 99;
let venue = "all";
let tier  = "all";
let tab = "team";

/* Player bets and team bets are two different products and were being ranked
   against each other in one list.

   They are not comparable. A player prop is on every bookmaker's app; a
   second-half throw-in line exists on one book in one competition, which
   makes it a niche bet however good the number is. Mixed together, whichever
   kind happened to score higher took the slots and the other disappeared off
   the bottom -- so the list answered "what is the best bet here" when the
   question actually being asked is "what is the best player bet" or "what is
   the best team bet", separately, because you would place them differently.

   One panel, two tabs, one variable. Cloning the panel would mean two copies
   of the controls, the slip, the order buttons and the recommender, and two
   places to fix everything from now on. */
let bestKind = "player";       // "player" | "team"

/* Both Best tabs open the same panel. */
function panelFor(target) {
  return target === "best-player" || target === "best-team" ? "best" : target;
}
let period = "ALL";
let scope = "core";
let sort = "default";
let strongOnly = false;
let source = "form";      // "form" = recent matches, "h2h" = previous meetings
let measure = "for";      // "for" | "against" | "matchup"
let showPast = false;
let includeMismatched = false;
let focus = "both";   // "both" | "0" | "1"

// A hit rate this far from an even split is worth your attention. Below it,
// ten matches simply cannot separate signal from noise.
const STRONG_HIGH = 80;
const STRONG_LOW = 20;

/* The markets worth leading with. "All" still shows everything that came
   through, which is now only the bettable set unless the report was built
   with --all-stats. */
const CORE_STATS = [
  "Goals", "Both teams to score", "Match goals", "Match corners",
  "Match cards", "Both teams carded",
  "Total shots", "Shots on target", "Corner kicks",
  "Fouls", "Tackles", "Offsides", "Throw-ins", "Yellow cards",
];

const VARS = ["--team-1", "--team-2"];
const boardEl = document.getElementById("board");

const tip = document.createElement("div");
tip.className = "tooltip";
document.body.appendChild(tip);

/* Lines are always quoted at .5 so a match can never land exactly on one.
   Stepping moves a whole unit: 13.5 to 14.5, not 13.5 to 14. */
function snapLine(value) {
  return Math.max(0.5, Math.round(value - 0.5) + 0.5);
}

function hasH2H() {
  return Array.isArray(DATA.h2h) && DATA.h2h.some(r => r.length);
}

/* Head to head reuses the whole rendering path: same record shape, same
   filters, just a different set of matches and its own lines. Two teams
   meeting each other produce different numbers from their form against
   everyone else, so the suggested lines cannot be shared. */
function activeRecords() {
  return source === "h2h" && hasH2H() ? DATA.h2h : DATA.records;
}

function activeLines() {
  const bucket = source === "h2h" && hasH2H() ? DATA.h2hLines : DATA.lines;
  return (bucket || {})[period] || {};
}

function activeStats() {
  const bucket = source === "h2h" && hasH2H() ? DATA.h2hStats : DATA.stats;
  return (bucket || {})[period] || [];
}

/* Standard of opposition. A club missing from last season's tables came up
   from a lower division, so it counts as bottom rather than unknown: putting
   it in mid-table by accident is the mistake this whole feature exists to
   stop. */
function tierOf(opponentId) {
  const map = (DATA.tiers || {}).map || {};
  return map[String(opponentId)] || "bottom";
}

function filtered(records) {
  let rows = records;
  if (venue !== "all") rows = rows.filter(r => r.venue === venue);
  if (tier !== "all" && DATA.tiers) {
    rows = rows.filter(r => tierOf(r.opponent_id) === tier);
  }
  return rows.slice(-games);
}

/* The id of the side this team is facing, or null on a report built before
   run.py started carrying team ids.

   Matching by name was tried first and is not safe. A record stores the
   opponent's short name while the fixture stores the full one, so "Manchester
   City" never equals "Man City", and fuzzy matching offered Everton as the
   closest thing to Coventry City. A wrong opponent here would silently
   attribute one player's record against Everton to a match against Coventry,
   which is worse than showing nothing. Ids or nothing. */
function opponentIdFor(teamIndex, fx = DATA) {
  const other = fx.teams[1 - teamIndex];
  return other && other.id !== undefined && other.id !== null ? other.id : null;
}

/* A player's own records against this opponent.

   Prefers `h2hPlayers`, which a build with --h2h and --players fetches
   specifically: lineups for every previous meeting the deeper search found,
   whether or not it falls inside the form window. Falls back to filtering the
   form records by meeting, which is all older reports have.

   The fallback is the thing this exists to get away from. Lineups are fetched
   per match, and only form matches were ever fetched, so a player's record
   "against this opponent" could only contain meetings inside the last N
   games. Two NFL clubs in different divisions meet once in twenty, so every
   card read 1/1 -- a head-to-head with the head-to-heads left out, which
   looks like a thin record rather than the unasked question it was. */
function h2hPlayerRecords(teamIndex, fx, name) {
  const deep = (fx.h2hPlayers || [])[teamIndex];
  if (!Array.isArray(deep) || !deep.length) return null;
  const mine = deep.filter(r => r.player === name);
  /* Null, not an empty array.
     An empty array is truthy in JavaScript, so returning one made the caller
     treat "this player does not appear in the deep set" as "the deep set is
     the answer, and the answer is nothing" -- and the form window's meetings
     were never consulted. A player who is missing from the deeper fetch
     because a single lineup 404'd, or because he was not in the squad list
     when it was read, would silently lose a head-to-head he actually has. */
  return mine.length ? mine : null;
}

/* Match ids in which this team faced the other one, across everything
   fetched rather than the current Matches filter. Two sides meet twice a
   season, so cutting that to "last 10" would usually leave nothing. */
function meetingIds(teamIndex, fx = DATA) {
  const oppId = opponentIdFor(teamIndex, fx);
  if (oppId === null) return null;
  const ids = new Set((fx.records[teamIndex] || [])
    .filter(m => m.opponent_id === oppId).map(m => m.id));
  return ids.size ? ids : null;
}

function hasPlayers() {
  return Array.isArray(DATA.players) && DATA.players.some(r => r.length);
}

/* Team records store stats as {period: {name: value}}. Player records are
   flat, because SofaScore only reports player numbers for the whole match.

   Every record also carries an `against` block: what the opposition managed
   in that match. It comes from the same payload at no extra cost, and it is
   what lets you ask the question that actually matters, which is whether one
   team's attack meets the other team's leak. */
function bucketFor(index) {
  if (measure === "for") return "stats";
  if (measure === "against") return "against";
  return index === 0 ? "stats" : "against";   // matchup
}

function statValue(record, statName, which) {
  const key = which || "stats";
  const block = record[key];
  // No silent fallback. An older report has no `against` block, and quietly
  // showing the `for` numbers in its place would be indistinguishable from
  // real data, which is worse than showing nothing.
  if (!block) return undefined;
  const bucket = block[period] || block;
  return bucket ? bucket[statName] : undefined;
}

function hasAgainst() {
  return DATA.records.some(rows => rows.some(r => r.against));
}

/* A team promoted, relegated, or arriving from a cup run carries a record
   built against different opposition. Coventry putting up 12 shots a game in
   the Championship says very little about Coventry away at Arsenal, but the
   hit rate looks identical either way, which is how a 100% record turns into
   a losing bet. This does not adjust for it, because doing that honestly
   needs a model. It flags it, so the number is read with the right amount of
   suspicion. */
function sampleMix(teamIndex) {
  const rows = filtered(activeRecords()[teamIndex]);
  const counts = {};
  rows.forEach(r => {
    const c = r.competition || "?";
    counts[c] = (counts[c] || 0) + 1;
  });
  const fixtureComp = DATA.fixture.competition;
  const matching = counts[fixtureComp] || 0;
  return {
    total: rows.length,
    matching,
    counts,
    mismatched: rows.length > 0 && matching / rows.length < 0.6,
  };
}

/* Whether this fixture pairs clubs from different domestic leagues.

   In a Champions League tie both clubs' records are domestic, because that is
   all that exists: eight European matches a season at most, none of them on
   matchday one. The mismatch filter below is built for the opposite problem,
   a promoted club carrying a Championship record into the Premier League, and
   applied here it throws away every row on the page and leaves a report that
   looks blank rather than caveated. So the filter is switched off for these,
   and the warning is left switched on. Older reports predate the flag and
   re-render without it, which reads as false and keeps the old behaviour. */
function isCrossLeague(fx) {
  return !!(fx && fx.fixture && fx.fixture.crossLeague);
}

/* Two months without a competitive match, and the page says so.

   Sixty days clears a winter break and an international window, and catches
   the thing that actually matters: a season opener priced off last season.
   The numbers below are real and were true when they were set; what they are
   not is current. Nothing else on this page carries a date, so without this
   a February hit rate reads exactly like a Tuesday one. */
function staleWarning() {
  const days = DATA.fixture && DATA.fixture.staleDays;
  if (!days || days < 60) return "";
  const months = Math.round(days / 30);
  return `<div class="warn">
    <strong>Last season's numbers.</strong> The most recent match behind these
    figures was <strong>${days} days</strong> ago &mdash; roughly ${months}
    months &mdash; so this is a first outing priced off an old sample. Squads,
    starters and coaching staff all move in a gap that size, and a player's
    share of the work is the first thing to change. Treat every line here as a
    starting point rather than an answer, and do your own due diligence before
    staking anything on it.
  </div>`;
}

function mismatchWarning() {
  // A darts player's form is every PDC event he has played, by design: no
  // single event has enough matches. The football warning about clubs from
  // different leagues is wrong here, so say the one thing that does matter.
  if (SPORT === "darts") {
    return `<p class="note">Form is each player's last 20 PDC matches across
      every event. Floor and Euro Tour matches are short (best of 11 legs) and
      majors are longer, so 180 and 100+ checkout counts move with match
      length as much as with form.</p>`;
  }
  const notes = [];
  DATA.records.forEach((rows, i) => {
    const mix = sampleMix(i);
    if (!mix.mismatched) return;
    const where = Object.entries(mix.counts)
      .sort((a, b) => b[1] - a[1])
      .map(([c, n]) => `${n} in ${c}`)
      .join(", ");
    notes.push(`<strong>${DATA.teams[i].name}</strong>: ${where}`);
  });

  if (!notes.length) return "";

  return `<div class="warn">
    <strong>Different opposition.</strong> These figures were not built against
    the standard of side they face here: ${notes.join("; ")}.
    A record set in another competition can be perfectly true and still a poor
    guide, because the hit rate carries no memory of who it was set against.
    Treat anything at 90% or 100% here with real suspicion.
    ${isCrossLeague(DATA) ? `<br><br>Expected here, not a fault in the data:
    the two clubs come from different leagues, so domestic form is the only
    sample either of them has. Rows are kept rather than filtered out, but
    they score nothing for context and carry no opponent-adjusted price.` : ""}
  </div>`;
}

/* Why a projection is missing. The opponent-adjusted model can only rate a
   team against opponents it has also rated, so a promoted club with ten
   Championship matches on file has almost nothing usable. Left unsaid, that
   showed up as Coventry projected for more corners at the Emirates than
   Arsenal, off a single match. Saying it out loud is the fix. */
function ratingsWarning() {
  const notes = DATA.ratingNotes || [];
  if (!notes.length) return "";
  const tp = DATA.tierProjection;
  const fallback = tp
    ? ` Instead, the <b>est</b> figures come from ${DATA.tierProjectionFrom}'s
        own record against bottom-tier sides: ${tp.matches}
        match${tp.matches === 1 ? "" : "es"}${tp.venue ? ` at ${tp.venue}` : ""}
        against ${tp.opponents.join(", ")}. That uses no data at all from the
        promoted side, which is the point, because their data is the part
        that does not carry across divisions. Hover any estimate to see the
        matches behind it.`
    : "";

  return `<div class="warn">
    <strong>No adjusted projection.</strong> ${notes.join("; ")}.
    The raw hit rates below are still real, but nothing has corrected them
    for the standard of opposition, so read them as what happened rather
    than what to expect.${fallback}
  </div>`;
}

function summarise(rows, statName, line, which) {
  const vals = rows.map(r => statValue(r, statName, which))
                   .filter(v => v !== undefined && v !== null);
  if (!vals.length) return null;
  const hits = vals.filter(v => v > line).length;
  return { vals, hits, pct: Math.round((hits / vals.length) * 100) };
}

function sparkline(rows, statName, line, colorVar, which) {
  const points = rows
    .map(r => ({ v: statValue(r, statName, which), r }))
    .filter(p => p.v !== undefined && p.v !== null);

  if (points.length < 2) return "";

  const W = 116, H = 38, PAD = 6;
  const vals = points.map(p => p.v).concat([line]);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const span = (hi - lo) || 1;

  const x = i => PAD + (i * (W - 2 * PAD)) / (points.length - 1);
  const y = v => H - PAD - ((v - lo) / span) * (H - 2 * PAD);

  const path = points.map((p, i) => `${x(i)},${y(p.v)}`).join(" ");

  /* Dots carry hit or miss against the line, so you can count them without
     doing arithmetic. Colour is not doing that job alone: a hit is a filled
     dot above the dashed line, a miss is a hollow one below it. That keeps
     it readable in greyscale and for red-green colour blindness, which this
     pair is exactly the wrong choice for on its own. The polyline stays in
     the team's colour, so identity is still carried. */
  const dots = points.map((p, i) => {
    const hit = p.v > line;
    const comp = p.r.competition ? ` &middot; ${p.r.competition}` : "";
    const tipText = `${p.r.date} ${p.r.venue === 'home' ? 'H' : 'A'} v ${p.r.opponent}`
      + ` &middot; ${p.v} &middot; ${hit ? 'over' : 'under'} ${line}${comp}`;
    return hit
      ? `<circle cx="${x(i)}" cy="${y(p.v)}" r="4" fill="var(--hit)"
           stroke="var(--surface-1)" stroke-width="1.5"
           data-tip="${tipText}"></circle>`
      : `<circle cx="${x(i)}" cy="${y(p.v)}" r="3.5" fill="var(--surface-1)"
           stroke="var(--miss)" stroke-width="2"
           data-tip="${tipText}"></circle>`;
  }).join("");

  return `<svg class="spark" width="${W}" height="${H}" role="img"
      aria-label="${statName}, oldest to newest">
    <line x1="0" y1="${y(line)}" x2="${W}" y2="${y(line)}"
      stroke="var(--baseline)" stroke-width="1" stroke-dasharray="3 3"></line>
    <polyline points="${path}" fill="none" stroke="var(${colorVar})"
      stroke-width="2" stroke-linejoin="round" stroke-linecap="round"></polyline>
    ${dots}
  </svg>`;
}

function sideHtml(rows, statName, line, index) {
  const letter = index === 0 ? "a" : "b";
  const colorVar = VARS[index];
  const which = bucketFor(index);
  const suffix = measure === "for" ? ""
    : (which === "against" ? " conceded" : " for");
  const tag = `<span class="team-tag">
      <span class="swatch" style="background:var(${colorVar})"></span>
      ${DATA.teams[index].name}${suffix}
    </span>`;

  const s = summarise(rows, statName, line, which);
  if (!s) {
    return `<div class="side ${letter}">${tag}
      <span class="empty">no data</span></div>`;
  }

  const seq = s.vals.map(v => (Number.isInteger(v) ? v : v.toFixed(1))).join(", ");

  return `<div class="side ${letter}">
    ${tag}
    <div class="figure">
      <div><span class="pct">${s.pct}%</span>
           <span class="frac">${s.hits}/${s.vals.length}</span></div>
      <div class="bar"><div class="fill"
        style="width:${s.pct}%;background:var(${colorVar})"></div></div>
    </div>
    ${sparkline(rows, statName, line, colorVar, which)}
    <span class="seq">${seq}</span>
  </div>`;
}

/* The projection answers the question a hit rate cannot: what should this
   team actually do in THIS fixture, against THIS opponent. It comes from the
   fitted attack and defence ratings, so a promoted side's flattering record
   gets discounted by the quality of who they are about to play.

   Flagged in red when the projection lands on the opposite side of the line
   from the record, because that is exactly the case worth catching: a true
   100% that the model expects to fail. */
function projectionHtml(name, line) {
  let proj = (DATA.projection || {})[period];
  let fromTier = false;

  // No fitted projection means one side could not be rated, which in
  // practice means they are promoted. Fall back to what the rated side does
  // to teams of that standard. Only the full match is available that way,
  // because the tier record is kept whole rather than split by half.
  if ((!proj || !proj[name]) && DATA.tierProjection && period === "ALL") {
    proj = DATA.tierProjection.stats;
    fromTier = true;
  }

  if (!proj || !proj[name] || line === undefined) return "";

  const values = proj[name];
  const teamRows = activeRecords().map(filtered);
  const shown = focusedIndexes();
  let conflict = false;

  shown.forEach(i => {
    const value = values[i];
    const s = summarise(teamRows[i], name, line, bucketFor(i));
    if (!s || value === undefined) return;
    const recordSaysOver = s.pct >= 60;
    const recordSaysUnder = s.pct <= 40;
    if ((recordSaysOver && value < line) || (recordSaysUnder && value > line)) {
      conflict = true;
    }
  });

  const text = shown.length === 1
    ? `<b>${values[shown[0]]}</b>`
    : `<b>${values[0]}</b> v <b>${values[1]}</b>`;

  const tp = DATA.tierProjection;
  const label = fromTier ? "est" : "proj";
  const why = fromTier
    ? `${DATA.tierProjectionFrom} against bottom-tier sides, `
      + `${tp.matches} match${tp.matches === 1 ? "" : "es"}`
      + (tp.venue ? ` at ${tp.venue}` : ", home and away")
      + `: ${tp.opponents.join(", ")}`
    : "Expected in this fixture, from opponent-adjusted ratings";

  return `<div class="proj${conflict ? " conflict" : ""}${fromTier ? " est" : ""}"
    title="${why}">
    ${label} ${text}${conflict ? " (record disagrees)" : ""}</div>`;
}

function visibleStats() {
  const lines = activeLines();
  let stats = activeStats().filter(n => lines[n] !== undefined);

  if (scope === "core") {
    const core = stats.filter(n => CORE_STATS.includes(n));
    if (core.length) stats = core;
  }

  const teamRows = activeRecords().map(filtered);

  const strength = name => {
    const line = lines[name];
    return Math.max(...teamRows.map((rows, i) => {
      const s = summarise(rows, name, line, bucketFor(i));
      return s ? Math.abs(s.pct - 50) : 0;
    }));
  };

  if (strongOnly) {
    stats = stats.filter(n => {
      const line = lines[n];
      return teamRows.some((rows, i) => {
        const s = summarise(rows, n, line, bucketFor(i));
        return s && (s.pct >= STRONG_HIGH || s.pct <= STRONG_LOW);
      });
    });
  }

  if (sort === "strongest") {
    stats = stats.slice().sort((a, b) => strength(b) - strength(a));
  }

  return stats;
}

function focusedIndexes() {
  return focus === "both" ? [0, 1] : [parseInt(focus, 10)];
}

function updateRow(row) {
  const name = row.dataset.stat;
  const line = activeLines()[name];
  const teamRows = activeRecords().map(filtered);
  const shown = focusedIndexes();

  row.querySelectorAll(".side").forEach(el => el.remove());
  row.classList.toggle("solo", shown.length === 1);
  const middle = row.querySelector(".middle");

  if (shown.length === 1) {
    middle.insertAdjacentHTML("afterend", sideHtml(teamRows[shown[0]], name, line, shown[0]));
  } else {
    middle.insertAdjacentHTML("beforebegin", sideHtml(teamRows[0], name, line, 0));
    middle.insertAdjacentHTML("afterend", sideHtml(teamRows[1], name, line, 1));
  }

  const strong = shown.some(i => {
    const s = summarise(teamRows[i], name, line, bucketFor(i));
    return s && (s.pct >= STRONG_HIGH || s.pct <= STRONG_LOW);
  });
  row.classList.toggle("strong", strong);

  const suggested = source === "h2h"
    ? (SUGGESTED_H2H[period] || {})[name]
    : (SUGGESTED[period] || {})[name];
  row.querySelector("input[data-line]").classList
    .toggle("edited", line !== suggested);
}

function updateAll() {
  boardEl.querySelectorAll(".stat-row").forEach(updateRow);
  teamCards();
  const teamRows = activeRecords().map(filtered);
  document.getElementById("sample").textContent =
    teamRows.map((r, i) => `${DATA.teams[i].name}: ${r.length} matches`)
            .join(" \\u00b7 ") + ".";
}

function setLine(row, value) {
  const clean = snapLine(value);
  activeLines()[row.dataset.stat] = clean;
  row.querySelector("input[data-line]").value = clean;
  updateRow(row);
}

function render() {
  const lines = activeLines();
  const stats = visibleStats();

  if (!stats.length) {
    boardEl.innerHTML =
      '<div class="stat-row"><div class="empty">Nothing matches these filters.</div></div>';
    updateSample();
    updateFilterSummary();
    return;
  }

  boardEl.innerHTML = stats.map(name => `
    <div class="stat-row" data-stat="${name}">
      <div class="middle">
        <div class="stat-label">${name}</div>
        <div class="stepper">
          <button type="button" data-step="-1" title="Lower the line by 1">&minus;</button>
          <input type="number" step="1" min="0.5" value="${lines[name]}"
                 data-line aria-label="Line for ${name}">
          <button type="button" data-step="1" title="Raise the line by 1">+</button>
        </div>
        ${projectionHtml(name, lines[name])}
      </div>
    </div>`).join("");

  document.getElementById("mismatch").innerHTML =
    staleWarning() + mismatchWarning() + ratingsWarning();
  updateAll();
  updateFilterSummary();
}

function updateSample() {
  const teamRows = activeRecords().map(filtered);
  document.getElementById("sample").textContent =
    teamRows.map((r, i) => `${DATA.teams[i].name}: ${r.length} matches`)
            .join(" \\u00b7 ") + ".";
}

/* --------------------------------------------------------------- standout

   Ranking by raw hit rate is the obvious approach and it is wrong, because
   5/5 outranks 18/20 while being far weaker evidence. These two functions
   fix that.

   wilsonLow gives the bottom of a 95% confidence interval, so a small
   sample is penalised for being small: 5/5 scores 0.57, 10/10 scores 0.72,
   20/20 scores 0.84. Ranking by it puts durable records above lucky ones.

   binomTail answers the question that actually matters: if this stat were a
   coin flip, how often would a record this good turn up anyway? Scanning
   1,400-odd combinations at ten matches each, roughly 15 will reach 9/10 by
   chance alone. Without that number on screen, a list of "strong" lines is
   indistinguishable from a list of flukes. */

function wilsonLow(k, n, z) {
  if (!n) return 0;
  z = z || 1.96;
  const p = k / n;
  const d = 1 + (z * z) / n;
  const centre = p + (z * z) / (2 * n);
  const margin = z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n));
  return (centre - margin) / d;
}

function binomTail(n, k) {
  // P(X >= k) for n fair coin flips, computed in logs to stay accurate.
  const logFact = [0];
  for (let i = 1; i <= n; i++) logFact[i] = logFact[i - 1] + Math.log(i);
  let total = 0;
  for (let i = k; i <= n; i++) {
    total += Math.exp(
      logFact[n] - logFact[i] - logFact[n - i] + n * Math.log(0.5)
    );
  }
  return total;
}

/* Turning a hit rate into a price is one division, and that is exactly why
   it is dangerous. 8/10 implies a fair price of 1.25, which looks like free
   money, but ten matches cannot tell 80% from 55%. Run the interval and the
   evidence only supports 2.04 or better.

   So two numbers are quoted. `fair` is what the point estimate says, and it
   is the optimistic one. `minPrice` comes from the bottom of the confidence
   interval and is the number to actually bet off, because it is the price at
   which you are still ahead if your sample flattered the team.

   Neither includes the bookmaker's margin. A real market is priced so the
   implied probabilities sum to more than 100%, typically 105-108% on these,
   so the available price is always worse than fair by design. */
function fairOdds(p) { return p > 0 ? 1 / p : Infinity; }

function fmtOdds(o) {
  // null has to be caught before isFinite, which says a null is finite --
  // it coerces to zero -- and then toFixed is called on nothing and the
  // whole panel dies. A leg that has never landed once legitimately has no
  // price, and "\u2014" says that without taking the page down with it.
  if (o === null || o === undefined) return "\u2014";
  if (typeof o !== "number" || !isFinite(o)) return "n/a";
  return o >= 10 ? o.toFixed(0) : o.toFixed(2);
}

/* ------------------------------------------------------------ count model

   The old `need` price looked only at how many matches went over the line and
   how many did not. That throws away almost everything: 4,5,3,6,4 corners and
   2,2,2,2,2 corners are both "5 from 5 over 1.5", and one of them is far
   safer than the other. It also never looked at the opponent, so Arsenal at
   home to Coventry priced the same as Arsenal away at City.

   So the price now comes from a count model instead:

     1. Take the opponent-adjusted expectation for this team in this fixture.
        That is the projection already on the page: league average times this
        team's attack rating times this opponent's defence rating, off the
        right home or away base. This is where the mismatch enters.

     2. Fit the spread from the team's own matches. If the variance is close
        to the mean, counts behave like a Poisson process and Poisson is used.
        If the variance is bigger, which is normal for shots, the negative
        binomial handles the extra spread rather than pretending it is not
        there and quoting a price that is too short.

     3. Read the probability straight off that distribution: for a line of
        1.5, P(X >= 2).

     4. Haircut for the fact that the expectation is itself estimated, by
        recomputing at the bottom of a one-sided 95% interval on the mean.

   The result moves continuously with the matchup, which is the entire point.
   A dominant side against a poor one lands near 1.07; a coin flip lands near
   2.00; and two different 19-from-20 records no longer both come out at
   1.31. */

const LG_C = [676.5203681218851, -1259.1392167224028, 771.32342877765313,
              -176.61502916214059, 12.507343278686905, -0.13857109526572012,
              9.9843695780195716e-6, 1.5056327351493116e-7];

function logGamma(z) {
  if (z < 0.5) return Math.log(Math.PI / Math.sin(Math.PI * z)) - logGamma(1 - z);
  z -= 1;
  let x = 0.99999999999980993;
  for (let i = 0; i < 8; i++) x += LG_C[i] / (z + i + 1);
  const t = z + 7.5;
  return 0.5 * Math.log(2 * Math.PI) + (z + 0.5) * Math.log(t) - t + Math.log(x);
}

function poissonCdf(k, mean) {
  if (mean <= 0) return 1;
  if (k < 0) return 0;
  let term = Math.exp(-mean), sum = term;
  for (let i = 1; i <= k; i++) { term *= mean / i; sum += term; }
  return Math.min(1, sum);
}

function negBinCdf(k, mean, size) {
  if (mean <= 0) return 1;
  if (k < 0) return 0;
  const p = size / (size + mean);
  let sum = 0;
  for (let i = 0; i <= k; i++) {
    sum += Math.exp(logGamma(i + size) - logGamma(i + 1) - logGamma(size)
                    + size * Math.log(p) + i * Math.log1p(-p));
  }
  return Math.min(1, sum);
}

function logChoose(n, k) {
  return logGamma(n + 1) - logGamma(k + 1) - logGamma(n - k + 1);
}

function binomCdf(k, n, p) {
  if (k < 0) return 0;
  if (k >= n) return 1;
  p = Math.min(1, Math.max(0, p));
  let sum = 0;
  for (let i = 0; i <= k; i++) {
    sum += Math.exp(logChoose(n, i) + i * Math.log(p) + (n - i) * Math.log1p(-p));
  }
  return Math.min(1, sum);
}

/* Variance over mean, pulled towards 1 by how little data there is.

   The ratio picks the distribution, and on a short sample it is itself a noisy
   estimate. Six matches of a player's shots gave a raw ratio of 0.46, which is
   more certainty than six numbers can support, and taking it literally priced
   a bet at 1.20 when the market was near 1.29. Shrunk with a prior of 8 the
   same sample gives 0.77, and a price of 1.29. */
const DISPERSION_PRIOR = 8;

function dispersion(vals) {
  const n = vals.length;
  if (n < 3) return 1;
  const m = vals.reduce((s, v) => s + v, 0) / n;
  if (m <= 0) return 1;
  const v = vals.reduce((s, x) => s + (x - m) * (x - m), 0) / (n - 1);
  return 1 + (n / (n + DISPERSION_PRIOR)) * (v / m - 1);
}

/* P(count > line) for a half-integer line. A line of 1.5 means 2 or more, so
   the question is P(X <= 1), hence the floor.

   Three distributions, chosen by how spread out the counts actually are:
   negative binomial when the variance beats the mean, which is normal for team
   shots; Poisson when they match; binomial when the variance is smaller, which
   is normal for a regular starter who takes two or three shots most weeks and
   almost never none.

   That third case was missing and its absence was expensive. Poisson on an
   underdispersed count puts far too much weight below the line: for a player
   expected to take 2.6 shots it assumes a 7% chance of taking none, which for
   a starting winger does not happen, and every player price came out long. */
function predictiveRatio(vals, expected) {
  const n = vals.length;
  if (n < 3 || expected <= 0) return dispersion(vals);
  const mean = vals.reduce((s, v) => s + v, 0) / n;
  if (mean <= 0) return dispersion(vals);
  const v = vals.reduce((s, x) => s + (x - mean) * (x - mean), 0) / (n - 1);
  const se = Math.sqrt(Math.max(v, 1e-9) / n) * (expected / mean);
  return (expected * dispersion(vals) + se * se) / expected;
}

function probOver(line, mean, vals, ratioIn) {
  if (mean <= 0) return 0;
  const k = Math.floor(line);
  const ratio = ratioIn === undefined ? dispersion(vals) : ratioIn;

  if (ratio > 1.05) {
    const size = mean / (ratio - 1);
    if (isFinite(size) && size > 0) return 1 - negBinCdf(k, mean, size);
  }

  if (ratio < 0.95) {
    const p = 1 - ratio;
    const trials = Math.max(2, Math.round(mean / p));
    if (trials > k) return 1 - binomCdf(k, trials, mean / trials);
  }

  return 1 - poissonCdf(k, mean);
}

/* Shrinkage of the model's stated log-odds towards its fixed point, fitted on
   the 4,197 settled model-priced Premier League bets the backtest produces at
   the production window of 38 matches, 2025-10-03 to 2026-08-29. The backtest
   said the count distributions are too narrow in the tail: bets called 90%
   landed 81%, bets called 95% landed 84%, bets near 60% were right. This is
   the exact mirror of calibrate() in model.py -- change one, run verify.py,
   change the other. The slope depends on the form window (a 10-match window
   fitted near 0.30), so refit if `games` changes in update.json. */
const CALIBRATION_A = 0.1813;
const CALIBRATION_B = 0.5647;

function calibrate(p) {
  p = Math.min(1 - 1e-9, Math.max(1e-9, p));
  const z = CALIBRATION_A + CALIBRATION_B * Math.log(p / (1 - p));
  return 1 / (1 + Math.exp(-z));
}

/* One place that turns a row into a price, so the slip, the best bets and the
   standout list cannot disagree with each other.

   `p` is the probability of the bet landing, `fair` is what that is worth, and
   `need` is what you should insist on before staking. When the fixture has an
   opponent-adjusted expectation the count model supplies all three. When it
   does not, which means one side could not be rated, it falls back to the old
   record-only interval and says so, because a made-up expectation would be
   worse than an honest blunt one. */
function priceRow(r) {
  const values = (r.forVals || r.vals || []);
  const expected = expectedFor(r);

  if (expected !== undefined && expected > 0 && values.length >= 3) {
    const n = values.length;
    const mean = values.reduce((s, v) => s + v, 0) / n;
    const variance = values.reduce((s, x) => s + (x - mean) * (x - mean), 0) / (n - 1);
    const se = Math.sqrt(Math.max(variance, 1e-9) / n);

    // One-sided 95% band on the expectation. The projection is an estimate,
    // and pricing off the point estimate assumes it is exact.
    //
    // The band is clipped to half and double the expectation. Ten matches of a
    // noisy stat can produce a standard error big enough to drag the lower
    // bound to nothing, and a bound of nothing prices everything at 20.0,
    // which is not caution, it is just noise wearing caution's clothes. A
    // fifty per cent haircut is already a severe one.
    // `need` widens the distribution to account for the expectation being
    // estimated, rather than moving its centre. See predictiveRatio.
    const wide = predictiveRatio(values, expected);
    let p = probOver(r.line, expected, values);
    let widened = probOver(r.line, expected, values, wide);
    if (!r.over) { p = 1 - p; widened = 1 - widened; }
    const pLow = Math.min(p, widened);

    // Both ends of the interval on the expectation, so a contradiction can be
    // detected rather than priced. If the record's own lower bound sits above
    // everything the model will allow even at its most generous, then one of
    // the two is wrong and neither should be trusted. That happens when a
    // ratings fit produces something absurd, like an expectation of 0.03
    // first-half offsides for a team that gets one nearly every half.
    const pHigh = Math.max(p, widened);

    // A second, blunter sanity check on the expectation itself. An opponent
    // adjustment should move a team's average, that is its whole job, but it
    // should not halve it or double it. When it does, the ratings fit for that
    // stat and period has gone wrong rather than found something. The case
    // that exposed this was an expected 0.46 second-half offsides for a side
    // that had gone over 0.5 in thirteen of twenty, which then priced at 21.
    const absurd = expected < 0.5 * mean || expected > 2 * mean;

    const conflict = absurd || r.score > pHigh + 0.05;

    // Calibration is applied last, to the quoted numbers only. The conflict
    // checks compare the record against the model's raw ceiling, which is a
    // question about whether the two views cohere, not about how much to
    // trust the confident one, so they stay on the uncalibrated values and
    // the set of bets surfaced does not change. Both p and the widened
    // probability pass through the same monotone map, so `need` keeps its
    // place on the pessimistic side of `fair`.
    p = calibrate(p);
    const pLowCal = calibrate(pLow);

    return {
      p, fair: fairOdds(p), need: fairOdds(Math.max(0.01, pLowCal)),
      expected, source: "model", conflict,
      recordFair: fairOdds(r.k / r.n), recordNeed: fairOdds(r.score),
    };
  }

  const recordP = calibrateRecord(smoothRate(r.k, r.n), "team");
  return {
    p: recordP, fair: fairOdds(recordP), need: fairOdds(r.score),
    expected: undefined, source: "record",
    recordFair: fairOdds(r.k / r.n), recordNeed: fairOdds(r.score),
  };
}

/* The opponent-adjusted expectation for the team this bet is on. Falls back to
   the cross-division estimate when the fitted one is missing. */
function expectedFor(r) {
  const fx = ALL.fixtures[r.fixtureIndex];
  if (!fx) return undefined;
  const idx = r.teamIndex;

  const fitted = ((fx.projection || {})[r.period] || {})[r.stat];
  if (fitted && fitted[idx] !== undefined) return fitted[idx];

  if (r.period === "ALL" && fx.tierProjection) {
    const est = (fx.tierProjection.stats || {})[r.stat];
    if (est && est[idx] !== undefined) return est[idx];
  }
  return undefined;
}

const VENUE_SPLITS = [
  { key: "all", label: "All matches" },
  { key: "home", label: "At home" },
  { key: "away", label: "Away" },
];

function scanLines(minSample) {
  const found = [];
  let combos = 0;
  let skipped = 0;

  scanFixtures().forEach(([fx, fxIndex]) => {
    Object.keys(fx.lines || {}).forEach(per => {
      const lines = fx.lines[per] || {};
      (fx.stats[per] || []).forEach(name => {
        if (!BETTABLE.has(name)) return;
        const line = lines[name];
        if (line === undefined) return;

        fx.records.forEach((records, teamIndex) => {
          // Skip teams whose record was built in another competition. This
          // is the Coventry case: a true 100% that will not survive contact
          // with the division they are actually playing in.
          if (!includeMismatched && !isCrossLeague(fx)) {
            const sample = records.slice(-games);
            const matching = sample.filter(
              r => (r.competition || "?") === fx.fixture.competition
            ).length;
            if (sample.length && matching / sample.length < 0.6) { skipped++; return; }
          }

          // Best split per team/stat/period, so one pattern is one row
          // rather than three near-identical ones.
          let best = null;

          // Darts has no venue: "home" is whoever SofaScore lists first, so a
          // home/away split halves a player's form for nothing.
          (SPORT === "darts" ? VENUE_SPLITS.slice(0, 1) : VENUE_SPLITS).forEach(split => {
            let rows = records;
            if (split.key !== "all") rows = rows.filter(r => r.venue === split.key);
            rows = rows.slice(-games);

            const vals = rows
              .map(r => (r.stats[per] || {})[name])
              .filter(v => v !== undefined && v !== null);

            if (vals.length < minSample) return;
            combos++;

            const over = vals.filter(v => v > line).length;
            const under = vals.length - over;
            const goingOver = over >= under;
            const k = goingOver ? over : under;

            const score = wilsonLow(k, vals.length);
            if (!best || score > best.score) {
              best = {
                score,
                k, n: vals.length,
                over: goingOver,
                chance: binomTail(vals.length, k),
                split: split.label,
                vals,
              };
            }
          });

          if (best) {
            found.push(Object.assign(best, {
              fixture: `${fx.fixture.home} v ${fx.fixture.away}`,
              fixtureIndex: fxIndex,
              team: fx.teams[teamIndex].name,
              teamIndex,
              stat: name,
              period: per,
              line,
            }));
          }
        });
      });
    });
  });

  found.sort((a, b) => b.score - a.score);
  return { found, combos, skipped };
}

/* ----------------------------------------------------------- player prices

   Same count model as the team bets, applied to one player's match-by-match
   numbers. Shots, tackles and fouls are counts and behave like counts, so
   there is no reason to price them any differently.

   The one thing that has to be handled separately is the opponent. There is
   no per-player rating, and fitting one from ten matches would be inventing
   precision. What there is, is the team's own opponent adjustment for the
   same stat: if Arsenal are expected to take 40% more shots than usual in
   this fixture, it is reasonable that their forwards are too. So the player's
   average is scaled by that ratio, clipped so a wild team projection cannot
   drag a player somewhere silly.

   Where the team has no projection, the player's raw average is used and the
   price is marked "record only", exactly as for a team bet. */

const PLAYER_STAT_TO_TEAM = {
  "Shots": "Total shots",
  "Shots on target": "Shots on target",
  "Tackles": "Tackles",
  "Fouls": "Fouls",
  "Goals": "Goals",

  // --- American football -------------------------------------------------
  // The own-team market whose volume drives the player's number. Only the
  // offensive ones have an honest pairing: a receiver's yards ride on the
  // team's passing game, a back's carries on the team's carries. Sacks and
  // tackles are driven by how often the OPPOSITION runs a play, and there is
  // no own-team market for that, so they are deliberately absent and their
  // adjustment stays neutral. Inventing a pairing to let them through the
  // scan would be a lie told to a gate.
  "Passing yards": "Net yards passing",
  "Passing attempts": "Net yards passing",
  "Passing completions": "First downs by passing",
  "Passing touchdowns": "Passing touchdowns",
  "Passing interceptions": "Interceptions thrown",
  "Rushing yards": "Rushing yards",
  "Rushing attempts": "Rushing attempts",
  "Rushing touchdowns": "Touchdowns",
  "Receiving yards": "Net yards passing",
  "Receiving receptions": "First downs by passing",
  "Receiving targets": "First downs by passing",
  "Receiving touchdowns": "Passing touchdowns",
  "Kicking total points": "Points",
  "Kicking fg made": "Field goals",

  // Derived markets. Anytime Touchdown rides on how many the team scores,
  // which is the honest pairing and the one bet365's own price moves with.
  // Passing and Rushing Yards is dominated by the passing half for every
  // quarterback who is not a running threat, so it pairs there.
  //
  // Rushing and Receiving Yards is deliberately absent. It straddles the
  // running game and the passing game, the mix is different for a back and
  // a slot receiver, and no single own-team market drives it. Same rule as
  // sacks and tackles: no honest pairing, no adjustment, rather than a
  // made-up one to get it through the gate.
  "Anytime touchdown": "Touchdowns",
  "Passing and rushing yards": "Net yards passing",

  // --- basketball ---------------------------------------------------------
  // Straightforward for once: a player's points ride on how many the team
  // scores, his rebounds on how many the team takes. The combination props
  // follow their dominant half -- points-rebounds-assists is mostly points.
  // Steals and blocks is deliberately absent: it straddles two team markets
  // and neither drives it.
  "Points": "Points",
  "Rebounds": "Rebounds",
  "Assists": "Assists",
  "Three pointers made": "3 pointers",
  "Steals": "Steals",
  "Blocks": "Blocks",
  "Turnovers": "Turnovers",
  "Points rebounds and assists": "Points",
  "Points and rebounds": "Points",
  "Points and assists": "Points",
  "Rebounds and assists": "Rebounds",

  // --- baseball -----------------------------------------------------------
  // Batting props ride on the own lineup's output. Pitcher props are absent:
  // the opposing lineup drives them and there is no own-team market for it.
  "Hits": "Hits",
  "Singles": "Hits",
  "Doubles": "Hits",
  "Total bases": "Hits",
  "Home runs": "Home runs",
  "RBIs": "Runs",
  "Runs": "Runs",
  "Hits runs and RBIs": "Runs",
};

/* Which player markets the scan will consider at all.

   Separate from the map above on purpose. That map answers "what team volume
   drives this player's number", and playerAdjustment already returns a
   neutral 1 when there is no answer. Using it as the eligibility gate as well
   conflated the two, and the cost was that every NFL prop bailed out on the
   first line of the scan: no pairing, no bet, however good the record. A
   sacks record is perfectly scannable; what it is not is adjustable, because
   sacks ride on how often the opposition runs a play and no own-team market
   measures that. Injected per sport so football's list is exactly what it
   always was. */
const PLAYER_SCAN_ALLOW = new Set(__PLAYER_SCAN_ALLOW__);

/* When there is no projection for the match, the odds stand in for it.

   A projection needs both sides rated on one scale, which a cross-league
   game (every Champions League tie, most cup ties) does not have, so
   playerAdjustment() used to fall back to 1 there: no adjustment at all.
   AEK Athens' forwards were priced off their Greek league shots as though
   Manchester City were a Greek side, and a 2.6-shot Varga came out at 50%
   for 3+ shots at the Etihad (20 Oct 2026).

   Betfair's match odds already rate both sides on one scale. They are
   turned into each side's expected goals (a Poisson fit to home, draw and
   away), and the side's expected goals in this game over its own goals per
   game is the adjustment. Shots fall less than goals against a strong side
   (more of them blocked or from distance), so shots take the ratio to the
   power 0.7 and shots on target to 0.8; goals take it whole. Not
   backtested: an informed default, and the page says when it is in use.
   Tackles and fouls stay neutral, as before. */
const ODDS_ADJ_POWER = { "Total shots": 0.7, "Shots on target": 0.8, "Goals": 1 };
const LAMBDA_CACHE = new Map();

function goalLambdas(fx = DATA) {
  const id = fx && fx.fixture ? String(fx.fixture.id) : null;
  if (!id || !MARKETS) return null;
  if (LAMBDA_CACHE.has(id)) return LAMBDA_CACHE.get(id);
  const o = (MARKETS[id] || {}).match;
  const ph = o && o.home && o.home.p, pd = o && o.draw && o.draw.p, pa = o && o.away && o.away.p;
  let best = null;
  if (ph > 0 && pd > 0 && pa > 0) {
    const pois = l => {
      const out = [Math.exp(-l)];
      for (let k = 1; k <= 10; k++) out.push(out[k - 1] * l / k);
      return out;
    };
    let err = Infinity;
    for (let lh = 0.15; lh <= 4.5; lh += 0.05) {
      const h = pois(lh);
      for (let la = 0.15; la <= 4.5; la += 0.05) {
        const a = pois(la);
        let H = 0, D = 0, A = 0;
        for (let i = 0; i <= 10; i++) for (let j = 0; j <= 10; j++) {
          const q = h[i] * a[j];
          if (i > j) H += q; else if (i === j) D += q; else A += q;
        }
        const e = (H - ph) * (H - ph) + (D - pd) * (D - pd) + (A - pa) * (A - pa);
        if (e < err) { err = e; best = [lh, la]; }
      }
    }
  }
  LAMBDA_CACHE.set(id, best);
  return best;
}

/* Basketball's version, and a better one: Paddy Power prices each side's
   points total directly, so there is no Poisson fit to do. The over and
   under at the main line, margin removed, say how far the market's
   expectation sits from the line (team points spread about 12 a game), and
   that over the side's own points per game is the adjustment. Points take it
   whole; assists and threes ride most of it (more points, more made shots to
   assist); rebounds only a little (they follow misses and pace, not scoring).
   Steals, blocks and turnovers stay neutral. Same role as the football one:
   only used when the ratings cannot rate the pair (opening night, when both
   sides' last 20 were mostly the playoff series against each other). Not
   backtested; the page says when it is in use. */
const BB_ODDS_POWER = { "Points": 1, "Field goals": 1, "Assists": 0.8, "3 pointers": 0.8,
                        "Free throws": 0.8, "Rebounds": 0.4 };
const BB_POINTS_SD = 12;

function probit(p) {
  // Acklam's rational approximation, plenty for 0.2 < p < 0.8.
  const a = [-39.6968302866538, 220.946098424521, -275.928510446969, 138.357751867269, -30.6647980661472, 2.50662827745924];
  const b = [-54.4760987982241, 161.585836858041, -155.698979859887, 66.8013118877197, -13.2806815528857];
  const q = p - 0.5, r = q * q;
  return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
       / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
}

function bbExpectedPoints(teamIndex, fx = DATA) {
  if (fx !== DATA) return null;
  const m = fixtureMarket(fx);
  const lines = (m && m.pp && m.pp.team) || [];
  const order = ppTeamOrder();
  const scope = order[0] === teamIndex ? "home" : "away";
  const mine = lines.filter(l => l.stat === "Points" && l.scope === scope);
  const over = mine.find(l => l.over), under = mine.find(l => !l.over && over && l.line === over.line);
  if (!over || !under) return null;
  const po = 1 / over.price, pu = 1 / under.price;
  const pOver = Math.min(0.8, Math.max(0.2, po / (po + pu)));
  return over.line + BB_POINTS_SD * probit(pOver);
}

function bbOddsAdjustment(stat, teamIndex, fx = DATA) {
  const teamStat = PLAYER_STAT_TO_TEAM[stat];
  const power = BB_ODDS_POWER[teamStat];
  if (!power) return null;
  const e = bbExpectedPoints(teamIndex, fx);
  if (!e) return null;
  const pts = filtered(fx.records[teamIndex]).map(r => ((r.stats || {}).ALL || {})["Points"])
    .filter(v => v !== undefined && v !== null);
  if (pts.length < 5) return null;
  const mean = pts.reduce((a, b) => a + b, 0) / pts.length;
  if (mean < 60) return null;
  return Math.min(1.3, Math.max(0.75, Math.pow(e / mean, power)));
}

function oddsAdjustment(stat, teamIndex, fx = DATA) {
  if (SPORT === "basketball") return bbOddsAdjustment(stat, teamIndex, fx);
  const power = ODDS_ADJ_POWER[PLAYER_STAT_TO_TEAM[stat]];
  if (!power || SPORT !== "football") return null;
  const lam = goalLambdas(fx);
  if (!lam) return null;
  const goals = filtered(fx.records[teamIndex]).map(r => (r.stats.ALL || {})["Goals"])
    .filter(v => v !== undefined && v !== null);
  if (goals.length < 5) return null;
  const mean = goals.reduce((s, v) => s + v, 0) / goals.length;
  if (mean <= 0.2) return null;
  return Math.min(2.5, Math.max(0.2, Math.pow(lam[teamIndex] / mean, power)));
}

/* The backtested model reads the opponent's numbers in the opponent's own
   league, so it cannot see the gap between two leagues: it priced AEK's Koita
   at 79% for a shot at the Etihad, about what he manages at home in Greece.
   In a cross-league game (no projection, odds in use) its chance is turned
   into an expected count (the Poisson rate giving that chance at that line),
   scaled by the same odds adjustment as the site's numbers, and priced back.
   Shots and shots on target only, as for the site's numbers. */
function crossLeagueModel(price, stat, line, t, fx = DATA) {
  if (!price || price.source !== "fmodel" || !ODDS_ADJ_POWER[PLAYER_STAT_TO_TEAM[stat]]) return price;
  if (opponentBasis(stat, t, fx) !== "odds") return price;
  const a = oddsAdjustment(stat, t, fx);
  const k = Math.round(line + 0.5);
  if (!a || !(k >= 1) || !(price.p > 0 && price.p < 1)) return price;
  const tail = lam => {
    let term = Math.exp(-lam), cdf = term;
    for (let i = 1; i < k; i++) { term *= lam / i; cdf += term; }
    return 1 - cdf;
  };
  let lo = 0.001, hi = 30;
  for (let i = 0; i < 60; i++) {
    const mid = (lo + hi) / 2;
    if (tail(mid) < price.p) lo = mid; else hi = mid;
  }
  const p = Math.min(0.995, Math.max(0.005, tail(((lo + hi) / 2) * a)));
  return Object.assign({}, price, { p, fair: fairOdds(p), need: fairOdds(p),
    modelRaw: price.p, crossLeague: a });
}

/* How a player line is adjusted for the opponent: "projection", "odds" or
   null when it is not adjusted at all. */
function opponentBasis(stat, teamIndex, fx = DATA) {
  const teamStat = PLAYER_STAT_TO_TEAM[stat];
  if (!teamStat) return null;
  const proj = ((fx.projection || {})["ALL"] || {})[teamStat]
            || (fx.tierProjection ? (fx.tierProjection.stats || {})[teamStat] : null);
  if (proj && proj[teamIndex] !== undefined) return "projection";
  return oddsAdjustment(stat, teamIndex, fx) !== null ? "odds" : null;
}

function playerAdjustment(stat, teamIndex, fx = DATA) {
  const teamStat = PLAYER_STAT_TO_TEAM[stat];
  if (!teamStat) return 1;

  const proj = ((fx.projection || {})["ALL"] || {})[teamStat]
            || (fx.tierProjection ? (fx.tierProjection.stats || {})[teamStat] : null);
  if (!proj || proj[teamIndex] === undefined) return oddsAdjustment(stat, teamIndex, fx) ?? 1;

  const rows = filtered(fx.records[teamIndex]);
  const values = rows.map(r => (r.stats.ALL || {})[teamStat])
                     .filter(v => v !== undefined && v !== null);
  if (values.length < 3) return 1;

  const mean = values.reduce((s, v) => s + v, 0) / values.length;
  if (mean <= 0) return 1;

  // Only a guard against a divide-by-nothing, not a modelling choice.
  //
  // This used to clip to 0.7 and 1.35, on the reasoning that an adjustment
  // should nudge a player line rather than move it a long way. That reasoning
  // was wrong, and expensively so. Coventry average 15.8 shots in the
  // Championship and are expected to manage 4.83 at the Emirates, which is a
  // true adjustment of 0.31. Clipping it to 0.7 priced their forwards at more
  // than double the shots they will actually get, and made a 3.00 shot line
  // look like 1.52.
  //
  // A mismatch really is a big move. That is what a mismatch is. The team
  // projection behind this already has its own sanity checks, so the wide
  // bounds here exist only to stop a near-zero average producing nonsense.
  return Math.min(2.5, Math.max(0.2, proj[teamIndex] / mean));
}

/* Minutes are the whole ballgame for a player line, and ignoring them was the
   single worst bug in this tool.

   Saka's last eight records included a match he did not play in at all, one
   where he came on for nine minutes, and one where he was off at half time.
   The nil from the game he missed was being counted as a losing bet. A
   bookmaker voids that bet; it is not a loss, it is not an event. Counting it
   dragged his record to 5/8 and his expectation to 1.9 shots, and "over 1.5
   shots" came out needing 3.00 when bet365 were offering 1.22.

   So: a record with no minutes is not an appearance and is discarded. What
   remains is converted to a rate per 90 and multiplied by the minutes he is
   expected to play, which is how the market prices it and the only way a
   45-minute cameo and a full match can sit in the same average. */

/* Below this it is a cameo, not an appearance -- and it is injected per sport,
   because 45 is a number about ninety-minute games rather than about sport. An
   NBA rotation player logging twenty-two minutes has played a full shift, and
   judging him against 45 would empty a basketball page the same way the gate
   emptied the NFL one, arriving from the opposite direction. */
const MIN_MINUTES = __MIN_MINUTES__;

/* A missing stat means zero, not "no data".

   SofaScore leaves the key out when a player records none of something. Read
   as unknown, that averages only the matches where he did do it: Truffert's
   shots on target read 1.25 a game when the truth was 0.62. Every shots on
   target and tackles price was built on roughly double the real number.

   Reports built before this was found still have the gaps in their data, so
   the fill happens here too rather than only at fetch time, and they are
   corrected by a re-render without refetching anything. */
const ZERO_FILL = new Set(__ZERO_FILL__);

/* The minutes gate only applies where minutes are reported.

   It keeps a 45-minute cameo out of a per-match average, which is right for
   football. American football has no equivalent figure and SofaScore sends 0
   for every player, so the gate silently discarded every NFL record: Justin
   Jefferson had twenty games of receiving yards on file and not one survived.
   Where nothing in the sample reports minutes, appearing in the box score is
   the appearance test instead -- the same signal the feed already uses to say
   a man did not play, which is an empty stats block. */
function reportsMinutes(played) {
  return played.some(g => (g.minutes || 0) > 0);
}

function appearances(played, stat) {
  const gated = reportsMinutes(played);
  return played
    .filter(g => gated
      ? (g.minutes || 0) >= MIN_MINUTES
      : Object.keys(g.stats || {}).length > 0)
    .map(g => {
      let value = g.stats[stat];
      if ((value === undefined || value === null) && ZERO_FILL.has(stat)) value = 0;
      return { value, minutes: g.minutes };
    })
    .filter(g => g.value !== undefined && g.value !== null);
}

/* --------------------------------------------- thin-sample pooling

   Below three appearances the record interval has a degenerate corner:
   every 1-from-1 player, whoever he is and whatever the stat, priced
   `need` at wilsonLow(1, 1) = 0.2065, which is 4.84, every time. The
   number carried no information about the player at all.

   So a thin sample is now partially pooled, which is the owner's request
   in his own words: "weight it on a mix of other players from their team
   in their position, and also their record over the past game or 2."

   The prior is the pooled per-90 rate for this stat among players of the
   same position class (G/D/M/F) on the same team, excluding the player
   himself, over the same filtered window his own record uses. The blend
   weight is w = minutes / (minutes + POOL_K), minutes-based rather than
   appearance-based so a 45-minute cameo counts as half a match of
   evidence, and the blended rate is priced through the same count-model
   path the three-plus branch has always used.

   HONESTY: there is NO backtest behind this. backtest.py settles team
   bets only; player bets have never been measured at all. This branch is
   principled shrinkage, not a validated model, and every row it touches
   says so on the page. */

/* Two full appearances' worth of prior evidence, in minutes. At one full
   appearance the team-mates carry 2/3 of the rate and his own match 1/3,
   which is the owner's "past game or 2"; at two it is an even split; at
   three the model path takes over on his own record entirely, as it
   always has, and the demonstration in the change notes shows that step
   is small in practice. */
const POOL_K = 2 * 90;

/* How unlike each other players of one position class are, as a
   coefficient of variation on the pooled rate. Team-mates are a proxy for
   the player, not a measurement of him, and the widening below has to
   carry that. 0.5 is a judgement call, not a fitted number. */
const POOL_SPREAD = 0.5;

/* Shrinkage of the ESTABLISHED player branch's stated log-odds -- the same
   Platt map as calibrate() with its own constants, fitted on player bets
   only. Fitted by logistic regression of outcome on log-odds over the 6,633
   settled established player bets (source "model", 3+ appearances) that
   `backtest.py --league "Premier League" --players` produces at the
   production window of 38 matches, fixtures 2025-09-20 to 2026-08-30, run
   2026-08-31: they said 75.5% and landed 68.2%. Both half-season splits
   held out of sample, and on the Championship unseen it closed a -6.9 gap
   to +0.6. Applied ONLY to the established branch: the thin blended branch
   measured nearly calibrated in the same run and this map would make it
   too cautious, and the record fallback stays raw as it does on the team
   path. This is the exact mirror of calibrate_player() in model.py --
   change one, run verify.py, change the other. Refit if `games` in
   update.json, MIN_MINUTES, or the player pricing maths changes. */
const PLAYER_CALIBRATION_A = -0.0227;
const PLAYER_CALIBRATION_B = 0.4454;
/* Basketball has its own fit. Applying the football constants to NBA player
bets made them far too cautious: on the 4,817 established player bets that
`backtest.py --league NBA --games 20 --players` settled (March to June 2026,
run 21 Oct 2026) they said 74% and landed 82%. Fitted the same way, on the
raw log-odds; fitted on either half it improved the other (Brier 0.139 to
0.129, and 0.139 to 0.135). Refit once this season has a few weeks in: the
fit is end of season and playoffs.
   Mirrors PLAYER_CALIBRATION_BY_SPORT in model.py. */
const PLAYER_CALIBRATION_BY_SPORT = {};  // basketball fit withdrawn 21 Oct 2026: see model.py

/* The record-only branch, which until now was quoted raw.

   Mirrors RECORD_SMOOTHING / RECORD_CALIBRATION in model.py -- verify.py
   checks the two agree. The reasoning lives on the Python side; the short
   version is that k/n hits exactly 1.0 on a perfect record, 2,214 gridiron
   bets were quoted at a probability of one, and one in six of them lost. */
const RECORD_SMOOTHING = 0.5;
const SPORT = __SPORT__;
const RECORD_CALIBRATION = {
  "american-football|team":   [0.0865, 0.5060],
  "american-football|player": [-0.1550, 0.8236],
  "football|team":            [0.0177, 0.2806],
};

function smoothRate(hits, total) {
  if (total <= 0) return 0;
  return (hits + RECORD_SMOOTHING) / (total + 2 * RECORD_SMOOTHING);
}

function calibrateRecord(p, kind) {
  const fit = RECORD_CALIBRATION[`${SPORT}|${kind}`];
  if (!fit) return p;
  p = Math.min(1 - 1e-9, Math.max(1e-9, p));
  const z = fit[0] + fit[1] * Math.log(p / (1 - p));
  return 1 / (1 + Math.exp(-z));
}

function calibratePlayer(p) {
  p = Math.min(1 - 1e-9, Math.max(1e-9, p));
  const [a, b] = PLAYER_CALIBRATION_BY_SPORT[SPORT] || [PLAYER_CALIBRATION_A, PLAYER_CALIBRATION_B];
  const z = a + b * Math.log(p / (1 - p));
  return 1 / (1 + Math.exp(-z));
}

function positionPrior(byPlayer, position, stat, excludeName) {
  let value = 0, minutes = 0, players = 0;
  const mins = [];
  byPlayer.forEach((played, name) => {
    if (name === excludeName) return;
    if ((played[0].position || "") !== position) return;
    const apps = appearances(played, stat);
    if (!apps.length) return;
    players += 1;
    apps.forEach(a => { value += a.value; minutes += a.minutes; mins.push(a.minutes); });
  });
  if (!players || minutes <= 0) return null;
  mins.sort((a, b) => a - b);
  return { per90: (value / minutes) * 90, value, minutes, players,
           medianMinutes: Math.min(90, mins[Math.floor(mins.length / 2)]) };
}

function pricePlayer(apps, line, over, adjustment, prior) {
  const n = apps.length;
  const values = apps.map(a => a.value);
  const hits = values.filter(v => (v > line) === over).length;
  const totalMinutes = apps.reduce((s, a) => s + a.minutes, 0);
  const totalValue = values.reduce((s, v) => s + v, 0);

  if (n < 3) {
    // Partial pooling toward the team/position prior -- see the comment
    // above, including the fact that no backtest has ever measured this.
    if (n && prior && totalMinutes > 0) {
      const w = totalMinutes / (totalMinutes + POOL_K);
      const ownPer90 = (totalValue / totalMinutes) * 90;
      const per90 = w * ownPer90 + (1 - w) * prior.per90;

      // Minutes: his own median once he has two appearances to take one
      // from. On a single appearance one match's minutes is not a median
      // of anything, so the smaller of that match and the position's
      // pooled median is used: understating a nailed-on starter slightly
      // lengthens the price, which is the safe direction for the overs
      // this page quotes.
      const sorted = apps.map(a => a.minutes).sort((x, y) => x - y);
      const ownMedian = Math.min(90, sorted[Math.floor(n / 2)]);
      const expectedMinutes = n >= 2
        ? ownMedian
        : Math.min(ownMedian, prior.medianMinutes || ownMedian);

      const expected = per90 * (expectedMinutes / 90) * adjustment;
      if (expected > 0) {
        // `need` widens for the blend's own uncertainty, the same move
        // predictiveRatio makes for a measured sample: the standard
        // error of the blended rate rides on top of the base
        // distribution (Poisson here, since dispersion() is 1 below
        // three appearances) as extra variance. The prior's error term
        // carries POOL_SPREAD as well as its counting error, because a
        // pooled team-mate rate can be precisely measured and still be
        // the wrong player's number.
        const seOwn = 90 * Math.sqrt(Math.max(totalValue, 1)) / totalMinutes;
        const sePrior = 90 * Math.sqrt(Math.max(prior.value, 1)) / prior.minutes;
        const spread = POOL_SPREAD * prior.per90;
        const sePer90 = Math.sqrt(
          w * w * seOwn * seOwn
          + (1 - w) * (1 - w) * (sePrior * sePrior + spread * spread));
        const se = sePer90 * (expectedMinutes / 90) * adjustment;
        const wide = (expected + se * se) / expected;

        let p = probOver(line, expected, values);
        let widened = probOver(line, expected, values, wide);
        if (!over) { p = 1 - p; widened = 1 - widened; }
        const pLow = Math.min(p, widened);

        return {
          p, fair: fairOdds(p), need: fairOdds(Math.max(0.01, pLow)),
          expected, source: "blend", hits, n,
          per90, expectedMinutes, minutes: totalMinutes,
          blend: { w, prior },
        };
      }
    }

    // No appearances at all, no same-position team-mates to pool from, or
    // an expectation of zero: the old record-only interval stands. A squad
    // member with no minutes gets no price on purpose -- a number built
    // entirely from team-mates would sit on the page looking like his,
    // and it is not.
    const p = calibrateRecord(smoothRate(hits, n), "player");
    return { p, fair: fairOdds(p), need: fairOdds(wilsonLow(hits, n)),
             expected: undefined, source: "record", hits, n };
  }

  // Rate per 90, then scaled to the minutes he is likely to get. Median
  // rather than mean minutes, so one early substitution does not decide it.
  if (totalMinutes <= 0 || totalValue <= 0) {
    const p = calibrateRecord(smoothRate(hits, n), "player");
    return { p, fair: fairOdds(p), need: fairOdds(wilsonLow(hits, n)),
             expected: undefined, source: "record", hits, n };
  }

  const sortedMinutes = apps.map(a => a.minutes).sort((x, y) => x - y);
  const expectedMinutes = Math.min(90, sortedMinutes[Math.floor(n / 2)]);
  const per90 = (totalValue / totalMinutes) * 90;
  const expected = per90 * (expectedMinutes / 90) * adjustment;

  // The standard error is in the sample's units and the expectation may be
  // nothing like the sample mean, so it is carried across as a proportion.
  // Subtracting an absolute 0.6 from an expectation of 0.9 left almost nothing
  // and priced a Coventry forward's shots at 20.0.
  const wide = predictiveRatio(values, expected);
  let p = probOver(line, expected, values);
  let widened = probOver(line, expected, values, wide);
  if (!over) { p = 1 - p; widened = 1 - widened; }
  const pLow = Math.min(p, widened);

  // Calibration last, to the quoted numbers only, as in priceRow(): both p
  // and the widened probability pass through the same monotone map, so
  // `need` keeps its place on the pessimistic side of `fair`. Only this
  // branch -- the blend and record branches above quote raw numbers on
  // purpose; see calibratePlayer().
  p = calibratePlayer(p);
  const pLowCal = calibratePlayer(pLow);

  return {
    p, fair: fairOdds(p), need: fairOdds(Math.max(0.01, pLowCal)),
    expected, source: "model", hits, n,
    per90, expectedMinutes, minutes: totalMinutes,
  };
}


/* ------------------------------------------------------ positional matchups

   The other half of a player bet. A player's own record says what he has
   been doing; it says nothing about whether the side in front of him this
   week tends to allow it. Saka clearing 0.5 shots in nine of ten is one half
   of the case. Whether forwards facing Aston Villa get their shot is the
   other, and until now the page never asked.

   Built from every player record already in the report, across all of its
   fixtures and not only the one on screen. To know what forwards have done
   against Villa you go through every other team's player records for the
   matches whose opponent was Villa. A league report holds twenty squads, so
   most of a team's matches have the opposing players on file; the ones that
   do not (cup ties, matches in another division, opponents not in this file)
   are counted and the shortfall is printed, because a rate over three matches
   must never look like one over thirty-eight.

   Position is the coarsest thing SofaScore gives: G, D, M or F. There is no
   winger, no left or right, so "right wingers facing Villa" is not
   expressible here and is not attempted. The formation string on a lineup
   could in principle place a man on a flank, but the mapping is undocumented,
   and a bet hung on a guessed flank is worse than one hung on nothing.
   Position class it is, and the page says so.

   The join is by id. A player record carries a match id, and that match sits
   in its own team's records with the opponent's id. The record's `opponent`
   is a short name and is never used to match, for the reason opponentIdFor()
   gives. Former-club rows carry no opponent id and are left out.

   Context only, by agreement. Nothing computed here reaches pricePlayer(),
   playerAdjustment(), any line or any projection. Today's backtest found
   that head-to-head history and possession both looked informative and
   measured as noise or as generic shrinkage, so nothing new moves a price
   until it has been backtested. This is shown beside the numbers, not fed
   into them. */

/* What to call a position class in English.

   Football's four are all SofaScore gives for that sport, and they are coarse
   enough to be a stated limitation: there is no winger, no left or right, so
   "right wingers facing Villa" is not expressible.

   Gridiron is the opposite case and it is the reason this now exists per
   sport. The feed reports QB, RB, WR, TE, CB, SAF and the rest -- exactly the
   granularity the question needs. "How does this defence do against running
   backs" is a real, answerable question with a real betting consequence, and
   until now the page could not ask it, because these names were not in this
   object and matchupProfile bailed out on the first line. */
const POSITION_NAME = {
  // Football.
  G: "goalkeepers", D: "defenders", M: "midfielders", F: "forwards",
  // Gridiron, offence.
  QB: "quarterbacks", RB: "running backs", FB: "fullbacks",
  WR: "wide receivers", TE: "tight ends",
  T: "tackles", C: "centers", OL: "offensive linemen",
  K: "kickers", P: "punters", LS: "long snappers",
  // Gridiron, defence. Kept so a defensive record is still labelled
  // correctly wherever one is shown, even though no defensive market is
  // proposed as a bet.
  CB: "cornerbacks", SAF: "safeties", DB: "defensive backs",
  LB: "linebackers", OLB: "outside linebackers",
  DE: "defensive ends", DT: "defensive tackles", DL: "defensive linemen",
  // Basketball.
  PG: "point guards", SG: "shooting guards", SF: "small forwards",
  PF: "power forwards",
};

/* What to look up for each player stat, and on whose side.

   "conceded": players of the SAME position class who FACED the opponent, and
   what they produced in the same stat. A forward's shots bet asks what the
   opponent gives up in shots to forwards; a keeper's saves bet asks how many
   saves keepers facing this attack have had to make. Same position, same
   stat, drawn from the opponent's matches. That covers shots, shots on
   target, goals, assists, tackles, passes and saves: for each of them the
   opponent's style is what governs how much of it a player in his role gets
   to do, and the players who have already been in his role against them are
   the direct evidence.

   "own": the opponent's OWN players, in the position class he will be
   contending with, and the mirror stat. Fouls have no same-position answer:
   a midfielder's fouls are committed on the men he closes down, so the
   question is how often the opponent's attackers get fouled, not what other
   midfielders have done. Committed maps to drawn and drawn to committed. The
   positions are a simplification forced by four classes: anyone defending
   (G, D, M) is taken to be fouling the opponent's forwards, which is the
   user's own example (a holding midfielder's fouls against Villa's strikers),
   and a forward's fouls are on the opponent's defenders. Coming the other
   way, a forward is fouled by defenders, a midfielder by midfielders, a
   defender or keeper by forwards.

   Minutes has no opposing half and is left out. */
const FOULS_ON = { G: "F", D: "F", M: "F", F: "D" };   // who a fouler fouls
const FOULED_BY = { G: "F", D: "F", M: "M", F: "D" };  // who fouls him
const MATCHUP_PAIRING = {
  "Shots":           { mode: "conceded", stat: "Shots" },
  "Shots on target": { mode: "conceded", stat: "Shots on target" },
  "Goals":           { mode: "conceded", stat: "Goals" },
  "Assists":         { mode: "conceded", stat: "Assists" },
  "Tackles":         { mode: "conceded", stat: "Tackles" },
  "Passes":          { mode: "conceded", stat: "Passes" },
  "Saves":           { mode: "conceded", stat: "Saves" },
  "Fouls":           { mode: "own", stat: "Fouled", positions: FOULS_ON },
  "Fouled":          { mode: "own", stat: "Fouls", positions: FOULED_BY },

  /* Gridiron. The whole reason this concept is worth having.
     A defence that has been giving up yards to running backs all season is
     the single most useful thing you can know about a running back's line
     this week, and unlike football's four position classes, the feed's RB /
     WR / TE / QB are precise enough for the answer to mean something. Same
     position, same stat, drawn from the opponent's matches. */
  "Rushing yards":        { mode: "conceded", stat: "Rushing yards" },
  "Rushing attempts":     { mode: "conceded", stat: "Rushing attempts" },
  "Receiving yards":      { mode: "conceded", stat: "Receiving yards" },
  "Receiving receptions": { mode: "conceded", stat: "Receiving receptions" },
  "Passing yards":        { mode: "conceded", stat: "Passing yards" },
  "Passing attempts":     { mode: "conceded", stat: "Passing attempts" },
  "Passing completions":  { mode: "conceded", stat: "Passing completions" },
  "Passing touchdowns":   { mode: "conceded", stat: "Passing touchdowns" },
  "Rushing and receiving yards": { mode: "conceded", stat: "Rushing and receiving yards" },
  "Passing and rushing yards":   { mode: "conceded", stat: "Passing and rushing yards" },
  "Anytime touchdown":    { mode: "conceded", stat: "Anytime touchdown" },

  /* Basketball. Positions are G / F / C, which is coarse, but a team that
     gets scored on by guards is a real and stable property. */
  "Points":               { mode: "conceded", stat: "Points" },
  "Rebounds":             { mode: "conceded", stat: "Rebounds" },
  "Three pointers made":  { mode: "conceded", stat: "Three pointers made" },
};

/* Fewer matches with data than this and the profile is marked thin. Three
   matches of forwards is a dozen appearances and one good afternoon. */
const MATCHUP_MIN_MATCHES = 5;

/* Built once per page from ALL, on first use, and never rebuilt: the payload
   does not change. Tens of thousands of records go in; what comes out is two
   maps of references, team id to position to records, plus the set of match
   ids each team has any data for, so a profile is a filter over one short
   list rather than a scan of the file. */
let MATCHUP_INDEX = null;
const MATCHUP_CACHE = new Map();

function matchupIndex() {
  if (MATCHUP_INDEX) return MATCHUP_INDEX;
  const conceded = new Map();   // team id -> position -> records of players who faced them
  const own = new Map();        // team id -> position -> that team's own player records
  const covered = { conceded: new Map(), own: new Map() };  // team id -> match ids with any data
  const seen = new Set();

  const add = (map, teamId, pos, r) => {
    let byPos = map.get(teamId);
    if (!byPos) { byPos = new Map(); map.set(teamId, byPos); }
    let list = byPos.get(pos);
    if (!list) { list = []; byPos.set(pos, list); }
    list.push(r);
  };
  const mark = (map, teamId, mid) => {
    let ids = map.get(teamId);
    if (!ids) { ids = new Set(); map.set(teamId, ids); }
    ids.add(mid);
  };

  (ALL.fixtures || []).forEach(fx => {
    if (!Array.isArray(fx.players)) return;
    fx.players.forEach((records, teamIndex) => {
      const team = (fx.teams || [])[teamIndex];
      if (!team || team.id === undefined || team.id === null) return;
      const byMatch = new Map(((fx.records || [])[teamIndex] || []).map(m => [m.id, m]));
      (records || []).forEach(r => {
        // A record from somewhere else cannot be evidence about THIS
        // opponent. Former-club rows were already excluded; club form on an
        // international fixture is the same thing at scale -- every record
        // is against a league side the national team is not playing.
        if (r.former_club || r.club) return;
        const m = byMatch.get(r.match_id);
        if (!m || m.opponent_id === undefined || m.opponent_id === null) return;
        // The same club sits in two fixtures of one file when a round spans
        // a midweek, carrying the same records under each. Counted once.
        const key = `${r.match_id}|${r.player_id !== undefined && r.player_id !== null ? r.player_id : r.player}`;
        if (seen.has(key)) return;
        seen.add(key);
        const pos = r.position || "?";
        add(own, team.id, pos, r);
        add(conceded, m.opponent_id, pos, r);
        mark(covered.own, team.id, r.match_id);
        mark(covered.conceded, m.opponent_id, r.match_id);
      });
    });
  });

  MATCHUP_INDEX = { conceded, own, covered };
  return MATCHUP_INDEX;
}

/* The opponent's profile against one position class, over one window of the
   opponent's matches. `window` is the list of that opponent's team records
   the caller is showing, so "last 10" means the same ten matches on both
   halves of the case; `windowKey` names the filter state for the cache.
   Appearances use the same 45-minute floor and zero-fill as the player's own
   record, so the two halves are counted the same way. The rate is per 90,
   never per appearance: a sub's twenty minutes would otherwise read as a
   forward who never shoots. The share is of appearances clearing the line,
   because that is what the bet asks. */
function matchupProfile(fx, oppIndex, playerPos, stat, line, window, windowKey) {
  const pairing = MATCHUP_PAIRING[stat];
  const opp = (fx.teams || [])[oppIndex];
  if (!pairing || !opp || opp.id === undefined || opp.id === null) return null;
  const pos = pairing.mode === "own" ? pairing.positions[playerPos] : playerPos;
  if (!pos || !POSITION_NAME[pos]) return null;

  const cacheKey = `${fx.fixture ? fx.fixture.id : ""}|${oppIndex}|${pos}|${stat}|${line}|${windowKey}`;
  const held = MATCHUP_CACHE.get(cacheKey);
  if (held) return held;
  if (MATCHUP_CACHE.size > 4000) MATCHUP_CACHE.clear();

  const idx = matchupIndex();
  const source = pairing.mode === "own" ? idx.own : idx.conceded;
  const pool = (source.get(opp.id) || new Map()).get(pos) || [];
  const windowIds = new Set(window.map(m => m.id));
  const withData = idx.covered[pairing.mode].get(opp.id) || new Set();
  let covered = 0;
  windowIds.forEach(id => { if (withData.has(id)) covered++; });

  /* The appearance test has to be the sport's, not football's.

     This used to be a bare `minutes < MIN_MINUTES` and that one line is why
     none of this worked for American football: the box score reports zero
     minutes for every player, so the filter discarded the entire pool and
     every gridiron profile came back empty -- silently, looking exactly like
     a sport with no data rather than a test that could not pass. Same rule as
     appearances() above: gate on minutes where minutes are reported, and on
     the presence of a stats block where they are not. */
  const inWindow = pool.filter(g => windowIds.has(g.match_id));
  const gated = reportsMinutes(inWindow);

  let n = 0, hits = 0, total = 0, minutes = 0;
  const matches = new Set();
  inWindow.forEach(g => {
    if (gated ? (g.minutes || 0) < MIN_MINUTES
              : !Object.keys(g.stats || {}).length) return;
    let v = (g.stats || {})[pairing.stat];
    if ((v === undefined || v === null) && ZERO_FILL.has(pairing.stat)) v = 0;
    if (v === undefined || v === null) return;
    n++; total += v; minutes += (g.minutes || 0);
    if (v > line) hits++;
    matches.add(g.match_id);
  });

  /* Per 90 where there are minutes, per appearance where there are not.

     Football needs the per-90: a substitute's twenty minutes would otherwise
     read as a forward who never shoots. Gridiron has no minutes at all, and
     per appearance is the right unit there anyway -- "receptions per game
     allowed to wide receivers" is how the question is actually asked. The
     unit is carried on the profile so the label can say which one it is
     rather than printing a per-game figure under a "per 90" heading. */
  const rate = n ? (minutes > 0 ? (total / minutes) * 90 : total / n) : null;

  const profile = {
    mode: pairing.mode, stat: pairing.stat, pos, posName: POSITION_NAME[pos],
    team: opp.name, teamId: opp.id, line,
    n, hits, matches: matches.size,
    share: n ? hits / n : null,
    per90: rate,
    unit: minutes > 0 ? "per 90" : "per game",
    windowMatches: window.length, covered,
    thin: matches.size < MATCHUP_MIN_MATCHES,
  };
  MATCHUP_CACHE.set(cacheKey, profile);
  return profile;
}

/* ------------------------------------------------------------- usage
//
   What a player's record cannot tell you: whether he still gets the ball.

   Every number on a player card counts what he DID. None of them count what
   he was GIVEN the chance to do, and for a receiver those are different
   questions with the same answer only while his role holds. A tight end with
   14 receptions from 15 games looks like a lock at 1+ until the game he sees
   one target all afternoon, and nothing on the page moved beforehand, because
   nothing on the page was watching the thing that changed.

   Target share is that missing number, and it was already in the payload:
   `Receiving targets` sits on every gridiron player record, so a man's share
   of his team's targets in a match is a sum over team-mates and a division.
   No refetch, no new endpoint.

   Each market is paired with the opportunity that feeds it. Receptions and
   receiving yards come from targets; rushing yards come from carries; a
   quarterback's numbers come from attempts. A market with no opportunity stat
   behind it simply gets none, rather than a fabricated one. */
const OPPORTUNITY = {
  "Receiving receptions":        "Receiving targets",
  "Receiving yards":             "Receiving targets",
  "Anytime touchdown":           "Receiving targets",
  "Rushing and receiving yards": "Receiving targets",
  "Rushing yards":               "Rushing attempts",
  "Rushing attempts":            "Rushing attempts",
  "Passing yards":               "Passing attempts",
  "Passing touchdowns":          "Passing attempts",
  "Passing completions":         "Passing attempts",
  "Passing and rushing yards":   "Passing attempts",
};

/* How many recent matches count as "lately". Three is a compromise: fewer is
   one bad afternoon, more and a role change three weeks ago stops showing. */
const USAGE_RECENT = 3;

function usageProfile(fx, teamIndex, name, stat, window) {
  const feeds = OPPORTUNITY[stat];
  if (!feeds) return null;
  const records = (fx.players || [])[teamIndex] || [];
  if (!records.length) return null;

  const ids = new Set(window.map(m => m.id));
  const teamTotal = new Map();   // match id -> the squad's total
  const his = new Map();         // match id -> his own
  records.forEach(r => {
    if (!ids.has(r.match_id)) return;
    const v = (r.stats || {})[feeds];
    if (v === undefined || v === null) return;
    teamTotal.set(r.match_id, (teamTotal.get(r.match_id) || 0) + v);
    if (r.player === name) his.set(r.match_id, v);
  });
  if (!his.size) return null;

  // Oldest first, so "recent" means the end of the list.
  const order = [...his.keys()].sort((a, b) => {
    const ia = window.findIndex(m => m.id === a);
    const ib = window.findIndex(m => m.id === b);
    return ia - ib;
  });
  const shares = order
    .map(id => {
      const tot = teamTotal.get(id) || 0;
      return tot > 0 ? his.get(id) / tot : null;
    })
    .filter(x => x !== null);
  if (!shares.length) return null;

  const mean = xs => xs.reduce((s, x) => s + x, 0) / xs.length;
  const recent = shares.slice(-USAGE_RECENT);
  const prior = shares.slice(0, -USAGE_RECENT);

  const opportunities = order.map(id => his.get(id));
  return {
    feeds,
    n: shares.length,
    share: mean(shares),
    recent: mean(recent),
    prior: prior.length >= 2 ? mean(prior) : null,
    last: opportunities[opportunities.length - 1],
    perGame: mean(opportunities),
    recentOpps: opportunities.slice(-USAGE_RECENT),
  };
}

/* The one-line read, and a warning when the thing that feeds the bet is
   drying up. A falling share is the only forward-looking signal here -- the
   record is entirely backward-looking by construction. */
function usageNote(u) {
  if (!u) return "";
  const word = u.feeds === "Receiving targets" ? "target share"
             : u.feeds === "Rushing attempts" ? "carry share"
             : "attempt share";
  const pct = x => `${Math.round(x * 100)}%`;
  let trend = "", cls = "usage-flat";
  if (u.prior !== null && u.prior > 0) {
    const ratio = u.recent / u.prior;
    if (ratio <= 0.6) { trend = ` &mdash; down from ${pct(u.prior)}`; cls = "usage-down"; }
    else if (ratio >= 1.4) { trend = ` &mdash; up from ${pct(u.prior)}`; cls = "usage-up"; }
  }
  const dry = u.recentOpps.every(v => v <= 1);
  return `<span class="usage ${cls}" title="His share of the squad's ${
    u.feeds.toLowerCase()} over this window, and over the last ${USAGE_RECENT} matches. A record counts what he did; this counts what he was given the chance to do.">${
    word} ${pct(u.recent)}${trend}${
    dry ? ` &middot; <b>${u.recentOpps.join(", ")} in the last ${u.recentOpps.length}</b>` : ""}</span>`;
}

/* Where this defence sits against every other one in the file.

   The profile on its own is a number without a scale. "36.2 rushing yards per
   game to running backs" means nothing until you know whether that is the
   softest run defence in the league or the hardest, and that is the whole
   substance of the idea: a good running back against a defence that has been
   giving up yards to running backs all season is a different bet from the
   same back against the best run defence in the file, and the line you should
   be taking is different too.

   So every team in the index is rated on the same stat for the same position,
   over everything the file holds for them, and the opponent is placed in that
   order. Whole file rather than a window, deliberately: the teams have to be
   measured over the same thing to be comparable, and a per-fixture window
   would rank each defence over a different set of matches.

   Teams with too little data are left out of the ranking rather than counted
   as zero, which would make an unseen defence look like the best in the
   league. If fewer than four teams qualify there is no league to compare to
   and this returns null, because a "2nd softest of 3" is not a fact. */
const MATCHUP_RANK_CACHE = new Map();
const MATCHUP_RANK_MIN_APPS = 6;
const MATCHUP_RANK_MIN_TEAMS = 4;

function matchupRank(m) {
  if (!m || !m.n || m.per90 === null || m.per90 === undefined) return null;
  const key = `${m.pos}|${m.stat}`;
  let table = MATCHUP_RANK_CACHE.get(key);

  if (!table) {
    const idx = matchupIndex();
    const source = m.mode === "own" ? idx.own : idx.conceded;
    const rates = [];
    source.forEach((byPos, teamId) => {
      const pool = byPos.get(m.pos) || [];
      const gated = reportsMinutes(pool);
      let n = 0, total = 0, minutes = 0;
      pool.forEach(g => {
        if (gated ? (g.minutes || 0) < MIN_MINUTES
                  : !Object.keys(g.stats || {}).length) return;
        let v = (g.stats || {})[m.stat];
        if ((v === undefined || v === null) && ZERO_FILL.has(m.stat)) v = 0;
        if (v === undefined || v === null) return;
        n++; total += v; minutes += (g.minutes || 0);
      });
      if (n < MATCHUP_RANK_MIN_APPS) return;
      rates.push({ teamId, rate: minutes > 0 ? (total / minutes) * 90 : total / n });
    });
    rates.sort((a, b) => b.rate - a.rate);      // most allowed first
    table = rates;
    MATCHUP_RANK_CACHE.set(key, table);
  }

  if (table.length < MATCHUP_RANK_MIN_TEAMS) return null;
  const mid = table[Math.floor(table.length / 2)].rate;

  /* Look the team up in the table, rather than slotting its windowed rate
     into it.

     The first version compared the profile's rate -- computed over the
     window on screen -- against a table computed over the whole file, and
     the two are not the same measurement. The result was that almost every
     defence in the NFL file came out "tough", several of them 31st of 32 at
     once, which is arithmetically impossible and was the tell. Comparing a
     number from one population against the ranks of another is not a
     ranking, it is a category error with a percentage sign on it.

     The table is the comparison, so the team's place in it is read directly.
     The windowed figure still prints beside the badge, and where the two
     disagree that is real information about recent form rather than an
     artefact. */
  const at = table.findIndex(r => r.teamId === m.teamId);
  if (at < 0) return null;
  const place = at + 1;
  const rate = table[at].rate;

  const share = (place - 1) / (table.length - 1);   // 0 = softest, 1 = toughest
  const verdict = share <= 0.33 ? "soft" : share >= 0.67 ? "tough" : "middling";
  return {
    place, of: table.length, verdict, rate,
    versusMid: mid > 0 ? rate / mid : null,
  };
}

/* The rank as a short badge: what it is, and how far from the middle. */
function matchupBadge(m) {
  if (SPORT === "american-football" && m && m.mode !== "own" && m.teamId != null) {
    const d = defRow(m.teamId, m.pos, m.stat);
    if (d && d.vsUsual) {
      const share = (d.place - 1) / Math.max(1, d.of - 1);
      const verdict = share <= 0.33 ? "soft" : share >= 0.67 ? "tough" : "middling";
      const word = share <= 0.5 ? `${d.place}${ordinal(d.place)} softest` : `${d.of - d.place + 1}${ordinal(d.of - d.place + 1)} toughest`;
      return `<span class="mu-rank mu-${verdict}" title="${d.vsUsual.toFixed(2)}x what offences usually get from this position; lead player ${d.lead.toFixed(1)} a game${d.recent ? "; last 4 games " + d.recent.toFixed(2) + "x" : ""}.">${word} of ${d.of} &middot; ${d.vsUsual.toFixed(2)}&times;</span>`;
    }
  }
  const r = matchupRank(m);
  if (!r) return "";
  const pct = r.versusMid ? Math.round((r.versusMid - 1) * 100) : null;
  const gap = pct === null || Math.abs(pct) < 3 ? "about the league median"
            : `${Math.abs(pct)}% ${pct > 0 ? "above" : "below"} the median`;
  const word = r.verdict === "soft" ? `${r.place}${ordinal(r.place)} softest`
             : r.verdict === "tough" ? `${r.of - r.place + 1}${ordinal(r.of - r.place + 1)} toughest`
             : `${r.place}${ordinal(r.place)} of ${r.of}`;
  return `<span class="mu-rank mu-${r.verdict}" title="Of the ${r.of} teams in this file with enough data on this position and stat, ${gap}.">${word} of ${r.of}</span>`;
}

function ordinal(n) {
  const s = ["th", "st", "nd", "rd"], v = n % 100;
  return s[(v - 20) % 10] || s[v] || s[0];
}

/* Who was measured, against whom, in one line of English. */
function matchupLabel(m) {
  const statName = m.stat === "Fouled" ? "fouls drawn"
                 : m.stat === "Fouls" ? "fouls committed" : m.stat.toLowerCase();
  return m.mode === "own"
    ? `${m.team} ${m.posName}, ${statName}`
    : `${m.posName} v ${m.team}, ${statName}`;
}

/* The sample, always. "9 of 10 matches" is the coverage statement: how many
   of the opponent's matches in this window have the relevant player data in
   this file. When fewer matches carried this position than carried any data
   at all, both numbers are given. */
function matchupSample(m) {
  const apps = `${m.n} app${m.n === 1 ? "" : "s"}`;
  const win = `${m.windowMatches} match${m.windowMatches === 1 ? "" : "es"}`;
  if (m.matches === m.covered) return `${apps} in ${m.matches} of ${win}`;
  return `${apps} in ${m.matches} matches; player data for ${m.covered} of ${win}`;
}

function matchupEmpty(m) {
  return m.mode === "own"
    ? `no ${escapeHtml(m.team)} player data in this window`
    : `no opposition player data v ${escapeHtml(m.team)} in this window `
      + `(${m.covered} of ${m.windowMatches} matches)`;
}

/* The Players tab cell. */
function matchupCell(m) {
  if (!m) return `<td class="mu" data-label="Matchup"><span class="mu-none">n/a</span></td>`;
  if (!m.n) {
    return `<td class="mu" data-label="Matchup"><span class="mu-none">${matchupEmpty(m)}</span></td>`;
  }
  const pct = Math.round(m.share * 100);
  return `<td class="mu${m.thin ? " mu-thin" : ""}" data-label="Matchup">
    <div class="mu-fig"><b>${pct}%</b> over ${m.line}</div>
    <div class="mu-rate">${m.per90.toFixed(1)} ${m.unit || "per 90"}</div>${
    m.thin
      ? `<div class="mu-fig"><span class="tag-thin" title="Only ${m.matches} match${
          m.matches === 1 ? "" : "es"} with player data for this position in
          this window. Too few to lean on.">thin: ${m.matches} match${
          m.matches === 1 ? "" : "es"}</span></div>`
      : ""}
    <div class="mu-fig">${matchupBadge(m)}</div>
    <div class="mu-note">${escapeHtml(matchupLabel(m))} &middot; ${matchupSample(m)}</div>
  </td>`;
}

/* The third block on a player pick in Best bets. */
function matchupHalf(m, teamIndex) {
  if (!m) return "";
  if (!m.n) {
    return `<div class="half">
      <span class="half-label">${escapeHtml(matchupLabel(m))}</span>
      <span class="half-num">&mdash;</span>
      <span class="mu-seq">${matchupEmpty(m)}</span>
    </div>`;
  }
  const pct = Math.round(m.share * 100);
  return `<div class="half${m.thin ? " mu-thin" : ""}">
    <span class="half-label">${escapeHtml(matchupLabel(m))}, over ${m.line}</span>
    <span class="half-num">${pct}% ${matchupBadge(m)}</span>
    <div class="bar"><div class="fill" style="width:${pct}%;
         background:var(${VARS[1 - teamIndex]})"></div></div>
    <span class="mu-seq">${m.per90.toFixed(1)} ${m.unit || "per 90"} &middot; ${matchupSample(m)}${
      m.thin ? ` &middot; <b>thin: ${m.matches} match${m.matches === 1 ? "" : "es"}</b>` : ""}</span>
  </div>`;
}


/* ------------------------------------------------------------- best bets

   The matchup scan. A hit rate on its own only tells you what one team did
   against whoever happened to be in front of them. The question worth asking
   is whether both halves of the fixture point the same way: Arsenal have gone
   over 5.5 corners in nine of their last ten at home, AND Coventry have
   conceded over 5.5 in eight of their last ten away. Two independent records
   agreeing is worth far more than one record twice as long, because they can
   fail independently.

   Venue is enforced on both sides. The home team's home record is matched
   against the away team's away record, never the pooled one, because that is
   the actual fixture.

   The two records are then pooled into one Wilson interval. That is the
   honest way to combine them: twenty observations at 85% supports a much
   shorter price than ten at 85%, and the interval says so by itself. It also
   refuses to let one side carry the other, because both halves must clear the
   bar individually before the pair is scored at all. */

/* Each side must clear this on its own before a pairing is scored. The
   default is 0.5: a team that has gone over in every one of its matches
   against an opponent that concedes over half the time is a real pattern,
   and demanding 65% from both halves threw a lot of those away. Adjustable
   on the page, because how strict to be is a judgement rather than a fact. */
let MATCHUP_FLOOR = 0.5;

/* Whether the scans look at this fixture or the whole round. Per fixture by
   default: when you are looking at Arsenal v Coventry you want that game's
   bets, not a list where nine of the ten rows are other matches. */
let scanScope = "fixture";

function scanFixtures() {
  if (scanScope === "fixture") {
    const index = ALL.fixtures.indexOf(DATA);
    return index >= 0 ? [[DATA, index]] : [];
  }
  return ALL.fixtures.map((fx, i) => [fx, i]);
}

/* The markets that actually exist. Injected from hitrates.py so there is one
   list, not two that drift apart.

   The scans filter on this rather than trusting the payload, because a report
   built before the bettable filter existed still carries every stat SofaScore
   returns, and re-rendering the page cannot change what is baked into its
   data. That is how "under 0.5 hit woodwork" ended up in a list of bets. */
const BETTABLE = new Set(__BETTABLE__);

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* A tail probability of 0.03% printed as "0.0%" reads as impossible, which is
   the one impression this number must never give. */
function fmtChance(p) {
  const pct = p * 100;
  if (pct < 0.05) return "under 0.05%";
  return `${pct.toFixed(pct < 1 ? 2 : 1)}%`;
}

function scanMatchups(minSample) {
  const found = [];
  let combos = 0;
  let skipped = 0;

  scanFixtures().forEach(([fx, fxIndex]) => {
    const now = Date.now() / 1000;
    // A single selected fixture is always scanned, even after kick-off: you
    // chose it deliberately. Only the whole-round view hides played games.
    if (scanScope !== "fixture" && !showPast
        && (fx.fixture.kickoff || 0) <= now) return;

    Object.keys(fx.lines || {}).forEach(per => {
      const lines = fx.lines[per] || {};

      (fx.stats[per] || []).forEach(name => {
        if (!BETTABLE.has(name)) return;
        const suggested = lines[name];
        if (suggested === undefined) return;

        // Both directions: the home side's attack against the away side's
        // defence, then the reverse.
        [0, 1].forEach(side => {
          const attackVenue  = side === 0 ? "home" : "away";
          const defendVenue  = side === 0 ? "away" : "home";

          // Same reason as the standout scan: in darts the listing order is
          // not a venue, so each player's full record is used.
          const anyVenue = SPORT === "darts";
          const attackRows = fx.records[side]
            .filter(r => anyVenue || r.venue === attackVenue).slice(-games);
          const defendRows = fx.records[1 - side]
            .filter(r => anyVenue || r.venue === defendVenue).slice(-games);

          // Same guard as the standout scan: a promoted club's record is
          // true and useless, and this is the exact fixture where pairing it
          // with a Premier League defence produces a beautiful wrong answer.
          if (!includeMismatched && !isCrossLeague(fx)) {
            const bad = [fx.records[side], fx.records[1 - side]].some(recs => {
              const sample = recs.slice(-games);
              const ok = sample.filter(
                r => (r.competition || "?") === fx.fixture.competition).length;
              return sample.length && ok / sample.length < 0.6;
            });
            if (bad) { skipped++; return; }
          }

          const forVals = attackRows
            .map(r => (r.stats[per] || {})[name])
            .filter(v => v !== undefined && v !== null);
          const againstVals = defendRows
            .map(r => (r.against[per] || {})[name])
            .filter(v => v !== undefined && v !== null);

          if (forVals.length < minSample || againstVals.length < minSample) return;

          // A short ladder around the suggested line, which is the median and
          // so stands in for where a bookmaker would hang it.
          //
          // The ladder is deliberately one-sided per direction. An over bet
          // BELOW the median, or an under bet ABOVE it, is a bet on the easy
          // side of the market: it will hit almost every week and be priced
          // at 1.05, and it swamped this list when both sides were allowed.
          // "Newcastle over 0.5 yellow cards, 20 from 20" is true, useless,
          // and exactly what a scan like this produces if you let it. So an
          // over only looks at the median and above, an under at the median
          // and below. It also halves the combinations trawled, which makes
          // everything that survives a little more meaningful.
          [-1, 0, 1].forEach(step => {
            const line = suggested + step;
            if (line < 0.5) return;
            combos++;

            const forOver     = forVals.filter(v => v > line).length;
            const againstOver = againstVals.filter(v => v > line).length;

            [true, false].forEach(over => {
              if (over && step < 0) return;
              if (!over && step > 0) return;
              const kFor = over ? forOver : forVals.length - forOver;
              const kAgn = over ? againstOver : againstVals.length - againstOver;

              const pFor = kFor / forVals.length;
              const pAgn = kAgn / againstVals.length;
              if (pFor < MATCHUP_FLOOR || pAgn < MATCHUP_FLOOR) return;

              const k = kFor + kAgn;
              const n = forVals.length + againstVals.length;
              const score = wilsonLow(k, n);

              found.push({
                score, k, n, over, line,
                stat: name, period: per,
                fixture: `${fx.fixture.home} v ${fx.fixture.away}`,
                fixtureIndex: fxIndex,
                competition: fx.fixture.competition,
                kickoff: fx.fixture.kickoff || 0,
                team: fx.teams[side].name,
                teamIndex: side,
                opponent: fx.teams[1 - side].name,
                attackVenue, defendVenue,
                kFor, nFor: forVals.length, pFor,
                kAgn, nAgn: againstVals.length, pAgn,
                forVals, againstVals,
                chance: binomTail(n, k),
                // Does the opponent-adjusted projection agree? Not required,
                // but a disagreement is worth seeing before you stake.
                proj: ((fx.projection || {})[per] || {})[name],
                est: !(fx.projection || {})[per]
                     && fx.tierProjection ? (fx.tierProjection.stats || {})[name] : undefined,
              });
            });
          });
        });
      });
    });
  });

  // One row per team and stat: keep only that pairing's best line and
  // direction, otherwise the top three are the same bet at three prices.
  //
  // The tiebreak matters more than it looks. The score depends only on how
  // many of n went the right way, so "over 0.5 goals" and "over 2.5 goals"
  // both score identically at 10/10, and without a tiebreak the list fills
  // up with lines nobody would price. Among equal records, take the most
  // demanding line: the highest for an over, the lowest for an under.
  const demand = r => (r.over ? r.line : -r.line);

  const best = new Map();
  found.forEach(r => {
    const key = [r.fixtureIndex, r.teamIndex, r.stat, r.period].join("|");
    const held = best.get(key);
    if (!held
        || r.score > held.score
        || (r.score === held.score && demand(r) > demand(held))) {
      best.set(key, r);
    }
  });

  // Across stats, a tie on score is broken by how close the line sits to what
  // the teams actually average. A line the record clears by a mile is a line
  // the bookmaker will price at odds not worth taking.
  const tightness = r => {
    const all = r.forVals.concat(r.againstVals);
    const mean = all.reduce((s, v) => s + v, 0) / all.length;
    return -Math.abs(mean - r.line);
  };

  const list = [...best.values()].sort(
    (a, b) => (b.score - a.score) || (tightness(b) - tightness(a)));
  return { found: list, combos, skipped };
}

/* ---------------------------------------------------- player best bets

   Player lines alongside the team matchups. A player row is a single record
   rather than two independent halves, so it can never be scored the way a
   matchup is: the Wilson bound on his own appearances is all the evidence
   there is. What earns one its place is the second, smaller record beside
   it -- the same line counted only in matches against this exact opponent,
   through the same match ids the players tab uses. Form and the head-to-head
   pointing the same way is the case this exists for; when the opponent
   record is one match old the card says so, because 1/1 dressed up as
   certainty is worse than no column at all.

   Overs only, at the suggested line, because that is how player markets are
   quoted and the suggested line stands in for where a book would hang one.
   Only stats with a real player market behind them are scanned, the same
   reasoning as BETTABLE for teams: Passes and Rating stay out, and so does
   Goals via PLAYER_SCAN_EXCLUDE, for the measured reason given there.

   The floor is applied to gateRate(), not to the raw record: the record is
   shrunk towards the market's own base rate first, so a player qualifies on
   how far he stands above typical for that market rather than on clearing
   one number shared by markets whose base rates run from 9% to 62%. On the
   raw record a short lucky streak in a rare-event market outscored genuine
   ability in a common one, and the backtest measured exactly that.

   Capped at three per fixture, one row per player. A fixture carries ninety
   players and five stats, and every appearance sample is drawn from the same
   handful of matches, so a hundred player rows would not be a hundred pieces
   of evidence, just the same ten matches wearing different shirts. Three
   against ten team picks keeps them from swamping the list while still
   surfacing the case above. Pricing goes through pricePlayer, the same
   minutes-aware path as the Players tab, never the team model. */

/* The whole ladder for one player, not just the rung the scan chose.

   The scan picks one number. A coupon may not carry that exact number, and
   the rung above or below is often the one worth taking -- and the only way
   to know is to see the record at every rung side by side. This is the table
   that was being pasted into chat by hand; it belongs on the page.

   Built from the row's own values, so it honours whatever the filters are
   set to: change the window to last 5, or to home games only, and the ladder
   re-reads with it. That matters more than it sounds. A leg that looks like
   1.43 across twenty games and 1.80 in away games is the difference between
   a bet and a mistake, and the venue split is one click away here. */
function ladderTable(stat, values, chosen) {
  const n = values.length;
  if (!n) return "";
  const all = ladderRungs(stat, values).map(threshold => {
    const hits = values.filter(v => v >= threshold).length;
    return { threshold, hits, rate: hits / n };
  }).filter(r => r.hits > 0 && r.rate < 1 && r.rate >= 0.2);

  /* One row per distinct record, at the highest line that achieves it.

     Gibbs clears 70 and 80 in the same seven games, because he has never
     landed between them -- so listing both is one fact printed twice, and the
     only sane answer is the bigger number. Collapsing also kills the tail,
     where six consecutive rungs all read 1/10 and none of them is a bet.
     Rungs below a one-in-five rate are dropped for the same reason. */
  const rungs = all.filter((r, i) =>
    i === all.length - 1 || all[i + 1].hits !== r.hits);
  if (!rungs.length) return "";

  const rows = rungs.map(r => {
    // The scan's rung may have been collapsed into the row above it, so mark
    // whichever row actually covers it rather than only an exact match.
    const here = chosen !== null && r.threshold >= chosen
      && !rungs.some(o => o.threshold >= chosen && o.threshold < r.threshold);
    return `<tr${here ? ' class="rung-here"' : ""}>
      <td class="rung">${r.threshold}+</td>
      <td>${r.hits}/${n}</td>
      <td>${Math.round(r.rate * 100)}%</td>
      <td><b>${fmtOdds(1 / r.rate)}</b></td>
      <td class="rung-need">${fmtOdds(1 / wilsonLow(r.hits, n))}</td>
    </tr>`;
  }).join("");

  return `<details class="ladder"><summary>every line on the ladder</summary>
    <table class="ladder-table">
      <thead><tr><th>line</th><th>record</th><th>rate</th><th>fair</th>
        <th>hold out for</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="ladder-note">Fair is one over the rate and is break-even, not an
      edge: back a rung only where the book pays more than it. Hold out for is
      the same price once the sample size is paid for. The highlighted row is
      the one the scan chose. Change the window or venue in Filters and this
      re-reads with it.</p></details>`;
}

/* The rungs a book actually posts, and the one worth quoting for a player.

   Mirrors parlay.py. The scan used to take its line from fx.playerLines --
   one number per stat shared across both squads -- which is right for
   ranking a page of players against each other and wrong for proposing a
   bet. It offered "Gibbs over 34.5 rushing and receiving yards" because 34.5
   is roughly the median of everyone who recorded any, while Gibbs' own median
   is 102, and a book prices that at about 1.02.

   So the question is asked the other way round: fix the rate, read off the
   line. Nothing is maximised except the threshold itself, which is why this
   needs no correction for looking -- a scan over rungs would be several
   nested tests of one question, and the winner would be whichever rung the
   sample flattered. */
const SCAN_FLOOR = 0.65;     // the rate the rung has to clear
/* Below this lower bound the rate is not evidence.

   Lower than the parlay's 0.45, and it has to be. The scan's default window
   is the last ten appearances, where a 0.45 bound demands 8 from 10 -- which,
   with the 0.65 rate floor on top, left almost every player with no eligible
   rung at all and dropped Gibbs entirely. At ten games this admits 7 from 10,
   and the scan's own gate, its multiple-comparison warning and the Need price
   all still apply on top. This only throws out a rung with nothing behind it. */
const SCAN_GUARD = 0.35;
const SCAN_MEDIAN_SHARE = 0.6;  // a rung far below his own median is not a bet
/* Count markets (catches, carries, completions, attempts) barely move from
   week to week, so 60% of the median is still a near-certain rung: 3+
   catches for a man who makes six. Those rungs topped every scan on hit rate
   and are the ones a book prices at 1.05. On counts the rung has to sit close
   to his normal output before it counts as a bet, which is what lets the
   yardage markets, where the value actually is, come through. Mirrored in
   parlay.py. */
const COUNT_MEDIAN_SHARE = 0.85;
const COUNT_STATS = new Set(["Receiving receptions", "Rushing attempts",
  "Passing attempts", "Passing completions"]);

/* Markets scored on a scale where whole numbers from one would be absurd: a
   ninety-average darts player would get ninety rungs, eighty-nine of them
   certainties. Mirrors COARSE_GRIDS in parlay.py -- [floor, step]. */
const COARSE_GRIDS = {
  "Average 3 darts": [70, 2],
  "Highest checkout": [40, 10],
};

function ladderRungs(stat, values) {
  const top = values.length ? Math.max(...values) : 0;
  if (top <= 0) return [];
  const rungs = [];
  const coarse = COARSE_GRIDS[stat];
  if (coarse) {
    for (let t = coarse[0]; t <= Math.floor(top); t += coarse[1]) rungs.push(t);
    return rungs;
  }
  if (/yards/i.test(stat)) {
    for (let t = 5; t < 50; t += 5) rungs.push(t);
    for (let t = 50; t <= top + 10; t += 10) rungs.push(t);
  } else {
    for (let t = 1; t <= Math.floor(top); t += 1) rungs.push(t);
  }
  return rungs.filter(t => t <= top);
}

function ladderLine(stat, values) {
  const n = values.length;
  if (!n) return null;
  const sorted = [...values].sort((a, b) => a - b);
  // A real median. Taking the upper of the two middle values on an even
  // sample lifts the floor just enough to reject the one rung that qualified.
  const median = n % 2
    ? sorted[(n - 1) / 2]
    : (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
  let best = null;
  ladderRungs(stat, values).forEach(threshold => {
    const share = COUNT_STATS.has(stat) ? COUNT_MEDIAN_SHARE : SCAN_MEDIAN_SHARE;
    if (median > 0 && threshold < share * median) return;
    const hits = values.filter(v => v >= threshold).length;
    if (!hits) return;
    // A record that has never missed says nothing about what the bet is
    // worth, only about how small the sample is. One over one is not a price.
    if (hits === n) return;
    if (hits / n >= SCAN_FLOOR && wilsonLow(hits, n) >= SCAN_GUARD) {
      best = { threshold, hits, total: n };
    }
  });
  return best;
}

/* The scan gate, mirrored from model.py -- change one, run verify.py,
   change the other.

   Markets the scan must never propose. The Players tab still shows the
   numbers and the custom builder will still price one on request; the
   objection is to the tool recommending the bet. Goals is excluded because
   the backtest proved the old floor structurally unable to select skill
   there: base rate 9.5% per appearance, no player in 745 with 10+
   appearances sustained 65%, so every qualifying record was a lucky streak
   -- quoted goals bets averaged an 82.5% pre-match record and landed
   21.8%. */
const PLAYER_SCAN_EXCLUDE = new Set(["Goals"]);

/* Pseudo-appearances of prior evidence the gate charges a record against,
   at the market's own base rate. Chosen by replaying both leagues ungated
   and re-gating offline: m of 5 matched or beat its neighbours in both
   leagues while keeping 64-70% of the old gate's volume. */
const GATE_PRIOR_APPS = 5;

/* The hit rate the player scan gates on: the raw record shrunk towards the
   market's own base rate. A fixed floor on hits/n cannot select skill in a
   market whose base rate sits far below it, only luck, and the measured
   overconfidence tracked exactly that distance (-3 points on tackles over
   0.5, -25 on goals). Shrinking first makes the floor relative: a 4/4 run
   clears 0.65 in a 60% market and fails it in a 25% one. `base` is the
   pooled rate at this line across every appearance in the squad's own
   window, so the gate sees only what the page already knows at kick-off. */
function gateRate(hits, total, base) {
  if (total + GATE_PRIOR_APPS <= 0) return 0;
  return (hits + GATE_PRIOR_APPS * base) / (total + GATE_PRIOR_APPS);
}

/* How many rows one fixture may contribute to the player shortlist.

   Three was the right number when player rows and team matchups shared a
   single list: the cap existed so a squad of fifty could not swamp the team
   bets, and three per fixture was the price of admission to somebody else's
   tab.

   Players have their own tab now, so there is nothing left to swamp, and
   three was actively hiding good bets. Courtland Sutton is the case that
   showed it: his 4+ receptions is 7 from 10, which clears every gate, and he
   was nowhere on the page because three Broncos rows had already been taken.

   Still capped rather than unlimited, because one fixture filling the whole
   round's list is its own kind of useless, and because a squad's worth of
   rows off one game is a lot of nearly-identical bets. The per-competition
   limit above still governs how many are actually shown. */
const PLAYER_SCAN_CAP = 8;

function scanPlayerBets(minSample) {
  const found = [];

  /* Every player row the scan actually looked at, before the per-player and
     per-fixture caps thin it out. The "this scan looked at N combinations"
     warning is about how many questions were asked, not how many answers
     survived, so the count has to be taken here. Reporting the team scan's
     count on this tab, which an earlier version did, was quietly describing
     a different experiment. */
  let combos = 0;

  scanFixtures().forEach(([fx, fxIndex]) => {
    if (!Array.isArray(fx.players) || !fx.players.some(r => r.length)) return;
    const now = Date.now() / 1000;
    if (scanScope !== "fixture" && !showPast
        && (fx.fixture.kickoff || 0) <= now) return;

    const keep = [];

    fx.players.forEach((records, teamIndex) => {
      const fxRows = [];
      // The same match window the team scan uses, venue pooled: a player's
      // ten-appearance sample does not survive being halved by venue.
      const allowed = new Set(fx.records[teamIndex].slice(-games).map(m => m.id));
      const meetings = meetingIds(teamIndex, fx);

      (fx.playerStats || []).forEach(stat => {
        if (!PLAYER_SCAN_ALLOW.has(stat)) return;
        if (PLAYER_SCAN_EXCLUDE.has(stat)) return;
        // Only a presence check now: if the report never derived a line for
        // this stat it has no data for it either. The line each row is
        // actually quoted at comes off that player's own ladder below.
        if ((fx.playerLines || {})[stat] === undefined) return;

        const adjustment = playerAdjustment(stat, teamIndex, fx);

        const byPlayer = new Map();
        records.forEach(r => {
          if (!allowed.has(r.match_id)) return;
          if (!byPlayer.has(r.player)) byPlayer.set(r.player, []);
          byPlayer.get(r.player).push(r);
        });

        // The market's own base rate at this line: every appearance by
        // every player in this squad's window, the population a record
        // has to stand out from before it means anything.
        const appsByName = new Map();
        byPlayer.forEach((played, name) => {
          appsByName.set(name, appearances(played, stat));
        });

        byPlayer.forEach((played, name) => {
          const apps = appsByName.get(name);
          if (apps.length < minSample) return;
          const vals = apps.map(a => a.value);

          // His own rung, not the squad's shared line.
          const rung = ladderLine(stat, vals);
          if (!rung) return;
          const line = rung.threshold - 0.5;
          const hits = rung.hits;

          // The squad's base rate has to be measured at the same rung, or the
          // gate is comparing his record at one line with everyone else's at
          // another.
          let bk = 0, bn = 0;
          appsByName.forEach(other => {
            other.forEach(a => { bn += 1; if (a.value > line) bk += 1; });
          });
          const base = bn ? bk / bn : 0;

          if (gateRate(hits, vals.length, base) < MATCHUP_FLOOR) return;

          let vs = null;
          const deepVs = h2hPlayerRecords(teamIndex, fx, name);
          const vsSource = deepVs || (meetings
            ? played.filter(g => meetings.has(g.match_id)) : null);
          if (vsSource && vsSource.length) {
            const vsApps = appearances(vsSource, stat);
            if (vsApps.length) {
              vs = { k: vsApps.filter(a => a.value > line).length,
                     n: vsApps.length,
                     deep: !!deepVs };
            }
          }

          const price = withModel(pricePlayer(apps, line, true, adjustment,
            positionPrior(byPlayer, played[0].position || "", stat, name)), name, stat, line, true, fx);
          if (!isFinite(price.fair)) return;

          // The opponent's half, over the same match window the player's
          // own record uses here (last N, venue pooled). Display only.
          const matchup = matchupProfile(
            fx, 1 - teamIndex, played[0].position || "", stat, line,
            ((fx.records || [])[1 - teamIndex] || []).slice(-games),
            `scan|${games}`);

          fxRows.push({
            score: wilsonLow(hits, vals.length),
            k: hits, n: vals.length, over: true, line,
            alt: true, threshold: rung.threshold,
            stat, period: "ALL",
            player: name, position: played[0].position || "",
            fixture: `${fx.fixture.home} v ${fx.fixture.away}`,
            fixtureIndex: fxIndex,
            competition: fx.fixture.competition,
            kickoff: fx.fixture.kickoff || 0,
            team: fx.teams[teamIndex].name,
            teamIndex,
            opponent: fx.teams[1 - teamIndex].name,
            forVals: vals, vals,
            chance: binomTail(vals.length, hits),
            vs,
            vsAgrees: vs ? vs.k / vs.n >= MATCHUP_FLOOR : null,
            matchup,
            // What feeds the bet, over the same window as the record.
            usage: usageProfile(fx, teamIndex, name, stat,
                                (fx.records[teamIndex] || []).slice(-games)),
            price,
          });
          combos++;
        });
      });

      /* One row per player, confirmed head-to-heads first, then evidence. A
         versus-opponent record only counts as confirmation on more than one
         meeting, and only when the meetings themselves point the right way.

         Capped per squad, not per fixture. The cap used to sit outside this
         loop, so both teams' players competed for the same few slots and the
         better-supported squad took the lot. Courtland Sutton is the case:
         8th of Denver's 9 qualifying players, comfortably inside a cap of
         eight, and absent from the page because Jacksonville's list was in
         the queue ahead of him. A fixture's shortlist showing one team's
         players is not a shortlist for that fixture. */
      const confirmed = r => (r.vsAgrees === true && r.vs.n > 1) ? 1 : 0;
      const bestByPlayer = new Map();
      fxRows.forEach(r => {
        const held = bestByPlayer.get(r.player);
        if (!held
            || confirmed(r) > confirmed(held)
            || (confirmed(r) === confirmed(held) && r.score > held.score)) {
          bestByPlayer.set(r.player, r);
        }
      });
      const ranked = [...bestByPlayer.values()].sort((a, b) =>
        (confirmed(b) - confirmed(a)) || (b.score - a.score));
      keep.push(...ranked.slice(0, PLAYER_SCAN_CAP));
    });

    found.push(...keep);
  });

  return { found, combos };
}

/* ----------------------------------------------------- recommended slip

   One suggested multiple per fixture: the fewest, best-evidenced legs whose
   fair prices multiply past a target.

   The honest framing matters here, so it is worth being explicit. A multiple
   is a worse bet than its legs -- the margin compounds, and the legs in one
   match are correlated, which makes the true price longer than the product of
   the parts. This exists because a short-priced single is dull, not because it
   is good value, and the panel says so rather than dressing it up.

   Selection is greedy on evidence, not on price. Taking the longest prices
   first would reach any target in two legs and would be the worst three bets
   on the board. So legs are ordered by how well supported they are, and the
   longest-priced among the well-supported ones are added until the product
   clears the target. */

function recommendedSlip() {
  const box = document.getElementById("rec-slip");
  if (!box) return;

  const target = parseFloat(document.getElementById("rtarget")?.value) || 3.0;
  const wanted = Math.max(2, parseInt(document.getElementById("rlegs")?.value, 10) || 3);

  const priceable = (window.__pool || window.__best || []).filter(r => {
    const pr = r.price || priceRow(r);
    return isFinite(pr.fair) && pr.fair > 1.05 && !pr.conflict;
  });

  /* The bar applies here too, or it is only half a standard: a suggested slip
     built from legs you would reject by hand is not a suggestion, it is a
     different opinion wearing the same panel.
   
     It cannot be absolute, though. Set the bar high enough and nothing clears
     it, and a panel that goes blank tells you less than a panel that says why.
     So the bar filters when it leaves enough to build with, and otherwise
     stands down and says it has. */
  const bar = slipBar();
  const above = priceable.filter(r => scorePick(r, 0).shown >= bar);
  const wantedNow = Math.max(2, parseInt(document.getElementById("rlegs")?.value, 10) || 3);
  const barHeld = above.length >= Math.max(2, wantedNow);
  const pool = barHeld ? above : priceable;
  const barNote = barHeld
    ? `Every leg here scores ${bar} or better before a price is typed.`
    : `Only ${above.length} selection${above.length === 1 ? "" : "s"} on the
       board score ${bar} or better, which is not enough for ${wantedNow} legs,
       so this is built from the whole qualifying set. Lower the bar, or widen
       Scope to the whole round, if you want it honoured.`;

  if (pool.length < 2) {
    box.innerHTML = `<div class="caution"><strong>No slip to suggest.</strong>
      There are not enough priceable bets here to build one.</div>`;
    return;
  }

  // Each leg needs to carry its share of the target. Asking for 3.00 from
  // three legs means about 1.44 each, so legs are drawn from those that clear
  // that bar, best-evidenced first.
  //
  // The first version sorted purely on evidence and took the top three, which
  // produced three near-certainties multiplying to 1.38 -- nowhere near the
  // target, and a slip nobody would place. Sorting purely on price is the
  // opposite mistake: it reaches any target in two legs by taking the two
  // worst bets on the board. The share-of-target bar is what balances the two.
  const perLeg = Math.pow(target, 1 / wanted);
  const fairOf = r => (r.price || priceRow(r)).fair;

  const byEvidence = (a, b) => {
    const ea = wilsonLow(a.k, a.n), eb = wilsonLow(b.k, b.n);
    if (Math.abs(ea - eb) > 0.04) return eb - ea;
    return fairOf(b) - fairOf(a);
  };

  // One leg per team per stat, so the slip is not three ways of betting on the
  // same thing happening. Correlated legs are the standard way a multiple
  // looks better than it is.
  // One leg per team per stat, so the slip is not three ways of betting on
  // the same thing happening. Best-evidenced wins the slot.
  const bestByKey = new Map();
  pool.forEach(r => {
    const key = `${r.fixtureIndex}|${r.teamIndex}|${r.stat}`;
    const held = bestByKey.get(key);
    if (!held || byEvidence(r, held) < 0) bestByKey.set(key, r);
  });

  /* Search the combinations rather than picking greedily.

     The old version took the best-evidenced legs clearing their share of the
     target and filled any gap with the longest prices on the board. That is
     fine while enough legs clear the share, and silently gives up once they
     do not: raise the target past the point where `wanted` legs each pay
     target^(1/wanted) and it stops following you, because no single leg it
     reaches for can make up the difference.

     A combination can. One leg at 3.00 and two at 1.40 pay 5.88 between them
     while none of the three clears 1.75 on its own, and greedy never sees it.
     So: rank the pool, keep the plausible top of it, and walk every
     combination of the right size. Of those that clear the target, take the
     best-evidenced; if none do, take the longest-priced so the shortfall is
     as small as the board allows. Twenty-eight legs choose three is four
     thousand combinations, which is nothing. */
  /* The candidates: the best-evidenced legs and the longest-priced ones.

     Ranking on one blended score and keeping the top slice quietly caps how
     far the slip can reach. Evidence and price pull in opposite directions,
     so a list ordered by any mixture of them holds the middle and throws away
     both ends -- and the long end is exactly what a high target needs. Taking
     the head of both lists keeps the shape of the board: the near-certainties
     that carry a slip and the prices that get it to the number. */
  const unique = [...bestByKey.values()];
  const cap = wanted >= 5 ? 14 : 18;
  const byEv = unique.slice().sort((a, b) => wilsonLow(b.k, b.n) - wilsonLow(a.k, a.n));
  const byPrice = unique.slice().sort((a, b) => fairOf(b) - fairOf(a));
  const ranked = [...new Set([...byEv.slice(0, cap), ...byPrice.slice(0, cap)])];

  const evidenceOf = r => wilsonLow(r.k, r.n);
  let bestHit = null, bestMiss = null;

  const walk = (start, chosen, price, score) => {
    if (chosen.length === wanted) {
      const cand = { legs: chosen.slice(), price, score };
      if (price >= target) {
        if (!bestHit || cand.score > bestHit.score) bestHit = cand;
      } else if (!bestMiss || cand.price > bestMiss.price) {
        bestMiss = cand;
      }
      return;
    }
    // Nothing left to reach the target with: every remaining leg is shorter
    // than this one, so the best this branch can still pay is bounded.
    for (let i = start; i < ranked.length; i++) {
      const r = ranked[i];
      chosen.push(r);
      walk(i + 1, chosen, price * fairOf(r), score + evidenceOf(r));
      chosen.pop();
    }
  };
  if (ranked.length >= wanted) walk(0, [], 1, 0);

  const picked = bestHit || bestMiss;
  const legs = picked ? picked.legs.slice() : ranked.slice(0, wanted);

  // Longest price last reads better in a list: the certainties set it up.
  legs.sort((a, b) => fairOf(a) - fairOf(b));

  window.__recLegs = legs;
  const combined = legs.reduce((acc, r) => acc * (r.price || priceRow(r)).fair, 1);
  const rows = legs.map(r => {
    const pr = r.price || priceRow(r);
    return `<li>${escapeHtml(r.player ? r.player + " (" + r.team + ")" : r.team)}
      ${r.alt ? `${r.threshold}+` : `${r.over ? "over" : "under"} ${r.line}`}
      ${escapeHtml(r.stat.toLowerCase())}
      ${r.period !== "ALL" ? `(${escapeHtml((ALL.periods || {})[r.period] || r.period)})` : ""}
      &mdash; <strong>${fmtOdds(pr.fair)}</strong> fair,
      record ${r.k}/${r.n}</li>`;
  }).join("");

  const short = combined < target;

  box.innerHTML = `<div class="caution">
    <strong>Suggested ${legs.length}-leg slip.</strong>
    Fair combined price <strong>${fmtOdds(combined)}</strong>
    ${short
      ? `, which is short of your ${fmtOdds(target)} target &mdash; the longest
         ${wanted} legs that qualify here do not multiply that far. Only
         ${pool.length} selection${pool.length === 1 ? "" : "s"} clear the
         current filters, so widen Scope to the whole round, drop Min each
         side, or ask for more legs.`
      : `, against your ${fmtOdds(target)} target.`}
    <ol class="rec-legs">${rows}</ol>
    <div class="rec-bar ${barHeld ? "is-ok" : "is-warn"}">${barNote}</div>
    <button type="button" class="add-btn" id="rec-add">Add these to my slip</button>
    <br><br>
    These are fair prices, not offers. You need a bookmaker to beat every one of
    them for the multiple to be worth taking, and the legs come from one round,
    so they are more correlated than the arithmetic assumes. A multiple is the
    shop's best product, not yours.
  </div>`;
}


/* The probability a row lands, however it was priced. Player rows are priced
   through a different path and do not all carry `p`, so the fair price is the
   fallback -- it is one over the same number. */
function probOf(r) {
  const pr = r.price || priceRow(r);
  if (pr && isFinite(pr.p) && pr.p > 0) return pr.p;
  if (pr && isFinite(pr.fair) && pr.fair > 1) return 1 / pr.fair;
  return r.n > 0 ? r.k / r.n : 0;
}

/* Value, in probability points: how much the matchup moves the number.

   This is the only edge signal the tool actually holds. The record is roughly
   what a book prices off; the opponent-adjusted projection knows who the
   opponent is, and where it says a bet lands more often than the raw form
   does, the price on offer is too long. That is value. A long price on its
   own is not -- it is just a bet that loses more often.

   Zero when nothing disagrees with the record, which is the honest answer
   rather than a flattering one: with no projection behind a row there is no
   second opinion, so there is no edge to claim. Those rows sink to the bottom
   of this ordering and the panel says why. */
function valueEdge(r) {
  const pr = r.price || priceRow(r);
  if (!pr || !isFinite(pr.p) || r.n <= 0) return 0;
  if (pr.source !== "model" && pr.source !== "blend") return 0;
  return pr.p - r.k / r.n;
}

/* Darts bets are priced off the record alone (no opponent-adjusted model
   across PDC events), and record-only scores top out in the 30s and 40s, so
   football's default bar of 60 left every darts slip unbuilt. Lowered once,
   on load, and only if nobody has typed their own. */
if (SPORT === "darts") {
  const el = document.getElementById("bbar");
  if (el && el.value === "60") el.value = "30";
}

function slipBar() {
  const el = document.getElementById("bbar");
  const v = el ? parseInt(el.value, 10) : 60;
  return isFinite(v) ? Math.max(0, Math.min(100, v)) : 60;
}

function bestBetsView() {
  const cardBar = slipBar();
  const minSample = parseInt(document.getElementById("bmin").value, 10) || 4;
  const limit = parseInt(document.getElementById("btop").value, 10) || 10;
  MATCHUP_FLOOR = Math.min(1, Math.max(0.3,
    (parseInt(document.getElementById("bfloor").value, 10) || 50) / 100));
  /* One scan or the other, never both in one list.
     See the note beside `bestKind`: a player prop and a team line are not
     competing for the same slot because you would not place them in the same
     place. The team scan still reports its combination count and skip count
     on the player tab, because the multiple-comparisons warning is about how
     many questions the page asked, and on the player tab that is the player
     scan's own count. */
  let found, combos, skipped = 0;
  if (bestKind === "team") {
    ({ found, combos, skipped } = scanMatchups(minSample));
  } else {
    ({ found, combos } = scanPlayerBets(minSample));
  }
  /* The quality gate.

     A hit rate on its own decides nothing. "19 from 20" is a magnificent
     record and a terrible bet, because the price that record justifies once
     the sample size is paid for is 1.31 and a bookmaker pays 1.10. `need` is
     where the two meet, so `need` is what a shortlist has to be cut on --
     everything above the bar is a bet you cannot get a price for, however
     good the number beside it looks.

     Measured rather than guessed: over a 267-row NFL pool the median need is
     1.91 and the quartiles are 1.71 and 2.17, so a bar of 2.00 keeps a little
     over half and throws out the tail that was never backable. Raise it to
     see more, lower it to see only the tight ones. */
  const needCap = parseFloat(document.getElementById("bneed")?.value) || 99;
  const beforeCap = found.length;
  found = found.filter(r => {
    const pr = r.price || priceRow(r);
    return isFinite(pr.need) && pr.need <= needCap;
  });
  const cutByNeed = beforeCap - found.length;

  /* One row per bet, not one per fixture it appears in.
     A club sitting in two upcoming fixtures in the same file carries its
     squad under both, so "Tre Tucker 2+ receptions" was listed twice. Keep
     the one that kicks off first, which is the one you can still back. */
  const byBet = new Map();
  found.forEach(r => {
    const key = `${r.player || r.team}|${r.stat}|${r.line}|${r.over}`;
    const held = byBet.get(key);
    if (!held || (r.kickoff || 0) < (held.kickoff || 0)) byBet.set(key, r);
  });
  found = [...byBet.values()];

  found = found.slice().sort((a, b) => b.score - a.score);

  const periodName = p => (ALL.periods && ALL.periods[p]) || p;
  const target = document.getElementById("bestbets");

  if (!found.length) {
    target.innerHTML = bestKind === "team"
      ? `<p class="empty">No matchup in
        ${scanScope === "fixture" ? "this fixture" : "this round"} had both halves
        at ${Math.round(MATCHUP_FLOOR * 100)}% or better on at least ${minSample}
        matches each. Lower "Min each side", or widen the scope.</p>`
      : `<p class="empty">No player in
        ${scanScope === "fixture" ? "this fixture" : "this round"} cleared
        ${Math.round(MATCHUP_FLOOR * 100)}% on at least ${minSample}
        appearances in a market the scan prices. Lower "Min each side", widen
        the scope, or check the report was built with --players: without them
        there are no player rows to find.</p>`;
    window.__best = [];
    recommendedSlip();
    return;
  }

  // Now that prices actually vary, one ordering no longer suits. Evidence puts
  // the best-supported records first. Likely sorts by the model's probability,
  // which favours mismatches. Price sorts the other way, surfacing the ones
  // that pay something, which are the ones worth pricing up against a book.
  const order = document.querySelector("[data-border][aria-pressed='true']")
    ?.dataset.border || "evidence";

  found.forEach(r => { r.price = r.price || priceRow(r); });

  // Drop the ones where the count model and the record cannot both be right.
  const contradictory = found.filter(r => r.price.conflict).length;
  found = found.filter(r => !r.price.conflict);

  if (!found.length) {
    target.innerHTML = `<p class="empty">Everything that qualified was thrown
      out because the model and the record contradicted each other. That
      usually means the ratings fit is thin for this competition.</p>`;
    window.__best = [];
    recommendedSlip();
    return;
  }

  /* These used to be three views of one number. "Most likely" sorted by
     `need` ascending and `need` is one over the Wilson lower bound -- which is
     exactly what the incoming sort on `score` already does, so Evidence and
     Most likely returned the same list in the same order. "Best price" sorted
     the other way, which is not a third opinion, it is the first one upside
     down: the longest prices among a set that has already passed the evidence
     gate are simply its weakest members. Pressing the buttons did nothing you
     would notice, and when it did, it was wrong.

     Three different questions, three different quantities:

       Evidence     the Wilson lower bound. What survives paying for the
                    sample size. Small samples are punished.
       Most likely  the calibrated probability itself. What lands most often,
                    sample size not charged for, so a thin 3/3 can lead.
       Best value   how far the opponent-adjusted projection sits above the
                    raw record. A book prices off form; the projection is the
                    part it is slower to see, and a bet the matchup likes more
                    than the form does is one whose price is too big. */
  if (order === "likely") {
    found.sort((a, b) => probOf(b) - probOf(a));
  } else if (order === "value") {
    /* Value, once the gate has already done the evidence.
       Ranking on evidence alone puts "1+ receiving receptions, 14 from 15" at
       the top: an outstanding record, a 1.07 fair price, and nothing you
       would ever back. Everything reaching this point has cleared the hit
       rate floor and the need cap, so the remaining question is simply how
       much it pays -- the longest price that the evidence still supports.
       Where the projection does disagree with the record, that edge breaks
       the tie, because it is the only genuine market signal here. */
    const fairOf = r => {
      const pr = r.price || priceRow(r);
      return isFinite(pr.fair) ? pr.fair : 0;
    };
    found.sort((a, b) => (fairOf(b) - fairOf(a)) || (valueEdge(b) - valueEdge(a)));
  }

  // Grouped by competition, because "top three this gameweek" means three
  // per division, not three across a file that happens to hold six leagues.
  const byComp = new Map();
  found.forEach(r => {
    if (!byComp.has(r.competition)) byComp.set(r.competition, []);
    byComp.get(r.competition).push(r);
  });

  const shown = [];
  // Everything that qualified, before the per-competition display cap. The
  // cards are a shortlist to read; the slip builder should be choosing from
  // the whole qualifying set, or raising the target just runs it out of legs
  // that the cap happened to keep.
  const qualifying = [];
  const blocks = [...byComp.entries()].map(([comp, rows]) => {
    rows.forEach(r => qualifying.push(r));
    const picks = rows.slice(0, limit);
    const cards = picks.map(r => {
      const i = shown.push(r) - 1;
      // A player row keeps the price the scan gave it. Sending it through
      // priceRow would price a player's shots off the team's expectation,
      // which is exactly the bug the custom builder already guards against.
      const price = r.player ? r.price : priceRow(r);
      r.price = price;                      // the slip reads this back

      // The same score the slip will give it, so the bar is visible before
      // you add anything rather than only afterwards. No price typed here,
      // so it is the provisional number and says so.
      const cardScore = scorePick(r, 0);
      const cardPass = cardScore.shown >= cardBar;
      const scoreChip = `<span class="pick-score ${cardPass ? "pass" : "fail"}"
        title="Provisional score out of 100 -- evidence, model agreement and
        context. Value is the other 45 points and needs the price you have been
        offered, so type it on the slip. Your bar is ${cardBar}.">score
        ${cardScore.shown}</span>`;

      if (r.player) {
        const fmtV = v => (Number.isInteger(v) ? v : v.toFixed(1));
        let vsHalf;
        if (r.vs) {
          const small = r.vs.n < 3;
          vsHalf = `<div class="half">
            <span class="half-label">v ${escapeHtml(r.opponent)}, ${
              r.vs.deep ? "previous meetings" : "meetings in this window"}</span>
            <span class="half-num">${r.vs.k}/${r.vs.n}</span>
            <div class="bar"><div class="fill" style="width:${(r.vs.k / r.vs.n) * 100}%;
                 background:var(${VARS[r.teamIndex]})"></div></div>
            <span class="seq">${
              small ? `only ${r.vs.n} meeting${r.vs.n === 1 ? "" : "s"} with player data`
              : r.vs.deep ? `${r.vs.n} appearance${r.vs.n === 1 ? "" : "s"} against them`
              : `${r.vs.n} inside the last ${games === 99 ? "" : games + " "}matches &mdash; rebuild with --h2h --players for the full history`}</span>
          </div>`;
        } else {
          vsHalf = `<div class="half">
            <span class="half-label">v ${escapeHtml(r.opponent)}</span>
            <span class="half-num">&mdash;</span>
            <span class="seq">${(r.fx && r.fx.h2hPlayers) || false
              ? "no previous meeting has player data"
              : "no meetings with player data &mdash; rebuild with --h2h --players"}</span>
          </div>`;
        }

        const agreeLine = r.vs
          ? (r.vsAgrees
              ? `<div class="agree yes">Record v ${escapeHtml(r.opponent)}
                   agrees (${r.vs.k}/${r.vs.n}${r.vs.n < 3 ? ", small sample" : ""})</div>`
              : `<div class="agree no">Record v ${escapeHtml(r.opponent)}
                   disagrees (${r.vs.k}/${r.vs.n})</div>`)
          : "";

        return `<div class="pick pick-player" data-best="${i}">
          <div class="pick-head">
            <div class="pick-line">${escapeHtml(r.player)} ${r.alt
                ? `${r.threshold}+` : `over ${r.line}`}
              ${escapeHtml(r.stat.toLowerCase())}
              <span class="tag-player">player &middot; ${escapeHtml(r.team)}</span>
              <span class="pos">${periodName(r.period)}</span></div>
            <div class="pick-fixture">${escapeHtml(r.fixture)}</div>
          </div>

          <div class="pick-halves${r.matchup ? " three" : ""}">
            <div class="half">
              <span class="half-label">Last ${r.n} appearances</span>
              <span class="half-num">${r.k}/${r.n}</span>
              <div class="bar"><div class="fill" style="width:${(r.k / r.n) * 100}%;
                   background:var(${VARS[r.teamIndex]})"></div></div>
              <span class="seq">${r.vals.map(fmtV).join(", ")}</span>
            </div>
            ${vsHalf}
            ${matchupHalf(r.matchup, r.teamIndex)}
          </div>

          <div class="pick-foot">
            <span><b>${r.k}/${r.n}</b> in form</span>
            ${usageNote(r.usage)}
            ${scoreChip}
            <span>fair <b>${fmtOdds(price.fair)}</b></span>
            <span class="need-cell">need <b>${fmtOdds(price.need)}</b>
              ${price.source === "model"
                ? `<span class="src" title="${price.per90.toFixed(2)} per 90 over ` +
                  `${price.expectedMinutes} expected minutes, adjusted for the matchup, ` +
                  `priced through the same path as the Players tab.">` +
                  `${price.expected.toFixed(1)}&nbsp;exp</span>`
                : price.source === "blend"
                ? `<span class="src warnsrc" title="Blended price: ` +
                  `${Math.round((1 - price.blend.w) * 100)}% from same-position ` +
                  `team-mates, ${Math.round(price.blend.w * 100)}% from his own ` +
                  `${price.n} appearance${price.n === 1 ? "" : "s"}. Unproven: no ` +
                  `backtest covers player bets.">` +
                  `${price.expected.toFixed(1)}&nbsp;exp &middot; ` +
                  `${Math.round((1 - price.blend.w) * 100)}% team</span>`
                : `<span class="src warnsrc" title="Too little data for the minutes ` +
                  `model, so this is the record-only interval.">record only</span>`}
            </span>
            <span class="chance">${fmtChance(r.chance)} by chance</span>
            ${agreeLine}
            <button type="button" class="add-btn" data-badd="${i}"
              data-in="${SLIP.some(s => s.key === rowKey(r)) ? 1 : 0}">
              ${SLIP.some(s => s.key === rowKey(r)) ? "Added" : "Add"}</button>
          </div>
          ${ladderTable(r.stat, r.vals, r.alt ? r.threshold : null)}
        </div>`;
      }
      const fair = price.fair;
      const need = price.need;
      const dir = r.over ? "over" : "under";

      // The projection, when there is one, is the only thing here that did
      // not come from the same matches as the record.
      let agree = "";
      const projValues = r.proj || r.est;
      if (projValues) {
        const expected = projValues[r.teamIndex];
        if (expected !== undefined) {
          const agrees = r.over ? expected > r.line : expected < r.line;
          agree = `<div class="agree ${agrees ? "yes" : "no"}">
            ${r.proj ? "Projected" : "Estimated"} ${expected}
            ${agrees ? "agrees" : "disagrees"}</div>`;
        }
      }

      return `<div class="pick" data-best="${i}">
        <div class="pick-head">
          <div class="pick-line">${escapeHtml(r.team)} ${dir} ${r.line}
            ${escapeHtml(r.stat.toLowerCase())}
            <span class="pos">${periodName(r.period)}</span></div>
          <div class="pick-fixture">${escapeHtml(r.fixture)}</div>
        </div>

        <div class="pick-halves">
          <div class="half">
            <span class="half-label">${escapeHtml(r.team)} ${SPORT === "darts" ? "form" : r.attackVenue}</span>
            <span class="half-num">${r.kFor}/${r.nFor}</span>
            <div class="bar"><div class="fill" style="width:${r.pFor * 100}%;
                 background:var(${VARS[r.teamIndex]})"></div></div>
            <span class="seq">${r.forVals.join(", ")}</span>
          </div>
          <div class="half">
            <span class="half-label">${SPORT === "darts"
              ? `${escapeHtml(r.opponent)}'s opponents`
              : `${escapeHtml(r.opponent)} conceded, ${r.defendVenue}`}</span>
            <span class="half-num">${r.kAgn}/${r.nAgn}</span>
            <div class="bar"><div class="fill" style="width:${r.pAgn * 100}%;
                 background:var(${VARS[1 - r.teamIndex]})"></div></div>
            <span class="seq">${r.againstVals.join(", ")}</span>
          </div>
        </div>

        <div class="pick-foot">
          <span><b>${r.k}/${r.n}</b> combined</span>
          ${scoreChip}
          <span>fair <b>${fmtOdds(fair)}</b></span>
          <span class="need-cell">need <b>${fmtOdds(need)}</b>
            ${price.source === "model"
              ? `<span class="src" title="Priced from an expected ${price.expected} in this fixture, ` +
                `read off a fitted count distribution. The record on its own would have said ` +
                `${fmtOdds(price.recordNeed)}.">${price.expected}&nbsp;exp</span>`
              : `<span class="src warnsrc" title="No opponent-adjusted expectation for this fixture, ` +
                `so this is the blunt record-only interval.">record only</span>`}
          </span>
          <span class="chance">${fmtChance(r.chance)} by chance</span>
          ${agree}
          <button type="button" class="add-btn" data-badd="${i}"
            data-in="${SLIP.some(s => s.key === rowKey(r)) ? 1 : 0}">
            ${SLIP.some(s => s.key === rowKey(r)) ? "Added" : "Add"}</button>
        </div>
      </div>`;
    }).join("");

    return `<div class="comp-head">${escapeHtml(comp)}
      <span class="pos">${rows.length} qualified</span></div>${cards}`;
  }).join("");

  window.__best = shown;
  window.__pool = qualifying;
  recommendedSlip();

  const weakest = shown[shown.length - 1];
  const expected = combos * binomTail(weakest.n, weakest.k);

  /* Say which question the list is answering. Three buttons that silently
     reorder a list are indistinguishable from three buttons that do nothing,
     which is roughly what the old ones did. */
  const noProjection = order === "value" &&
    !found.some(r => Math.abs(valueEdge(r)) > 0.001);
  const ORDER_NOTES = {
    evidence: `Ordered by <strong>evidence</strong>: the bottom of the 95%
      interval, so a long record beats a short hot streak. The safest reading
      of what is here, and the one that ignores price entirely.`,
    likely: `Ordered by <strong>how often it lands</strong>: the calibrated
      probability itself, with no charge for sample size. A perfect three from
      three can lead this list, so read the record beside each one &mdash; that
      is the difference between this order and Evidence, and the reason both
      exist.`,
    value: noProjection
      ? `Ordered by <strong>value</strong>, but nothing here has an
         opponent-adjusted projection behind it, so there is no second opinion
         to disagree with the record and no edge to rank on. This list is
         unchanged from Evidence. Build with <code>--adjust</code> to fit the
         ratings and this order starts working.`
      : `Ordered by <strong>value</strong>: how far the opponent-adjusted
         projection sits above the raw record. A book prices mostly off form;
         the projection knows who the opponent is. Where it says a bet lands
         more often than the form does, the price on offer is too long &mdash;
         and that, not a long price on its own, is what value means.`,
  };
  const orderNote =
    `<div class="order-note">${ORDER_NOTES[order] || ORDER_NOTES.evidence}</div>`;

  target.innerHTML = `
    <div class="caution">
      ${bestKind === "team" ? `<strong>What this is.</strong> Both halves of the fixture pointing the
      same way: the team's own record at this venue, and what their opponent
      concedes at theirs. Two records agreeing is stronger evidence than one
      record twice as long, because they can fail independently. Both halves
      must clear ${Math.round(MATCHUP_FLOOR * 100)}% on their own before a
      pairing is scored at all, so a 10/10 cannot drag a 3/10 into the list.`
        : `<strong>What this is.</strong>
      The picks marked "player" are one record, not two: a single player's
      own appearances, priced through the same per-90 minutes model as the
      Players tab. Where the data allows it, the card also shows his record
      at this line against this exact opponent; the form record and the
      head-to-head agreeing is the strongest signal these rows carry, and the
      number of meetings is printed beside it because 1/1 is one match, not a
      pattern. To qualify at all, a player's record is first shrunk towards
      the market's own base rate, so a short streak in a market where the
      event is rare cannot buy its way in; goals are not proposed at all,
      because no player sustains a scoring rate any floor would accept and
      every qualifying record there was a lucky run. At most ${PLAYER_SCAN_CAP} player rows per fixture are let in,
      so they cannot swamp the team matchups. The third block is the
      opponent's half of the case: what they have allowed in this stat to
      players of his position class, or for fouls what the players he will be
      marking have drawn, over the same match window, with the sample and
      coverage printed. Position is only G, D, M or F, so it cannot tell a
      winger from a striker. It is context and moves no price.`}
      <br><br>
      <strong>What it is not.</strong> This scan looked at
      <strong>${combos}</strong> combinations, and
      ${expected < 1
        ? `fewer than <strong>one</strong> of them would`
        : `roughly <strong>${expected.toFixed(0)}</strong> of them would`}
      look this good with nothing behind them at all. Both records also come from the same matches
      the lines were derived from, which flatters them. <strong>Need</strong> is
      the price the evidence supports once the sample size is accounted for, and
      it is the only number here worth betting off. Nothing on this page knows
      what the bookmaker is offering, and the price is the entire bet.
      ${skipped ? `<br><br><strong>${skipped}</strong> pairings were left out
        because one side's record was built in a different competition.` : ""}
      ${cutByNeed ? `<br><br><strong>${cutByNeed}</strong> qualifying record${
        cutByNeed === 1 ? " was" : "s were"} dropped for needing a price longer
        than ${needCap.toFixed(2)}. They are real records; they are not bets,
        because no bookmaker pays what the evidence behind them demands.` : ""}
      ${contradictory ? `<br><br><strong>${contradictory}</strong> more were
        dropped because the count model and the raw record contradicted each
        other beyond what either one's uncertainty allows. When those two
        disagree that badly, one of them is wrong and there is no way to tell
        which from here.` : ""}
    </div>
    ${orderNote}
    ${blocks}`;
}

function rowKey(r) {
  return [r.player || "", r.fixtureIndex, r.teamIndex,
          r.stat, r.period, r.line, r.over].join("|");
}

function standoutView() {
  const minSample = parseInt(document.getElementById("smin").value, 10) || 6;
  const limit = parseInt(document.getElementById("stop").value, 10) || 20;

  const { found, combos, skipped } = scanLines(minSample);
  const shown = found.slice(0, limit);
  window.__shown = shown;

  const periodName = p => (ALL.periods && ALL.periods[p]) || p;

  if (!shown.length) {
    document.getElementById("standout").innerHTML =
      '<p class="empty">Nothing met the minimum sample. Lower it, or build with more matches.</p>';
    return;
  }

  // How many of the scanned combinations would reach the weakest shown
  // record purely by chance? This is the number that keeps you honest.
  const weakest = shown[shown.length - 1];
  const expected = combos * binomTail(weakest.n, weakest.k);

  const rows = shown.map((r, i) => {
    const p = r.k / r.n;
    const price = priceRow(r);
    r.price = price;
    const fair = price.fair;
    const minPrice = price.need;
    return `
    <tr data-row="${i}" data-plow="${1 / minPrice}" data-fair="${fair}" data-min="${minPrice}">
      <td class="player-name">${r.stat}
        <span class="pos">${periodName(r.period)}</span>
        <span class="sub-line">${r.team} &middot; ${r.split} &middot; ${r.fixture}</span></td>
      <td class="dir">${r.over ? "Over" : "Under"} ${r.line}</td>
      <td data-label="Record">
        <div><span class="pct">${Math.round(p * 100)}%</span>
             <span class="frac">${r.k}/${r.n}</span></div>
        <div class="bar"><div class="fill" style="width:${p * 100}%;
             background:var(${VARS[r.teamIndex]})"></div></div>
      </td>
      <td class="odds" data-label="Fair">${fmtOdds(fair)}</td>
      <td class="odds odds-min" data-label="Need">${fmtOdds(minPrice)}</td>
      <td data-label="Your price">
        <input class="price-input" type="number" step="0.05" min="1.01"
               data-price aria-label="Bookmaker price for ${r.stat}"></td>
      <td class="verdict" data-verdict data-label="Verdict"></td>
      <td class="chance" data-label="By chance">${(r.chance * 100).toFixed(1)}%</td>
      <td><button type="button" class="add-btn" data-add="${i}"
            data-in="${SLIP.some(s => s.key === rowKey(r)) ? 1 : 0}">
            ${SLIP.some(s => s.key === rowKey(r)) ? "Added" : "Add"}</button></td>
    </tr>`;
  }).join("");

  document.getElementById("standout").innerHTML = `
    <div class="caution">
      <strong>Read this before using any of it.</strong>
      This scan looked at <strong>${combos}</strong> combinations of fixture, team,
      stat, period and venue. Of those, roughly <strong>${expected.toFixed(0)}</strong>
      would look at least this consistent even if every one of them were a coin flip.
      The list below is therefore a shortlist to price up, not a set of findings.
      A hit rate is not an edge: the only thing that makes a bet worth taking is the
      price being wrong, and there is no odds feed here to tell you that.
      The lines are also derived from these same matches, which flatters them.
      ${skipped ? `<br><br><strong>${skipped}</strong> team-stat combinations were
        left out because that side's record was built in a different competition
        from the one they are playing in. Use the toggle to include them, but a
        promoted side's numbers against weaker opposition are exactly the sort of
        true record that loses money.` : ""}
      <br><br>
      <strong>Fair</strong> is the price the hit rate implies on its own.
      <strong>Need</strong> is the price the <em>evidence</em> supports, taken from the
      bottom of a 95% interval, and it is the one to bet off. Ten matches cannot tell
      80% from 55%, so 8/10 reads as a fair 1.25 while only really justifying 2.04.
      Neither figure includes the bookmaker's margin, which is typically 5 to 8% on
      these markets and always works against you.
    </div>
    <div class="board"><table class="ptable">
      <thead><tr>
        <th>Stat</th><th>Line</th><th>Record</th>
        <th title="Price implied by the hit rate itself">Fair</th>
        <th title="Price implied by the bottom of the confidence interval">Need</th>
        <th>Your price</th><th>Verdict</th><th>By chance</th><th></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

/* ------------------------------------------------------------------ slip

   A score out of 100, built from four things that can each be justified
   rather than one number pulled out of the air. The breakdown is always
   shown, because a score you cannot interrogate is just an opinion with a
   number stuck on it.

   Value carries the most weight by a distance, and deliberately so. The
   record tells you what happened; only the price tells you whether the bet
   is worth making. A 10/10 record at 1.10 is a bad bet and a 6/10 record at
   4.00 may be a good one. */
const SLIP = [];

function scorePick(r, price) {
  const parts = {};

  /* Every one of these used to saturate, and a score that is always 100 is
     not a score. Value maxed out at fifteen per cent above `need`, which is
     an ordinary price rather than a good one. Evidence maxed at fourteen
     matches, and a team matchup routinely has twenty. Agreement and context
     were each all-or-nothing. On a real Premier League report the whole board
     came back at 100 out of 100, so a bar set anywhere passed everything and
     told you nothing.

     Each part is now a curve over the range the number actually occupies. */

  const clamp01 = x => Math.max(0, Math.min(1, x));

  // Value: how far the price beats what the evidence supports. Zero without a
  // price, because without one there is nothing to judge -- and zero at `need`
  // itself, because `need` is break-even, not profit. Full marks at double it:
  // log-spaced, so the middle of the range is where most bets land rather than
  // all crowded against the ceiling.
  if (!price || price <= 1) {
    parts.value = 0;
  } else {
    const need = (r.price || priceRow(r)).need;
    // A record of 0 from n gives a Wilson lower bound of 0 and therefore an
    // infinite need, which turned the whole score into NaN. It is not an
    // error: it means the evidence supports no price at all, so no price can
    // beat it. Score the value at zero and let the evidence and agreement
    // parts speak instead.
    const ratio = (isFinite(need) && need > 0) ? price / need : 0;
    parts.value = ratio > 1
      ? Math.round(45 * clamp01(Math.log(ratio) / Math.log(2)))
      : 0;
  }

  // Evidence: not the sample size but what the sample supports, which is the
  // Wilson lower bound -- it already charges for a short record. Half of the
  // interval's bottom is no evidence at all; 85% is as much as ten or twenty
  // matches can ever show.
  const low = wilsonLow(r.k, r.n);
  parts.evidence = Math.round(25 * clamp01((low - 0.50) / 0.35));

  // Agreement: does the opponent-adjusted projection point the same way, and
  // by how much? A projection sitting a whisker the right side of the line is
  // not the same evidence as one sitting a third of the way clear of it, and
  // scoring them both fifteen said it was.
  const proj = ((ALL.fixtures[r.fixtureIndex].projection || {})[r.period] || {})[r.stat];
  if (proj === undefined) {
    parts.agreement = 7;                      // unknown, so neither rewarded nor punished
  } else {
    const expected = proj[r.teamIndex];
    const agrees = r.over ? expected > r.line : expected < r.line;
    const margin = Math.abs(expected - r.line) / Math.max(0.5, Math.abs(r.line));
    parts.agreement = agrees ? Math.round(15 * clamp01(margin / 0.30)) : 0;
  }

  // Context: was the record built against the right standard of opposition?
  // Graded, for the same reason as agreement: 59% of a sample in the right
  // competition and 0% of it were both scored zero.
  const fx = ALL.fixtures[r.fixtureIndex];
  const sample = fx.records[r.teamIndex].slice(-games);
  const matching = sample.filter(
    x => (x.competition || "?") === fx.fixture.competition
  ).length;
  const coverage = sample.length ? matching / sample.length : 0;
  parts.context = Math.round(15 * clamp01((coverage - 0.30) / 0.60));

  const total = parts.value + parts.evidence + parts.agreement + parts.context;

  /* Without a price, value is not zero. It is unknown.

     Scoring it zero capped every un-priced leg at 55 out of 100, so a bar set
     anywhere sensible rejected the entire board until a price had been typed
     into every row -- which reads as the bar being broken rather than as the
     bar working. So when there is no price the three parts that *can* be
     judged are rescaled to a hundred and the number is marked provisional.
     Type a price and the real score takes over, usually downwards, which is
     the correct direction for a surprise. */
  const priced = !!(price && price > 1);
  const shown = priced ? total : Math.round((total / 55) * 100);
  return { total, parts, priced, shown };
}

/* A better leg of the same shape, for a leg that has missed the bar.

   "Better" has to be judged at the same price, or the comparison collapses
   into "something longer" and the slip gets worse one swap at a time. So each
   candidate is scored against the price you were quoted for the leg it would
   replace. With no price typed, the fair prices have to be close instead: a
   1.20 quietly swapped for a 4.00 is not the slip you asked for, however well
   the 4.00 scores.

   Correlation is the other half. A replacement that doubles up on a team and
   stat already in the slip is not a second bet, it is the same bet twice at
   multiplied odds, which is how a multiple comes to look better than it is. */
/* Which replacement has already been offered under which leg.

   Two legs failing the bar at a similar price nominate the same replacement,
   because it is simply the best thing on the board in that bracket -- and a
   panel that offers you one bet twice is inviting you to put it on twice.
   Keyed by slip position so a single row can be rewritten in place (the price
   handler does exactly that) without disturbing the others' offers or
   excluding itself from its own. */
const SWAP_OFFERED = new Map();

function alternativesFor(entry, index, count = 2) {
  const pool = window.__pool || window.__best || [];
  if (!pool.length) return [];

  SWAP_OFFERED.delete(index);
  const elsewhere = new Set();
  SWAP_OFFERED.forEach(keys => keys.forEach(k => elsewhere.add(k)));

  const current = scorePick(entry.row, entry.price);
  const bar = slipBar();
  const fairOfRow = r => (r.price || priceRow(r)).fair;
  const mine = fairOfRow(entry.row);

  // Everything the rest of the slip already commits to.
  const taken = new Set(SLIP.map(s => s.key));
  const committed = new Set(SLIP.filter((s, i) => i !== index)
    .map(s => `${s.row.fixtureIndex}|${s.row.teamIndex}|${s.row.stat}`));

  const out = [];
  pool.forEach(r => {
    if (taken.has(rowKey(r))) return;
    if (elsewhere.has(rowKey(r))) return;
    if (committed.has(`${r.fixtureIndex}|${r.teamIndex}|${r.stat}`)) return;

    const fair = fairOfRow(r);
    if (!isFinite(fair) || fair <= 1.05) return;
    // Same price bracket, so the slip still reaches the number it was built
    // for. Wider when a price has been typed, because then the score is
    // judging the price directly and the bracket only has to stop absurdities.
    const lo = entry.price > 1 ? 0.6 : 0.75;
    const hi = entry.price > 1 ? 1.8 : 1.35;
    if (isFinite(mine) && (fair < mine * lo || fair > mine * hi)) return;

    const s = scorePick(r, entry.price);
    if (s.shown < bar || s.shown <= current.shown) return;
    out.push({ row: r, score: s });
  });

  out.sort((a, b) => b.score.shown - a.score.shown);
  const chosen = out.slice(0, count);
  SWAP_OFFERED.set(index, chosen.map(a => rowKey(a.row)));
  return chosen;
}

/* One line describing a selection, for the swap suggestions. */
function legLabel(r) {
  const what = r.player
    ? `${r.player} ${r.alt ? r.threshold + "+" : (r.over ? "over " : "under ") + r.line} ${r.stat.toLowerCase()}`
    : `${r.team} ${r.over ? "over" : "under"} ${r.line} ${r.stat.toLowerCase()}`;
  return escapeHtml(what);
}

/* The combined-price panel, as its own function so it can be refreshed when a
   price changes without rebuilding the table underneath it. */
function comboPanel(priced) {
  if (priced.length <= 1) return "";

  const combined = priced.reduce((acc, s) => acc * s.price, 1);
  // Multiply the supported probabilities, not the raw records, so a long
  // shot leg is not flattered by a small sample that happened to be perfect.
  const chance = priced.reduce(
    (acc, s) => acc * Math.min(0.999, 1 / (s.row.price || priceRow(s.row)).need), 1);
  const fair = 1 / chance;
  const perLeg = Math.pow(fair / combined, 1 / priced.length);

  return `<div class="caution">
    <strong>Putting ${priced.length} of these together.</strong>
    Combined price <strong>${fmtOdds(combined)}</strong>, against a fair price of
    <strong>${fmtOdds(fair)}</strong> on the conservative estimates.
    ${combined >= fair
      ? "That clears, but only if the legs are genuinely independent, and they rarely are."
      : `You would need each leg to be about <strong>${((perLeg - 1) * 100).toFixed(1)}%</strong>
         better priced than it is for this to break even.`}
    <br><br>
    Worth knowing what multiples do. The bookmaker's margin compounds with every
    leg: at a typical 5% per market, a treble carries about 16% against you and a
    five-fold about 28%. Singles are where value survives. Accumulators are the
    most profitable product in the shop, and not for the person buying them.
  </div>`;
}


/* Refresh only the parts of the slip that depend on a typed price. Deliberately
   never touches the inputs, so typing is never interrupted. */
function updateSlipTotals() {
  const holder = document.getElementById("slip-combo");
  if (!holder) return;
  const priced = SLIP.filter(s => s.price > 1);
  holder.innerHTML = comboPanel(priced);
}


/* What a slip leg is worth, with the record as the floor.

   The slip was printing "n/a" for legs whose model price came back
   non-finite, which is the one thing it must never do: the record is sitting
   right there. Nine times in twenty is a 45% chance and 45% is 2.22 -- that
   arithmetic needs no model and cannot fail.

   So the model price is used when it exists and the record answers when it
   does not. The only honest "n/a" left is a leg that has never landed once:
   zero from twenty says the price is longer than twenty, and how much longer
   is not something twenty matches can tell you.

   fair  = one over the strike rate. What the record alone implies.
   need  = one over the bottom of the 95% interval. What the evidence
           supports once the sample size is paid for, and the number to bet
           off, because ten matches cannot tell 80% from 55%. */
function slipPrice(r) {
  const held = r.price || priceRow(r);
  const k = r.k, n = r.n;
  const out = {
    fair: held && isFinite(held.fair) ? held.fair : null,
    need: held && isFinite(held.need) ? held.need : null,
    source: held && held.source ? held.source : "record",
  };
  if (out.fair === null && n > 0 && k > 0) { out.fair = n / k; out.source = "record"; }
  if (out.need === null && n > 0 && k > 0) {
    const low = wilsonLow(k, n);
    out.need = low > 0 ? 1 / low : null;
    out.source = "record";
  }
  return out;
}

/* The score as it should read: a number, and a mark when forty-five of its
   hundred points could not be judged because no price has been typed yet. */
function scoreText(sc) {
  return sc.priced ? String(sc.shown)
    : `${sc.shown}<sup title="Provisional: value is 45 of the 100 points and ` +
      `cannot be scored until you type the price you have been offered. This ` +
      `is the other 55 rescaled, and it will usually fall once a real price ` +
      `goes in.">?</sup>`;
}

function breakdownText(sc) {
  const p = sc.parts;
  return (sc.priced
      ? `<span>value ${p.value}/45</span>`
      : `<span class="unscored">value &mdash;/45 &middot; no price yet</span>`)
    + `<span>evidence ${p.evidence}/25</span>`
    + `<span>model ${p.agreement}/15</span>`
    + `<span>context ${p.context}/15</span>`;
}

/* What to do about a leg that has missed the bar. */
function swapBlock(entry, i) {
  const bar = slipBar();
  const sc = scorePick(entry.row, entry.price);
  if (sc.shown >= bar) return "";

  const alts = alternativesFor(entry, i);
  if (!alts.length) {
    return `<div class="swap-none">Scores ${sc.shown}, under your bar of
      ${bar}${sc.priced ? "" : " on the provisional number"}. Nothing else on
      the board beats it at a similar price, so the choice is to take it
      knowing what it is, drop it, or lower the bar.</div>`;
  }

  const options = alts.map(a => `<li>
    <span class="swap-leg">${legLabel(a.row)}</span>
    <span class="swap-meta">${a.row.k}/${a.row.n} &middot;
      fair ${fmtOdds((a.row.price || priceRow(a.row)).fair)} &middot;
      needs ${fmtOdds((a.row.price || priceRow(a.row)).need)}</span>
    <span class="swap-score">${a.score.shown}</span>
    <button type="button" class="add-btn" data-swap="${i}"
      data-swap-key="${escapeHtml(rowKey(a.row))}">Swap in</button>
  </li>`).join("");

  return `<div class="swap-has">
    <div class="swap-head">Scores ${sc.shown}, under your bar of ${bar}.
      ${alts.length === 1 ? "This one is" : "These are"} stronger at about the
      same price${entry.price > 1 ? `, judged at the ${fmtOdds(entry.price)} you were quoted` : ""}:</div>
    <ol class="swap-list">${options}</ol>
  </div>`;
}

function slipView() {
  const el = document.getElementById("slip");

  if (!SLIP.length) {
    el.innerHTML = `<p class="empty">
      Nothing added yet. Open Standout lines and press "Add" on any row.
    </p>`;
    return;
  }

  const bar = slipBar();
  let clearing = 0;
  SWAP_OFFERED.clear();

  const rows = SLIP.map((entry, i) => {
    const r = entry.row;
    const sc = scorePick(r, entry.price);
    const pass = sc.shown >= bar;
    if (pass) clearing += 1;
    const cls = pass ? "good" : (sc.shown < bar - 20 ? "poor" : "");

    return `<tr data-slip="${i}">
      <td class="player-name">${r.player ? `${r.player} ${r.stat.toLowerCase()}` : r.stat}
        <span class="pos">${r.player ? "player" : (ALL.periods || {})[r.period] || r.period}</span>
        <span class="sub-line">${r.player ? r.team : r.team} &middot;
          ${r.over ? "Over" : "Under"} ${r.line} &middot; ${r.fixture}</span></td>
      <td class="num" data-label="Record">${r.k}/${r.n}
        <span class="pos">${r.n ? Math.round((r.k / r.n) * 100) + "%" : ""}</span></td>
      <td class="odds" data-label="Fair">${fmtOdds(slipPrice(r).fair)}</td>
      <td class="odds odds-min" data-label="Need">${fmtOdds(slipPrice(r).need)}</td>
      <td data-label="Your price">
        <input class="price-input" type="number" step="0.05" min="1.01"
               value="${entry.price || ""}" data-slip-price
               aria-label="Price for ${r.stat}"></td>
      <td data-label="Score">
        <div class="score ${cls}">${scoreText(sc)}</div>
        <div class="breakdown">${breakdownText(sc)}</div>
        <div class="bar-chip ${pass ? "pass" : "fail"}"
             title="Your bar is ${bar}. ${pass
               ? "This clears it."
               : "This does not, so a replacement is suggested below."}">
          ${pass ? "clears " + bar : "below " + bar}</div>
      </td>
      <td><button type="button" class="add-btn" data-remove="${i}">Remove</button></td>
    </tr>
    <tr class="swap-row" data-swap-for="${i}"${pass ? " hidden" : ""}>
      <td colspan="7">${swapBlock(entry, i)}</td>
    </tr>`;
  }).join("");

  // What happens if you put them together.
  const priced = SLIP.filter(s => s.price > 1);
  const combo = comboPanel(priced);

  const short = SLIP.length - clearing;
  const summary = `<div class="slip-bar-summary ${short ? "is-warn" : "is-ok"}">
    <strong>${clearing} of ${SLIP.length}</strong>
    leg${SLIP.length === 1 ? "" : "s"} clear your bar of ${bar}.
    ${short
      ? `The ${short === 1 ? "one that does not has" : short + " that do not have"}
         a replacement suggested underneath ${short === 1 ? "it" : "them"}.`
      : `Nothing here is being carried by the rest.`}
    <span class="pos">A leg with no price typed is scored provisionally on the
      55 points that do not need one.</span>
  </div>`;

  el.innerHTML = `${summary}<div id="slip-combo">${combo}</div>
    <div class="board"><table class="ptable">
      <thead><tr>
        <th>Selection</th><th>Record</th>
        <th title="One over the strike rate: what the record alone implies">Fair</th>
        <th title="One over the bottom of the 95% interval: what the evidence supports once the sample size is paid for">Need</th>
        <th>Your price</th><th>Score</th><th></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

/* ------------------------------------------------------------ post-match

   For a fixture that has been played: what the projections said, what actually
   happened, and why each one held or did not.

   The point is not to keep score. It is that a projection which was wrong is
   only useful if you can see *how* it was wrong, and the two failure modes look
   nothing alike. A projection of 5.2 corners against an actual 5 that still
   lost the bet is a line problem. A projection of 5.2 against an actual 1 is a
   model problem. Printing both as "missed" would hide the only distinction
   that matters.

   Nothing here is fitted or adjusted. It reports and stops, for the same
   reason review.py does: a single match is far too little to learn from, and
   the temptation to tune on it is exactly how a model ends up explaining last
   Saturday and knowing nothing about next Saturday. */

function resultView() {
  const box = document.getElementById("result");
  if (!box) return;

  const res = DATA.fixture.result;
  if (!res) { box.innerHTML = ""; return; }

  const proj = DATA.projection || {};
  const lines = [];

  Object.keys(proj).forEach(per => {
    Object.entries(proj[per] || {}).forEach(([stat, pair]) => {
      const got = ((res.stats || {})[per] || {})[stat];
      if (!got) return;

      [0, 1].forEach(side => {
        const expected = pair[side];
        const actual = got[side];
        if (expected === undefined || actual === undefined) return;
        lines.push({
          per, stat, side, expected, actual,
          error: expected > 0 ? (actual - expected) / expected : 0,
        });
      });
    });
  });

  if (!lines.length) {
    box.innerHTML = `<div class="caution">
      <strong>${escapeHtml(DATA.fixture.home)} ${res.home}&ndash;${res.away}
      ${escapeHtml(DATA.fixture.away)}.</strong>
      This fixture had no projections to check, so there is nothing to review.
    </div>`;
    return;
  }

  // Worst first: the misses are the informative part, and burying them under
  // the hits is how a review becomes a victory lap.
  lines.sort((a, b) => Math.abs(b.error) - Math.abs(a.error));

  const close = lines.filter(l => Math.abs(l.error) <= 0.2).length;
  const rows = lines.slice(0, 14).map(l => {
    const team = DATA.teams[l.side].name;
    const period = l.per !== "ALL"
      ? ` (${escapeHtml((ALL.periods || {})[l.per] || l.per)})` : "";
    const pct = (l.error * 100).toFixed(0);

    let verdict, cls;
    if (Math.abs(l.error) <= 0.2) {
      verdict = "projection held";
      cls = "good";
    } else if (Math.abs(l.error) <= 0.45) {
      verdict = l.error > 0 ? "ran over the projection" : "fell short of it";
      cls = "";
    } else {
      verdict = l.error > 0 ? "far above the projection" : "far below it";
      cls = "poor";
    }

    return `<tr>
      <td>${escapeHtml(team)} ${escapeHtml(l.stat.toLowerCase())}${period}</td>
      <td class="num">${l.expected.toFixed(1)}</td>
      <td class="num">${l.actual}</td>
      <td class="num ${cls}">${l.error > 0 ? "+" : ""}${pct}%</td>
      <td>${verdict}</td>
    </tr>`;
  }).join("");

  const share = Math.round(close / lines.length * 100);

  box.innerHTML = `<div class="caution">
    <strong>${escapeHtml(DATA.fixture.home)} ${res.home}&ndash;${res.away}
    ${escapeHtml(DATA.fixture.away)} &mdash; how the projections did.</strong>
    ${close} of ${lines.length} landed within 20% of the projection (${share}%).
    <div class="board"><table class="ptable">
      <thead><tr>
        <th>Stat</th><th>Projected</th><th>Actual</th><th>Error</th><th></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    One match is far too little to draw a conclusion from, and a projection
    that missed by 60% here is not evidence the model is broken any more than
    one that landed is evidence it works. What it is good for is spotting a
    pattern across weeks: run <code>review.py</code> once a few rounds have
    settled, and that will tell you something this table cannot.
  </div>`;
}


/* ------------------------------------------------------- custom bet builder

   Build any bet over a stat this report tracks, at any line, and have it
   scored by exactly the same machinery as a scanned one. That last part is the
   whole point: a bet you type in has to be comparable with one the scan found,
   or the slip is mixing two different meanings of "score".

   So this constructs the same row shape the scan produces -- same keys, same
   values array, same record -- and hands it to the same priceRow(). Nothing
   here reimplements any maths. Markets outside these stats are deliberately
   not offered, because there is no record behind them to price against, and a
   score with nothing under it would be worse than no score. */

function customFixture() {
  const i = parseInt(document.getElementById("c-fixture").value, 10);
  return ALL.fixtures[i] || DATA;
}

function fillCustom() {
  const fxSel = document.getElementById("c-fixture");
  if (!fxSel) return;

  const current = ALL.fixtures.indexOf(DATA);
  fxSel.innerHTML = ALL.fixtures.map((f, i) =>
    `<option value="${i}"${i === current ? " selected" : ""}>` +
    `${escapeHtml(f.fixture.home)} v ${escapeHtml(f.fixture.away)}</option>`
  ).join("");

  fillCustomTeams();
}

function fillCustomTeams() {
  const fx = customFixture();
  const teamSel = document.getElementById("c-team");
  teamSel.innerHTML = fx.teams.map((t, i) =>
    `<option value="${i}">${escapeHtml(t.name)}</option>`).join("");

  const perSel = document.getElementById("c-period");
  perSel.innerHTML = Object.keys(fx.stats || {}).map(per =>
    `<option value="${per}">${escapeHtml((ALL.periods || {})[per] || per)}</option>`
  ).join("");

  fillCustomPlayers();
  fillCustomStats();
}

function fillCustomPlayers() {
  const fx = customFixture();
  const teamIndex = parseInt(document.getElementById("c-team").value, 10) || 0;
  const sel = document.getElementById("c-player");
  const records = (fx.players || [])[teamIndex] || [];

  const names = [...new Set(records.map(r => r.player))].sort();
  sel.innerHTML = `<option value="">Team stat</option>` +
    names.map(n => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join("");
}

function fillCustomStats() {
  const fx = customFixture();
  const player = document.getElementById("c-player").value;
  const per = document.getElementById("c-period").value || "ALL";
  const sel = document.getElementById("c-stat");

  // A player bet is always whole-match: SofaScore does not split a player's
  // numbers by half, so offering a half here would be inventing data.
  const names = player
    ? (fx.playerStats || []).filter(n => BETTABLE.has(n) || PLAYER_EXTRA.has(n))
    : (fx.stats[per] || []).filter(n => BETTABLE.has(n));

  sel.innerHTML = names.map(n =>
    `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join("");

  document.getElementById("c-period").disabled = !!player;
  customPreview();
}

/* Player stats worth betting that the team-level BETTABLE list does not carry.
   Fouls is the one that matters: it is the closest thing this data has to a
   card market, since cards are not in the per-player feed at all. */
const PLAYER_EXTRA = new Set(["Fouls", "Fouled", "Saves", "Goals", "Assists"]);

/* The row a custom bet describes, in the shape the scan and the slip expect,
   or null when there is not enough behind it to price. */
function customRow() {
  const fx = customFixture();
  const fixtureIndex = parseInt(document.getElementById("c-fixture").value, 10) || 0;
  const teamIndex = parseInt(document.getElementById("c-team").value, 10) || 0;
  const playerName = document.getElementById("c-player").value;
  const stat = document.getElementById("c-stat").value;
  const per = playerName ? "ALL" : (document.getElementById("c-period").value || "ALL");
  const over = document.getElementById("c-side").value === "over";
  const line = parseFloat(document.getElementById("c-line").value);
  const price = parseFloat(document.getElementById("c-price").value) || 0;

  if (!stat || !isFinite(line)) return null;

  if (playerName) {
    const records = (fx.players || [])[teamIndex] || [];
    const mine = records.filter(r => r.player === playerName);

    // Appearances, not raw rows: a match he did not play is an absence, not a
    // zero, and counting it as a zero is what made every player price wrong
    // once before. appearances() applies the same minutes floor and zero-fill
    // the Players tab uses, so a bet built here means the same thing.
    const apps = appearances(mine, stat);
    if (apps.length < 3) return null;

    const vals = apps.map(a => a.value);
    const hits = vals.filter(v => over ? v > line : v < line).length;

    // Priced through pricePlayer(), not the team path. A player expectation is
    // a per-90 rate scaled to the minutes he is likely to get, and the team
    // path has no notion of minutes at all: it found no projection, fell back
    // to the bare record, and priced a fouls under at 1.00 off a 0/14 record.
    const byName = new Map();
    records.forEach(r => {
      if (!byName.has(r.player)) byName.set(r.player, []);
      byName.get(r.player).push(r);
    });
    const price_ = withModel(pricePlayer(apps, line, over, playerAdjustment(stat, teamIndex),
      positionPrior(byName, mine[0].position || "", stat, playerName)), playerName, stat, line, over, fx);

    return {
      player: playerName,
      stat, line, over, period: "ALL",
      k: hits, n: vals.length,
      score: wilsonLow(hits, vals.length),
      team: fx.teams[teamIndex].name,
      teamIndex,
      fixture: `${fx.fixture.home} v ${fx.fixture.away}`,
      fixtureIndex,
      chance: binomTail(vals.length, hits),
      forVals: vals, vals,
      price: price_,
      typed: price,
      custom: true,
    };
  }

  const rows = fx.records[teamIndex] || [];
  const vals = rows.map(r => (r.stats[per] || {})[stat])
                   .filter(v => v !== undefined && v !== null);
  if (vals.length < 3) return null;

  const hits = vals.filter(v => over ? v > line : v < line).length;
  const opponent = fx.teams[1 - teamIndex].name;

  return {
    stat, line, over, period: per,
    k: hits, n: vals.length,
    score: wilsonLow(hits, vals.length),
    team: fx.teams[teamIndex].name,
    teamIndex,
    opponent,
    fixture: `${fx.fixture.home} v ${fx.fixture.away}`,
    fixtureIndex,
    chance: binomTail(vals.length, hits),
    forVals: vals, vals, price,
    custom: true,
  };
}

function customPreview() {
  const box = document.getElementById("c-preview");
  if (!box) return;

  const r = customRow();
  if (!r) {
    box.innerHTML = `<span class="muted">Pick a stat with at least three
      matches behind it.</span>`;
    return;
  }

  // A player row carries its own price, worked out from minutes; a team row is
  // priced from the fixture projection. Using priceRow() for both showed a
  // player bet as fair 1.00, because the team path has no player projection to
  // find and quietly fell back to the raw record.
  const priced = r.player ? r.price : priceRow(r);
  const price = parseFloat(document.getElementById("c-price").value) || 0;
  const { total, parts } = scorePick(r, price);

  const verdict = !price
    ? "Type a price to score it."
    : price >= priced.need
      ? `<strong>${fmtOdds(price)} clears the ${fmtOdds(priced.need)} you need.</strong>`
      : `<strong>${fmtOdds(price)} is short of the ${fmtOdds(priced.need)} you need.</strong>`;

  box.innerHTML = `
    Record <strong>${r.k}/${r.n}</strong>.
    Fair <strong>${fmtOdds(priced.fair)}</strong>,
    need <strong>${fmtOdds(priced.need)}</strong>.
    ${price ? `Score <strong>${total}</strong>/100.` : ""}
    ${verdict}
    ${priced.conflict ? `<br><span class="muted">The record and the projection
      disagree beyond either one's uncertainty here, so treat both with
      suspicion.</span>` : ""}`;
}


/* ---------------------------------------------------------------- players */

/* Every player row currently on screen, so the Add button can find its pick
   by index rather than by re-deriving it from the DOM. */
let PLAYER_ROWS = [];

/* A player pick shaped like a team pick, so the slip does not need to know
   the difference. `player` is the flag that distinguishes them where it
   matters, which is only in how the line is described. */
function playerRow(p, stat, line, teamIndex, price) {
  return {
    player: p.name,
    stat, line, over: true,
    period: "ALL",
    k: p.hits, n: p.vals.length,
    score: wilsonLow(p.hits, p.vals.length),
    team: DATA.teams[teamIndex].name,
    teamIndex,
    fixture: `${DATA.fixture.home} v ${DATA.fixture.away}`,
    fixtureIndex: ALL.fixtures.indexOf(DATA),
    chance: binomTail(p.vals.length, p.hits),
    forVals: p.vals,
    vals: p.vals,
    price,
  };
}

function playerView() {
  if (!hasPlayers()) return;
  if (pMode === "squads") { squadView(); return; }
  PLAYER_ROWS = [];

  const stat = document.getElementById("pstat").value;
  const line = parseFloat(document.getElementById("pline").value) || 0;
  const minApps = parseInt(document.getElementById("pmin").value, 10) || 1;

  // Honour the Team control, the same Both/Home/Away buttons the team tab
  // already obeys. Rendering both squads regardless was the reason picking a
  // team did nothing here and you still had to scroll past the other one.
  const shown = focusedIndexes();

  const blocks = DATA.players.map((records, teamIndex) => {
    if (!shown.includes(teamIndex)) return "";

    // Scope player rows to exactly the matches the team filters are showing,
    // so "last 5, home only" means the same thing on both tabs.
    // activeRecords, not DATA.records, so the Sample control reaches this tab.
    // On head to head that leaves the meetings both sides have player numbers
    // for, which is what "how did he do against this lot" actually means.
    const allowed = new Set(filtered(activeRecords()[teamIndex]).map(m => m.id));
    // Former-club rows come from another team's matches, so their match ids
    // are not in `allowed` and never can be. They are admitted separately,
    // and only where the filters above still mean something: never on head to
    // head, which is a question about these two clubs; never under an
    // Opposition tier filter, which is fitted to this division and cannot
    // classify another league's sides; and only for the venue being asked
    // about. Anything else would quietly show numbers the filters exclude.
    const importsOk = source !== "h2h" && tier === "all";
    const rows = records.filter(r =>
      allowed.has(r.match_id)
      || (importsOk && r.former_club && (venue === "all" || r.venue === venue)));

    const byPlayer = new Map();
    for (const r of rows) {
      if (!byPlayer.has(r.player)) byPlayer.set(r.player, []);
      byPlayer.get(r.player).push(r);
    }

    const meetings = source === "h2h" ? null : meetingIds(teamIndex);
    const oppName = DATA.teams[1 - teamIndex].name;

    // The opponent's half of each row, over the opponent's matches under the
    // same filters, so both halves of the case cover the same window. Only
    // offered when the report carries team ids and the stat has a pairing.
    const oppWindow = filtered(DATA.records[1 - teamIndex] || []);
    const windowKey = `tab|${games}|${venue}|${tier}`;
    const matchupOn = opponentIdFor(teamIndex) !== null && !!MATCHUP_PAIRING[stat];

    const colorVar = VARS[teamIndex];
    const title = `<h2 class="team-title">
        <span class="swatch" style="background:var(${colorVar})"></span>
        ${DATA.teams[teamIndex].name}
      </h2>`;

    const built = [...byPlayer.entries()].map(([name, played]) => {
      // Appearances, not records. A match he watched from the bench is not a
      // losing bet, it is a void one, and counting it as a loss is what made
      // every player price nonsense.
      const apps = appearances(played, stat);
      const vals = apps.map(a => a.value);

      // A new signing is not the same thing as a fringe player, and hiding
      // both behind one appearance count conflates them. Christos Tzolis
      // started for Arsenal with one appearance in the sample and simply was
      // not on the page: the data was there, the minimum hid it, and the
      // absence looked identical to a missing transfer.
      //
      // So anyone who has actually played is kept, and the ones below the
      // minimum are marked as thin rather than dropped. A single match is
      // genuinely weak evidence, which is what the flag says; it is not a
      // reason to pretend the player does not exist.
      if (!vals.length) return null;
      const thin = vals.length < minApps;

      const hits = vals.filter(v => v > line).length;
      const pct = Math.round((hits / vals.length) * 100);
      const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
      const missed = played.length - apps.length;

      // The same line, against this opponent only. Two shots in his last two
      // against them, on top of the form record, is the case that made this
      // worth a column of its own.
      let vs = null;
      if (meetings) {
        const vsApps = appearances(
          played.filter(g => meetings.has(g.match_id)), stat);
        if (vsApps.length) {
          vs = { k: vsApps.filter(a => a.value > line).length, n: vsApps.length };
        }
      }

      // Where the sample came from. A signing's record at his old club is
      // worth seeing, but it is background rather than form for this side:
      // different team, different role, different service. It must never sit
      // on the page looking like he did it here.
      const imported = played.filter(g => g.former_club);
      const from = imported.length
        ? [...new Set(imported.map(g => g.former_club.name))].join(", ")
        : null;

      return { name, pos: played[0].position || "", played, apps, vals,
               hits, pct, avg, missed, thin, vs,
               imported: imported.length, from,
               matchup: matchupOn
                 ? matchupProfile(DATA, 1 - teamIndex, played[0].position || "",
                                  stat, line, oppWindow, windowKey)
                 : null };
    }).filter(Boolean);

    // Well-evidenced players first, then the thin ones. A single appearance
    // sorting to the top on a 100% record would be the most misleading row on
    // the page.
    built.sort((a, b) =>
      (a.thin ? 1 : 0) - (b.thin ? 1 : 0) ||
      b.pct - a.pct || b.vals.length - a.vals.length);

    if (!built.length) {
      return `<div class="team-block">${title}
        <div class="board"><div class="stat-row">
          <span class="empty">No player met the minimum appearances.</span>
        </div></div></div>`;
    }

    const fmt = v => (Number.isInteger(v) ? v : v.toFixed(1));

    const adjustment = playerAdjustment(stat, teamIndex);

    const body = built.map(p => {
      const fake = p.played.map(g => ({
        date: g.date, venue: g.venue, opponent: g.opponent,
        stats: { [stat]: g.stats[stat] },
      }));
      const strong = p.pct >= STRONG_HIGH || p.pct <= STRONG_LOW;

      const price = withModel(pricePlayer(p.apps, line, true, adjustment,
        positionPrior(byPlayer, p.pos, stat, p.name)), p.name, stat, line, true);
      const row = playerRow(p, stat, line, teamIndex, price);
      const inSlip = SLIP.some(s => s.key === rowKey(row));
      const index = PLAYER_ROWS.push({ row, price }) - 1;

      return `<tr class="${strong ? "strong" : ""}${p.thin ? " thin" : ""}">
        <td class="player-name">${p.name}<span class="pos">${p.pos}</span>${
          p.thin
            ? `<span class="tag-thin" title="Only ${p.vals.length} appearance${
                p.vals.length === 1 ? "" : "s"} in this sample: probably a new
                signing or returning from injury. The rate may be real, but one
                or two matches cannot tell you.">new / thin sample</span>`
            : ""}${
          p.from
            ? `<span class="tag-thin" title="${p.imported} of these ${
                p.vals.length} appearances were for ${p.from} before he signed.
                Different side, different role, different service: treat it as
                background rather than form for this team.">incl. ${
                p.imported} at ${p.from}</span>`
            : ""}</td>
        <td class="num" data-label="Apps">${p.vals.length}</td>
        <td class="num" data-label="Avg">${p.avg.toFixed(1)}
          ${price.source === "model"
            ? `<span class="pos">${price.per90.toFixed(1)}/90</span>` : ""}</td>
        <td>
          <div class="pcell">
            <div class="figure">
              <div><span class="pct">${p.pct}%</span>
                   <span class="frac">${p.hits}/${p.vals.length}</span></div>
              <div class="bar"><div class="fill"
                style="width:${p.pct}%;background:var(${colorVar})"></div></div>
            </div>
            ${sparkline(fake, stat, line, colorVar)}
            <span class="seq">${p.vals.map(fmt).join(", ")}</span>
          </div>
        </td>
        ${meetings ? `<td class="num" data-label="v ${oppName}">${
          p.vs
            ? `<b>${p.vs.k}/${p.vs.n}</b>`
            : `<span class="pos">not met</span>`}</td>` : ""}
        ${matchupOn ? matchupCell(p.matchup) : ""}
        <td class="odds" data-label="Fair">${fmtOdds(price.fair)}</td>
        <td class="odds odds-min" data-label="Need">${fmtOdds(price.need)}
          ${price.source === "model"
            ? `<span class="src" title="${price.per90.toFixed(2)} per 90 across ` +
              `${price.minutes} minutes in ${price.n} appearances, over ` +
              `${price.expectedMinutes} expected minutes, then adjusted ` +
              `${adjustment >= 1 ? "up" : "down"} for the matchup.">` +
              `${price.expected.toFixed(1)}&nbsp;exp</span>`
            : price.source === "blend"
            ? `<span class="src warnsrc" title="Blended price, only ${price.n} ` +
              `appearance${price.n === 1 ? "" : "s"}: ` +
              `${Math.round((1 - price.blend.w) * 100)}% of the rate is the ` +
              `${price.blend.prior.players} other ${POSITION_NAME[p.pos] || "players"} ` +
              `in this squad pooled (${price.blend.prior.per90.toFixed(2)} per 90), ` +
              `${Math.round(price.blend.w * 100)}% his own record, over ` +
              `${price.expectedMinutes} expected minutes. Unproven: no backtest ` +
              `covers player bets.">` +
              `${price.expected.toFixed(1)}&nbsp;exp &middot; ` +
              `${Math.round((1 - price.blend.w) * 100)}% team</span>`
            : `<span class="src warnsrc">record only</span>`}
        </td>
        <td><button type="button" class="add-btn" data-padd="${index}"
              data-in="${inSlip ? 1 : 0}">${inSlip ? "Added" : "Add"}</button></td>
      </tr>`;
    }).join("");

    return `<div class="team-block">${title}
      <div class="board"><table class="ptable">
        <thead><tr>
          <th>Player</th><th>Apps</th><th>Avg</th><th>${stat} over ${line}</th>
          ${meetings ? `<th title="The same line, counting only matches against
            ${oppName}. Drawn from every match fetched, not the Matches filter,
            because two sides usually meet twice a season.">v ${oppName}</th>` : ""}
          ${matchupOn ? `<th title="The other half of the case: what ${
            escapeHtml(oppName)} have allowed in this stat to players of the
            same position class, or for fouls what the players he will be
            marking have drawn, over ${escapeHtml(oppName)}'s matches under
            the same filters. Position is G, D, M or F only. Context: it is
            not part of the price.">Matchup</th>` : ""}
          <th title="Price implied by the record and the model">Fair</th>
          <th title="Price the evidence supports">Need</th><th></th>
        </tr></thead>
        <tbody>${body}</tbody>
      </table></div>
    </div>`;
  });

  const panel = document.getElementById("players");
  const note = document.getElementById("pnote");
  if (note) {
    note.hidden = source !== "h2h";
    note.textContent = source === "h2h"
      ? "Head to head: only previous meetings that fall inside the matches "
        + "fetched for each side carry player numbers, so this sample is "
        + "smaller than the team head to head above."
      : "";
  }
  const roomy = shown.length === 2 && window.innerWidth >= TWO_UP_MIN;
  panel.classList.toggle("two-up", roomy);
  document.querySelector(".wrap").classList.toggle("wide", roomy);
  panel.innerHTML = blocks.join("");
}

/* ------------------------------------------------ squads and player profiles

   The Players tab opens on the two sides rather than a stat table. Tap a
   side (or a name in its XI) and then a player, and his profile shows every
   market he has a record in: the last ten, the rate per 90 and a short
   ladder of lines, each with our chance, a fair price, a rough bookmaker
   price and the edge between them. Football adds two markets the stat table
   could never show, to be booked and to score. The old by-stat table is
   still one button away ("Compare by stat").

   Three prices, kept apart on purpose:
   - Ours: the same pricePlayer() chance the rest of the page uses, on the
     filters above and adjusted for this matchup.
   - Betfair: the exchange's price where it lists the market (to score,
     shots on target 1+ and 2+, shown a card), from reports/markets.json,
     which publish.sh writes beside the reports.
   - Est. bookie: what a bookmaker pricing off his whole record would
     roughly offer, the calibrated chance over every match on file with
     BOOK_MARGIN added. A guide, not a scraped price, and the page says so.
     Type the real price into the box and the edge uses that instead.

   The booking and scoring models are heuristic and not backtested. */

let pMode = "squads";
let pState = { fx: null, team: null, player: null };
let MARKETS = null;
let MARKETS_AT = null;
const PRICE_IN = {};

/* Assumed bookmaker margin on a single player prop, as a mark-up on the
   implied chance. A judgement call, not a fitted number: set it from real
   prices once a few have been typed in against the estimate. */
const BOOK_MARGIN = 0.12;

/* Cards per foul when a side has too few fouls on file to measure its own. */
const CARDS_PER_FOUL_DEFAULT = 0.13;

const PP_HEADLINE = [["Fouled", 0.5], ["Fouls", 0.5], ["Shots", 0.5],
                     ["Shots on target", 0.5], ["Tackles", 0.5]];

function normName(s) {
  return String(s || "").normalize("NFKD").replace(/[^a-zA-Z ]/g, "")
    .toLowerCase().split(" ").filter(Boolean).join(" ");
}

function fixtureMarket(fx) {
  fx = fx || DATA;
  if (!MARKETS || !fx || !fx.fixture) return null;
  return MARKETS[String(fx.fixture.id)] || null;
}

function playerMarket(name) {
  const m = fixtureMarket();
  return m && m.players ? m.players[normName(name)] || null : null;
}

function loadMarkets() {
  if (typeof fetch !== "function" || location.protocol === "file:") return;
  fetch("markets.json", { cache: "no-store" })
    .then(r => (r.ok ? r.json() : null))
    .then(j => {
      if (!j || !j.events) return;
      MARKETS = j.events;
      MARKETS_AT = j.fetched || null;
      oddsStrip();
      if (tab === "players") playerView();
      if (tab === "value") valueView();
    })
    .catch(() => {});
}

/* ------------------------------------------------- the backtested model

   reports/fmodel.json, written by fmodel_live.py before every publish: a
   chance for each starter in the predicted or confirmed XI at 15 football
   lines (shots 1-3+, shots on target 1-2+, fouls 1-2+, fouled 1-3+,
   tackles 1-3+, to score, to assist). It is trained on team and opponent
   style, the players he lines up against, partners, head to head and
   league strength as well as his own form, and in the out-of-sample test
   (July 2026 on) it beat pricePlayer on all 15 lines and was within about a
   point of the truth at every chance level. See USAGE.md, "Player model".

   Where it has a chance it replaces pricePlayer's; anywhere else (other
   lines, other sports, a player with under three full games on file) the
   page keeps its own. It assumes the player starts. */
let FMODEL = null;

/* reports/usmodel.json, written by usmodel_live.py before every publish: the
   backtested NBA and NFL player models (LightGBM on form, team and opponent
   style, Elo, what the defence concedes to his position, missing team-mates
   and head to head), a chance at every line for each player expected to
   play. Out of sample (NFL from December 2025, NBA from April 2026) the blend
   of it with the site's own chance beat the site on 11 of 12 NFL markets and
   every NBA one. It is used exactly where the football model is: see
   withModel(). */
let USMODEL = null;

function loadUSModel() {
  if (SPORT !== "basketball" && SPORT !== "american-football") return;
  if (typeof fetch !== "function" || location.protocol === "file:") return;
  fetch("usmodel.json", { cache: "no-store" })
    .then(r => (r.ok ? r.json() : null))
    .then(j => {
      if (!j || !j.events) return;
      const events = {};
      for (const [id, ev] of Object.entries(j.events)) {
        const by = {};
        for (const [n, pl] of Object.entries(ev.players || {})) by[normName(n)] = pl;
        // confirmed: the model used a confirmed line-up (usmodel_live.py)
        events[id] = { confirmed: !!ev.confirmed, players: by };
      }
      USMODEL = { events, blend: (j.blend || {})[SPORT] || {} };
      BEST_CACHE.clear();
      if (tab === "players") playerView();
      if (tab === "value") valueView();
    })
    .catch(() => {});
}

function loadFModel() {
  if (typeof fetch !== "function" || location.protocol === "file:") return;
  fetch("fmodel.json", { cache: "no-store" })
    .then(r => (r.ok ? r.json() : null))
    .then(j => {
      if (!j || !j.events) return;
      const out = {};
      for (const [id, ev] of Object.entries(j.events)) {
        const by = {};
        for (const [n, pl] of Object.entries(ev.players || {})) by[normName(n)] = pl;
        out[id] = { confirmed: !!ev.confirmed, players: by };
      }
      FMODEL = out;
      BEST_CACHE.clear();
      if (tab === "players") playerView();
    })
    .catch(() => {});
}

function modelEvent(fx) {
  fx = fx || DATA;
  if (!fx || !fx.fixture) return null;
  if (SPORT === "football") return FMODEL ? FMODEL[String(fx.fixture.id)] || null : null;
  return USMODEL ? USMODEL.events[String(fx.fixture.id)] || null : null;
}

/* To be booked from the cards model (cards_model.py via fmodel.json): the
   side's expected cards from the backtested cards model, split across the
   XI by fouls per 90 over expected minutes. Null where it has no chance. */
function cardModelP(name, fx) {
  if (SPORT !== "football") return null;
  return modelP(name, "Card", 0.5, fx);
}

/* The model's chance of OVER `line` for this player, or null. */
function modelP(name, stat, line, fx) {
  const ev = modelEvent(fx);
  const pl = ev && ev.players[normName(name)];
  if (!pl) return null;
  const k = line + 0.5;
  if (!Number.isInteger(k)) return null;
  const v = ((pl.lines || {})[stat] || {})[String(k)];
  return typeof v === "number" ? v : null;
}

/* The Players tab's own chance where fmodel has none, recalibrated.

   scorer_audit.py replayed pricePlayer on every starter since July 2026: it
   ran high on every shots and shots on target line but 1+ (shots on target
   2+ said 19% and landed 7%), because the player calibration above pulls
   every log-odds towards 50%. A Platt map per line, chosen on August and
   holding on September and October, goes in fmodel/site_calib.json and
   reaches the page here at render. Football only, "Stat|k" for "k+", and
   only on the record-based branches (three or more appearances) it was
   fitted on; a line with no map keeps pricePlayer's number. */
const SITE_CALIB = __SITE_CALIB__;

function siteCalibrated(price, stat, line, over) {
  if (SPORT !== "football" || !price || price.source === "blend" || (price.n || 0) < 3) return price;
  const k = line + 0.5;
  const c = Number.isInteger(k) ? SITE_CALIB[`${stat}|${k}`] : null;
  if (!c || !(price.p > 0 && price.p < 1)) return price;
  const pOver = Math.min(1 - 1e-4, Math.max(1e-4, over ? price.p : 1 - price.p));
  const cal = 1 / (1 + Math.exp(-(c[0] + c[1] * Math.log(pOver / (1 - pOver)))));
  const q = over ? cal : 1 - cal;
  return Object.assign({}, price, { p: q, fair: fairOdds(q), need: Math.max(price.need || 0, fairOdds(q)),
    siteCalibrated: true, siteP: price.p });
}

/* pricePlayer's answer with the model's chance swapped in, when it has one. */
function withModel(price, name, stat, line, over, fx) {
  let p = modelP(name, stat, line, fx);
  if (!price) return price;
  if (p === null) return siteCalibrated(price, stat, line, over);
  // NBA and NFL: the model's chance blended with the site's own, recalibrated,
  // with the weights fitted on the validation period (usmodel.json "blend").
  const bl = SPORT !== "football" && USMODEL && USMODEL.blend[stat];
  if (bl) {
    const lg = q => { q = Math.min(1 - 1e-4, Math.max(1e-4, q)); return Math.log(q / (1 - q)); };
    const sg = z => 1 / (1 + Math.exp(-z));
    const siteOver = over ? price.p : 1 - price.p;
    const sf = sg(bl.site_cal[0] + bl.site_cal[1] * lg(siteOver));
    p = sg(bl.blend[0] + bl.blend[1] * lg(p) + bl.blend[2] * lg(sf));
  }
  const q = over ? p : 1 - p;
  const ev = modelEvent(fx);
  const pl = ev && ev.players[normName(name)];
  const mu = pl && pl.mu ? pl.mu[stat] : undefined;
  return Object.assign({}, price, { p: q, fair: fairOdds(q), need: fairOdds(q),
    source: "fmodel", us: SPORT !== "football", siteP: price.p, modelMu: mu });
}

function matchOddsHtml() {
  const m = fixtureMarket();
  if (!m || !m.match) return "";
  const o = m.match;
  const cell = (label, r, t) => r && r.price
    ? `<span class="mo-cell">${t === undefined ? "" :
        `<span class="swatch" style="background:var(${VARS[t]})"></span>`}
        <span>${escapeHtml(label)}</span><b>${fmtOdds(r.price)}</b>
        <small>${Math.round(r.p * 100)}%</small></span>`
    : "";
  const when = MARKETS_AT
    ? new Date(MARKETS_AT * 1000).toLocaleString("en-GB",
        { weekday: "short", hour: "2-digit", minute: "2-digit" })
    : "";
  return `<div class="mo-strip"><span class="mo-label">To win</span>
    ${cell(DATA.teams[0].name, o.home, 0)}${cell("Draw", o.draw)}${cell(DATA.teams[1].name, o.away, 1)}
    <span class="mo-muted">Betfair${o.matched ? ", £" + Number(o.matched).toLocaleString("en-GB") + " matched" : ""}${when ? ", " + when : ""}</span></div>`;
}

function oddsStrip() {
  const el = document.getElementById("odds-strip");
  if (!el) return;
  el.innerHTML = matchOddsHtml();
  el.hidden = !el.innerHTML;
}

function teamWinText(t) {
  const m = fixtureMarket();
  if (!m || !m.match) return "";
  const r = t === 0 ? m.match.home : m.match.away;
  return r && r.price ? `to win ${fmtOdds(r.price)} (${Math.round(r.p * 100)}%)` : "";
}

/* The same rows playerView() reads, under the same filters, by player. */
function squadPlayers(teamIndex) {
  const records = (DATA.players || [])[teamIndex] || [];
  const allowed = new Set(filtered(activeRecords()[teamIndex]).map(m => m.id));
  const importsOk = source !== "h2h" && tier === "all";
  const byPlayer = new Map();
  for (const r of records) {
    if (!(allowed.has(r.match_id)
          || (importsOk && r.former_club && (venue === "all" || r.venue === venue)))) continue;
    if (!byPlayer.has(r.player)) byPlayer.set(r.player, []);
    byPlayer.get(r.player).push(r);
  }
  byPlayer.forEach(rows => rows.sort((a, b) => (a.date < b.date ? -1 : 1)));
  return byPlayer;
}

/* Every match on file for him, no filters: the record a bookmaker sees. */
function allPlayed(teamIndex, name) {
  return ((DATA.players || [])[teamIndex] || []).filter(r => r.player === name);
}

function currentXI(t) {
  const store = DATA.lineups || {};
  const lu = store.confirmed || store.predicted;
  if (!lu) return null;
  const side = t === 0 ? lu.home : lu.away;
  if (!side) return null;
  return { confirmed: !!store.confirmed, formation: side.formation || "",
           xi: side.xi || [], missing: (side.missing || []).map(m => m[0]) };
}

/* Real appearances only, oldest first. */
function gatedApps(played) {
  const gated = reportsMinutes(played);
  return played.filter(g => gated
    ? (g.minutes || 0) >= MIN_MINUTES
    : Object.keys(g.stats || {}).length > 0);
}

/* Rate per 90 with a missing key read as nought. */
function rate90(played, stat) {
  const apps = gatedApps(played);
  const mins = apps.reduce((s, g) => s + (g.minutes || 0), 0);
  if (mins <= 0) return null;
  return apps.reduce((s, g) => s + ((g.stats || {})[stat] || 0), 0) / mins * 90;
}

function expectedMinutesOf(played) {
  const m = gatedApps(played).map(g => g.minutes || 0).sort((a, b) => a - b);
  return m.length ? Math.min(90, m[Math.floor(m.length / 2)]) : 0;
}

/* What sort of player he is, from what he does per 90 rather than the
   G/D/M/F SofaScore gives. The point is the Mac Allister and Szoboszlai
   case: two "midfielders", one doing the covering and the fouling. */
function roleOf(played, pos) {
  if (SPORT !== "football") return "";
  if (pos === "G") return "Goalkeeper";
  const r = s => rate90(played, s) || 0;
  const def = r("Tackles") + r("Fouls") + r("Interceptions");
  const att = r("Shots") + r("Key passes") + 3 * r("xG");
  if (pos === "F") return def > att ? "Pressing forward" : "Forward";
  if (pos === "D") return att >= 0.6 * def ? "Attacking defender" : "Defender";
  if (pos === "M") {
    if (def >= 1.5 * att) return "Holding midfielder";
    if (att >= 1.3 * def) return "Attacking midfielder";
    return "Box-to-box midfielder";
  }
  return "";
}

function lastRate(played, stat, line, count) {
  const apps = gatedApps(played).slice(-(count || 10));
  const v = apps.map(g => (g.stats || {})[stat] ?? 0);
  const k = v.filter(x => x > line).length;
  return { k, n: v.length, p: v.length ? k / v.length : 0 };
}

let FOULED90_BASE = null;
/* Average fouled per 90 among regular outfield players across the whole
   report, the yardstick for "the man he is up against draws a lot". */
function fouledBase() {
  if (FOULED90_BASE !== null) return FOULED90_BASE;
  let v = 0, m = 0;
  for (const fx of ALL.fixtures) for (const side of fx.players || []) for (const r of side) {
    if (r.position === "G" || (r.minutes || 0) < MIN_MINUTES) continue;
    v += (r.stats || {}).Fouled || 0; m += r.minutes || 0;
  }
  FOULED90_BASE = m > 0 ? v / m * 90 : 1;
  return FOULED90_BASE;
}

/* Who he is likely to be up against, from the line-up shapes. */
function opponentsFor(t, name) {
  const store = DATA.lineups || {};
  const lu = store.confirmed || store.predicted;
  if (!lu || !lu.home || !lu.away) return [];
  const shapes = [luShape(lu.home), luShape(lu.away)];
  const me = shapes[t].lines.flat().find(q => q.name === name);
  if (!me) return [];
  return luOpponents(me, shapes[1 - t]);
}

/* To be booked. Fouls per 90 times this side's cards per foul, over his
   expected minutes, scaled by how many fouls the side is projected to give
   away in this match, and by how much the men he is up against get fouled.
   Poisson for at least one card. Heuristic, not backtested. */
function cardCase(t, name, played, neutral) {
  if (SPORT !== "football") return null;
  const apps = gatedApps(played);
  if (apps.length < 3) return null;
  const fouls90 = rate90(played, "Fouls");
  if (fouls90 === null) return null;
  const expMin = expectedMinutesOf(played);
  let F = 0, Y = 0;
  for (const r of filtered(DATA.records[t] || [])) {
    const s = (r.stats || {}).ALL || {};
    F += s.Fouls || 0; Y += s["Yellow cards"] || 0;
  }
  const perFoul = F >= 30 ? Y / F : CARDS_PER_FOUL_DEFAULT;
  const matchAdj = neutral ? 1 : playerAdjustment("Fouls", t);
  const opps = (neutral ? [] : opponentsFor(t, name)).map(o => {
    const rec = allPlayed(1 - t, o.name);
    return { name: o.name, fouled90: rec.length ? rate90(rec, "Fouled") : null };
  });
  const known = opps.filter(o => o.fouled90 !== null);
  let oppAdj = 1;
  if (known.length) {
    const avg = known.reduce((s, o) => s + o.fouled90, 0) / known.length;
    oppAdj = Math.min(1.2, Math.max(0.85, Math.sqrt(avg / fouledBase())));
  }
  const lam = fouls90 * (expMin / 90) * perFoul * matchAdj * oppAdj;
  return { p: 1 - Math.exp(-lam), lam, fouls90, perFoul, matchAdj, oppAdj, opps, expMin,
           n: apps.length };
}

/* To score. Expected goals and goals per 90, blended 60/40 where the feed
   carries xG, over his expected minutes, scaled by this side's projected
   goals against its usual. Heuristic, not backtested. */
function scoreCase(t, played, neutral) {
  if (SPORT !== "football") return null;
  const apps = gatedApps(played);
  if (apps.length < 3) return null;
  const goals90 = rate90(played, "Goals") || 0;
  const hasXg = apps.some(g => (g.stats || {}).xG !== undefined);
  const xg90 = hasXg ? rate90(played, "xG") || 0 : null;
  const rate = hasXg ? 0.6 * xg90 + 0.4 * goals90 : goals90;
  const expMin = expectedMinutesOf(played);
  const adj = neutral ? 1 : playerAdjustment("Goals", t);
  const lam = rate * (expMin / 90) * adj;
  return { p: 1 - Math.exp(-lam), lam, goals90, xg90, expMin, adj, n: apps.length };
}

function estBookie(p) {
  if (!(p > 0)) return null;
  return 1 / Math.min(0.96, p * (1 + BOOK_MARGIN));
}

function lineLabel(line) {
  return Number.isInteger(line + 0.5) ? `${line + 0.5}+` : `over ${line}`;
}

function rungsFor(stat, vals) {
  // Centred on his own numbers rather than one squad-wide line, so a
  // quarterback's 245 passing yards and a back's 10 rushing yards both get
  // lines worth reading: three at most, starting from the highest he clears
  // eight times in ten, stopping once he clears it under one time in five.
  const sorted = vals.slice().sort((a, b) => a - b);
  const med = sorted[Math.floor(sorted.length / 2)] || 0;
  let cands;
  if (med >= 5) {
    const step = Math.max(5, Math.round(med * 0.25 / 5) * 5);
    cands = [med - 3 * step, med - 2 * step, med - step, med, med + step]
      .map(x => Math.floor(x) + 0.5).filter(x => x > 0);
  } else {
    cands = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5];
  }
  cands = [...new Set(cands)];
  const rate = l => vals.filter(v => v > l).length / vals.length;
  let start = 0;
  cands.forEach((l, i) => { if (rate(l) >= 0.8) start = i; });
  const out = [];
  for (let i = start; i < cands.length && out.length < 3; i++) {
    if (out.length && rate(cands[i]) < 0.2) break;
    out.push(cands[i]);
  }
  return out.length ? out : [cands[0]];
}

function betfairFor(name, stat, line) {
  const pm = playerMarket(name);
  if (!pm) return null;
  if (stat === "Goals" && line === 0.5) return pm.score || null;
  if (stat === "Shots on target" && line === 0.5) return pm.sot1 || null;
  if (stat === "Shots on target" && line === 1.5) return pm.sot2 || null;
  return null;
}

function edgeHtml(p, price) {
  if (!(price > 1) || !(p > 0)) return `<span class="pp-edge">&ndash;</span>`;
  const e = p * price - 1;
  const cls = e >= 0.03 ? "pp-pos" : e <= -0.03 ? "pp-neg" : "";
  return `<span class="pp-edge ${cls}">${e >= 0 ? "+" : ""}${Math.round(e * 100)}%</span>`;
}

/* One priced line in a profile. `ours` and `book` are chances; `bf` the
   Betfair runner if listed. The edge is ours against, in order: a price you
   typed, Betfair's back price, the bookmaker estimate. */
function rungHtml(key, label, record, ours, book, bf, addIndex) {
  const est = estBookie(book);
  const typed = PRICE_IN[key];
  const parts = String(key).split("|");
  const ppp = parts.length === 4 ? ppPrice(parts[1], parts[2], parseFloat(parts[3]), true) : null;
  const b3 = parts.length === 4 ? ppPrice(parts[1], parts[2], parseFloat(parts[3]), true, "b365") : null;
  const ref = typed || b3 || ppp || (bf && bf.back) || est;
  const real = typed || b3 || ppp || (bf && bf.back);
  return `<div class="pp-rung" data-pkey="${escapeHtml(key)}" data-pp="${ours}" data-pdef="${b3 || ppp || (bf && bf.back) || est || ""}">
    ${real ? verdictHtml({ p: ours, price: real, n: 5 }) : ""}<span class="pp-line">${label}</span>
    <span class="pp-rec">${record}</span>
    <span class="pp-kv"><small>Ours</small><b>${Math.round(ours * 100)}%</b></span>
    <span class="pp-kv"><small>Fair</small><b>${fmtOdds(fairOdds(ours))}</b></span>
    ${b3 ? `<span class="pp-kv pp-ppp"><small>Bet365</small><b>${fmtOdds(b3)}</b></span>` : ""}
    ${ppp ? `<span class="pp-kv pp-ppp"><small>Paddy Power</small><b>${fmtOdds(ppp)}</b></span>` : ""}
    ${bf ? `<span class="pp-kv pp-bf" title="Betfair Exchange back price${bf.mid ? ", mid " + fmtOdds(bf.mid) : ""}"><small>Betfair</small><b>${fmtOdds(bf.back)}</b></span>` : ""}
    <span class="pp-kv" title="A rough guide to what a bookmaker pricing off his whole record would offer: the chance over every match on file, plus a ${Math.round(BOOK_MARGIN * 100)}% margin. Not a scraped price."><small>Est. bookie</small><b>${est ? "~" + fmtOdds(est) : "&ndash;"}</b></span>
    <label class="pp-kv pp-in"><small>Your price</small><input type="number" step="0.01" min="1.01" inputmode="decimal" data-spin="1" data-pprice="${escapeHtml(key)}" value="${typed || ""}" placeholder="price"></label>
    <span class="pp-kv"><small>Edge</small>${edgeHtml(ours, ref)}</span>
    ${addIndex === null ? "" : (() => {
      const entry = PLAYER_ROWS[addIndex];
      const inSlip = SLIP.some(s => s.key === rowKey(entry.row));
      return `<button type="button" class="add-btn" data-padd="${addIndex}" data-in="${inSlip ? 1 : 0}">${inSlip ? "Added" : "Add"}</button>`;
    })()}
  </div>`;
}

function seqHtml(played, stat, line) {
  const apps = gatedApps(played).slice(-10);
  if (!apps.length) return "";
  return `<div class="pp-seq" title="Last ${apps.length}, oldest first">` + apps.map(g => {
    const v = (g.stats || {})[stat] ?? 0;
    const shown = Number.isInteger(v) ? v : v.toFixed(1);
    return `<span class="${v > line ? "pp-hit" : "pp-miss"}" title="${escapeHtml(g.date || "")} v ${escapeHtml(g.opponent || "")}">${shown}</span>`;
  }).join("") + `</div>`;
}

function profileChart(played, stat, line, t) {
  const pts = gatedApps(played).slice(-10).map(g => ({
    v: (g.stats || {})[stat] ?? 0, label: oppAbbrev(g.opponent),
    tip: `${g.date || ""} ${g.venue === "home" ? "v" : "at"} ${g.opponent || ""}` }));
  if (!pts.length) return "";
  return `<div class="pp-chartwrap">${jChart(pts, line, VARS[t], stat)}</div>`;
}

function playerStatsFor(pos) {
  return (DATA.playerStats || []).filter(s =>
    s !== "Minutes" && (pos === "G" ? s !== "Shots" && s !== "Shots on target" && s !== "Goals"
                                    : s !== "Saves"));
}

/* ------------------------------------------------- strongest lines

   Every line a player has a record in, ranked by our chance, so the
   strongest ones read off the top of the page for any sport. A line is
   kept between 55% and 92%: below that it is not a strong line, and above
   it the price is too short to be worth a bet. Ours is the same pricePlayer()
   chance the profile shows, on his last ten under the filters. */
const STRONG_MIN = 0.55, STRONG_MAX = 0.92;
let pOrder = "lineup";
const BEST_CACHE = new Map();
let pStrongStat = "all";

/* Our chance first; level on that (the record-only branch tops out at the
   same number for every perfect ten), the full record breaks the tie, then
   the bigger sample. */
function strongOrder(a, b) {
  return (b.p - a.p) || (b.all - a.all) || (b.nAll - a.nAll);
}

/* Left out of "All" on the fixture list only, because a passes line clears
   so reliably it would fill the list. It has its own chip. */
const STRONG_ALL_SKIP = new Set(["Passes"]);

function playerBestLines(t, name, played) {
  const key = [DATA.fixture.id, t, name, games, venue, tier, source, period].join("|");
  if (BEST_CACHE.has(key)) return BEST_CACHE.get(key);
  const pos = played[0].position || "";
  const recent = gatedApps(played).slice(-10);
  const out = [];
  for (const stat of playerStatsFor(pos)) {
    const sApps = appearances(played, stat);
    const vals = sApps.map(a => a.value);
    if (!vals.some(v => v > 0)) continue;
    const recentApps = appearances(recent, stat);
    if (recentApps.length < 5) continue;
    const adj = playerAdjustment(stat, t);
    for (const line of rungsFor(stat, vals)) {
      const price = withModel(pricePlayer(recentApps, line, true, adj, null), name, stat, line, true);
      if (!(price.p >= STRONG_MIN && price.p <= STRONG_MAX)) continue;
      const r = lastRate(played, stat, line);
      const kAll = vals.filter(v => v > line).length;
      out.push({ t, name, stat, line, p: price.p, k: r.k, n: r.n, all: kAll / vals.length, nAll: vals.length });
    }
  }
  out.sort(strongOrder);
  BEST_CACHE.set(key, out);
  return out;
}

function strongChip(b, withName) {
  const cls = b.p >= 0.8 ? "pp-hi" : b.p >= 0.68 ? "pp-mid" : "";
  return `<span class="pp-tag ${cls}">${withName ? `<b class="pp-who">${escapeHtml(b.name)}</b> ` : ""}${
    escapeHtml(b.stat)} ${escapeHtml(lineLabel(b.line))} &middot; ${b.k}/${b.n} &middot; <b>${Math.round(b.p * 100)}%</b></span>`;
}

/* The strongest player lines in the whole fixture, both sides. Players in
   a known XI only, once there is one; everyone with five recent
   appearances otherwise. */
function strongestCandidates() {
  const rows = [];
  [0, 1].forEach(t => {
    const xi = currentXI(t);
    const names = xi && xi.xi.length ? new Set(xi.xi.map(p => p.name)) : null;
    squadPlayers(t).forEach((played, name) => {
      if (names && !names.has(name)) return;
      if (!gatedApps(played).length) return;
      rows.push(...playerBestLines(t, name, played));
    });
  });
  return rows;
}

/* The strongest player lines in the whole fixture, both sides, one per
   player. Players in a known XI only, once there is one. */
function strongestInFixture(limit, stat) {
  const all = strongestCandidates().filter(b =>
    stat === "all" ? !STRONG_ALL_SKIP.has(b.stat) : b.stat === stat);
  all.sort(strongOrder);
  const seen = new Set(), out = [];
  for (const b of all) {
    const k = b.t + "|" + b.name;
    if (seen.has(k)) continue;
    seen.add(k); out.push(b);
    if (out.length >= (limit || 15)) break;
  }
  return out;
}

function strongestHtml() {
  const cands = strongestCandidates();
  if (!cands.length) return "";
  const counts = new Map();
  cands.forEach(b => counts.set(b.stat, (counts.get(b.stat) || 0) + 1));
  const statsHere = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(e => e[0]);
  if (pStrongStat !== "all" && !counts.has(pStrongStat)) pStrongStat = "all";
  const top = strongestInFixture(15, pStrongStat);
  const chips = [["all", "All"], ...statsHere.map(s => [s, s])].map(([v, t]) =>
    `<button type="button" class="pp-schip" data-pstrong="${escapeHtml(v)}" aria-pressed="${v === pStrongStat}">${escapeHtml(t)}</button>`).join("");
  return `<div class="pp-section">Strongest player lines</div>
    <div class="pp-schips">${chips}</div>
    <div class="pp-strong">${top.map((b, i) => `<button type="button" class="pp-srow" data-pteam="${b.t}" data-pplayer="${escapeHtml(b.name)}">
      <span class="pp-rank">${i + 1}</span>
      <span class="swatch" style="background:var(${VARS[b.t]})"></span>
      <span class="pp-sname"><b>${escapeHtml(b.name)}</b><small>${escapeHtml(b.stat)} ${escapeHtml(lineLabel(b.line))}</small></span>
      <span class="pp-srec">${b.k}/${b.n}</span>
      <span class="pp-spct">${Math.round(b.p * 100)}%</span>
      <span class="pp-sbar"><i style="width:${Math.round(b.p * 100)}%"></i></span>
    </button>`).join("")}</div>`;
}

/* ------------------------------------------------- Paddy Power

   Real Paddy Power prices, when paddypower_prices.py has fetched the game
   (reports/paddypower.json, merged into markets.json). Each Paddy Power line
   is read as a stat, a line and a side, so our chance can be worked out at
   exactly Paddy Power's line, over or under, and set against its price.
   NFL market names are mapped; others are shown once their names are known. */

const PP_STAT = {
  "Receiving Yds": "Receiving yards", "Alt Receiving Yds": "Receiving yards",
  "Rushing Yds": "Rushing yards", "Alt Rushing Yds": "Rushing yards",
  "Passing Yds": "Passing yards", "Alt Passing Yds": "Passing yards",
  "Total Receptions": "Receiving receptions", "Alt Receptions": "Receiving receptions",
  "Rushing + Receiving Yds": "Rushing and receiving yards",
  "Alt Rushing + Receiving Yds": "Rushing and receiving yards",
  "Passing + Rushing Yds": "Passing and rushing yards",
  "Alt Passing + Rushing Yds": "Passing and rushing yards",
  "Passing TDs": "Passing touchdowns", "Alt Passing TDs": "Passing touchdowns",
  "Any Time Touchdown Scorer": "Anytime touchdown",
  // Football: the event page carries the scorer market by default.
  "Player To Score": "Goals", "Anytime Goalscorer": "Goals",
  // Basketball: paddypower_prices.py names them; side and line are set.
  "Points": "Points", "Rebounds": "Rebounds", "Assists": "Assists",
  "Made Threes": "Three pointers made", "Blocks": "Blocks", "Steals": "Steals",
  "Pts + Reb + Ast": "Points rebounds and assists", "Pts + Reb": "Points and rebounds",
  "Pts + Ast": "Points and assists", "Reb + Ast": "Rebounds and assists",
};

/* Football: one market per line, every player a runner. Mirrors pplog.py. */
const PP_PATTERNS = [
  [/^Player To Have (\\d+) Or More Shots$/, "Shots"],
  [/^Player To Commit (\\d+) Or More Fouls$/, "Fouls"],
  [/^Player To Be Fouled (\\d+) Or More Times$/, "Fouled"],
  [/^Player To Have (\\d+) Or More Shots On Target$/, "Shots on target"],
  [/^Player To Make (\\d+) Or More Tackles$/, "Tackles"],
  [/^Player To Have (\\d+) Or More Assists$/, "Assists"],
];
const PP_YES = { "Player Shown a Card": "Card", "Player Assists": "Assists" };
/* The bookmakers the pages carry prices for, by their key in markets.json. */
const BOOKS = { pp: "Paddy Power", b365: "Bet365" };

/* Take, acceptable or avoid, for one priced line.
   Take: more likely than not by our numbers, the price beats our chance by
   5% or more, and the record behind it is five games or more.
   Acceptable: more likely than not and about fair (within 5% either way),
   or value we cannot fully vouch for: a thin record or the card estimate.
   Long shot: under 50% by our numbers. However big the edge looks, it rests
   on one or two games in ten, so it is never called take or acceptable.
   Avoid: the price is more than 5% worse than our chance. */
function verdictOf(v) {
  if (!(v.price > 1) || !(v.p > 0)) return null;
  const e = v.p * v.price - 1;
  if (e < -0.05) return "avoid";
  // The card estimate is never "take": it is uncalibrated, and on 20 Oct
  // 2026 it showed edges of +80% to +150% on players at 9.0 to 12.0, which
  // is the estimate being wrong, not value. Under 50%, like any bet under
  // 50%, it is a long shot; acceptable only above that and 5% clear.
  if (v.heuristic) return v.p >= 0.5 && e >= 0.05 ? "ok" : "long";
  if (v.p < 0.5) return "long";
  // Nothing adjusted it for the opponent (no projection, no match odds, no
  // model): it can be acceptable, never take.
  // Two guards before anything is called take, found on NBA opening night
  // (21 Oct 2026), when the model called 116 of 561 Paddy Power lines take:
  //   * stale data: no competitive game in two months means every record is
  //     last season's (for the NBA, mostly playoffs, heavier minutes for the
  //     starters), so the whole board leans one way and that is not value;
  //   * on basketball, an edge over 30% on a player line is our number being
  //     off, as on the football team lines.
  // Both can still be acceptable. Lift the second once pplog has settled a
  // few weeks of NBA lines and says how far off the model runs.
  // staleDays is set on every fixture; stale means past the 60-day line the
  // page's own warning uses (fixed 21 Oct 2026: it blocked every take).
  const stale = DATA && DATA.fixture && (DATA.fixture.staleDays || 0) > 60;
  // NBA and NFL: the backtested model is about as sharp as Paddy Power on
  // real lines (checked 21 Oct 2026), so a gap that wide is more likely ours.
  const tooBig = (SPORT === "basketball" || SPORT === "american-football") && e > 0.3;
  // Team lines: take only when the team model priced the line in a market
  // that passed teamline_backtest.py, from that market's threshold to the 30%
  // cap (teamlines.verdict() is the same rule for teamlog.py).
  if (v.team) return v.tested && e >= v.threshold && e <= 0.3 && (v.n || 0) >= 5 && !stale ? "take" : "ok";
  if (e >= 0.05 && (v.n || 0) >= 5 && !v.unadjusted && !stale && !tooBig) return "take";
  return "ok";
}

function verdictHtml(v) {
  const k = verdictOf(v);
  if (!k) return "";
  const text = { take: "Take", ok: "Acceptable", long: "Long shot", avoid: "Avoid" }[k];
  const why = {
    take: "More likely than not, and the price beats our chance by 5% or more, on a record of five games or more",
    ok: "More likely than not and close to a fair price, or value resting on a thin record or an estimate",
    long: "Under 50% by our numbers: a big edge here is noise, not value",
    avoid: "The price is more than 5% worse than our chance",
  }[k];
  return `<span class="vd vd-${k}" title="${why}">${text}</span>`;
}


/* One player's Paddy Power lines as {stat, line, over, price, label}. */
function ppLines(name, src = "pp") {
  const m = fixtureMarket();
  const rows = m && m[src] && m[src].players ? m[src].players[normName(name)] : null;
  if (!rows) return [];
  const out = [];
  for (const r of rows) {
    const pat = PP_PATTERNS.find(([rx]) => rx.test(r.m));
    if (pat) {
      const n = parseInt(r.m.match(pat[0])[1], 10);
      out.push({ stat: pat[1], line: n - 0.5, over: true, price: r.p, label: `${n}+`, market: r.m });
      continue;
    }
    if (PP_YES[r.m]) {
      const st = PP_YES[r.m];
      out.push({ stat: st, line: 0.5, over: true, price: r.p,
                 label: st === "Card" ? "to be booked" : "1+", market: r.m });
      continue;
    }
    const stat = PP_STAT[r.m];
    if (!stat) continue;
    if (stat === "Anytime touchdown" || stat === "Goals") {
      out.push({ stat, line: 0.5, over: true, price: r.p,
                 label: stat === "Goals" ? "to score" : "Anytime TD", market: r.m });
      continue;
    }
    if (r.o === "OVER" || r.o === "UNDER") {
      if (r.l == null) continue;
      out.push({ stat, line: r.l, over: r.o === "OVER", price: r.p,
                 label: `${r.o === "OVER" ? "Over" : "Under"} ${r.l}`, market: r.m });
      continue;
    }
    const n = parseFloat(String(r.s).replace(/[^0-9.].*$/, ""));
    if (!(n > 0)) continue;
    out.push({ stat, line: n - 0.5, over: true, price: r.p, label: `${n}+`, market: r.m });
  }
  return out.map(o => Object.assign(o, { src }));
}

function ppPrice(name, stat, line, over, src = "pp") {
  const hit = ppLines(name, src).find(x => x.stat === stat && x.line === line && x.over === (over !== false));
  return hit ? hit.price : null;
}

/* Our chance at a Paddy Power line: the same pricePlayer() as everywhere,
   on his last ten under the filters, matchup-adjusted. */
function ppValued(t, name, played, src = "pp") {
  const lines = ppLines(name, src);
  if (!lines.length) return [];
  const recent = gatedApps(played).slice(-10);
  const adj = {};
  const out = [];
  for (const x of lines) {
    if (x.stat === "Card") {
      // To be booked: the profile's fouls-based cardCase, half last ten and
      // half everything. Heuristic: shown, never counted as value.
      const r = cardCase(t, name, recent), f = cardCase(t, name, played);
      if (!r || !f) continue;
      const p = cardModelP(name) ?? 1 - Math.exp(-(r.lam + f.lam) / 2);
      out.push(Object.assign({}, x, { t, name, p, edge: p * x.price - 1, k: 0, n: r.n,
        k5: null, n5: null, priced: { p, fair: fairOdds(p), need: fairOdds(p) }, heuristic: true }));
      continue;
    }
    const apps = appearances(recent, x.stat);
    if (apps.length < 4) continue;
    const a = adj[x.stat] ?? (adj[x.stat] = playerAdjustment(x.stat, t));
    // Always priced as the over and turned round for an under, so the two
    // sides of one line add up to 100%. Pricing the under directly runs it
    // through the record calibration a second time, and both sides of
    // McCaffrey's 59.5 came out at 46%.
    let overPrice = withModel(pricePlayer(apps, x.line, true, a, null), name, x.stat, x.line, true);
    overPrice = crossLeagueModel(overPrice, x.stat, x.line, t);
    // Football to-score: the xG-based scoreCase, half last ten and half
    // everything, as on the profile. A goals record alone is too noisy.
    if (x.stat === "Goals" && SPORT === "football" && overPrice.source !== "fmodel") {
      const sc = (() => {
        const r = scoreCase(t, recent), f = scoreCase(t, played);
        if (!r || !f) return null;
        return 1 - Math.exp(-(r.lam + f.lam) / 2);
      })();
      if (sc === null) continue;
      overPrice = Object.assign({}, overPrice, { p: sc, fair: fairOdds(sc) });
    }
    const price = x.over ? overPrice : Object.assign({}, overPrice,
      { p: 1 - overPrice.p, fair: fairOdds(1 - overPrice.p) });
    const vals = apps.map(q => q.value);
    const k = vals.filter(v => x.over ? v > x.line : v <= x.line).length;
    const last5 = gatedApps(played).slice(-5).map(g => (g.stats || {})[x.stat] ?? 0);
    const k5 = last5.filter(v => x.over ? v > x.line : v <= x.line).length;
    const basis = opponentBasis(x.stat, t);
    out.push(Object.assign({}, x, { t, name, p: price.p, edge: price.p * x.price - 1,
      k, n: vals.length, k5, n5: last5.length, priced: price,
      unadjusted: price.source !== "fmodel" && !basis,
      oddsAdj: price.source !== "fmodel" && basis === "odds" }));
  }
  // One ladder per stat. The model scores 15 lines and the site prices the
  // rest, and the two used to disagree on the same player: Zini's 3+ shots
  // came out at 28% from the model and his 4+ at 42% from the site. Above
  // the model's top line each line now keeps the site's step down from the
  // line below it, applied to the model's chance; and no line is ever priced
  // above the line below it.
  const byStat = {};
  out.forEach(v => {
    if (v.over && v.priced && !v.heuristic) (byStat[v.stat] = byStat[v.stat] || []).push(v);
  });
  Object.values(byStat).forEach(list => {
    list.sort((a, b) => a.line - b.line);
    const seen = new Map();
    list.forEach(v => { if (!seen.has(v.line) || v.priced.source === "fmodel") seen.set(v.line, v); });
    const rungs = [...seen.values()];
    let anchor = null;
    for (const v of rungs) {
      if (v.priced.source === "fmodel") { anchor = v; continue; }
      if (!anchor) continue;
      const siteA = anchor.priced.siteP ?? anchor.p;
      const siteV = v.priced.siteP ?? v.p;
      const p = siteA > 0 ? Math.min(anchor.p, anchor.p * Math.min(1, siteV / siteA)) : anchor.p;
      list.filter(w => w.line === v.line && w.priced.source !== "fmodel").forEach(w => {
        w.p = p; w.edge = p * w.price - 1; w.unadjusted = false;
        w.priced = Object.assign({}, w.priced, { p, fair: fairOdds(p), need: fairOdds(p),
          source: "fmodel-tail", siteP: siteV });
      });
      anchor = Object.assign({}, v, { p, priced: { source: "fmodel-tail", siteP: siteV } });
    }
    // Monotone from the top down: a lower line never sits under a higher one.
    let floor = 0;
    [...rungs].reverse().forEach(v => {
      const same = list.filter(w => w.line === v.line);
      const p = Math.max(floor, ...same.map(w => w.p));
      same.forEach(w => {
        if (w.p < p) {
          w.p = p; w.edge = p * w.price - 1;
          w.priced = Object.assign({}, w.priced, { p, fair: fairOdds(p), need: fairOdds(p) });
        }
      });
      floor = p;
    });
  });
  // Lines we think are more likely than not first, best edge first; long
  // shots after. An edge on a 2-in-10 record is noise, not value.
  out.sort((a, b) => ((b.p >= 0.5) - (a.p >= 0.5)) || (b.edge - a.edge));
  return out;
}

/* Team news for every sport (team_news.py): the confirmed line-up, ESPN's
   injury report (NBA, NFL) and SofaScore's missing players. */
function injuryOf(t, name) {
  const side = (DATA.injuries || {})[t === 0 ? "home" : "away"] || [];
  const hit = side.find(r => normName(r[0]) === normName(name));
  return hit ? hit[2] : null;
}
const INJ_OUT = /^(Out|Injured Reserve|Suspen|Doubtful|Inactive|Not in squad|Bench)/;

/* Who is out, above the Value tab: only men with a recent record, so it
   reads as news rather than the whole treatment room. */
function teamNewsHtml() {
  const inj = DATA.injuries;
  if (!inj || SPORT === "darts") return "";
  const sides = [0, 1].map(t => {
    const recent = squadPlayers(t);
    const rows = (inj[t === 0 ? "home" : "away"] || []).filter(r => INJ_OUT.test(r[2] || "")
      && recent.has(r[0]) && gatedApps(recent.get(r[0])).length >= 3);
    return rows.length ? `<span class="lu-dot lu-dot${t}"></span> <b>${escapeHtml(DATA.teams[t].name)}</b> without `
      + rows.map(r => `${escapeHtml(r[0])} <small>(${escapeHtml(r[2])})</small>`).join(", ") : "";
  }).filter(Boolean);
  const src = [inj.source, inj.fetched].filter(Boolean).join(", ");
  const how = SPORT === "football"
    ? "They are left off below, and the model prices the XI without them."
    : "They are left off below, and the model prices their team-mates with them missing.";
  // data-tuck: it is the news itself, so tuckProse() never folds it away
  return `<p class="note gs-missing" data-tuck="1"><b>Team news</b>${src ? ` (${escapeHtml(src)})` : ""}: `
    + (sides.length ? sides.join(" &nbsp; ") + ". " + how : "nobody with a recent record is out.") + `</p>`;
}

/* Under a value row: whether the chance is the model's, whether it rests on
   a predicted XI, and a warning when the edge is too big to take on trust. */
function modelNote(v) {
  if (!v.priced || (v.priced.source !== "fmodel" && v.priced.source !== "fmodel-tail")) {
    if (v.unadjusted) return " &middot; <b>no opponent adjustment</b>";
    return v.oddsAdj ? " &middot; opponent from the match odds" : "";
  }
  const ev = modelEvent();
  const bits = [v.priced.source === "fmodel-tail" ? "model, extended" : "model"];
  if (typeof v.priced.modelMu === "number") bits[0] = `model expects ${fmtN(v.priced.modelMu)}`;
  if (ev && !ev.confirmed) bits.push(SPORT === "football" ? "predicted XI" : "before the line-up");
  if (ev && ev.confirmed && SPORT !== "football") bits.push("confirmed line-up");
  if (v.edge > 0.4) bits.push("<b>big edge: check team news</b>");
  return " &middot; " + bits.join(" &middot; ");
}

function ppRowHtml(v, withName) {
  const long = v.p < 0.5;
  const cls = long ? "pp-long" : v.edge >= 0.05 ? "pp-pos" : v.edge <= -0.05 ? "pp-neg" : "";
  const inj = injuryOf(v.t, v.name);
  if (v.stat === "Card") {
    return `<div class="pp-rung">
    ${verdictHtml(v)}<span class="pp-line">${withName ? `<b>${escapeHtml(v.name)}</b><br>` : ""}To be booked</span>
    <span class="pp-rec">fouls-based estimate, not yet calibrated</span>
    <span class="pp-kv"><small>Ours</small><b>${Math.round(v.p * 100)}%</b></span>
    <span class="pp-kv"><small>Fair</small><b>${fmtOdds(fairOdds(v.p))}</b></span>
    <span class="pp-kv pp-ppp"><small>${BOOKS[v.src || "pp"]}</small><b>${fmtOdds(v.price)}</b></span>
    <span class="pp-kv"><small>Edge</small><span class="pp-edge pp-long">${v.edge >= 0 ? "+" : ""}${Math.round(v.edge * 100)}%</span></span>
  </div>`;
  }
  const row = playerRow({ name: v.name, hits: v.k, vals: Array(v.n).fill(0) }, v.stat, v.line, v.t, v.priced);
  row.over = v.over;
  const idx = PLAYER_ROWS.push({ row, price: v.priced }) - 1;
  const inSlip = SLIP.some(s => s.key === rowKey(row));
  return `<div class="pp-rung">
    ${verdictHtml(v)}<span class="pp-line">${withName ? `<b>${escapeHtml(v.name)}</b>${inj ? ` <span class="lu-badge pp-out">${escapeHtml(inj)}</span>` : ""}<br>` : ""}${escapeHtml(v.stat)} ${escapeHtml(v.label)}</span>
    <span class="pp-rec">${v.k5 === null ? "fouls-based estimate" : `${v.k5}/${v.n5} last 5 &middot; ${v.k}/${v.n} last ${v.n}`}${modelNote(v)}</span>
    <span class="pp-kv"><small>Ours</small><b>${Math.round(v.p * 100)}%</b></span>
    <span class="pp-kv"><small>Fair</small><b>${fmtOdds(fairOdds(v.p))}</b></span>
    <span class="pp-kv pp-ppp"><small>${BOOKS[v.src || "pp"]}</small><b>${fmtOdds(v.price)}</b></span>
    <span class="pp-kv"><small>${long ? "Long shot" : "Edge"}</small><span class="pp-edge ${cls}">${v.edge >= 0 ? "+" : ""}${Math.round(v.edge * 100)}%</span></span>
    <button type="button" class="add-btn" data-padd="${idx}" data-in="${inSlip ? 1 : 0}">${inSlip ? "Added" : "Add"}</button>
  </div>`;
}

function ppCardHtml(t, name, played, src = "pp") {
  const vals = ppValued(t, name, played, src);
  if (!vals.length) return "";
  const m = fixtureMarket();
  const book = BOOKS[src];
  const when = m && m[src] && m[src].at ? new Date(m[src].at * 1000).toLocaleString("en-GB",
    { weekday: "short", hour: "2-digit", minute: "2-digit" }) : "";
  const n = { take: 0, ok: 0, long: 0, avoid: 0 };
  vals.forEach(v => { const k = verdictOf(v); if (k) n[k]++; });
  const sum = `${n.take} to take &middot; ${n.ok} acceptable &middot; ${n.long} long shots &middot; ${n.avoid} to avoid`;
  return `<div class="pp-section">${book} lines${when ? " &middot; prices from " + when : ""} &middot; ${sum}</div>
    <div class="pp-stat pp-ppcard">${vals.map(v => ppRowHtml(v)).join("")}
    <p class="note">Every ${book} line for him, best value first, each marked take, acceptable, long shot or avoid. Ours is worked out at ${book}'s own line. Prices move: check before betting.</p></div>`;
}

/* No more than VALUE_PER_PLAYER lines per player in a value list, his
   biggest edges kept (value_cap.py MAX_PER_PLAYER). Lines on one player land
   together: eight on one man are one bet on one night, not eight. `seen`
   carries the count across lists that are read as one, take then acceptable. */
const VALUE_PER_PLAYER = 1;
function capPerPlayer(list, seen = new Map()) {
  return list.filter(v => {
    const k = v.t + "|" + v.name;
    const n = seen.get(k) || 0;
    if (n >= VALUE_PER_PLAYER) return false;
    seen.set(k, n + 1);
    return true;
  });
}

/* Best value across the whole game, for the Players front page. */
function ppBestHtml(src = "pp") {
  const m = fixtureMarket();
  if (!m || !m[src]) return "";
  const rows = [];
  const best = new Map();
  [0, 1].forEach(t => squadPlayers(t).forEach((played, name) => {
    if (!gatedApps(played).length) return;
    if (INJ_OUT.test(injuryOf(t, name) || "")) return;
    ppValued(t, name, played, src).forEach(v => {
      if (!(v.p >= 0.5 && v.edge > 0 && v.n >= 5)) return;
      // Football to-score is logged but not called value until the results
      // say how far off it runs (pplog.py UNCALIBRATED), unless the
      // backtested model priced it, which is calibrated.
      if (SPORT === "football" && v.stat === "Card") return;
      if (SPORT === "football" && v.stat === "Goals" && (v.priced || {}).source !== "fmodel") return;
      // "Over 2.5" and "3+" are the same bet: keep the better price.
      const k = [t, name, v.stat, v.line, v.over].join("|");
      if (!best.has(k) || best.get(k).price < v.price) best.set(k, v);
    });
  }));
  rows.push(...best.values());
  if (!rows.length) return "";
  rows.sort((a, b) => b.edge - a.edge);
  return `<div class="pp-section">Best value at ${BOOKS[src]}</div>
    <div class="pp-stat pp-ppcard">${capPerPlayer(rows).slice(0, 12).map(v => ppRowHtml(v, true)).join("")}
    <p class="note">Lines where our chance (50% or more) beats ${BOOKS[src]}'s price, biggest edge first, one per player. Players ruled out are left off; anyone questionable is marked, so check the inactives. Ours leans on the last ten games and is not proven on player bets: treat a big edge as a reason to look closer, not a certainty.</p></div>`;
}

/* ------------------------------------------------- Team lines

   Paddy Power's team markets on the same reply as the player ones (no extra
   request): each side's corners, cards, fouls and shots on target, and the
   match corners and cards. Priced with the same count model as the team
   bets (probOver, then calibrate), from the last ten games under the filters.

   The expectation, in order of trust:
     1. the fixture's opponent-adjusted projection, when it has one;
     2. in a cross-league game, the side's own average scaled by the match
        odds (corners to the power 0.5, shots 0.7, shots on target 0.8, as for
        the players). Fouls and cards are not scaled: they follow the referee
        and the league more than the opponent;
     3. otherwise the side's own average, marked unadjusted, so it can be
        acceptable but never take.
   Match totals add the two sides' expectations, with the spread read from
   the per-match totals in both records. */
// Corners follow territory: the underdog's fall further than its shots do,
// so they take the full ratio. First try (0.5) called Villarreal over 4.5
// corners at Anfield a +52% take against Paddy Power's 2.75 (20 Oct 2026).
// 1 then went too far the other way: Bodo/Glimt expected 2.0 corners in
// Naples against a record of 4 unders in 10. 0.7, as for shots.
const TEAM_ODDS_POWER = { "Corner kicks": 0.7, "Total shots": 0.7, "Shots on target": 0.8 };
const TEAM_STAT_LABEL = { "Corner kicks": "corners", "Yellow cards": "cards", "Fouls": "fouls",
                          "Shots on target": "shots on target", "Total shots": "shots" };

function ppTeamOrder() {
  // Paddy Power's home and away against the page's teams, by name.
  const m = fixtureMarket();
  const pp = m && m.pp;
  if (!pp || !pp.home) return [0, 1];
  const words = s => new Set(normName(s).split(" ").filter(w => w.length >= 3
    && !["the", "club", "real", "sporting", "city", "united"].includes(w)));
  const overlap = (a, b) => { const A = words(a); let n = 0; words(b).forEach(w => { if (A.has(w)) n++; }); return n; };
  const t0 = DATA.teams[0].name, t1 = DATA.teams[1].name;
  const straight = overlap(pp.home, t0) + overlap(pp.away, t1);
  const crossed = overlap(pp.home, t1) + overlap(pp.away, t0);
  return crossed > straight ? [1, 0] : [0, 1];
}

function teamExpected(stat, t) {
  const proj = ((DATA.projection || {}).ALL || {})[stat];
  if (proj && proj[t] !== undefined && proj[t] > 0) return { e: proj[t], basis: "projection" };
  const vals = filtered(DATA.records[t]).slice(-10).map(r => ((r.stats || {}).ALL || {})[stat])
    .filter(v => v !== undefined && v !== null);
  if (vals.length < 3) return null;
  const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
  const power = TEAM_ODDS_POWER[stat];
  if (isCrossLeague(DATA) && power && SPORT === "football") {
    const lam = goalLambdas(DATA);
    const goals = filtered(DATA.records[t]).map(r => ((r.stats || {}).ALL || {})["Goals"])
      .filter(v => v !== undefined && v !== null);
    const g = goals.length ? goals.reduce((a, b) => a + b, 0) / goals.length : 0;
    if (lam && goals.length >= 5 && g > 0.2) {
      const adj = Math.min(2.5, Math.max(0.2, Math.pow(lam[t] / g, power)));
      return { e: mean * adj, basis: "odds", adj };
    }
  }
  return { e: mean, basis: "record" };
}

function teamValued() {
  const m = fixtureMarket();
  const lines = (m && m.pp && m.pp.team) || [];
  if (!lines.length || SPORT !== "football") return [];
  const order = ppTeamOrder();
  const out = [];
  lines.forEach(l => {
    let vals, exp, name, unadjusted = false, basis;
    if (l.scope === "match") {
      const a = teamExpected(l.stat, 0), b = teamExpected(l.stat, 1);
      if (!a || !b) return;
      exp = a.e + b.e;
      basis = a.basis === b.basis ? a.basis : "record";
      unadjusted = a.basis === "record" || b.basis === "record";
      vals = [0, 1].flatMap(t => filtered(DATA.records[t]).slice(-10).map(r => {
        const f = ((r.stats || {}).ALL || {})[l.stat], g = (((r.against || {}).ALL) || {})[l.stat];
        return f === undefined || f === null || g === undefined || g === null ? null : f + g;
      })).filter(v => v !== null);
      name = "Match";
    } else {
      const t = order[l.scope === "home" ? 0 : 1];
      const x = teamExpected(l.stat, t);
      if (!x) return;
      exp = x.e; basis = x.basis; unadjusted = x.basis === "record";
      vals = filtered(DATA.records[t]).slice(-10).map(r => ((r.stats || {}).ALL || {})[l.stat])
        .filter(v => v !== undefined && v !== null);
      name = DATA.teams[t].name;
      l = Object.assign({}, l, { t });
    }
    if (vals.length < 5 || !(exp > 0)) return;
    let p = probOver(l.line, exp, vals);
    if (!l.over) p = 1 - p;
    p = calibrate(p);
    // A market that passed teamline_backtest.py (TEAM-LINES.md) is priced by
    // the team model, the number that was tested, and only those can be take.
    const tested = teamModelChance(l);
    if (tested) { p = tested.p; exp = tested.mu; basis = "model"; }
    const hits = vals.filter(v => l.over ? v > l.line : v < l.line).length;
    // An edge over 30% on a main line is far more likely our number being
    // off than Paddy Power's, so it can be acceptable but never take.
    const edge = p * l.price - 1;
    // The record has to agree before it is a take: at least half the last
    // games landed, and the expectation within half and double the side's
    // own average (the same sanity check priceRow() makes on team bets).
    const own = vals.reduce((a, b) => a + b, 0) / vals.length;
    const disagree = hits / vals.length < 0.5
      || (l.scope !== "match" && (exp < 0.5 * own || exp > 2 * own));
    out.push({
      team: true, t: l.t, name, stat: l.stat, line: l.line, over: l.over, price: l.price,
      src: "pp", p, edge, k: hits, n: vals.length, expected: exp, basis,
      // On 21 Oct 2026, 26 of the 30 takes on the European pages were team
      // corners from the cross-league odds scaling, never tested against
      // results. Since the backtest (22 Oct 2026) a team line is take only
      // when the team model prices it in a market that passed, from that
      // market's threshold (verdictOf); everything else is acceptable at most.
      tested: !!tested, threshold: tested ? tested.threshold : null,
      unadjusted: !tested, suspect: edge > 0.3, disagree,
      label: `${TEAM_STAT_LABEL[l.stat] || l.stat} ${l.over ? "over" : "under"} ${l.line}`,
    });
  });
  // "Over 5.5" and "6 or more" can both appear: keep the better price.
  const best = new Map();
  out.forEach(v => {
    const k = [v.name, v.stat, v.line, v.over].join("|");
    if (!best.has(k) || best.get(k).price < v.price) best.set(k, v);
  });
  return [...best.values()];
}

/* The team model's chance for a Paddy Power team line, when its market
   passed teamline_backtest.py. report.py attaches each side's expected count
   and spread (DATA.teamModel, from context.team_model_mu) and the passed
   markets (ALL.teamLineGate) at build time; a match total adds the two sides
   and takes the spread the backtest fitted on match totals. */
function teamModelChance(l) {
  const gate = ((ALL.teamLineGate || {}).markets || {})[`${l.stat}|${l.scope === "match" ? "match" : "side"}`];
  const sides = (DATA.teamModel || {})[l.stat];
  if (!gate || !sides) return null;
  let mu, alpha;
  if (l.scope === "match") {
    if (!sides[0] || !sides[1] || !(gate.alpha_match >= 0)) return null;
    mu = sides[0].mu + sides[1].mu; alpha = gate.alpha_match;
  } else {
    const x = sides[l.t];
    if (!x) return null;
    mu = x.mu; alpha = x.alpha;
  }
  if (!(mu > 0)) return null;
  const k = Math.floor(l.line);
  const under = alpha < 1e-6 ? poissonCdf(k, mu) : negBinCdf(k, mu, 1 / alpha);
  return { p: l.over ? 1 - under : under, mu, threshold: gate.threshold };
}

function teamRowHtml(v) {
  const long = v.p < 0.5;
  const cls = long ? "pp-long" : v.edge >= 0.05 ? "pp-pos" : v.edge <= -0.05 ? "pp-neg" : "";
  const basis = { projection: "opponent-adjusted projection", odds: "opponent from the match odds",
                  record: "own record, no opponent adjustment",
                  model: "team model, backtested" }[v.basis];
  return `<div class="pp-rung">
    ${verdictHtml(v)}<span class="pp-line"><b>${escapeHtml(v.name)}</b><br>${escapeHtml(v.label)}</span>
    <span class="pp-rec">${v.k}/${v.n} last ${v.n} &middot; expect ${v.expected.toFixed(1)} &middot; ${basis}${v.suspect ? " &middot; edge too big to trust" : v.disagree ? " &middot; record disagrees" : ""}</span>
    <span class="pp-kv"><small>Ours</small><b>${Math.round(v.p * 100)}%</b></span>
    <span class="pp-kv"><small>Fair</small><b>${fmtOdds(fairOdds(v.p))}</b></span>
    <span class="pp-kv pp-ppp"><small>${BOOKS[v.src]}</small><b>${fmtOdds(v.price)}</b></span>
    <span class="pp-kv"><small>${long ? "Long shot" : "Edge"}</small><span class="pp-edge ${cls}">${v.edge >= 0 ? "+" : ""}${Math.round(v.edge * 100)}%</span></span>
  </div>`;
}

function teamValueHtml() {
  const vals = teamValued();
  if (!vals.length) return "";
  const g = { take: [], ok: [], long: [], avoid: [] };
  vals.forEach(v => { const k = verdictOf(v); if (k) g[k].push(v); });
  g.take.sort((a, b) => b.edge - a.edge);
  g.ok.sort((a, b) => b.edge - a.edge);
  const rows = g.take.concat(g.ok);
  return `<div class="pp-section">Team lines${g.take.length ? ` &middot; ${g.take.length} to take` : ""} (${rows.length})</div>
    <div class="pp-stat pp-ppcard">${rows.length ? rows.slice(0, 30).map(teamRowHtml).join("")
      : `<p class="note">Nothing worth taking or acceptable in the team markets.</p>`}
    <p class="note">Paddy Power's corners, cards, fouls and shots-on-target lines for each side and the match, priced off the last ten games. Left off: ${g.long.length} long shot${g.long.length === 1 ? "" : "s"} and ${g.avoid.length} priced worse than our chance. ${teamGateNote()} Cards and fouls follow the referee as much as the teams: treat those as the weaker calls.</p></div>`;
}

function teamGateNote() {
  const g = ALL.teamLineGate || {};
  const passed = Object.keys(g.markets || {}).map(k => {
    const [stat, scope] = k.split("|");
    return `${TEAM_STAT_LABEL[stat] || stat} (${scope === "match" ? "match total" : "one side"}) from a ${Math.round(g.markets[k].threshold * 100)}% edge`;
  });
  if (!passed.length) return "No team market has passed the backtest, so none is called take: acceptable at most.";
  const short = g.shortfall > 0 ? ` A take's chance runs high (the backtest's takes landed ${Math.round(g.shortfall * 100)} points below it), so read its edge as smaller than shown.` : "";
  return `Only markets that passed the backtest can be take, priced by the team model: ${passed.join(", ")}. Every other team line is acceptable at most.${short}`;
}

/* ------------------------------------------------- Value tab

   Every bookmaker line on the game (Bet365 and Paddy Power), priced by us
   with the same ppValued() the profiles use and sorted into take,
   acceptable and avoid. Where both books price the same line, the better
   price is the one shown. */
function valueView() {
  const el = document.getElementById("valuetab");
  if (!el) return;
  if (!hasPlayers()) {
    el.innerHTML = `<p class="note">No player markets for this game.</p>`;
    return;
  }
  const m = fixtureMarket();
  const srcs = Object.keys(BOOKS).filter(s => m && m[s]);
  if (!srcs.length) {
    el.innerHTML = `<p class="note">No Bet365 or Paddy Power prices for this game yet. They show here once a publish has fetched them.</p>`;
    return;
  }
  PLAYER_ROWS = [];
  const best = new Map();
  [0, 1].forEach(t => squadPlayers(t).forEach((played, name) => {
    if (!gatedApps(played).length) return;
    if (INJ_OUT.test(injuryOf(t, name) || "")) return;
    srcs.forEach(src => ppValued(t, name, played, src).forEach(v => {
      const k = [t, name, v.stat, v.line, v.over].join("|");
      if (!best.has(k) || best.get(k).price < v.price) best.set(k, v);
    }));
  }));
  const groups = { take: [], ok: [], long: [], avoid: [] };
  best.forEach(v => { const k = verdictOf(v); if (k) groups[k].push(v); });
  groups.take.sort((a, b) => b.edge - a.edge);
  groups.ok.sort((a, b) => b.edge - a.edge);
  const capSeen = new Map();
  const beforeCap = groups.take.length + groups.ok.length;
  groups.take = capPerPlayer(groups.take, capSeen);
  groups.ok = capPerPlayer(groups.ok, capSeen);
  const capped = beforeCap - groups.take.length - groups.ok.length;
  const when = srcs.map(s => m[s].at
    ? `${BOOKS[s]} ${new Date(m[s].at * 1000).toLocaleString("en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit" })}`
    : BOOKS[s]).join(" &middot; ");
  const block = (title, list, note) => list.length
    ? `<div class="pp-section">${title} (${list.length})</div>
       <div class="pp-stat pp-ppcard">${list.slice(0, 40).map(v => ppRowHtml(v, true)).join("")}
       <p class="note">${note}</p></div>`
    : "";
  const basis = opponentBasis("Shots", 0);
  const oppNote = basis === "odds"
    ? (SPORT === "basketball" ? " The ratings cannot rate this pair yet, so the opponent comes from Paddy Power's team points totals."
       : " These two sides play in different leagues, so the opponent's strength comes from Betfair's match odds.")
    : !basis ? " <b>No opponent adjustment for this game</b> (no projection and no match odds), so nothing is called take unless the backtested model priced it." : "";
  el.innerHTML = `<p class="note">Prices from ${when}. Each line is our chance against the better of the two prices.${oppNote} Prices move: check before betting.</p>`
    + teamNewsHtml()
    + teamValueHtml()
    + (block("Take", groups.take, "More likely than not, and the price beats our chance by 5% or more, on a record of five games or more. Biggest edge first, one line per player across Take and Acceptable.")
       || `<div class="pp-section">Take</div><p class="note">Nothing to take on this game at the current prices.</p>`)
    + block("Acceptable", groups.ok, "More likely than not and close to a fair price, or value we cannot fully vouch for: a thin record or the card estimate. Fine as part of a slip, not on its own.")
    + `<p class="note">Left off: ${groups.long.length} long shot${groups.long.length === 1 ? "" : "s"} (under 50% by our numbers), ${groups.avoid.length} line${groups.avoid.length === 1 ? "" : "s"} priced worse than our chance${capped ? ` and ${capped} more line${capped === 1 ? "" : "s"} on players already listed` : ""}. Every line is still on each player's profile.</p>`;
}

function squadHome() {
  const blocks = [0, 1].map(t => {
    const byPlayer = squadPlayers(t);
    const xi = currentXI(t);
    const names = xi && xi.xi.length
      ? xi.xi.map(p => `<button type="button" class="pp-chip" data-pteam="${t}" data-pplayer="${escapeHtml(p.name)}">
          <span class="lu-shirt">${escapeHtml(p.shirt ?? "")}</span>${escapeHtml(p.name)}</button>`).join("")
      : "";
    return `<div class="pp-teamcard">
      <button type="button" class="pp-team" data-pteam="${t}">
        <span class="swatch" style="background:var(${VARS[t]})"></span>
        <b>${escapeHtml(DATA.teams[t].name)}</b>
        <span class="pp-sub">${byPlayer.size} players${teamWinText(t) ? " &middot; " + teamWinText(t) : ""}</span>
        <span class="pp-go">Squad &rsaquo;</span>
      </button>
      ${names ? `<div class="pp-xilabel">${xi.confirmed ? "Confirmed" : "Predicted"} XI${xi.formation ? " &middot; " + escapeHtml(xi.formation) : ""}</div>
        <div class="pp-chips">${names}</div>` : `<div class="pp-xilabel">No line-up yet</div>`}
    </div>`;
  });
  return `<div class="pp-teams">${blocks.join("")}</div>${ppBestHtml("b365")}${ppBestHtml()}${strongestHtml()}`;
}

function squadList(t) {
  const byPlayer = squadPlayers(t);
  const xi = currentXI(t);
  const xiNames = xi ? xi.xi.map(p => p.name) : [];
  const shirts = new Map(xi ? xi.xi.map(p => [p.name, p.shirt]) : []);
  const order = { G: 0, D: 1, M: 2, F: 3 };
  const entries = [...byPlayer.entries()].filter(([, played]) => gatedApps(played).length);
  const row = ([name, played]) => {
    const pos = played[0].position || "";
    const role = roleOf(played, pos);
    const chips = playerBestLines(t, name, played).slice(0, 3).map(b => strongChip(b)).join("");
    const card = cardCase(t, name, played);
    const cardTag = card && card.p >= 0.2
      ? `<span class="pp-tag pp-card">Card ${Math.round(card.p * 100)}%</span>` : "";
    return `<button type="button" class="pp-row" data-pteam="${t}" data-pplayer="${escapeHtml(name)}">
      <span class="lu-shirt">${escapeHtml(shirts.get(name) ?? "")}</span>
      <span class="pp-name"><b>${escapeHtml(name)}</b><small>${escapeHtml(role || POSITION_NAME[pos] || pos)} &middot; ${gatedApps(played).length} apps</small></span>
      <span class="pp-tags">${chips}${cardTag}</span>
      <span class="pp-go">&rsaquo;</span>
    </button>`;
  };
  const top = e => (playerBestLines(t, e[0], e[1])[0] || { p: 0 }).p;
  const orderSeg = `<div class="seg pp-order">
    <button type="button" data-porder="lineup" aria-pressed="${pOrder === "lineup"}">${xiNames.length ? "Line-up" : "Position"}</button>
    <button type="button" data-porder="strong" aria-pressed="${pOrder === "strong"}">Strongest</button></div>`;
  if (pOrder === "strong") {
    const ranked = entries.slice().sort((a, b) => top(b) - top(a));
    return `<div class="pp-crumbs"><button type="button" class="pp-back" data-pback="home">&lsaquo; Both teams</button></div>
      <h2 class="team-title"><span class="swatch" style="background:var(${VARS[t]})"></span>${escapeHtml(DATA.teams[t].name)}
        <span class="pp-sub">${teamWinText(t)}</span></h2>
      ${orderSeg}
      <p class="note">Ranked by each player's strongest line: our chance, last ten under the filters, 55 to 92%.</p>
      ${ranked.map(row).join("")}`;
  }
  const inXi = xiNames.map(n => entries.find(([name]) => name === n)).filter(Boolean);
  const rest = entries.filter(([name]) => !xiNames.includes(name))
    .sort((a, b) => (order[a[1][0].position] ?? 9) - (order[b[1][0].position] ?? 9)
                    || gatedApps(b[1]).length - gatedApps(a[1]).length);
  const missingXi = xiNames.filter(n => !byPlayer.has(n));
  return `<div class="pp-crumbs"><button type="button" class="pp-back" data-pback="home">&lsaquo; Both teams</button></div>
    <h2 class="team-title"><span class="swatch" style="background:var(${VARS[t]})"></span>${escapeHtml(DATA.teams[t].name)}
      <span class="pp-sub">${teamWinText(t)}</span></h2>
    ${orderSeg}
    ${inXi.length ? `<div class="pp-section">${xi.confirmed ? "Confirmed" : "Predicted"} XI</div>${inXi.map(row).join("")}` : ""}
    ${missingXi.length ? `<p class="note">In the XI with no record in this report: ${missingXi.map(escapeHtml).join(", ")}</p>` : ""}
    ${xi && xi.missing.length ? `<p class="note gs-missing"><b>Missing:</b> ${xi.missing.map(escapeHtml).join(", ")}</p>` : ""}
    <div class="pp-section">${inXi.length ? "Rest of the squad" : "Squad"}</div>
    ${rest.map(row).join("") || `<p class="note">No one else with an appearance under these filters.</p>`}`;
}

function profileView(t, name) {
  const byPlayer = squadPlayers(t);
  const played = byPlayer.get(name);
  const back = `<div class="pp-crumbs"><button type="button" class="pp-back" data-pback="home">&lsaquo; Both teams</button>
    <button type="button" class="pp-back" data-pback="team">&lsaquo; ${escapeHtml(DATA.teams[t].name)}</button></div>`;
  if (!played || !gatedApps(played).length) {
    return back + `<p class="note">${escapeHtml(name)} has no appearance on file under these filters.</p>`;
  }
  const pos = played[0].position || "";
  const role = roleOf(played, pos);
  const apps = gatedApps(played);
  const avgMin = apps.reduce((s, g) => s + (g.minutes || 0), 0) / apps.length;
  const xi = currentXI(t);
  const status = !xi ? "" : xi.xi.some(p => p.name === name)
    ? `<span class="lu-badge ${xi.confirmed ? "lu-conf" : ""}">${xi.confirmed ? "Starting" : "Predicted to start"}</span>`
    : xi.missing.includes(name) ? `<span class="lu-badge pp-out">Missing</span>`
    : `<span class="lu-badge">${xi.confirmed ? "Not starting" : "Not in predicted XI"}</span>`;
  const fullRec = allPlayed(t, name);
  const oppName = DATA.teams[1 - t].name;
  // Ours reads his last ten appearances under the filters, the form a
  // "9 of his last 10" case is about; the bookmaker estimate reads every
  // match on file. The edge is the gap between the two.
  const recent = apps.slice(-10);

  let html = back + `<div class="pp-hero">
    <div><span class="swatch" style="background:var(${VARS[t]})"></span>
      <b class="pp-big">${escapeHtml(name)}</b> ${status}</div>
    <div class="pp-sub">${escapeHtml(DATA.teams[t].name)} &middot; ${escapeHtml(role || POSITION_NAME[pos] || pos)}
      &middot; ${apps.length} apps here${avgMin > 0 ? ", " + Math.round(avgMin) + " min average" : ""}
      ${teamWinText(t) ? " &middot; side " + teamWinText(t) : ""}</div>
  </div>`;

  // Booked and to score.
  const markets = [];
  // Ten matches of fouls or goals is a thin read on its own, so ours for
  // these two is half his last ten and half everything under the filters.
  const halfAndHalf = (a, b) => {
    if (a && b) a.p = 1 - Math.exp(-(a.lam + b.lam) / 2);
    return a;
  };
  const card = halfAndHalf(cardCase(t, name, recent), cardCase(t, name, played));
  const cardModel = card ? cardModelP(name) : null;
  if (card && cardModel !== null) card.p = cardModel;
  if (card) {
    const cardFull = cardCase(t, name, fullRec.length ? fullRec : played, true);
    const bf = (playerMarket(name) || {}).card || null;
    const opp = card.opps.length
      ? ` Up against ${card.opps.map(o => `${escapeHtml(o.name)}${o.fouled90 !== null ? " (fouled " + o.fouled90.toFixed(1) + "/90)" : ""}`).join(" and ")}, x${card.oppAdj.toFixed(2)}.`
      : "";
    markets.push(`<div class="pp-stat pp-market">
      <div class="pp-stat-head"><b>To be booked</b>
        <span>${card.fouls90.toFixed(2)} fouls/90 &middot; ${Math.round(card.expMin)} min expected</span></div>
      <p class="pp-why">${card.fouls90.toFixed(2)} fouls per 90 over his last ${card.n}, and ${escapeHtml(DATA.teams[t].name)} get a card for every ${(1 / card.perFoul).toFixed(1)} fouls.
        Projected to foul ${card.matchAdj >= 1 ? "more" : "less"} than usual here (x${card.matchAdj.toFixed(2)}).${opp}
        ${cardModel !== null
          ? `The chance is from the cards model: ${escapeHtml(DATA.teams[t].name)}'s expected cards tonight (backtested, it beat the team model on every test window), split across the XI by fouls per 90 and expected minutes. The split between players is not backtested: card history per player is not in the data yet.`
          : "The chance is half this form and half his full record under the filters. Heuristic, not backtested: card history per player is not in the data yet, so this works from fouls."}</p>
      ${profileChart(recent, "Fouls", 0.5, t)}
      ${rungHtml(`${DATA.fixture.id}|${name}|card`, "Card", `fouls, last ${card.n}`, card.p,
                 cardFull ? cardFull.p : null, bf, null)}
    </div>`);
  }
  const score = halfAndHalf(scoreCase(t, recent), scoreCase(t, played));
  if (score && pos !== "G") {
    const bf = (playerMarket(name) || {}).score || null;
    const goalsApps = appearances(played, "Goals");
    const p0 = { name, hits: goalsApps.filter(a => a.value > 0.5).length, vals: goalsApps.map(a => a.value) };
    const price = { p: score.p, fair: fairOdds(score.p), need: fairOdds(score.p) };
    const row = playerRow(p0, "Goals", 0.5, t, price);
    const idx = PLAYER_ROWS.push({ row, price }) - 1;
    const scoreFull = scoreCase(t, fullRec.length ? fullRec : played, true);
    const r10 = lastRate(played, "Goals", 0.5);
    markets.push(`<div class="pp-stat pp-market">
      <div class="pp-stat-head"><b>To score</b>
        <span>${score.xg90 !== null ? score.xg90.toFixed(2) + " xG/90 &middot; " : ""}${score.goals90.toFixed(2)} goals/90</span></div>
      <p class="pp-why">${score.xg90 !== null ? "60% expected goals, 40% actual goals, " : "Goals "}per 90 over ${Math.round(score.expMin)} expected minutes,
        ${score.adj >= 1 ? "up" : "down"} x${score.adj.toFixed(2)} for what ${escapeHtml(DATA.teams[t].name)} are projected to score against ${escapeHtml(oppName)}. Heuristic, not backtested.</p>
      ${profileChart(played, "Goals", 0.5, t)}
      ${rungHtml(`${DATA.fixture.id}|${name}|score`, "Anytime", `${r10.k}/${r10.n} last ${r10.n}`, score.p,
                 scoreFull ? scoreFull.p : null, bf, idx)}
    </div>`);
  }

  const bestHere = playerBestLines(t, name, played).slice(0, 6);
  if (bestHere.length) {
    html += `<div class="pp-section">His strongest lines</div><div class="pp-chips">${bestHere.map(b => strongChip(b)).join("")}</div>`;
  }

  html += ppCardHtml(t, name, played, "b365");
  html += ppCardHtml(t, name, played);

  // Every stat he has a record in.
  const adjCache = {};
  const stats = playerStatsFor(pos).map(stat => {
    const sApps = appearances(played, stat);
    if (!sApps.length) return "";
    const vals = sApps.map(a => a.value);
    // Never done it in this window: nothing to price, and a record-only
    // chance off 0/10 would only invent an edge.
    if (!vals.some(v => v > 0)) return "";
    const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
    const per = rate90(played, stat);
    const adjustment = adjCache[stat] ?? (adjCache[stat] = playerAdjustment(stat, t));
    const prior = positionPrior(byPlayer, pos, stat, name);
    const fullApps = appearances(fullRec, stat);
    const recentApps = appearances(recent, stat);
    const rungs = rungsFor(stat, vals).map(line => {
      const price = withModel(pricePlayer(recentApps.length ? recentApps : sApps, line, true, adjustment, prior),
                              name, stat, line, true);
      const book = pricePlayer(fullApps.length ? fullApps : sApps, line, true, 1, prior);
      const hits = vals.filter(v => v > line).length;
      const p0 = { name, hits, vals };
      const row = playerRow(p0, stat, line, t, price);
      const idx = PLAYER_ROWS.push({ row, price }) - 1;
      const r10 = lastRate(played, stat, line);
      const rec = `${r10.k}/${r10.n} last ${r10.n}${vals.length > r10.n ? ` &middot; ${hits}/${vals.length} all` : ""}`;
      return rungHtml(`${DATA.fixture.id}|${name}|${stat}|${line}`, lineLabel(line), rec,
                      price.p, book.p, betfairFor(name, stat, line), idx);
    }).join("");
    const firstLine = rungsFor(stat, vals)[0] ?? 0.5;
    return `<div class="pp-stat">
      <div class="pp-stat-head"><b>${escapeHtml(stat)}</b>
        <span>avg ${avg.toFixed(1)}${per !== null ? " &middot; " + per.toFixed(2) + "/90" : ""}${
          Math.abs(adjustment - 1) >= 0.05 ? ` &middot; matchup x${adjustment.toFixed(2)}` : ""}</span></div>
      ${profileChart(played, stat, firstLine, t)}
      ${rungs}
    </div>`;
  }).join("");

  html += (markets.length ? `<div class="pp-section">Player markets</div><div class="pp-grid">${markets.join("")}</div>` : "")
    + `<div class="pp-section">By stat</div><div class="pp-grid">${stats}</div>
    <p class="note">Ours is this page's chance from his last ten appearances under the filters above, adjusted for ${escapeHtml(oppName)} and shrunk the way settled player picks say it should be. Est. bookie is a guide, not a scraped price:
    the chance over every match on file plus a ${Math.round(BOOK_MARGIN * 100)}% margin, which is roughly how a bookmaker prices a player line.
    Betfair is the exchange's back price where it lists the market. Type the real price in and the edge uses it.
    A void bet on a player who does not play is a void, not a loss.</p>`;
  return html;
}

function squadView() {
  const panel = document.getElementById("players");
  panel.classList.remove("two-up");
  document.querySelector(".wrap").classList.remove("wide");
  if (pState.fx !== DATA) pState = { fx: DATA, team: null, player: null };
  PLAYER_ROWS = [];
  let html;
  if (pState.player !== null && pState.team !== null) html = profileView(pState.team, pState.player);
  else if (pState.team !== null) html = squadList(pState.team);
  else html = squadHome();
  panel.innerHTML = `<div class="pp-wrap">${html}</div>`;
}

function setPlayerMode(mode) {
  pMode = mode;
  document.querySelectorAll("[data-pmode]").forEach(b =>
    b.setAttribute("aria-pressed", b.dataset.pmode === mode));
  const stat = mode === "stat";
  ["pstat-controls", "pstat-note"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.hidden = !stat;
  });
  if (!stat) { const n = document.getElementById("pnote"); if (n) n.hidden = true; }
  playerView();
}

document.getElementById("pp-mode")?.addEventListener("click", e => {
  const b = e.target.closest("[data-pmode]");
  if (b) setPlayerMode(b.dataset.pmode);
});

document.getElementById("players").addEventListener("click", e => {
  if (pMode !== "squads") return;
  const back = e.target.closest("[data-pback]");
  if (back) {
    if (back.dataset.pback === "home") pState.team = null;
    pState.player = null;
    squadView();
    window.scrollTo({ top: document.querySelector(".tabs").offsetTop - 8 });
    return;
  }
  const ps = e.target.closest("[data-pstrong]");
  if (ps) { pStrongStat = ps.dataset.pstrong; squadView(); return; }
  const ord = e.target.closest("[data-porder]");
  if (ord) { pOrder = ord.dataset.porder; squadView(); return; }
  const pick = e.target.closest("[data-pteam]");
  if (pick) {
    pState.fx = DATA;
    pState.team = parseInt(pick.dataset.pteam, 10);
    pState.player = pick.dataset.pplayer ?? null;
    squadView();
    window.scrollTo({ top: document.querySelector(".tabs").offsetTop - 8 });
  }
});

document.getElementById("players").addEventListener("input", e => {
  const inp = e.target.closest("input[data-pprice]");
  if (!inp) return;
  const v = parseFloat(inp.value);
  if (v > 1) PRICE_IN[inp.dataset.pprice] = v; else delete PRICE_IN[inp.dataset.pprice];
  const rung = inp.closest(".pp-rung");
  const edge = rung && rung.querySelector(".pp-edge");
  if (!edge) return;
  const ours = parseFloat(rung.dataset.pp);
  const def = parseFloat(rung.dataset.pdef);
  edge.outerHTML = edgeHtml(ours, v > 1 ? v : def);
});

/* ---------------------------------------------- Jarvis-style charts

   The same picture Jarvis shows on a pick: a ring of the last games, a
   segment per game, green and thick for a hit and thin red for a miss, with
   the count in the middle; and a line chart of the values with the line
   dashed across it, a filled green dot over the line and a hollow red one
   under it, so the count reads in greyscale too. The polyline is in the
   team's colour. Hover a dot for the date and opponent. */

const SVG_W = 470, SVG_H = 170;

function jNum(v) {
  return Number.isInteger(v) ? String(v) : (Math.round(v * 10) / 10).toString();
}

function jStep(raw) {
  const p = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  return [1, 2, 5, 10].map(k => k * p).find(s => s >= raw) || 10 * p;
}

/* points: [{v, label, tip}], oldest first. */
function jChart(points, line, colorVar, unit) {
  const W = SVG_W, H = SVG_H, L = 30, R = 38, T = 16, B = 24;
  const n = points.length;
  if (!n) return "";
  const pw = W - L - R, ph = H - T - B;
  const lo = Math.min(0, ...points.map(p => p.v));
  const max = Math.max(...points.map(p => p.v), line, 0.5);
  const tick = jStep((max - lo) * 1.1 / 4);
  const top = Math.ceil((max * 1.1) / tick) * tick;
  const x = i => L + (n > 1 ? (i * pw) / (n - 1) : pw / 2);
  const y = v => T + ph - ((v - lo) / ((top - lo) || 1)) * ph;
  let s = `<svg class="jchart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${
    escapeHtml(unit)}, last ${n}, against the ${jNum(line)} line">`;
  for (let v = lo; v <= top + 1e-9; v += tick) {
    if (Math.abs(y(v) - y(line)) >= 6) {
      s += `<line x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" class="jg"/>`;
    }
    s += `<text x="${L - 6}" y="${(y(v) + 3).toFixed(1)}" text-anchor="end" class="jt">${jNum(v)}</text>`;
  }
  s += `<line x1="${L}" x2="${W - R}" y1="${y(line).toFixed(1)}" y2="${y(line).toFixed(1)}" class="jline"/>`;
  s += `<text x="${W - R + 4}" y="${(y(line) + 3).toFixed(1)}" class="jll">${escapeHtml(lineLabel(line))}</text>`;
  s += `<polyline points="${points.map((p, i) => `${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ")}"
    fill="none" style="stroke:var(${colorVar})" stroke-width="1.8" opacity="0.9"/>`;
  points.forEach((p, i) => {
    const hit = p.v > line;
    s += `<circle cx="${x(i).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="4" class="${hit ? "jhit" : "jmiss"}">
      <title>${escapeHtml(p.tip || "")}: ${jNum(p.v)} ${escapeHtml(unit)} ${hit ? "(over)" : "(under)"}</title></circle>`;
    if (n <= 12 || i % 2 === n % 2) {
      s += `<text x="${x(i).toFixed(1)}" y="${H - 7}" text-anchor="middle" class="jx">${escapeHtml(p.label || "")}</text>`;
    }
  });
  // Value labels on the best and the latest, as Jarvis does.
  let best = 0;
  points.forEach((p, i) => { if (p.v > points[best].v) best = i; });
  for (const i of new Set([best, n - 1])) {
    s += `<text x="${x(i).toFixed(1)}" y="${(y(points[i].v) - 9).toFixed(1)}" text-anchor="middle" class="jv">${jNum(points[i].v)}</text>`;
  }
  return s + `</svg>`;
}

function jRing(points, line) {
  const n = points.length;
  if (!n) return "";
  const cx = 60, cy = 60, r = 50, gap = n > 1 ? 3.2 : 0;
  const hits = points.filter(p => p.v > line).length;
  let s = `<svg class="jring" viewBox="0 0 120 120" role="img" aria-label="${hits} of the last ${n} over the line">`;
  const pt = a => [cx + r * Math.cos(a * Math.PI / 180), cy + r * Math.sin(a * Math.PI / 180)];
  points.forEach((p, i) => {
    const hit = p.v > line;
    if (n === 1) {
      s += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" class="${hit ? "jseg-hit" : "jseg-miss"}"/>`;
      return;
    }
    const a0 = -90 + (i * 360) / n + gap / 2, a1 = -90 + ((i + 1) * 360) / n - gap / 2;
    const [x0, y0] = pt(a0), [x1, y1] = pt(a1);
    s += `<path d="M${x0.toFixed(2)},${y0.toFixed(2)} A${r},${r} 0 0 1 ${x1.toFixed(2)},${y1.toFixed(2)}"
      fill="none" class="${hit ? "jseg-hit" : "jseg-miss"}"><title>${escapeHtml(p.tip || "")}: ${jNum(p.v)}</title></path>`;
  });
  s += `<text x="${cx}" y="${cy + 6}" text-anchor="middle" class="jr1">${hits}/${n}</text>`;
  s += `<text x="${cx}" y="${cy + 22}" text-anchor="middle" class="jr2">over</text>`;
  return s + `</svg>`;
}

function oppAbbrev(name) {
  const w = String(name || "").replace(/[^A-Za-z ]/g, "").split(" ").filter(x => x.length > 2 && !["FC", "AFC", "The"].includes(x));
  return (w[0] || name || "").slice(0, 3).toUpperCase();
}

/* ------------------------------------------------- Team stats as one chart

   The Team stats tab is one view, not a card per stat. The stat list sits
   down the side, always open; tap one and the chart beside it switches to
   it. Above the chart: which side (both, home, away), which period (full,
   1st, 2nd), how many games, and the line. Both sides share one chart,
   each in its own colour, with a ring each for the hit count. Same picture
   as Jarvis's pick cards. The side and period buttons drive the same
   controls as the Filters panel, so everything else on the page agrees.
   The original board is one tap away ("Table"). */

let teamMode = "cards";
let tcStat = null;
let tcLast = 10;

/* series: [{pts: [{v, tip, label}], colorVar}]. x is game order, oldest
   first, aligned on the newest game, so "last 10" lines up across sides. */
function jChart2(series, line, unit, labels) {
  const W = 640, H = 260, L = 34, R = 40, T = 20, B = 28;
  const n = Math.max(...series.map(s => s.pts.length));
  if (!n) return "";
  const pw = W - L - R, ph = H - T - B;
  const all = series.flatMap(s => s.pts.map(p => p.v));
  const lo = Math.min(0, ...all);
  const max = Math.max(...all, line, 0.5);
  const tick = jStep((max - lo) * 1.1 / 5);
  const top = Math.ceil((max * 1.1) / tick) * tick;
  const x = i => L + (n > 1 ? (i * pw) / (n - 1) : pw / 2);
  const y = v => T + ph - ((v - lo) / ((top - lo) || 1)) * ph;
  let s = `<svg class="jchart jbig" viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeHtml(unit)} against the ${jNum(line)} line">`;
  for (let v = lo; v <= top + 1e-9; v += tick) {
    if (Math.abs(y(v) - y(line)) >= 6) {
      s += `<line x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" class="jg"/>`;
    }
    s += `<text x="${L - 6}" y="${(y(v) + 3).toFixed(1)}" text-anchor="end" class="jt">${jNum(v)}</text>`;
  }
  s += `<line x1="${L}" x2="${W - R}" y1="${y(line).toFixed(1)}" y2="${y(line).toFixed(1)}" class="jline"/>`;
  s += `<text x="${W - R + 4}" y="${(y(line) + 3).toFixed(1)}" class="jll">${escapeHtml(lineLabel(line))}</text>`;
  for (const se of series) {
    const off = n - se.pts.length;
    s += `<polyline points="${se.pts.map((p, i) => `${x(i + off).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ")}"
      fill="none" style="stroke:var(${se.colorVar})" stroke-width="2.2" opacity="0.9"/>`;
  }
  for (const se of series) {
    const off = n - se.pts.length;
    se.pts.forEach((p, i) => {
      const hit = p.v > line;
      s += `<circle cx="${x(i + off).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="4.5" class="${hit ? "jhit" : "jmiss"}"
        ${hit ? "" : `style="stroke:var(${se.colorVar})"`}><title>${escapeHtml(p.tip || "")}: ${jNum(p.v)} ${escapeHtml(unit)}</title></circle>`;
    });
    const last = se.pts[se.pts.length - 1];
    if (last) s += `<text x="${x(n - 1).toFixed(1)}" y="${(y(last.v) - 10).toFixed(1)}" text-anchor="middle" class="jv">${jNum(last.v)}</text>`;
  }
  const step = n > 14 ? 2 : 1;
  for (let i = 0; i < n; i += step) {
    const lab = labels ? labels[i] : (i === n - 1 ? "latest" : `${i - n + 1}`);
    s += `<text x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle" class="jx">${escapeHtml(lab || "")}</text>`;
  }
  return s + `</svg>`;
}

function tcPoints(rows, name, which) {
  return rows
    .map(r => ({ v: statValue(r, name, which), r }))
    .filter(p => p.v !== undefined && p.v !== null)
    .map(p => ({ v: p.v, label: oppAbbrev(p.r.opponent),
                 tip: `${p.r.date} ${p.r.venue === "home" ? "v" : "at"} ${p.r.opponent}` }));
}

function teamCards() {
  const el = document.getElementById("tcards");
  if (!el) return;
  const board = document.getElementById("board");
  const cards = teamMode === "cards";
  el.hidden = !cards;
  if (board) board.hidden = cards;
  if (!cards) return;

  const lines = activeLines();
  const stats = visibleStats();
  if (!stats.length) { el.innerHTML = `<p class="note">Nothing matches these filters.</p>`; return; }
  if (!stats.includes(tcStat)) tcStat = stats[0];
  const teamRows = activeRecords().map(filtered);
  const shown = focusedIndexes();

  // The list down the side: every stat, each side's last-N count beside it.
  const list = stats.map(name => {
    const line = lines[name];
    const badges = shown.map(i => {
      const pts = tcPoints(teamRows[i], name, bucketFor(i)).slice(-tcLast);
      if (!pts.length) return "";
      const k = pts.filter(p => p.v > line).length, r = k / pts.length;
      return `<span class="tl-badge ${r >= 0.8 ? "tl-hi" : r >= 0.6 ? "tl-mid" : ""}"><i style="background:var(${VARS[i]})"></i>${k}/${pts.length}<span class="tl-pct">${Math.round(r * 100)}%</span></span>`;
    }).join("");
    return `<button type="button" class="tl-item${name === tcStat ? " tl-on" : ""}" data-tcstat="${escapeHtml(name)}">
      <span class="tl-name">${escapeHtml(name)}<small>${escapeHtml(lineLabel(line))}</small></span>
      <span class="tl-badges">${badges}</span></button>`;
  }).join("");

  const name = tcStat, line = lines[name];
  const series = [], rings = [];
  shown.forEach(i => {
    const which = bucketFor(i);
    const pts = tcPoints(teamRows[i], name, which);
    const last = pts.slice(-tcLast);
    const suffix = measure === "for" ? "" : (which === "against" ? " conceded" : " for");
    if (last.length) series.push({ pts: last, colorVar: VARS[i] });
    const all = pts.filter(p => p.v > line).length;
    const avg = pts.length ? pts.reduce((a, p) => a + p.v, 0) / pts.length : 0;
    rings.push(`<div class="tv-ring">
      <div class="tv-ringsvg">${jRing(last, line)}</div>
      <div class="tv-ringtxt"><span class="tc-team"><span class="swatch" style="background:var(${VARS[i]})"></span>${escapeHtml(DATA.teams[i].name)}${suffix}</span>
        <small>${pts.length ? `${all}/${pts.length} all &middot; avg ${jNum(avg)}` : "no data"}</small></div>
    </div>`);
  });
  const labels = series.length === 1 ? series[0].pts.map(p => p.label) : null;

  const seg = (attr, items, cur) => `<div class="seg tv-seg">${items.map(([v, t]) =>
    `<button type="button" ${attr}="${v}" aria-pressed="${String(v) === String(cur)}">${escapeHtml(t)}</button>`).join("")}</div>`;
  const periods = [["ALL", "Full"], ["1ST", "1st half"], ["2ND", "2nd half"]].filter(([p]) => DATA.lines[p]);

  el.innerHTML = `<div class="tv">
    <nav class="tv-list" aria-label="Stats">
      <div class="seg tl-order">
        <button type="button" data-tcsort="default" aria-pressed="${sort !== "strongest"}">Standard</button>
        <button type="button" data-tcsort="strongest" aria-pressed="${sort === "strongest"}">Strongest</button>
      </div>${list}</nav>
    <section class="tv-main">
      <div class="tv-head">
        <h3>${escapeHtml(name)}</h3>
        <div class="tc-step">
          <button type="button" data-tstep="-1" aria-label="Lower the line">&minus;</button>
          <span class="tc-line">${escapeHtml(lineLabel(line))}</span>
          <button type="button" data-tstep="1" aria-label="Raise the line">+</button>
        </div>
        ${projectionHtml(name, line)}
      </div>
      <div class="tv-controls">
        ${seg("data-tcfocus", [["both", "Both"], ["0", DATA.teams[0].name], ["1", DATA.teams[1].name]], focus)}
        ${periods.length > 1 ? seg("data-tcperiod", periods, period) : ""}
        ${seg("data-tclast", [[5, "Last 5"], [10, "Last 10"], [20, "Last 20"]], tcLast)}
      </div>
      <div class="tv-rings">${rings.join("")}</div>
      <div class="tv-chart">${jChart2(series, line, name, labels)}</div>
      <p class="note tv-note">Oldest on the left, newest on the right. Filled dot: over the line. Hollow: under. Hover a dot for the match.</p>
    </section>
  </div>`;
}

function setTeamMode(mode) {
  teamMode = mode;
  document.querySelectorAll("[data-tmode]").forEach(b =>
    b.setAttribute("aria-pressed", b.dataset.tmode === mode));
  teamCards();
}

document.getElementById("tmode")?.addEventListener("click", e => {
  const b = e.target.closest("[data-tmode]");
  if (b) setTeamMode(b.dataset.tmode);
});

document.getElementById("tcards")?.addEventListener("click", e => {
  const pick = e.target.closest("[data-tcstat]");
  if (pick) { tcStat = pick.dataset.tcstat; teamCards(); return; }
  // Side and period go through the Filters panel's own buttons, so the
  // whole page moves together.
  const f = e.target.closest("[data-tcfocus]");
  if (f) { document.querySelector(`[data-focus="${f.dataset.tcfocus}"]`)?.click(); return; }
  const p = e.target.closest("[data-tcperiod]");
  if (p) { document.querySelector(`[data-period="${p.dataset.tcperiod}"]`)?.click(); return; }
  const so = e.target.closest("[data-tcsort]");
  if (so) { document.querySelector(`[data-sort="${so.dataset.tcsort}"]`)?.click(); return; }
  const l = e.target.closest("[data-tclast]");
  if (l) { tcLast = parseInt(l.dataset.tclast, 10); teamCards(); return; }
  const b = e.target.closest("[data-tstep]");
  if (!b) return;
  const name = tcStat;
  const lines = activeLines();
  const next = snapLine((lines[name] ?? 0.5) + parseInt(b.dataset.tstep, 10));
  const row = [...document.querySelectorAll("#board .stat-row")].find(r => r.dataset.stat === name);
  if (row) setLine(row, next); else lines[name] = next;
  teamCards();
});

/* Two trimmed tables need about 1590px plus margins. Below that the squads
   stack and the Team control above does the work instead. */
const TWO_UP_MIN = 1640;

function fillPlayerStats() {
  const select = document.getElementById("pstat");
  const tabs = document.querySelector(".tabs");

  // Darts has no squads, so no player tabs, but the two players ARE the
  // "teams" and the team scans are exactly the darts bets.
  if (SPORT === "darts") {
    tabs.hidden = false;
    ["players", "best-player", "value"].forEach(t => {
      const b = tabs.querySelector(`[data-tab="${t}"]`);
      if (b) b.hidden = true;
    });
    const label = { team: "Stats", "best-team": "Best bets", lineups: "Match" };
    Object.entries(label).forEach(([t, text]) => {
      const b = tabs.querySelector(`[data-tab="${t}"]`);
      if (b) b.textContent = text;
    });
    if (["players", "lineups", "best-player"].includes(tab)) switchTab("team");
    return;
  }

  if (!hasPlayers()) {
    tabs.hidden = true;
    if (tab === "players") switchTab("team");
    return;
  }

  tabs.hidden = false;
  const previous = select.value;
  select.innerHTML = DATA.playerStats
    .map(n => `<option value="${n}">${n}</option>`).join("");

  const wanted = DATA.playerStats.includes(previous)
    ? previous
    : (DATA.playerStats.includes("Shots") ? "Shots" : DATA.playerStats[0]);

  select.value = wanted;
  document.getElementById("pline").value = DATA.playerLines[wanted] ?? 0.5;
}

/* --------------------------------------------------------------- fixtures */

/* The two series colours come from the clubs' kits, worked out at build time
   and shipped per fixture. Applied here rather than baked into the stylesheet
   because they change with the fixture, and again on a theme change because
   the light and dark values are separately chosen rather than one flipped.

   Reports built before this existed have no colours block and simply keep the
   stylesheet's defaults. */
function applyTeamColours() {
  const root = document.documentElement;
  if (!DATA.colours) {
    root.style.removeProperty("--team-1");
    root.style.removeProperty("--team-2");
    return;
  }

  const stamped = root.getAttribute("data-theme");
  const dark = stamped
    ? stamped === "dark"
    : window.matchMedia("(prefers-color-scheme: dark)").matches;

  const pair = DATA.colours[dark ? "dark" : "light"] || DATA.colours.light;
  if (!pair) return;
  root.style.setProperty("--team-1", pair[0]);
  root.style.setProperty("--team-2", pair[1]);
}

function applyFixture() {
  applyTeamColours();
  fillCustom();
  resultView();
  SUGGESTED = {};
  for (const [key, bucket] of Object.entries(DATA.lines)) {
    SUGGESTED[key] = Object.assign({}, bucket);
  }
  SUGGESTED_H2H = {};
  for (const [key, bucket] of Object.entries(DATA.h2hLines || {})) {
    SUGGESTED_H2H[key] = Object.assign({}, bucket);
  }

  // Reports built before "against" existed have no conceded numbers.
  if (!hasAgainst() && measure !== "for") measure = "for";
  document.querySelectorAll("[data-measure]").forEach(b => {
    b.disabled = b.dataset.measure !== "for" && !hasAgainst();
    b.setAttribute("aria-pressed", b.dataset.measure === measure);
  });

  // A fixture between newly promoted sides may have no previous meetings.
  if (!hasH2H() && source === "h2h") source = "form";
  document.querySelectorAll("[data-source]").forEach(b => {
    b.disabled = b.dataset.source === "h2h" && !hasH2H();
    b.setAttribute("aria-pressed", b.dataset.source === source);
  });

  // Darts: no venue and no halves, so those controls go rather than sit
  // there greyed out or, worse, quietly halving the sample.
  if (SPORT === "darts") {
    if (venue !== "all") venue = "all";
    ["[data-venue]", "[data-period]"].forEach(sel => {
      const b = document.querySelector(sel);
      const g = b && b.closest(".control-group");
      if (g) g.hidden = true;
    });
  }

  // A fixture can be missing a half if SofaScore never published it.
  if (!DATA.lines[period]) period = "ALL";
  document.querySelectorAll("[data-period]").forEach(b => {
    b.disabled = !DATA.lines[b.dataset.period];
    b.setAttribute("aria-pressed", b.dataset.period === period);
  });

  // The opposition filter is only meaningful when last season's tables were
  // read, and only some fixtures are built with them.
  const tierGroup = document.getElementById("tier-group");
  if (tierGroup) {
    tierGroup.hidden = !DATA.tiers;
    if (!DATA.tiers && tier !== "all") {
      tier = "all";
      document.querySelectorAll("[data-tier]").forEach(b =>
        b.setAttribute("aria-pressed", b.dataset.tier === "all"));
    }
  }

  document.getElementById("competition").textContent = DATA.fixture.competition;
  document.getElementById("title").textContent =
    `${DATA.fixture.home} v ${DATA.fixture.away}`;
  document.getElementById("kickoff").textContent = DATA.fixture.date || "";

  // Referee line. DATA.referee is absent until an official is appointed,
  // which is normal for most of the week: say nothing rather than print
  // zeros, because a zero here reads as "a referee who gives no cards".
  // Display only. These numbers feed no line, price or projection anywhere,
  // by agreement: head to head and possession both looked informative and
  // measured as noise, so a referee effect gets shown before it is trusted.
  const refEl = document.getElementById("referee");
  if (refEl) {
    const ref = DATA.referee;
    if (ref && ref.name) {
      let text = "Referee: " + ref.name;
      if (ref.yellowsPerGame != null) {
        text += " \u00b7 " + ref.yellowsPerGame.toFixed(2) + " yellows and "
              + ref.redsPerGame.toFixed(2) + " reds per game over "
              + ref.games + " matches";
        if (ref.games < 10) text += " (small sample)";
      } else {
        text += " \u00b7 no card history on record";
      }
      refEl.textContent = text;
      refEl.hidden = false;
    } else {
      refEl.hidden = true;
    }
  }
  document.getElementById("legend-0").textContent = DATA.teams[0].name;
  document.getElementById("legend-1").textContent = DATA.teams[1].name;
  document.getElementById("focus-0").textContent = DATA.teams[0].name;
  document.getElementById("focus-1").textContent = DATA.teams[1].name;
  document.title = `${DATA.fixture.home} v ${DATA.fixture.away}: hit rates`;

  fillPlayerStats();
  oddsStrip();
  render();
  if (tab === "players") playerView();
  if (tab === "standout") standoutView();
  if (onBest()) bestBetsView();
  if (tab === "value") valueView();
  lineupPick = null;
  if (tab === "lineups") lineupView();
}

function switchTab(target) {
  tab = target;
  if (target === "best-player") bestKind = "player";
  if (target === "best-team") bestKind = "team";
  /* Player bets open on value, team bets on evidence.
     A player shortlist ordered by evidence is a list of near-certainties
     paying 1.05, which is not what anybody opens the tab for. */
  if (target === "best-player" || target === "best-team") {
    const want = target === "best-player" ? "value" : "evidence";
    document.querySelectorAll("[data-border]").forEach(btn =>
      btn.setAttribute("aria-pressed", btn.dataset.border === want));
  }
  const panel = panelFor(target);
  document.querySelectorAll("[data-tab]").forEach(b =>
    b.setAttribute("aria-selected", b.dataset.tab === target));
  document.querySelectorAll(".panel").forEach(p =>
    p.hidden = p.dataset.panel !== panel);
  if (target === "players") playerView();
  else document.querySelector(".wrap").classList.remove("wide");
  if (target === "standout") standoutView();
  if (target === "value") valueView();
  if (panel === "best") bestBetsView();
  if (target === "slip") slipView();
  if (target === "lineups") lineupView();
}

/* Is a Best tab the one on screen? Everything that used to test
   `tab === "best"` has to ask this instead, or a control change on the
   Players tab silently stops refreshing the cards. */
function onBest() {
  return tab === "best-player" || tab === "best-team";
}

/* ------------------------------------------------- defence ranks, v2 */
/* The soft-defence ranking, made granular. The first version averaged every
   appearance by a player at the position, which a defence could flatter by
   facing teams that rotate four receivers, and it never asked who those
   yards came against. This measures three things per defence, per position,
   per stat, over every game in the file:

     per game   everything the position produced against them, summed
     lead man   the best single player at the position that game (WR1, RB1),
                which is what most props are actually on
     vs usual   each game's total divided by what THAT offence usually gets
                from the position in its other games, averaged. 1.25x means
                offences get a quarter more than normal against this defence.
                This is the ranking, because it takes the schedule out.

   plus the same "vs usual" over the last four games, so a defence that has
   started leaking shows it before the season average catches up. */
const DEF_CACHE = new Map();
const DEF_MIN_GAMES = 4;
const DEF_RECENT = 4;

function defOffenceMap() {
  if (DEF_CACHE.has("_off")) return DEF_CACHE.get("_off");
  const off = new Map();      // `${defenceId}|${matchId}` -> offence team id
  const names = new Map();    // team id -> name
  (ALL.fixtures || []).forEach(fx => {
    (fx.teams || []).forEach((t, ti) => {
      if (!t || t.id == null) return;
      names.set(t.id, t.name);
      ((fx.records || [])[ti] || []).forEach(m => {
        if (m.opponent_id != null) {
          off.set(`${m.opponent_id}|${m.id}`, t.id);
          if (!names.has(m.opponent_id) && m.opponent) names.set(m.opponent_id, m.opponent);
        }
      });
    });
  });
  const out = { off, names };
  DEF_CACHE.set("_off", out);
  return out;
}

function defPerGame(records, stat) {
  const games = new Map();    // match id -> {total, lead}
  (records || []).forEach(r => {
    const v = (r.stats || {})[stat];
    if (v === undefined || v === null) return;
    const g = games.get(r.match_id) || { total: 0, lead: 0, date: r.date };
    g.total += v; g.lead = Math.max(g.lead, v);
    games.set(r.match_id, g);
  });
  return games;
}

/* Defensive positions come labelled every way SofaScore can think of (DE,
   DT, NT, DL; CB, SAF, DB). A tackle prop on a linebacker and one on a
   safety are different questions, but a nose tackle and a defensive tackle
   are the same one, so these are pooled into three groups. */
const DEF_GROUPS = { DL: ["DE", "DT", "DL", "NT"], DB: ["CB", "SAF", "DB", "S", "FS", "SS"],
                     LB: ["LB", "OLB", "ILB", "MLB"],
                     // Basketball: SofaScore lists G, GF, F, FG, FC, C, CF.
                     // Pooled by the first letter, the role he mostly plays.
                     BBG: ["G", "GF"], BBF: ["F", "FG", "FC"], BBC: ["C", "CF"] };
function posList(byPos, pos) {
  if (!byPos) return [];
  const g = DEF_GROUPS[pos];
  return g ? g.flatMap(p => byPos.get(p) || []) : (byPos.get(pos) || []);
}
function posMatch(have, want) {
  const g = DEF_GROUPS[want];
  return g ? g.includes(have) : have === want;
}

function defenceTable(pos, stat) {
  const key = `${pos}|${stat}`;
  if (DEF_CACHE.has(key)) return DEF_CACHE.get(key);
  const idx = matchupIndex();
  const { off, names } = defOffenceMap();
  // What each offence usually gets from this position, game by game.
  const ownGames = new Map();
  idx.own.forEach((byPos, teamId) => ownGames.set(teamId, defPerGame(posList(byPos, pos), stat)));
  const usual = (teamId, skipMatch) => {
    const g = ownGames.get(teamId);
    if (!g) return null;
    let n = 0, s = 0;
    g.forEach((v, mid) => { if (mid !== skipMatch) { n++; s += v.total; } });
    return n >= 3 && s > 0 ? s / n : null;
  };
  const rows = [];
  idx.conceded.forEach((byPos, defId) => {
    const games = [...defPerGame(posList(byPos, pos), stat).entries()]
      .sort((a, b) => (a[1].date < b[1].date ? -1 : 1));
    if (games.length < DEF_MIN_GAMES) return;
    const ratios = games.map(([mid, g]) => {
      const u = usual(off.get(`${defId}|${mid}`), mid);
      return u ? g.total / u : null;
    });
    const valid = ratios.filter(x => x !== null);
    const recent = ratios.slice(-DEF_RECENT).filter(x => x !== null);
    const avg = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
    rows.push({
      teamId: defId, name: names.get(defId) || String(defId), games: games.length,
      perGame: avg(games.map(([, g]) => g.total)), lead: avg(games.map(([, g]) => g.lead)),
      leadSeries: games.map(([, g]) => g.lead),
      vsUsual: valid.length >= 3 ? avg(valid) : null,
      recent: recent.length >= 2 ? avg(recent) : null,
    });
  });
  // Rank on vs-usual where it exists; raw per game breaks ties and fills gaps.
  rows.sort((a, b) => ((b.vsUsual ?? 0) - (a.vsUsual ?? 0)) || (b.perGame - a.perGame));
  rows.forEach((r, i) => { r.place = i + 1; });
  const recentOrder = rows.filter(r => r.recent !== null).sort((a, b) => b.recent - a.recent);
  recentOrder.forEach((r, i) => { r.recentPlace = i + 1; });
  DEF_CACHE.set(key, rows);
  return rows;
}

function defRow(teamId, pos, stat) {
  const t = defenceTable(pos, stat);
  const r = t.find(x => x.teamId === teamId);
  return r ? { ...r, of: t.length } : null;
}

/* What the BEST man at a position got against this defence, against his own
   usual. A run defence can rank tough on everyone's yards and still give a
   genuinely good back his hundred: the Ravens were a "tough" run matchup the
   week Bijan Robinson ran for about 100 on them. Per game: the leading player
   at the position, his output that day divided by his own average in his
   other games. Averaged, plus the biggest single day, so the page can say
   who it was. Null under three games with a usable usual. */
function defTopMan(defId, pos, stat) {
  const key = `top|${defId}|${pos}|${stat}`;
  if (DEF_CACHE.has(key)) return DEF_CACHE.get(key);
  const idx = matchupIndex();
  const { off } = defOffenceMap();
  const byPos = idx.conceded.get(defId);
  const games = new Map();
  posList(byPos, pos).forEach(r => {
    const v = (r.stats || {})[stat];
    if (v === undefined || v === null) return;
    const g = games.get(r.match_id);
    if (!g || v > g.v) games.set(r.match_id, { v, player: r.player, date: r.date });
  });
  const ratios = [];
  let best = null;
  games.forEach((g, mid) => {
    const team = off.get(`${defId}|${mid}`);
    const own = posList(idx.own.get(team), pos)
      .filter(r => r.player === g.player && r.match_id !== mid && (r.stats || {})[stat] != null);
    if (own.length < 3) return;
    const usual = own.reduce((a, r) => a + r.stats[stat], 0) / own.length;
    if (usual <= 0) return;
    const ratio = g.v / usual;
    ratios.push({ ratio, date: g.date });
    if (usual >= ((DEF_LADDER[stat] || [0])[1] || 0) && (!best || g.v > best.v)) best = { ...g, usual };
  });
  ratios.sort((a, b) => (a.date < b.date ? -1 : 1));
  const out = ratios.length >= 3
    ? { ratio: ratios.reduce((a, x) => a + x.ratio, 0) / ratios.length, n: ratios.length, best }
    : null;
  DEF_CACHE.set(key, out);
  return out;
}

/* Who this defence is missing. A ranking earned with a shutdown corner is
   not the defence that turns up without him: Denver were the toughest on
   receivers with Pat Surtain II, and he was out. Not modelled, because one
   absence is not a number, but put on the pick so it cannot be missed. */
const DEF_COVER = { WR: ["CB", "S", "SAF", "DB", "FS", "SS"], TE: ["S", "SAF", "LB", "OLB", "ILB", "MLB", "CB"],
                    RB: ["LB", "OLB", "ILB", "MLB", "DE", "DT", "NT", "DL", "S", "SAF"], QB: ["CB", "S", "SAF", "DE", "OLB", "DB"] };
function defMissing(defIndex, pos) {
  const want = DEF_COVER[pos] || [];
  const regular = new Map();
  ((DATA.players || [])[defIndex] || []).forEach(r => regular.set(r.player, (regular.get(r.player) || 0) + 1));
  return [...nflOut(defIndex).keys()].filter(name => {
    const row = nflInjuries(defIndex).find(x => x[0] === name);
    return row && want.includes((row[1] || "").toUpperCase());
  });
}

/* Is the player's role growing? Targets for anything caught, carries for
   rushing, attempts for passing: the last three games against his last ten.
   Volume leads yards, so a receiver whose targets jumped from six to nine is
   a better bet than his ten-game yards say. Folded in at the square root and
   capped at 15% either way, because three games is still three games. */
const DEF_USAGE = { "Receiving yards": "Receiving targets", "Receiving receptions": "Receiving targets",
                    "Rushing yards": "Rushing attempts", "Passing yards": "Passing attempts" };
function usageTrend(p, stat) {
  if (p.role) return null;
  const u = (p.u || []).filter(x => x != null);
  if (!DEF_USAGE[stat] || u.length < 5) return null;
  const last = u.slice(-3), mean = a => a.reduce((x, y) => x + y, 0) / a.length;
  const all = mean(u);
  if (all <= 0) return null;
  const adj = Math.min(1.15, Math.max(0.85, Math.sqrt(mean(last) / all)));
  return { recent: mean(last), all, adj, word: DEF_USAGE[stat].replace("Receiving ", "").replace("Rushing attempts", "carries").replace("Passing attempts", "attempts") };
}

/* The Defences tab on gridiron pages: both defences in this fixture, every
   position and market that props are written on, in one grid. */
const DEF_ROWS = [["QB", "Passing yards"], ["RB", "Rushing yards"], ["RB", "Receiving yards"],
                  ["WR", "Receiving yards"], ["WR", "Receiving receptions"],
                  ["TE", "Receiving yards"], ["TE", "Receiving receptions"]];
const DEF_POS = { QB: "QBs", RB: "RBs", WR: "WRs", TE: "TEs", LB: "LBs", DB: "DBs", DL: "D-line" };

/* Ladder lines bookies actually offer, per market. */
const DEF_LADDER = {
  "Passing yards": [175, 200, 225, 250, 275, 300],
  "Rushing yards": [25, 40, 50, 60, 75, 100],
  "Receiving yards": [25, 40, 50, 60, 75, 100],
  "Receiving receptions": [2, 3, 4, 5, 6, 7, 8],
  "Defensive combine tackles": [2, 3, 4, 5, 6, 7, 8, 9, 10],
  "Defensive assist tackles": [1, 2, 3, 4],
  "Defensive sacks": [0.5, 1, 1.5],
};

/* Defensive props: the same machinery pointed the other way. "vs usual"
   here is what defenders at the position make against THIS offence, divided
   by what the same defenders make against everyone else, so an offence that
   runs a lot of plays, or leaves its quarterback exposed, shows up as
   generous. Sacks are rare enough that the hit bar is lower (half his games
   rather than seven in ten), or no pass rusher would ever qualify. */
const DEFP_ROWS = [["LB", "Defensive combine tackles"], ["DB", "Defensive combine tackles"],
                   ["DL", "Defensive combine tackles"], ["LB", "Defensive assist tackles"],
                   ["DB", "Defensive assist tackles"], ["DL", "Defensive sacks"], ["LB", "Defensive sacks"]];
const DEFP_RATE = { "Defensive sacks": 0.5 };
let defMode = "offence";

/* Who is actually playing. NFL inactives are announced about 90 minutes
   before kick-off; once SofaScore has the confirmed roster, anyone not on it,
   or listed as missing, is dropped from the picks. Before then: everyone. */
function defActive(teamIndex) {
  const lu = (DATA.lineups || {}).confirmed;
  if (!lu) return null;
  const side = lu[teamIndex === 0 ? "home" : "away"] || {};
  const roster = new Set([...(side.xi || []).map(p => p.name), ...(side.bench || [])]);
  const out = new Set((side.missing || []).map(m => m[0]));
  if (!roster.size) return null;
  return { roster, out };
}

/* Days before the inactives, the injury report is the best guide there is.
   It comes from ESPN at build time (nfl_injuries.py): anyone Out, Doubtful,
   on IR or suspended is treated as not playing. Questionable is left in and
   flagged, because most questionable players play. */
const NFL_OUT = /^(out|doubtful|injured reserve|ir\\b|suspen|pup|physically unable|non-football|reserve)/i;
function nflInjuries(teamIndex) {
  return ((DATA.injuries || {})[teamIndex === 0 ? "home" : "away"]) || [];
}
function nflOut(teamIndex) {
  return new Map(nflInjuries(teamIndex).filter(x => NFL_OUT.test(x[2] || "")).map(x => [x[0], x[2]]));
}
function nflQuestionable(teamIndex) {
  return new Map(nflInjuries(teamIndex).filter(x => /^questionable/i.test(x[2] || "")).map(x => [x[0], x[2]]));
}

/* A change at quarterback, worked out at build time from the injury report,
   the confirmed inactives and a manual override (nfl_injuries.py). Every
   receiver's record was built catching passes from the man who has been
   starting, so when somebody else starts, those records are scaled by how
   the new man's passing compares: yards by yards per start, receptions by
   completions per start. */
function qbChange(teamIndex) {
  return ((DATA.qbChange || {})[teamIndex === 0 ? "home" : "away"]) || null;
}
function qbScale(teamIndex, stat) {
  const q = qbChange(teamIndex);
  if (!q) return 1;
  if (stat === "Receiving yards") return q.yds || 1;
  if (stat === "Receiving receptions") return q.rec || 1;
  return 1;
}

/* The players who actually get the ball at a position: top two by average
   over their last ten games with the stat recorded. Injured and inactive
   players are left out, and a quarterback who is not starting is never the
   quarterback pick. */
function defPlayers(teamIndex, pos, stat, count) {
  const by = new Map();
  const active = defActive(teamIndex);
  const injured = nflOut(teamIndex);
  const q = qbChange(teamIndex);
  ((DATA.players || [])[teamIndex] || []).forEach(r => {
    if (!posMatch(r.position, pos) || r.former_club) return;
    if (active && (!active.roster.has(r.player) || active.out.has(r.player))) return;
    if (injured.has(r.player)) return;
    if (q && pos === "QB" && r.player === q.from) return;
    const v = (r.stats || {})[stat];
    if (v === undefined || v === null) return;
    if (!by.has(r.player)) by.set(r.player, []);
    by.get(r.player).push(r);
  });
  const scale = qbScale(teamIndex, stat);
  return [...by.entries()].map(([name, rs]) => {
    rs.sort((a, b) => (a.date < b.date ? -1 : 1));
    let v = rs.slice(-10).map(r => r.stats[stat] * scale);
    const uStat = DEF_USAGE[stat];
    let u = uStat ? rs.slice(-10).map(r => (r.stats || {})[uStat] ?? null) : [];
    // A new role. When the starter goes down and the backup takes twenty
    // carries a week, his ten-game record is mostly games from a different
    // job: Emanuel Wilson had 3 and 9 carries before 21, 21 and 20, and the
    // ten-game view would not offer him a line at all. So if his usage over
    // the games since it jumped (at least three) runs at 1.6 times or more
    // what it was before, he is judged on those games alone, and tagged.
    let role = null;
    if (uStat) {
      const allU = rs.map(r => (r.stats || {})[uStat] ?? 0);
      for (let k = Math.min(6, allU.length - 1); k >= 3; k--) {
        const recent = allU.slice(-k), before = allU.slice(-k - 6, -k);
        // Two games of the old job to compare against, or one if the new
        // job has already lasted four.
        if (before.length < (k >= 4 ? 1 : 2)) continue;
        const mr = recent.reduce((a, b) => a + b, 0) / k;
        const mb = before.reduce((a, b) => a + b, 0) / before.length;
        // One quiet game is allowed inside the new role (Wilson's 9 carries
        // between two 21s), but not the most recent one.
        const kept = recent.filter(x => x >= mb * 1.3).length;
        if (kept >= k - 1 && recent[k - 1] >= mb * 1.3 && mr >= Math.max(1, mb) * 1.6) {
          role = { games: k, recent: mr, before: mb };
          v = rs.slice(-k).map(r => r.stats[stat] * scale);
          u = rs.slice(-k).map(r => (r.stats || {})[uStat] ?? null);
          break;
        }
      }
    }
    return { name, v, u, role, avg: v.reduce((a, b) => a + b, 0) / v.length, scaled: scale !== 1 };
  }).filter(p => p.v.length >= 5 || (p.role && p.v.length >= 3)).sort((a, b) => b.avg - a.avg)
    .slice(0, count || (pos === "QB" ? 1 : 2));
}

/* The line to take for one player against one defence. Over a soft defence:
   the HIGHEST ladder rung he has cleared 7 times in 10 or more, provided his
   average scaled by how generous the defence is still clears it. Against a
   tough one: the same test, but the defence has to leave room, so this is
   usually a lower rung or nothing at all. */
function defLine(p, stat, factor, minRate) {
  const ladder = DEF_LADDER[stat] || [];
  const need = minRate || 0.7;
  let best = null;
  for (const L of ladder) {
    const k = p.v.filter(x => x >= L).length;
    const proj = p.avg * factor;
    if (k / p.v.length >= need && proj >= L * (need < 0.7 ? 1 : 1.1)) best = { line: L, k, n: p.v.length, proj };
  }
  return best;
}

const statWordNfl = s => ({ "Receiving receptions": "receptions", "Defensive combine tackles": "tackles",
  "Defensive assist tackles": "assisted tackles", "Defensive sacks": "sacks" }[s] || s.toLowerCase());
const fmtN = x => x.toFixed(x < 10 ? 1 : 0);

/* The quarterback banner, plus anyone who matters on the injury report. */
function nflStatusHtml() {
  const teams = DATA.teams;
  const parts = [];
  [0, 1].forEach(t => {
    const q = qbChange(t);
    if (q) {
      const to = q.to ? `<b>${escapeHtml(q.to)}</b> expected to start${q.toStarts ? ` (${q.toStarts} start${q.toStarts === 1 ? "" : "s"} on record)` : " (no starts on record)"}`
                      : `backup with no record expected to start`;
      parts.push(`<div class="nfl-qb"><span class="lu-dot lu-dot${t}"></span><div>
        <b>QB change, ${escapeHtml(teams[t].name)}:</b> ${escapeHtml(q.from)} ${escapeHtml(q.reason || "out")}. ${to}.
        <span class="lu-muted">Receiver lines scaled &times;${(q.yds || 1).toFixed(2)} on yards and &times;${(q.rec || 1).toFixed(2)} on receptions.
        Source: ${escapeHtml(q.source || "injury report")}.</span></div></div>`);
    }
  });
  // Skill players and regular defenders only: a list of every practice-squad
  // tight end is noise.
  const regular = t => {
    const c = new Map();
    ((DATA.players || [])[t] || []).forEach(r => c.set(r.player, (c.get(r.player) || 0) + 1));
    return c;
  };
  const lines = [0, 1].map(t => {
    const seen = regular(t);
    const out = nflInjuries(t).filter(x => (seen.get(x[0]) || 0) >= 3 && (NFL_OUT.test(x[2] || "") || /^questionable/i.test(x[2] || "")));
    if (!out.length) return "";
    return `<div class="nfl-inj"><span class="lu-dot lu-dot${t}"></span><span>${out.slice(0, 8).map(x =>
      `${escapeHtml(x[0])} <span class="lu-muted">${escapeHtml(x[1] || "")}</span> <b class="${NFL_OUT.test(x[2]) ? "lu-lo" : "lu-mid"}">${escapeHtml(x[2])}</b>`).join(" &middot; ")}</span></div>`;
  }).join("");
  const when = (DATA.injuries || {}).fetched;
  return parts.join("") + (lines ? `<div class="lu-card nfl-injcard"><div class="lu-who"><b>Injury report</b>
      <span class="lu-muted">${when ? "ESPN, " + escapeHtml(when) + ". " : ""}Out, doubtful and IR are left out of every pick below.</span></div>${lines}</div>` : "");
}

/* The Defences tab on basketball pages. Same measure as gridiron: per
   defence and position, what that position produced against them over its
   own usual (1.15x = 15% more than normal), ranked across every defence in
   the file. Then each player's last ten scaled by that, against Paddy
   Power's main line where there is one. */
const BB_DEF_STATS = ["Points", "Rebounds", "Assists", "Three pointers made", "Points rebounds and assists"];
const BB_DEF_POS = { BBG: "Guards", BBF: "Forwards", BBC: "Centres" };
const BB_STAT_WORD = { "Points": "points", "Rebounds": "rebounds", "Assists": "assists",
  "Three pointers made": "threes", "Points rebounds and assists": "PRA" };

function bbPosGroup(pos) {
  return Object.keys(BB_DEF_POS).find(g => DEF_GROUPS[g].includes(pos)) || null;
}

function basketballDefenceHtml() {
  const teams = DATA.teams;
  const rankWord = r => {
    const share = (r.place - 1) / Math.max(1, r.of - 1);
    return share <= 0.5 ? `${r.place}${ordinal(r.place)} softest` : `${r.of - r.place + 1}${ordinal(r.of - r.place + 1)} toughest`;
  };
  const defCard = d => {
    const rows = Object.keys(BB_DEF_POS).flatMap(pos => BB_DEF_STATS.map(stat => {
      const r = defRow(teams[d].id, pos, stat);
      if (!r || !r.vsUsual) return "";
      const soft = 1 - (r.place - 1) / Math.max(1, r.of - 1);
      const cls = soft >= 0.66 ? "def-soft" : soft <= 0.34 ? "def-tough" : "";
      const recent = r.recent ? ` &middot; last ${DEF_RECENT}: ${r.recent.toFixed(2)}&times;` : "";
      return `<div class="def-row ${cls}">
        <div class="def-row-top"><span>${BB_DEF_POS[pos]} &middot; ${BB_STAT_WORD[stat]}</span><b>${rankWord(r)}</b></div>
        <i class="def-bar"><em style="width:${Math.round(soft * 100)}%"></em></i>
        <div class="def-sub">${r.vsUsual.toFixed(2)}&times; usual &middot; ${fmtN(r.perGame)}/game${recent}</div>
      </div>`;
    })).join("");
    return `<div class="lu-card"><div class="lu-who"><span class="lu-dot lu-dot${d}"></span><b>${escapeHtml(teams[d].name)} defence</b>
      <span class="lu-muted">longer bar = softer</span></div>${rows || `<p class="note">Not enough games against this defence in the file yet.</p>`}</div>`;
  };

  // Players: last ten scaled by the defence, against the main line.
  const picks = [];
  [0, 1].forEach(t => {
    const d = 1 - t;
    squadPlayers(t).forEach((played, name) => {
      const apps = gatedApps(played);
      if (apps.length < 5) return;
      if (INJ_OUT.test(injuryOf(t, name) || "")) return;
      const pos = bbPosGroup(played[played.length - 1].position || "");
      if (!pos) return;
      const recent = apps.slice(-10);
      BB_DEF_STATS.forEach(stat => {
        const r = defRow(teams[d].id, pos, stat);
        if (!r || !r.vsUsual) return;
        const vals = recent.map(g => (g.stats || {})[stat]).filter(v => v !== undefined && v !== null);
        if (vals.length < 5) return;
        const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
        if (avg < 1) return;
        const factor = Math.min(1.25, Math.max(0.8, r.vsUsual));
        const proj = avg * factor;
        const main = ppLines(name, "pp").filter(x => x.stat === stat && x.over && /^Over/.test(x.label));
        const line = main.length ? main.reduce((a, b) => Math.abs(b.price - 1.9) < Math.abs(a.price - 1.9) ? b : a) : null;
        const gap = line ? (proj - line.line) / Math.max(1, line.line) : null;
        picks.push({ t, name, pos, stat, r, avg, proj, factor, line, gap,
          hits: line ? vals.filter(v => v > line.line).length : null, n: vals.length });
      });
    });
  });
  const withLine = picks.filter(x => x.line && Math.abs(x.gap) >= 0.08 && Math.abs(x.factor - 1) >= 0.05
    && Math.sign(x.gap) === Math.sign(x.factor - 1));
  withLine.sort((a, b) => Math.abs(b.gap) - Math.abs(a.gap));
  const pick = x => `<div class="def-pick">
      <div class="def-pick-main"><span class="lu-dot lu-dot${x.t}"></span>
        <b>${escapeHtml(x.name)}</b> ${x.gap > 0 ? "over" : "under"} ${x.line.line} ${BB_STAT_WORD[x.stat]}
        <span class="lu-muted">&middot; Paddy ${fmtOdds(x.line.price)} for the over &middot; ${x.hits}/${x.n} over it last ${x.n}</span></div>
      <div class="def-sub">avg ${fmtN(x.avg)}, ${x.factor.toFixed(2)}&times; v ${escapeHtml(DATA.teams[1 - x.t].name)} (${rankWord(x.r)} v ${BB_DEF_POS[x.pos].toLowerCase()}) = <b>${fmtN(x.proj)}</b></div>
    </div>`;
  const stale = DATA.fixture && (DATA.fixture.staleDays || 0) > 60
    ? `<p class="note"><b>Early-season numbers.</b> These defences are measured on last season's games, playoffs included, and rosters have changed since. Treat the rankings as a rough guide until a few weeks of this season are in.</p>` : "";
  return `${stale}
    <h3 class="lu-h">Lines the matchup points to</h3>
    ${withLine.length ? `<div class="lu-card">${withLine.slice(0, 10).map(pick).join("")}</div>`
      : `<div class="lu-card lu-empty">No Paddy Power line in this game sits far enough from what the matchup says.${(fixtureMarket() || {}).pp ? "" : " (No Paddy Power prices for this game yet.)"}</div>`}
    <div class="def-grid">${defCard(1)}${defCard(0)}</div>
    <details class="lu-more"><summary>How this is worked out</summary><p class="note">
      For each defence and position (guards, forwards, centres), every game's total for that position is divided by
      what the same offence usually gets from it in its other games, then averaged: 1.15&times; means opponents get 15%
      more than normal. That takes the schedule out. A player's last ten is scaled by it (held between 0.8 and 1.25)
      and set against Paddy Power's main line; only gaps of 8% or more, pointing the same way as the matchup, are listed.
      Not backtested: a guide to where to look, not a price.</p></details>`;
}

function defenceView(el) {
  if (SPORT === "basketball") { el.innerHTML = basketballDefenceHtml(); return; }
  const teams = DATA.teams;
  const status = (DATA.lineups || {}).confirmed
    ? `<span class="lu-badge lu-conf">Inactives applied</span>`
    : `<span class="lu-badge">Inactives not out yet</span>`;
  const toggle = `<div class="seg lu-seg">` + [["offence", "QBs &amp; receivers"], ["defence", "Tackles &amp; sacks"]].map(([m, l]) =>
    `<button type="button" data-defmode="${m}" aria-pressed="${m === defMode}">${l}</button>`).join("") + `</div>`;
  const head = `<div class="lu-head">${toggle}${status}<span class="lu-muted">Picks update about 90 minutes before kick-off, when the actives are confirmed.</span></div>`
    + nflStatusHtml();
  el.innerHTML = head + (defMode === "defence" ? defensivePropsHtml() : offencePropsHtml());
}

function offencePropsHtml() {
  const teams = DATA.teams;
  const picks = [], fades = [];
  DEF_ROWS.forEach(([pos, stat]) => [0, 1].forEach(d => {
    const r = defRow(teams[d].id, pos, stat);
    if (!r || !r.vsUsual) return;
    const share = (r.place - 1) / Math.max(1, r.of - 1);
    const top = defTopMan(teams[d].id, pos, stat);
    defPlayers(1 - d, pos, stat).forEach((p, rank) => {
      // Every featured player gets a line now, not only those facing the
      // softest third. The lead man is scaled by what lead men get against
      // this defence (top), the second by the position as a whole; both by
      // whether his role is growing.
      const factor = rank === 0 && top ? top.ratio : r.vsUsual;
      const usage = usageTrend(p, stat);
      const adj = factor * (usage ? usage.adj : 1);
      const item = { p, r, pos, stat, d, share, top: rank === 0 ? top : null, usage, factor: adj,
                     missing: defMissing(d, pos) };
      const l = defLine(p, stat, adj);
      const beaten = top && top.ratio >= 0.95;
      if (l && (share < 0.66 || beaten)) {
        picks.push({ ...item, l, tier: share <= 0.34 ? "soft" : share < 0.66 ? "fair" : "tough",
                     score: (l.k / l.n) * adj });
      } else if (share >= 0.66 && !beaten && p.avg >= (DEF_LADDER[stat] || [0])[0]) {
        // Only players with a real role: a backup averaging 15 yards is not
        // a line anyone is choosing whether to take.
        fades.push(item);
      }
    });
  }));
  picks.sort((a, b) => b.score - a.score);
  fades.sort((a, b) => b.share - a.share);

  const rankWord = r => {
    const share = (r.place - 1) / Math.max(1, r.of - 1);
    return share <= 0.5 ? `${r.place}${ordinal(r.place)} softest` : `${r.of - r.place + 1}${ordinal(r.of - r.place + 1)} toughest`;
  };
  const qbTag = p => p.scaled ? ` <span class="nfl-tag">QB-adjusted</span>` : "";

  const tierTag = x => x.tier === "tough"
    ? ` <span class="nfl-tag">tough D, top men still score</span>`
    : x.tier === "fair" ? ` <span class="nfl-tag">middling D</span>` : "";
  const pickCard = x => `<div class="def-pick">
      <div class="def-pick-main"><span class="lu-dot lu-dot${1 - x.d}"></span>
        <b>${escapeHtml(x.p.name)}</b> <span class="def-line">${x.l.line}+ ${statWordNfl(x.stat)}</span>${qbTag(x.p)}${tierTag(x)}${x.p.role ? ` <span class="nfl-tag">new role: last ${x.p.role.games} games</span>` : ""}</div>
      <div class="def-pick-why">
        <span><b class="lu-hi">${x.l.k}/${x.l.n}</b> his last ${x.l.n}</span>
        <span>avg ${fmtN(x.p.avg)} &rarr; <b>${fmtN(x.l.proj)}</b> v this D</span>
        <span>${escapeHtml(teams[x.d].name)}: <b class="${x.tier === "tough" ? "lu-mid" : "lu-hi"}">${rankWord(x.r)}</b> v ${DEF_POS[x.pos]}, ${x.r.vsUsual.toFixed(2)}&times; usual</span>
        ${x.top ? `<span>lead ${DEF_POS[x.pos]} v them: <b>${x.top.ratio.toFixed(2)}&times;</b> their own usual${x.top.best ? `, best ${escapeHtml(x.top.best.player)} ${fmtN(x.top.best.v)} (usual ${fmtN(x.top.best.usual)})` : ""}</span>` : ""}
        ${x.p.role ? `<span>${DEF_USAGE[x.stat] === "Rushing attempts" ? "carries" : "targets"} <b class="lu-hi">${fmtN(x.p.role.recent)}</b> a game since the jump, ${fmtN(x.p.role.before)} before</span>` : ""}
        ${x.missing && x.missing.length ? `<span><b class="lu-hi">${escapeHtml(teams[x.d].name)} without ${x.missing.map(escapeHtml).join(", ")}</b>, not in the ranking</span>` : ""}
        ${x.usage ? `<span>${x.usage.word} ${fmtN(x.usage.recent)} last 3 v ${fmtN(x.usage.all)}${x.usage.adj > 1.03 ? ` <b class="lu-hi">&#9650;</b>` : x.usage.adj < 0.97 ? ` <b class="lu-lo">&#9660;</b>` : ""}</span>` : ""}
      </div></div>`;
  const fadeLine = x => `<div class="def-fade"><span class="lu-dot lu-dot${1 - x.d}"></span>
      <b>${escapeHtml(x.p.name)}</b> ${statWordNfl(x.stat)}${qbTag(x.p)} <span class="lu-muted">&middot; ${escapeHtml(teams[x.d].name)} ${rankWord(x.r)} v ${DEF_POS[x.pos]}, ${x.r.vsUsual.toFixed(2)}&times; usual &middot; avg ${fmtN(x.p.avg)}</span></div>`;

  // One card per defence: each market as a bar, full = softest in the file.
  const defCard = d => {
    const rows = DEF_ROWS.map(([pos, stat]) => {
      const r = defRow(teams[d].id, pos, stat);
      if (!r || !r.vsUsual) return "";
      const soft = 1 - (r.place - 1) / Math.max(1, r.of - 1);
      const cls = soft >= 0.66 ? "def-soft" : soft <= 0.34 ? "def-tough" : "";
      const jump = r.recentPlace ? r.place - r.recentPlace : 0;
      const big = Math.max(4, Math.round(r.of / 4));
      const trend = jump >= big ? `<span class="def-up">&#9650; leaking</span>` : -jump >= big ? `<span class="def-down">&#9660; tighter</span>` : "";
      return `<div class="def-row ${cls}">
        <div class="def-row-top"><span>${DEF_POS[pos]} &middot; ${statWordNfl(stat)}</span><b>${rankWord(r)}</b></div>
        <i class="def-bar"><em style="width:${Math.round(soft * 100)}%"></em></i>
        <div class="def-sub">${r.vsUsual.toFixed(2)}&times; usual &middot; ${fmtN(r.perGame)}/game &middot; lead ${fmtN(r.lead)} ${trend}</div>
      </div>`;
    }).join("");
    return `<div class="lu-card"><div class="lu-who"><span class="lu-dot lu-dot${d}"></span><b>${escapeHtml(teams[d].name)} defence</b>
      <span class="lu-muted">longer bar = softer</span></div>${rows}</div>`;
  };

  return `
    <h3 class="lu-h">Best lines v these defences</h3>
    ${picks.length ? `<div class="lu-card">${picks.slice(0, 8).map(pickCard).join("")}</div>`
      : `<div class="lu-card lu-empty">No player in this game whose record, role and matchup back a line.</div>`}
    ${fades.length ? `<h3 class="lu-h">Tough matchups that even top players struggle against: lower your line or avoid</h3><div class="lu-card">${fades.slice(0, 5).map(fadeLine).join("")}</div>` : ""}
    <div class="def-grid">${defCard(1)}${defCard(0)}</div>
    <details class="lu-more"><summary>How this is worked out</summary><p class="note">
      <b>vs usual</b>: what offences get from that position against this defence, divided by what the same offences
      get everywhere else, so a soft schedule does not flatter it. <b>lead v them</b>: what the best man at the
      position got against this defence, against his own average, because a defence can rank tough on everyone
      and still concede to a genuinely good player. <b>Best lines</b> take the highest ladder rung a player has
      cleared 7 times in his last 10, where his average, scaled by the defence (the lead-man figure for the lead
      man) and by his usage trend (targets or carries, last 3 v last 10, at most 15% either way), still clears it
      by 10%. Tough defences only make the list when their lead-man figure is 0.95 or better. <b>New role</b>: a
      player whose targets or carries jumped to 1.6 times what they were (every game since at 1.3 times or more
      bar one, the latest included, at least three games) is judged on those games only. <b>Without</b>: defenders on the injury report as out at
      positions that cover this one; the ranking was built with them, so it flatters the defence.
      <b>lead</b> is the top player at the position each game. &#9650;/&#9660; mark a defence whose last
      ${DEF_RECENT} games rank a long way from its season. <b>QB-adjusted</b> means the starting quarterback has
      changed, so the receiver's games are rescaled to the new man's passing before anything is counted.</p></details>`;
}

/* Tackles and sacks. The defender's own record, scaled by how generous the
   offence he faces is to his position group. */
function defensivePropsHtml() {
  const teams = DATA.teams;
  const picks = [], fades = [];
  DEFP_ROWS.forEach(([pos, stat]) => [0, 1].forEach(o => {
    // o is the OFFENCE; the defenders are on the other side.
    const r = defRow(teams[o].id, pos, stat);
    if (!r || !r.vsUsual) return;
    const share = (r.place - 1) / Math.max(1, r.of - 1);   // 0 = most generous
    defPlayers(1 - o, pos, stat, 3).forEach(p => {
      const item = { p, r, pos, stat, o, share };
      const l = defLine(p, stat, r.vsUsual, DEFP_RATE[stat]);
      if (l && share <= 0.5) picks.push({ ...item, l, score: (l.k / l.n) * r.vsUsual });
      else if (share >= 0.66 && p.avg >= (DEF_LADDER[stat] || [0])[0]) fades.push(item);
    });
  }));
  // One line per player: his best market, not tackles and assists twice over.
  const bestPer = new Map();
  picks.sort((a, b) => b.score - a.score).forEach(x => {
    const k = x.p.name + "|" + x.stat;
    if (!bestPer.has(k)) bestPer.set(k, x);
  });
  const top = [...bestPer.values()];
  const tackles = top.filter(x => x.stat !== "Defensive sacks");
  const sacks = top.filter(x => x.stat === "Defensive sacks");
  fades.sort((a, b) => b.share - a.share);

  const rankWord = r => {
    const share = (r.place - 1) / Math.max(1, r.of - 1);
    return share <= 0.5 ? `${r.place}${ordinal(r.place)} most generous` : `${r.of - r.place + 1}${ordinal(r.of - r.place + 1)} stingiest`;
  };
  const pickCard = x => `<div class="def-pick">
      <div class="def-pick-main"><span class="lu-dot lu-dot${1 - x.o}"></span>
        <b>${escapeHtml(x.p.name)}</b> <span class="def-line">${x.l.line}+ ${statWordNfl(x.stat)}</span>
        <span class="lu-muted">${escapeHtml(DEF_POS[x.pos])}</span></div>
      <div class="def-pick-why">
        <span><b class="lu-hi">${x.l.k}/${x.l.n}</b> his last ${x.l.n}</span>
        <span>avg ${x.p.avg.toFixed(1)} &rarr; <b>${x.l.proj.toFixed(1)}</b> v this offence</span>
        <span>${escapeHtml(teams[x.o].name)}: <b class="lu-hi">${rankWord(x.r)}</b> to ${DEF_POS[x.pos]}, ${x.r.vsUsual.toFixed(2)}&times; usual</span>
      </div></div>`;
  const fadeLine = x => `<div class="def-fade"><span class="lu-dot lu-dot${1 - x.o}"></span>
      <b>${escapeHtml(x.p.name)}</b> ${statWordNfl(x.stat)} <span class="lu-muted">&middot; ${escapeHtml(teams[x.o].name)} ${rankWord(x.r)} to ${DEF_POS[x.pos]}, ${x.r.vsUsual.toFixed(2)}&times; usual &middot; avg ${x.p.avg.toFixed(1)}</span></div>`;

  const offCard = o => {
    const rows = DEFP_ROWS.map(([pos, stat]) => {
      const r = defRow(teams[o].id, pos, stat);
      if (!r || !r.vsUsual) return "";
      const soft = 1 - (r.place - 1) / Math.max(1, r.of - 1);
      const cls = soft >= 0.66 ? "def-soft" : soft <= 0.34 ? "def-tough" : "";
      return `<div class="def-row ${cls}">
        <div class="def-row-top"><span>${DEF_POS[pos]} &middot; ${statWordNfl(stat)}</span><b>${rankWord(r)}</b></div>
        <i class="def-bar"><em style="width:${Math.round(soft * 100)}%"></em></i>
        <div class="def-sub">${r.vsUsual.toFixed(2)}&times; usual &middot; ${r.perGame.toFixed(1)}/game to the group &middot; top man ${r.lead.toFixed(1)}</div>
      </div>`;
    }).join("");
    return `<div class="lu-card"><div class="lu-who"><span class="lu-dot lu-dot${o}"></span><b>${escapeHtml(teams[o].name)} offence</b>
      <span class="lu-muted">longer bar = gives up more</span></div>${rows}</div>`;
  };

  const list = (xs, empty) => xs.length
    ? `<div class="lu-card">${xs.slice(0, 6).map(pickCard).join("")}</div>`
    : `<div class="lu-card lu-empty">${empty}</div>`;
  return `
    <h3 class="lu-h">Tackles v these offences</h3>
    ${list(tackles, "No defender whose record backs a tackle line against a generous offence here.")}
    <h3 class="lu-h">Sacks</h3>
    ${list(sacks, "No pass rusher with a sack in half his games against an offence that gives them up.")}
    ${fades.length ? `<h3 class="lu-h">Stingy offences: lower your line or avoid</h3><div class="lu-card">${fades.slice(0, 5).map(fadeLine).join("")}</div>` : ""}
    <div class="def-grid">${offCard(1)}${offCard(0)}</div>
    <details class="lu-more"><summary>How this is worked out</summary><p class="note">
      <b>vs usual</b>: what a position group (linebackers, defensive backs, the defensive line) makes against this offence,
      divided by what the same defenders make against everyone else. Offences that run a lot of plays give up more
      tackles; offences with a leaky line give up more sacks. <b>Tackles</b> are combined (solo plus assisted).
      A tackle line is the highest rung he has cleared 7 times in his last 10, where his average scaled by the offence
      still clears it by 10%. A sack line needs a sack in half his games and the scaled average to reach the line.
      Groups: D-line is DE, DT and NT; DBs are corners and safeties.</p></details>`;
}

/* ---------------------------------------------------------------- line-ups */
/* The Line-ups tab. Predicted XI days out, the confirmed one about an hour
   before kick-off, both from SofaScore. Click a player for his record and the
   man directly opposite him: a full-back who fouls once a game against a
   winger who is fouled once a game is the pairing the tab exists to find.
   Pairing is by formation and the order SofaScore lists players in (each
   line right to left), so it is a good guess, not tracking data. */
let lineupMode = null;
let lineupPick = null;          // {team: 0|1, name}
const LU_ROWS = [["Shots", 1], ["Shots", 2], ["Shots on target", 1],
                 ["Fouls", 1], ["Fouled", 1], ["Fouled", 2], ["Tackles", 1], ["Tackles", 2]];

function luRecords(t, name) {
  return ((DATA.players || [])[t] || [])
    .filter(r => r.player === name && !r.former_club && (r.minutes || 0) >= 45)
    .sort((a, b) => (a.date < b.date ? -1 : 1)).slice(-10);
}
function luRate(recs, stat, line) {
  const v = recs.map(r => (r.stats || {})[stat] ?? 0);
  const k = v.filter(x => x >= line).length;
  return { k, n: v.length, p: v.length ? k / v.length : null,
           avg: v.length ? v.reduce((a, b) => a + b, 0) / v.length : null };
}
function luShape(side) {
  const out = (side.xi || []).filter(p => p.pos !== "G");
  const gk = (side.xi || []).filter(p => p.pos === "G");
  let sizes = String(side.formation || "").split("-").map(Number).filter(n => n > 0);
  if (sizes.reduce((a, b) => a + b, 0) !== out.length) {
    sizes = ["D", "M", "F"].map(c => out.filter(p => p.pos === c).length).filter(n => n);
  }
  const lines = [];
  let i = 0;
  for (const s of sizes) { lines.push(out.slice(i, i + s)); i += s; }
  lines.forEach((ln, li) => ln.forEach((p, j) => {
    p.depth = lines.length > 1 ? li / (lines.length - 1) : 0.5;   // 0 back line, 1 front line
    p.lat = ln.length > 1 ? j / (ln.length - 1) : 0.5;            // 0 right, 1 left
    p.line = li;
  }));
  return { gk, lines };
}
/* The man (or two) directly opposite. Attackers face the back line, the back
   line faces the attackers, midfield faces the mirrored midfield line. A
   right-sided player faces the opponent's left side, hence 1 - lat. */
function luOpponents(p, oppShape) {
  const L = oppShape.lines;
  if (!L.length) return [];
  let pool;
  // Strictly past halfway: in a 4-3-3 the midfield three sit at exactly 0.5
  // and face the other midfield, not the centre-backs.
  if (p.line === 0) {
    pool = L.filter((ln, i) => i > 0 && ln[0].depth > 0.5).flat();
    if (!pool.length) pool = L[L.length - 1];
  }
  else if (p.depth > 0.5) pool = L[0];
  else {
    const want = 1 - p.depth;
    pool = L.reduce((best, ln) =>
      Math.abs(ln[0].depth - want) < Math.abs(best[0].depth - want) ? ln : best, L[0]);
  }
  if (!pool || !pool.length) return [];
  const target = 1 - p.lat;
  const d = q => Math.abs(q.lat - target);
  const best = Math.min(...pool.map(d));
  return pool.filter(q => d(q) <= best + 0.1).slice(0, 2);
}
function luPct(r) {
  if (!r || !r.n) return `<span class="lu-muted">no record</span>`;
  const cls = r.p >= 0.8 ? "lu-hi" : r.p >= 0.6 ? "lu-mid" : "lu-lo";
  return `<b class="${cls}">${r.k}/${r.n}</b>`;
}
function luSurname(n) {
  const parts = String(n || "").split(" ");
  const keep = ["de", "van", "von", "da", "di", "dos", "del", "der", "le", "la", "el", "ter", "ten"];
  let i = parts.length - 1;
  while (i > 0 && keep.includes(parts[i - 1].toLowerCase())) i--;
  return parts.slice(i).join(" ");
}

/* Every facing pair, scored on the two foul markets that are a matchup by
   nature: one man's fouls are literally the other man's fouls won. */
function luPairs(shapes) {
  const out = [];
  for (const t of [0, 1]) {
    const mine = shapes[t], theirs = shapes[1 - t];
    for (const p of mine.lines.flat()) {
      for (const o of luOpponents(p, theirs)) {
        const pr = luRecords(t, p.name), or = luRecords(1 - t, o.name);
        if (pr.length < 5 || or.length < 5) continue;
        const a = luRate(pr, "Fouled", 1), b = luRate(or, "Fouls", 1);
        out.push({ score: Math.min(a.p, b.p), t, p: p.name, o: o.name,
                   text: luVs(p.name, "fouled", a, o.name, "fouls", b) });
      }
    }
  }
  const seen = new Set();
  return out.sort((x, y) => y.score - x.score)
    .filter(x => { const k = x.p + "|" + x.o; if (seen.has(k)) return false; seen.add(k); return true; });
}

/* ------------------------------------------------------ game state */
/* What kind of game this is going to be, and what that does to each
   player's numbers. A midfielder who averages two tackles got them in games
   where his side had about its usual share of the ball. Put the same side at
   home to a team that will sit in, and he spends the afternoon in possession
   and makes fewer; put them away at the champions and he makes more.

   Two estimates of the game, blended:

     fitted    the team projection already on the page: each side's attack
               rating times the other's defence rating, per stat. It knows
               who is strong and who is weak, so it carries team level.
     ball      expected possession, from each side's average share of the
               ball combined head to head (log5), with a small home tilt.
               With the ball you shoot and get fouled; without it you
               tackle and foul.

   For each player and market: his average over his last ten starts, times
   (what his team is projected to do here / what it did in those same ten
   games), with the two factors averaged geometrically. The line is read off
   a Poisson on that adjusted average, and his raw record has to agree. */
let gsSection = "fouls";
const GS_SECTIONS = [["fouls", "Fouls"], ["shots", "Shots"], ["tackles", "Tackles"]];
const GS_MARKETS = {
  fouls: [["Fouls", [1, 2, 3], "fouls"], ["Fouled", [1, 2, 3], "fouled"]],
  shots: [["Shots", [1, 2, 3, 4], "shots"], ["Shots on target", [1, 2], "on target"]],
  tackles: [["Tackles", [1, 2, 3, 4], "tackles"]],
};
/* The team stat each player stat is a share of, which side's projection it
   reads, and whether having the ball pushes it up (+1) or down (-1). */
const GS_TEAM = {
  "Shots":           { stat: "Total shots",     side: "for",     ball: +1 },
  "Shots on target": { stat: "Shots on target", side: "for",     ball: +1 },
  "Fouls":           { stat: "Fouls",           side: "for",     ball: -1 },
  "Fouled":          { stat: "Fouls",           side: "against", ball: +1 },
  "Tackles":         { stat: "Tackles",         side: "for",     ball: -1 },
};
const GS_MIN_MODEL = 0.6;    // the adjusted chance a line has to reach
const GS_MIN_RECORD = 0.5;   // and his shrunk record has to agree this far
let GS_CACHE = null;

const gsAvg = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
const gsVal = (rec, side, stat) => {
  const block = side === "for" ? (rec.stats || {}).ALL : (rec.against || {}).ALL;
  const v = (block || {})[stat];
  return v === undefined || v === null ? null : v;
};

function gsState() {
  if (GS_CACHE && GS_CACHE.id === DATA.fixture.id) return GS_CACHE;
  const team = t => {
    const recs = ((DATA.records || [])[t] || []).filter(r => !r.club).slice(-10);
    const pick = (side, stat) => gsAvg(recs.map(r => gsVal(r, side, stat)).filter(v => v !== null));
    return { n: recs.length, poss: pick("for", "Ball possession"),
             xg: pick("for", "Expected goals"), xga: pick("against", "Expected goals"),
             byMatch: new Map(((DATA.records || [])[t] || []).map(r => [r.id, r])) };
  };
  const teams = [team(0), team(1)];
  let poss = [50, 50];
  if (teams[0].poss && teams[1].poss) {
    const lg = p => Math.log(p / (1 - p));
    const h = Math.min(0.85, Math.max(0.15, teams[0].poss / 100));
    const a = Math.min(0.85, Math.max(0.15, teams[1].poss / 100));
    // Shrunk a little: two averages over ten games each overstate the gap.
    const lo = 0.85 * (lg(h) - lg(a)) + 0.06;
    const p0 = 100 / (1 + Math.exp(-lo));
    poss = [p0, 100 - p0];
  }
  const proj = ((DATA.projection || {}).ALL) || {};
  const tierMap = ((DATA.tiers || {}).map) || {};
  const tierLab = ((DATA.tiers || {}).labels) || {};
  const tiers = DATA.teams.map(t => tierLab[tierMap[String(t.id)]] || null);
  GS_CACHE = { id: DATA.fixture.id, teams, poss, proj, tiers };
  return GS_CACHE;
}

/* The game-state multiplier for one player's market, measured against the
   games his own average came from rather than a season figure, so a player
   who only started the easy ones is compared with the easy ones. */
function gsFactor(t, stat, recs) {
  const st = gsState();
  const def = GS_TEAM[stat];
  const games = recs.map(r => st.teams[t].byMatch.get(r.match_id)).filter(Boolean);
  const usual = gsAvg(games.map(g => gsVal(g, def.side, def.stat)).filter(v => v !== null));
  const usualPoss = gsAvg(games.map(g => gsVal(g, "for", "Ball possession")).filter(v => v !== null));
  const projRow = st.proj[def.stat];
  const projTeam = projRow ? projRow[def.side === "for" ? t : 1 - t] : null;
  const mf = projTeam && usual ? projTeam / usual : null;
  let pf = null;
  if (usualPoss && st.teams[0].poss && st.teams[1].poss) {
    const here = st.poss[t];
    pf = def.ball > 0 ? here / usualPoss : (100 - here) / (100 - usualPoss);
  }
  let f = mf && pf ? Math.sqrt(mf * pf) : (mf || pf || 1);
  f = Math.min(1.6, Math.max(0.6, f));
  return { f, mf, pf, usual, projTeam };
}

function gsPoisAtLeast(mu, k) {
  let term = Math.exp(-mu), cdf = 0;
  for (let i = 0; i < k; i++) { cdf += term; term *= mu / (i + 1); }
  return Math.max(0, 1 - cdf);
}

/* Who to price: the XI if there is one, otherwise the men who started most
   of the last five, so the tab still works days out. */
function gsSquads() {
  const store = DATA.lineups || {};
  const lu = store.confirmed || store.predicted;
  if (lu) {
    return { source: store.confirmed ? "confirmed XI" : "predicted XI",
             sides: [lu.home, lu.away].map(s => (s.xi || []).filter(p => p.pos !== "G").map(p => p.name)) };
  }
  const sides = [0, 1].map(t => {
    const recs = (DATA.players || [])[t] || [];
    const ids = [...new Set(recs.map(r => r.match_id))];
    const dates = new Map(recs.map(r => [r.match_id, r.date]));
    const last5 = new Set(ids.sort((a, b) => (dates.get(a) < dates.get(b) ? 1 : -1)).slice(0, 5));
    const starts = new Map();
    recs.forEach(r => {
      if (!last5.has(r.match_id) || r.former_club || r.position === "G" || (r.minutes || 0) < 45) return;
      starts.set(r.player, (starts.get(r.player) || 0) + 1);
    });
    return [...starts.entries()].filter(([, n]) => n >= 3).map(([name]) => name);
  });
  return { source: "regular starters (no line-up yet)", sides };
}

/* Every player's best line in one market, adjusted, with the reasoning. */
function gsRows(stat, lines) {
  const out = [], against = [];
  const squads = gsSquads();
  squads.sides.forEach((names, t) => names.forEach(name => {
    const recs = luRecords(t, name);
    if (recs.length < 5) return;
    const vals = recs.map(r => (r.stats || {})[stat] ?? 0);
    const avg = gsAvg(vals);
    if (!avg) return;
    const g = gsFactor(t, stat, recs);
    const mu = avg * g.f;
    let best = null;
    for (const L of lines) {
      const k = vals.filter(v => v >= L).length;
      const rec = (k + 2) / (vals.length + 4);
      // Blended with his shrunk record: the Poisson alone reads hot at short
      // lines (LESSONS.md: 90% calls land about 79%).
      const p = (gsPoisAtLeast(mu, L) + rec) / 2;
      if (p >= GS_MIN_MODEL && rec >= GS_MIN_RECORD) best = { L, k, n: vals.length, p, rec };
    }
    const row = { t, name, avg, mu, g, best };
    if (best) out.push(row);
    // Game state working against a line his record would otherwise back.
    const L1 = lines[0];
    const k1 = vals.filter(v => v >= L1).length;
    if (g.f <= 0.85 && (k1 + 2) / (vals.length + 4) >= 0.6) {
      against.push({ ...row, L: L1, k: k1, n: vals.length,
                     p: (gsPoisAtLeast(mu, L1) + (k1 + 2) / (vals.length + 4)) / 2 });
    }
  }));
  out.sort((a, b) => (b.best.p - a.best.p) || (b.best.L - a.best.L));
  against.sort((a, b) => a.g.f - b.g.f);
  return { out, against };
}

function gsArrow(f) {
  const pct = Math.round((f - 1) * 100);
  if (pct >= 8) return `<span class="gs-up">&#9650; ${pct}%</span>`;
  if (pct <= -8) return `<span class="gs-down">&#9660; ${-pct}%</span>`;
  return `<span class="lu-muted">level</span>`;
}

function gsRowHtml(x, word) {
  const why = [];
  if (x.g.mf) why.push(`team ${fmtGs(x.g.projTeam)} here v ${fmtGs(x.g.usual)} usual`);
  if (x.g.pf) why.push(`ball ${Math.round(gsState().poss[x.t])}%`);
  return `<div class="def-pick">
    <div class="def-pick-main"><span class="lu-dot lu-dot${x.t}"></span>
      <b>${escapeHtml(x.name)}</b> <span class="def-line">${x.best.L}+ ${word}</span>
      <span class="gs-p">${Math.round(x.best.p * 100)}%</span></div>
    <div class="def-pick-why">
      <span><b class="lu-hi">${x.best.k}/${x.best.n}</b> his last ${x.best.n}</span>
      <span>avg ${x.avg.toFixed(1)} &rarr; <b>${x.mu.toFixed(1)}</b> here ${gsArrow(x.g.f)}</span>
      <span>${why.join(" &middot; ")}</span>
    </div></div>`;
}
const fmtGs = v => v == null ? "&ndash;" : v.toFixed(v < 10 ? 1 : 0);

function gsAgainstHtml(xs, word) {
  if (!xs.length) return "";
  return `<details class="lu-more"><summary>Game state works against (${xs.length})</summary>
    <div class="lu-card">${xs.slice(0, 5).map(x => `<div class="def-fade"><span class="lu-dot lu-dot${x.t}"></span>
      <b>${escapeHtml(x.name)}</b> ${x.L}+ ${word} <span class="lu-muted">&middot; ${x.k}/${x.n} record, but
      ${x.avg.toFixed(1)} &rarr; ${x.mu.toFixed(1)} here (${Math.round(x.p * 100)}%)</span> ${gsArrow(x.g.f)}</div>`).join("")}</div></details>`;
}

/* The card at the top: possession, level, expected volume. */
function gsCardHtml() {
  const st = gsState();
  const T = DATA.teams;
  const P = st.proj;
  const pair = (k, d) => P[k] ? `${P[k][0].toFixed(d)} v ${P[k][1].toFixed(d)}` : null;
  const p0 = Math.round(st.poss[0]);
  const hasBall = st.teams[0].poss && st.teams[1].poss;
  const dom = st.poss[0] >= st.poss[1] ? 0 : 1;
  const gap = Math.abs(st.poss[0] - 50);
  const script = !hasBall ? "No possession record for one side, so only the fitted ratings are used."
    : gap < 6 ? "Even on the ball. Player numbers move little from their usual."
    : `${escapeHtml(T[dom].name)} expected to have the ball. Their shots and fouls won go up;
       ${escapeHtml(T[1 - dom].name)}'s tackles and fouls committed go up, and the reverse for each.`;
  const vol = [["Shots", pair("Total shots", 1)], ["On target", pair("Shots on target", 1)],
               ["Goals", pair("Goals", 2)], ["Fouls", pair("Fouls", 1)], ["Tackles", pair("Tackles", 1)]]
    .filter(x => x[1]).map(x => `<div class="gs-vol"><span>${x[0]}</span><b>${x[1]}</b></div>`).join("");
  const xg = t => st.teams[t].xg != null ? `xG ${st.teams[t].xg.toFixed(2)} for, ${st.teams[t].xga.toFixed(2)} against` : "";
  const side = t => `<div class="gs-side ${t ? "gs-r" : ""}"><span class="gs-name"><span class="lu-dot lu-dot${t}"></span>
      <b>${escapeHtml(T[t].name)}</b></span>${st.tiers[t] ? `<span class="lu-muted">${escapeHtml(st.tiers[t])}</span>` : ""}
      <span class="lu-muted">${xg(t)}</span></div>`;
  return `<div class="lu-card gs-card">
    <div class="gs-teams">${side(0)}${side(1)}</div>
    ${hasBall ? `<div class="gs-poss"><b>${p0}%</b><i class="gs-bar"><em style="width:${p0}%"></em></i><b>${100 - p0}%</b></div>
      <div class="gs-caption">expected possession</div>` : ""}
    ${vol ? `<div class="gs-vols">${vol}</div>` : ""}
    <p class="gs-script">${script}</p>
  </div>`;
}

/* Fouls, Shots, Tackles: one market family at a time. */
function gsSectionHtml(shapes) {
  const seg = `<div class="seg gs-seg">` + GS_SECTIONS.map(([k, l]) =>
    `<button type="button" data-gssec="${k}" aria-pressed="${k === gsSection}">${l}</button>`).join("") + `</div>`;
  const squads = gsSquads();
  let body = "";
  if (gsSection === "fouls" && shapes) {
    const pairs = luPairs(shapes).filter(x => x.score >= 0.6).slice(0, 5);
    body += pairs.length
      ? `<h3 class="lu-h">Head-to-head foul matchups</h3><div class="lu-card lu-best">${pairs.map(x => x.text).join("")}</div>`
      : `<p class="note">No foul matchup where both sides are at 60% or better.</p>`;
  }
  GS_MARKETS[gsSection].forEach(([stat, lines, word]) => {
    const { out, against } = gsRows(stat, lines);
    const title = { Fouls: "Fouls committed", Fouled: "Fouls won", Shots: "Shots",
                    "Shots on target": "Shots on target", Tackles: "Tackles" }[stat];
    body += `<h3 class="lu-h">${title}, adjusted for this game</h3>` + (out.length
      ? `<div class="lu-card">${out.slice(0, 6).map(x => gsRowHtml(x, word)).join("")}</div>`
      : `<div class="lu-card lu-empty">Nobody reaches ${Math.round(GS_MIN_MODEL * 100)}% on this market once the game state is applied.</div>`)
      + gsAgainstHtml(against, word);
  });
  return `<div class="gs-head"><h3 class="lu-h gs-h">Player lines</h3>${seg}
      <span class="lu-muted">from the ${escapeHtml(squads.source)}</span></div>${body}
    <details class="lu-more"><summary>How this is worked out</summary><p class="note">
      Each player's average over his last ten starts (45 minutes or more) is multiplied by the game state:
      what his team is projected to do here, divided by what it did in those same ten games. Two projections are
      blended: the fitted team ratings on this page (attack times the opponent's defence, so team level is in it),
      and expected possession from both sides' average share of the ball. Shots and fouls won rise with the ball;
      tackles and fouls committed rise without it. The percentage is the average of two numbers: a Poisson chance on the
      adjusted average, and his own record pulled two games towards 50% (the Poisson alone runs hot at short lines).
      A line shows only if that reaches ${Math.round(GS_MIN_MODEL * 100)}% and his shrunk record is at least
      ${Math.round(GS_MIN_RECORD * 100)}%. &#9650;/&#9660; is the game-state change to his average.</p></details>`;
}

/* Darts: the match itself. Who wins, how many legs, by how much, the likely
   scores and the 180s, all from one number, each man's chance of winning a
   leg (darts_model.py). Fair prices are one over the chance. */
function dartsMatchView(el) {
  const m = DATA.dartsModel;
  const T = DATA.teams;
  if (!m) {
    el.innerHTML = `<div class="lu-card lu-empty">No match model for this one: one of the players has no
      results on record, or the format is not known yet.</div>`;
    return;
  }
  const pct = x => `${Math.round(x * 100)}%`;
  const fair = x => x > 0.005 ? (1 / x).toFixed(2) : "&mdash;";
  const fmt = m.format[0] === "legs" ? `first to ${m.format[1]} legs` : `first to ${m.format[1]} sets, each first to ${m.format[2]} legs`;
  const thin = Math.min(m.gamesA, m.gamesB) < 10;
  const pa = m.winA, pb = 1 - m.winA;
  const hasMkt = m.marketWinA != null;
  const fav = x => x >= 0.5 ? escapeHtml(T[0].name) : escapeHtml(T[1].name);
  const side = x => Math.round(Math.max(x, 1 - x) * 100);
  const mktLine = hasMkt
    ? `<div class="gs-vols">
        <div class="gs-vol"><span>Model</span><b>${fav(m.modelWinA)} ${side(m.modelWinA)}%</b></div>
        <div class="gs-vol"><span>Exchange</span><b>${fav(m.marketWinA)} ${side(m.marketWinA)}%</b></div>
        <div class="gs-vol"><span>Used</span><b>${fav(pa)} ${side(pa)}%</b></div></div>`
    : "";
  const flag = hasMkt && m.flag
    ? `<p class="gs-script"><b>The model and the exchange disagree by ${Math.round(Math.abs(m.modelWinA - m.marketWinA) * 100)} points.</b>
        The model rates on results alone and its favourite wins 61% of the time; the market knows more. Read the gap
        as a warning, not an edge.</p>`
    : "";
  const noMkt = !hasMkt
    ? `<p class="gs-script">No exchange price for this match, so this is the model alone. It rates on results
        only; check it against a bookmaker before trusting a big favourite.</p>`
    : "";
  const head = `<div class="lu-card gs-card">
    <div class="gs-teams">
      <div class="gs-side"><span class="gs-name"><span class="lu-dot lu-dot0"></span><b>${escapeHtml(T[0].name)}</b></span>
        <span class="lu-muted">rating ${m.ratingA} &middot; ${m.gamesA} matches</span></div>
      <div class="gs-side gs-r"><span class="gs-name"><span class="lu-dot lu-dot1"></span><b>${escapeHtml(T[1].name)}</b></span>
        <span class="lu-muted">rating ${m.ratingB} &middot; ${m.gamesB} matches</span></div>
    </div>
    <div class="gs-poss"><b>${pct(pa)}</b><i class="gs-bar"><em style="width:${Math.round(pa * 100)}%"></em></i><b>${pct(pb)}</b></div>
    <div class="gs-caption">to win the match &middot; fair ${fair(pa)} v ${fair(pb)} &middot; ${fmt}</div>
    <div class="gs-vols">
      <div class="gs-vol"><span>Leg</span><b>${pct(m.legA)} / ${pct(1 - m.legA)}</b></div>
      ${m.expLegs != null ? `<div class="gs-vol"><span>Legs</span><b>${m.expLegs.toFixed(1)}</b></div>` : ""}
      ${m.exp180 != null ? `<div class="gs-vol"><span>180s</span><b>${m.exp180.toFixed(1)}</b></div>` : ""}
    </div>
    ${mktLine}${flag}${noMkt}
    ${thin ? `<p class="gs-script">Fewer than 10 matches on record for one player, so the rating is still settling: treat the price as rough.</p>` : ""}
  </div>`;

  const row = (label, p, extra) => `<div class="def-row">
      <div class="def-row-top"><span>${label}</span><b>${pct(p)} &middot; ${fair(p)}</b></div>
      <i class="def-bar"><em style="width:${Math.round(p * 100)}%"></em></i>${extra ? `<div class="def-sub">${extra}</div>` : ""}</div>`;

  const totals = (m.totalLegs || []).map(([L, p]) =>
    row(`Over ${L} legs`, p, `under ${pct(1 - p)} &middot; ${fair(1 - p)}`)).join("");
  const hcp = (m.handicap || []).map(([h, a, b]) =>
    row(`${escapeHtml(T[0].name)} -${h}`, a, `${escapeHtml(T[1].name)} -${h}: ${pct(b)} &middot; ${fair(b)}`)).join("");
  const scores = (m.scores || []).slice(0, 8).map(([a, b, p]) =>
    `<div class="gs-vol"><span>${a}-${b}</span><b>${pct(p)}</b></div>`).join("");
  const t180 = (m.total180 || []).filter(([L]) => Math.abs(L - m.exp180) <= 3.1).map(([L, p]) =>
    row(`Over ${L} 180s`, p, `under ${pct(1 - p)} &middot; ${fair(1 - p)}`)).join("");
  const most = m.most180 ? `<div class="gs-vols">
      <div class="gs-vol"><span>${escapeHtml(T[0].name)}</span><b>${pct(m.most180[0])} &middot; ${fair(m.most180[0])}</b></div>
      <div class="gs-vol"><span>Tie</span><b>${pct(m.most180[1])} &middot; ${fair(m.most180[1])}</b></div>
      <div class="gs-vol"><span>${escapeHtml(T[1].name)}</span><b>${pct(m.most180[2])} &middot; ${fair(m.most180[2])}</b></div></div>` : "";

  el.innerHTML = head
    + (totals ? `<h3 class="lu-h">Total legs</h3><div class="lu-card">${totals}</div>` : "")
    + (hcp ? `<h3 class="lu-h">Handicap (legs)</h3><div class="lu-card">${hcp}</div>` : "")
    + (scores ? `<h3 class="lu-h">Most likely scores</h3><div class="lu-card"><div class="gs-vols">${scores}</div></div>` : "")
    + (t180 ? `<h3 class="lu-h">Match 180s</h3><div class="lu-card">${t180}
        <div class="def-sub">${m.rate180[0].toFixed(2)} and ${m.rate180[1].toFixed(2)} a leg, from ${m.legs180[0]} and ${m.legs180[1]} legs with stats</div></div>` : "")
    + (most ? `<h3 class="lu-h">Most 180s</h3><div class="lu-card">${most}</div>` : "")
    + `<details class="lu-more"><summary>How this is worked out, and how good it is</summary><p class="note">
      One leg-level rating per player over every cached PDC result since 2018, updated in date order with only
      earlier matches, so a 6-4 counts as ten pieces of evidence. The chance of winning a leg comes from the
      rating gap, with an edge for throwing first; the match, the legs and the scores are worked out exactly for
      this format, averaged over who wins the bull. Replayed over 1,723 past matches it put its favourite through
      61% of the time and was calibrated within a point or two at every level up to 80% (log loss 0.657 against
      0.693 for a coin flip). Total legs run about 3 points high on the longer matches. 180s are each man's rate
      per leg, shrunk towards the field, over the legs the scores say will be played: predicted 5.24 a match
      against 5.29 actual over 506 matches. Where the Betfair Exchange prices the match, the winner chance used is a
      blend leaning ${Math.round((m.marketWeight || 0.75) * 100)}% on the market, and every other number here is
      recomputed from it so the page agrees with itself. The weight is refitted from results once enough
      priced matches have finished.</p></details>`;
}

function lineupView() {
  const el = document.getElementById("lineups");
  if (!el) return;
  if (SPORT === "darts") { dartsMatchView(el); return; }
  if (SPORT !== "football") { defenceView(el); return; }
  const store = DATA.lineups || {};
  const modes = ["predicted", "confirmed"].filter(m => store[m]);
  if (!modes.length) {
    el.innerHTML = `<p class="note">No line-up yet. Predicted XIs usually appear a day or two out and
      the confirmed one about an hour before kick-off. Until then the lines below use each side's regular starters.</p>`
      + gsCardHtml() + gsSectionHtml(null);
    return;
  }
  if (!modes.includes(lineupMode)) lineupMode = store.confirmed ? "confirmed" : "predicted";
  const lu = store[lineupMode];
  const shapes = [luShape(lu.home), luShape(lu.away)];

  const toggle = `<div class="seg lu-seg">` + ["predicted", "confirmed"].map(m =>
    `<button type="button" data-lumode="${m}" aria-pressed="${m === lineupMode}" ${store[m] ? "" : "disabled"}>
       ${m === "predicted" ? "Predicted" : "Confirmed"}</button>`).join("") + `</div>`;

  let changes = "";
  if (store.predicted && store.confirmed) {
    const names = s => new Set([...s.home.xi, ...s.away.xi].map(p => p.name));
    const conf = names(store.confirmed);
    const dropped = [...names(store.predicted)].filter(n => !conf.has(n));
    if (dropped.length) changes = `<p class="note lu-warn">Predicted but not starting: ${dropped.map(escapeHtml).join(", ")}</p>`;
  }

  const chip = (p, t) => `<button type="button" class="lu-chip lu-t${t} ${lineupPick && lineupPick.team === t && lineupPick.name === p.name ? "lu-on" : ""}"
      data-luteam="${t}" data-luname="${escapeHtml(p.name)}" title="${escapeHtml(p.name)}">
      <span class="lu-shirt">${escapeHtml(p.shirt ?? "")}</span>${escapeHtml(luSurname(p.name))}</button>`;
  // Away at the top attacking down (their right is screen left), home at the
  // bottom attacking up (their right is screen right).
  const row = (ln, t) => `<div class="lu-row">${(t === 1 ? ln : [...ln].reverse()).map(p => chip(p, t)).join("")}</div>`;
  const away = shapes[1], home = shapes[0];
  const pitch = `<div class="lu-pitch">
      ${row(away.gk, 1)}${away.lines.map(ln => row(ln, 1)).join("")}
      <div class="lu-half"></div>
      ${[...home.lines].reverse().map(ln => row(ln, 0)).join("")}${row(home.gk, 0)}
    </div>`;

  const status = lineupMode === "confirmed"
    ? `<span class="lu-badge lu-conf">Confirmed</span>`
    : `<span class="lu-badge">Predicted</span>`;
  const head = `<div class="lu-head">${toggle}${status}
      <span class="lu-muted">${escapeHtml(DATA.teams[0].name)} ${escapeHtml(lu.home.formation || "")}
      &middot; ${escapeHtml(DATA.teams[1].name)} ${escapeHtml(lu.away.formation || "")}</span></div>`;

  const missing = [lu.home, lu.away].map((s, t) => (s.missing || []).length
      ? `<span class="lu-dot lu-dot${t}"></span> ${(s.missing || []).map(m => escapeHtml(m[0])).join(", ")}` : "")
    .filter(Boolean);
  const out = missing.length ? `<p class="note gs-missing"><b>Missing:</b> ${missing.join(" &nbsp; ")}</p>` : "";

  el.innerHTML = head + changes + out + gsCardHtml()
    + `<div class="lu-grid">${pitch}<div id="lu-detail">${luDetail(shapes)}</div></div>`
    + gsSectionHtml(shapes);
}

/* Compact tiles for one player's record: one tile per market, the hit
   count large, the average small. */
function luTiles(rs) {
  return `<div class="lu-tiles">` + LU_ROWS.map(([s, l]) => {
    const r = luRate(rs, s, l);
    const cls = !r.n ? "" : r.p >= 0.8 ? "lu-hi" : r.p >= 0.6 ? "lu-mid" : "lu-lo";
    return `<div class="lu-tile"><span>${s === "Shots on target" ? "On target" : s} ${l}+</span>
      <b class="${cls}">${r.n ? r.k + "/" + r.n : "&ndash;"}</b>
      <small>${r.avg == null ? "" : "avg " + r.avg.toFixed(1)}</small></div>`;
  }).join("") + `</div>`;
}
/* One matchup line: the two rates as bars meeting in the middle. */
function luVs(leftName, leftLabel, a, rightName, rightLabel, b) {
  const w = r => (r && r.n ? Math.round(r.p * 100) : 0);
  const strong = a.n >= 5 && b.n >= 5 && a.p >= 0.7 && b.p >= 0.7;
  return `<div class="lu-vs ${strong ? "lu-strong" : ""}">
    <div class="lu-vs-side"><span>${escapeHtml(luSurname(leftName))} ${leftLabel}</span><b>${a.n ? a.k + "/" + a.n : "&ndash;"}</b>
      <i class="lu-bar lu-bar-l"><em style="width:${w(a)}%"></em></i></div>
    <div class="lu-vs-mid">${strong ? "match" : "v"}</div>
    <div class="lu-vs-side lu-r"><span>${escapeHtml(luSurname(rightName))} ${rightLabel}</span><b>${b.n ? b.k + "/" + b.n : "&ndash;"}</b>
      <i class="lu-bar"><em style="width:${w(b)}%"></em></i></div>
  </div>`;
}

function luDetail(shapes) {
  if (!lineupPick) return `<div class="lu-empty">Tap a player to see his record and the man directly opposite him.</div>`;
  const t = lineupPick.team;
  const p = shapes[t].lines.flat().concat(shapes[t].gk).find(q => q.name === lineupPick.name);
  if (!p) return `<div class="lu-empty">${escapeHtml(lineupPick.name)} is not in this XI.</div>`;
  const opps = p.pos === "G" ? [] : luOpponents(p, shapes[1 - t]);
  const recs = luRecords(t, p.name);
  const posName = { G: "Goalkeeper", D: "Defender", M: "Midfielder", F: "Forward" }[p.pos] || "";
  let html = `<div class="lu-card">
    <div class="lu-who"><span class="lu-dot lu-dot${t}"></span><b>${escapeHtml(p.name)}</b>
      <span class="lu-muted">${escapeHtml(DATA.teams[t].name)} &middot; ${posName}${recs.length ? " &middot; last " + recs.length : ""}</span></div>
    ${recs.length ? luTiles(recs) : `<div class="lu-empty">No record for him in this report.</div>`}
  </div>`;
  for (const o of opps) {
    const ors = luRecords(1 - t, o.name);
    html += `<div class="lu-card">
      <div class="lu-who"><span class="lu-muted">Up against</span>
        <span class="lu-dot lu-dot${1 - t}"></span>
        <button type="button" class="lu-link" data-luteam="${1 - t}" data-luname="${escapeHtml(o.name)}">${escapeHtml(o.name)}</button></div>
      ${luVs(p.name, "fouled", luRate(recs, "Fouled", 1), o.name, "fouls", luRate(ors, "Fouls", 1))}
      ${luVs(p.name, "fouls", luRate(recs, "Fouls", 1), o.name, "fouled", luRate(ors, "Fouled", 1))}
      ${ors.length ? `<details class="lu-more"><summary>${escapeHtml(luSurname(o.name))}'s record</summary>${luTiles(ors)}</details>` : ""}
    </div>`;
  }
  return html;
}

/* Football only for now: an NFL line-up is a 53-man depth chart, and
   "the man directly opposite" means something different there. */
if (SPORT !== "football") {
  const b = document.querySelector('[data-tab="lineups"]');
  if (b) b.textContent = "Defences";
}

document.addEventListener("click", e => {
  const dm = e.target.closest("[data-defmode]");
  if (dm) { defMode = dm.dataset.defmode; lineupView(); return; }
  const gs = e.target.closest("[data-gssec]");
  if (gs) { gsSection = gs.dataset.gssec; lineupView(); return; }
  const m = e.target.closest("[data-lumode]");
  if (m && !m.disabled) { lineupMode = m.dataset.lumode; lineupView(); return; }
  const c = e.target.closest("[data-luname]");
  if (c) { lineupPick = { team: Number(c.dataset.luteam), name: c.dataset.luname }; lineupView(); }
});

/* ---------------------------------------------------------------- wiring */

// Delegated to the board, so handlers survive every re-render.

boardEl.addEventListener("click", e => {
  const btn = e.target.closest("button[data-step]");
  if (!btn) return;
  const row = btn.closest(".stat-row");
  setLine(row, activeLines()[row.dataset.stat] + parseFloat(btn.dataset.step));
});

boardEl.addEventListener("input", e => {
  const input = e.target.closest("input[data-line]");
  if (!input) return;
  const value = parseFloat(input.value);
  if (Number.isNaN(value)) return;          // half-typed, leave it alone
  const row = input.closest(".stat-row");
  activeLines()[row.dataset.stat] = Math.max(0, value);
  updateRow(row);
});

/* The guard matters. Clicking a stepper blurs the input, firing `change`
   with the value from before the click. Comparing against DATA.lines, the
   single source of truth, makes that stale event a no-op. */
boardEl.addEventListener("change", e => {
  const input = e.target.closest("input[data-line]");
  if (!input) return;
  const row = input.closest(".stat-row");
  const current = activeLines()[row.dataset.stat];
  const typed = parseFloat(input.value);
  if (Number.isNaN(typed) || snapLine(typed) === current) {
    input.value = current;
    return;
  }
  setLine(row, typed);
});

function wireTooltips(el) {
  el.addEventListener("mouseover", e => {
    const dot = e.target.closest("circle[data-tip]");
    if (!dot) return;
    tip.innerHTML = dot.dataset.tip;
    tip.style.opacity = "1";
  });
  el.addEventListener("mousemove", e => {
    if (tip.style.opacity !== "1") return;
    tip.style.left = (e.clientX + 12) + "px";
    tip.style.top = (e.clientY - 36) + "px";
  });
  el.addEventListener("mouseout", e => {
    if (e.target.closest("circle[data-tip]")) tip.style.opacity = "0";
  });
}
wireTooltips(boardEl);
wireTooltips(document.getElementById("players"));

function segment(attr, apply) {
  document.querySelectorAll(`[data-${attr}]`).forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(`[data-${attr}]`).forEach(b =>
        b.setAttribute("aria-pressed", b === btn));
      apply(btn.dataset[attr]);
    });
  });
}

segment("games", v => {
  games = parseInt(v, 10);
  render();
  if (tab === "players") playerView();
  if (tab === "standout") standoutView();
  if (onBest()) bestBetsView();
});
segment("border", () => bestBetsView());
/* A darts match carries four markets, so one fixture is too thin a board to
   pick from. Darts opens Best bets and Standout lines on every match in the
   report; the button still switches back to one fixture. */
if (SPORT === "darts") {
  scanScope = "round";
  document.querySelectorAll("[data-scope2]").forEach(b =>
    b.setAttribute("aria-pressed", b.dataset.scope2 === "round"));
}
segment("scope2", v => {
  scanScope = v;
  bestBetsView();
  standoutView();
});
document.getElementById("bfloor").addEventListener("input", () => {
  clearTimeout(standoutTimer);
  standoutTimer = setTimeout(bestBetsView, 140);
});
segment("tier", v => { tier = v; render(); if (tab === "players") playerView(); });
segment("venue", v => { venue = v; render(); if (tab === "players") playerView(); });
segment("period", v => { period = v; render(); });
segment("source", v => { source = v; render(); if (tab === "players") playerView(); });
segment("measure", v => { measure = v; render(); });
segment("focus", v => { focus = v; render(); if (tab === "players") playerView(); });
segment("scope", v => { scope = v; render(); });
segment("sort", v => { sort = v; render(); });

document.getElementById("strong-only").addEventListener("click", e => {
  strongOnly = !strongOnly;
  e.currentTarget.setAttribute("aria-pressed", strongOnly);
  render();
});

document.querySelectorAll("[data-tab]").forEach(btn => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

document.getElementById("reset").addEventListener("click", () => {
  for (const key of Object.keys(SUGGESTED)) {
    DATA.lines[key] = Object.assign({}, SUGGESTED[key]);
  }
  for (const key of Object.keys(SUGGESTED_H2H)) {
    DATA.h2hLines[key] = Object.assign({}, SUGGESTED_H2H[key]);
  }
  render();
});

document.getElementById("theme").addEventListener("click", () => {
  const now = document.documentElement.getAttribute("data-theme");
  document.documentElement.setAttribute(
    "data-theme", now === "dark" ? "light" : "dark");
  applyTeamColours();
  render();
  if (tab === "players") playerView();
});

/* The report is a static snapshot, but the browser knows the time, so it can
   drop fixtures that have already kicked off. That keeps a weekend card
   useful all weekend instead of going stale one match at a time. */
/* "Sat 23 Aug, 15:00" in the reader's own timezone. The payload stores a
   unix timestamp precisely so this can be local rather than UTC: a 20:00 UTC
   kick-off is a 21:00 one in most of Europe, and getting that wrong by an
   hour is the sort of thing that loses a bet. */
function shortWhen(kickoff) {
  if (!kickoff) return "";
  const d = new Date(kickoff * 1000);
  const day = d.toLocaleDateString(undefined,
    { weekday: "short", day: "numeric", month: "short" });
  const time = d.toLocaleTimeString(undefined,
    { hour: "2-digit", minute: "2-digit", hour12: false });
  return `${day}, ${time}`;
}

const fixtureSelect = document.getElementById("fixture");
const pastToggle = document.getElementById("show-past");

function upcomingIndexes() {
  const now = Date.now() / 1000;
  return ALL.fixtures
    .map((f, i) => i)
    .filter(i => showPast || (ALL.fixtures[i].fixture.kickoff || 0) > now);
}

function fillFixtures() {
  let indexes = upcomingIndexes();

  // If every fixture has been played, show them all rather than an empty page.
  const allPlayed = indexes.length === 0;
  if (allPlayed) indexes = ALL.fixtures.map((f, i) => i);

  const now = Date.now() / 1000;

  // Soonest first. A weekend card is read in kick-off order, not in whatever
  // order the clubs came back from the league table.
  indexes.sort((a, b) =>
    (ALL.fixtures[a].fixture.kickoff || 0) - (ALL.fixtures[b].fixture.kickoff || 0));

  fixtureSelect.innerHTML = indexes.map(i => {
    const f = ALL.fixtures[i].fixture;
    const played = (f.kickoff || 0) <= now;
    return `<option value="${i}">${shortWhen(f.kickoff)}  ${f.home} v ${f.away}`
         + `${played ? " (played)" : ""}</option>`;
  }).join("");

  const hidden = ALL.fixtures.length - indexes.length;
  pastToggle.hidden = ALL.fixtures.length < 2;
  pastToggle.textContent = hidden
    ? `Show ${hidden} played`
    : (showPast ? "Hide played" : "All upcoming");
  pastToggle.setAttribute("aria-pressed", showPast);

  // Keep the current fixture selected if it survived the filter.
  const current = ALL.fixtures.indexOf(DATA);
  if (indexes.includes(current)) {
    fixtureSelect.value = String(current);
  } else {
    DATA = ALL.fixtures[indexes[0]];
    fixtureSelect.value = String(indexes[0]);
    applyFixture();
  }

  document.getElementById("fixture-group").hidden = indexes.length < 2;
}

/* The index links straight to a fixture with #e<event id>. Matching on the
   event id rather than a position means the link survives a rebuild that
   reorders or drops fixtures, which happens every week. */
function applyDeepLink() {
  const match = /^#e(\\d+)$/.exec(location.hash || "");
  if (!match) return false;

  const wanted = parseInt(match[1], 10);
  const found = ALL.fixtures.findIndex(f => f.fixture.id === wanted);
  if (found < 0) return false;

  DATA = ALL.fixtures[found];

  // A fixture that has already kicked off is filtered out of the dropdown by
  // default, so linking to one has to turn the filter off or the selection
  // gets thrown straight back to the first upcoming match.
  if ((DATA.fixture.kickoff || 0) <= Date.now() / 1000 && !showPast) {
    showPast = true;
    fillFixtures();
  }

  // The dropdown is the visible truth. Leaving it pointing at a different
  // fixture from the one on screen is worse than not linking at all.
  fixtureSelect.value = String(found);
  applyFixture();
  return true;
}

window.addEventListener("hashchange", applyDeepLink);
window.matchMedia("(prefers-color-scheme: dark)")
  .addEventListener("change", () => { applyTeamColours(); render(); });

if (ALL.fixtures.length > 1) {
  fixtureSelect.addEventListener("change", () => {
    DATA = ALL.fixtures[parseInt(fixtureSelect.value, 10)];
    applyFixture();
  });
  pastToggle.addEventListener("click", () => {
    showPast = !showPast;
    fillFixtures();
  });
  fillFixtures();
  // After fillFixtures, never before. fillFixtures resets the selection to
  // the first upcoming fixture whenever the current one is not in its list,
  // so calling this first meant the deep link was silently overwritten and
  // the link landed on whatever happened to be at the top.
  applyDeepLink();
} else {
  document.getElementById("fixture-group").hidden = true;
  pastToggle.hidden = true;
}

/* Rebuilding both squad tables on every keystroke is laggy once a report
   holds a full league round, so wait for a pause in the typing. */
let playerTimer = null;
function playerViewSoon() {
  clearTimeout(playerTimer);
  playerTimer = setTimeout(playerView, 120);
}

// Dragging a window across the threshold, or turning a phone, should re-lay
// the squads rather than leaving two clipped tables on screen.
window.addEventListener("resize", () => {
  if (tab === "players") playerViewSoon();
});

const pstat = document.getElementById("pstat");
pstat.addEventListener("change", () => {
  document.getElementById("pline").value = DATA.playerLines[pstat.value] ?? 0.5;
  playerView();
});
document.getElementById("pline").addEventListener("input", playerViewSoon);
document.getElementById("pmin").addEventListener("input", playerViewSoon);

let standoutTimer = null;
function standoutSoon() {
  clearTimeout(standoutTimer);
  standoutTimer = setTimeout(standoutView, 140);
}
document.getElementById("include-mismatched").addEventListener("click", e => {
  includeMismatched = !includeMismatched;
  e.currentTarget.setAttribute("aria-pressed", includeMismatched);
  standoutView();
  bestBetsView();
});

// The best-bets controls and its own Add button. Picks added here have no
// price box beside them, because a matchup card is a shortlist entry rather
// than a priced bet: you type the price in on the slip.
["bmin", "btop", "bneed"].forEach(id =>
  document.getElementById(id).addEventListener("input", () => {
    clearTimeout(standoutTimer);
    standoutTimer = setTimeout(bestBetsView, 140);
  }));

/* The bar is one setting read by three places: the cards, the suggested slip
   and your own slip. Changing it has to reach all of them. */
document.getElementById("bbar")?.addEventListener("input", () => {
  clearTimeout(standoutTimer);
  standoutTimer = setTimeout(() => { bestBetsView(); slipView(); }, 140);
});

document.getElementById("players").addEventListener("click", e => {
  const btn = e.target.closest("button[data-padd]");
  if (!btn) return;
  const entry = PLAYER_ROWS[parseInt(btn.dataset.padd, 10)];
  if (!entry) return;

  const key = rowKey(entry.row);
  const at = SLIP.findIndex(s => s.key === key);
  if (at >= 0) SLIP.splice(at, 1);
  else SLIP.push({ key, row: entry.row, price: 0 });

  playerView();
  slipView();
  document.getElementById("slip-count").textContent = SLIP.length ? ` (${SLIP.length})` : "";
});

document.getElementById("valuetab")?.addEventListener("click", e => {
  const btn = e.target.closest("button[data-padd]");
  if (!btn) return;
  const entry = PLAYER_ROWS[parseInt(btn.dataset.padd, 10)];
  if (!entry) return;
  const key = rowKey(entry.row);
  const at = SLIP.findIndex(s => s.key === key);
  if (at >= 0) SLIP.splice(at, 1);
  else SLIP.push({ key, row: entry.row, price: 0 });
  valueView();
  slipView();
  document.getElementById("slip-count").textContent = SLIP.length ? ` (${SLIP.length})` : "";
});

document.getElementById("bestbets").addEventListener("click", e => {
  const btn = e.target.closest("button[data-badd]");
  if (!btn) return;
  const r = (window.__best || [])[parseInt(btn.dataset.badd, 10)];
  if (!r) return;

  const key = rowKey(r);
  const at = SLIP.findIndex(s => s.key === key);
  if (at >= 0) SLIP.splice(at, 1);
  else SLIP.push({ key, row: r, price: 0 });

  bestBetsView();
  slipView();
  document.getElementById("slip-count").textContent = SLIP.length ? ` (${SLIP.length})` : "";
});

document.getElementById("standout").addEventListener("click", e => {
  const btn = e.target.closest("button[data-add]");
  if (!btn) return;
  const r = (window.__shown || [])[parseInt(btn.dataset.add, 10)];
  if (!r) return;

  const key = rowKey(r);
  const at = SLIP.findIndex(s => s.key === key);
  if (at >= 0) {
    SLIP.splice(at, 1);
  } else {
    const priceInput = btn.closest("tr").querySelector("input[data-price]");
    SLIP.push({ key, row: r, price: parseFloat(priceInput?.value) || 0 });
  }
  standoutView();
  slipView();
  document.getElementById("slip-count").textContent = SLIP.length ? ` (${SLIP.length})` : "";
});

document.getElementById("slip").addEventListener("click", e => {
  const swap = e.target.closest("button[data-swap]");
  if (swap) {
    const i = parseInt(swap.dataset.swap, 10);
    const key = swap.dataset.swapKey;
    const row = (window.__pool || window.__best || []).find(r => rowKey(r) === key);
    if (!row || !SLIP[i]) return;
    // The quoted price belonged to the leg being replaced, not to this one,
    // so it does not come along. Carrying it over would score the new leg
    // against a price nobody has offered for it.
    SLIP[i] = { key, row, price: 0 };
    slipView();
    bestBetsView();
    standoutView();
    return;
  }

  const btn = e.target.closest("button[data-remove]");
  if (!btn) return;
  SLIP.splice(parseInt(btn.dataset.remove, 10), 1);
  slipView();
  standoutView();
  document.getElementById("slip-count").textContent = SLIP.length ? ` (${SLIP.length})` : "";
});

document.getElementById("slip").addEventListener("input", e => {
  const input = e.target.closest("input[data-slip-price]");
  if (!input) return;
  const row = input.closest("tr");
  const i = parseInt(row.dataset.slip, 10);
  SLIP[i].price = parseFloat(input.value) || 0;

  /* Update this row's score in place. It used to call slipView() on a timer,
     which rebuilt the whole table with innerHTML -- and that destroys the very
     input being typed into. The element is replaced by a fresh one, so focus,
     cursor position and any digits typed in the meantime are lost. Typing
     "2.50" got as far as "2" and then the field emptied itself, which reads
     as the box simply refusing input.

     Only the score and its breakdown depend on the price, so only those are
     rewritten. Nothing touches the input, so typing is never interrupted. */
  const bar = slipBar();
  const sc = scorePick(SLIP[i].row, SLIP[i].price);
  const pass = sc.shown >= bar;

  const score = row.querySelector(".score");
  if (score) {
    score.innerHTML = scoreText(sc);
    score.className = "score " + (pass ? "good" : (sc.shown < bar - 20 ? "poor" : ""));
  }
  const breakdown = row.querySelector(".breakdown");
  if (breakdown) breakdown.innerHTML = breakdownText(sc);

  const chip = row.querySelector(".bar-chip");
  if (chip) {
    chip.className = "bar-chip " + (pass ? "pass" : "fail");
    chip.textContent = pass ? `clears ${bar}` : `below ${bar}`;
  }

  /* The replacement suggestions depend on the price too -- a leg that looked
     thin at 1.80 is a different proposition at 2.60, and so are the legs that
     would beat it. Rewritten in place for the same reason as the score: this
     row holds the field being typed into and must not be rebuilt. */
  const swapRow = row.parentNode &&
    row.parentNode.querySelector(`tr[data-swap-for="${i}"]`);
  if (swapRow) {
    swapRow.hidden = pass;
    const cell = swapRow.querySelector("td");
    if (cell) cell.innerHTML = pass ? "" : swapBlock(SLIP[i], i);
  }

  const summary = document.querySelector(".slip-bar-summary");
  if (summary) {
    const clearing = SLIP.filter(s => scorePick(s.row, s.price).shown >= bar).length;
    const strong = summary.querySelector("strong");
    if (strong) strong.textContent = `${clearing} of ${SLIP.length}`;
    summary.className = "slip-bar-summary " +
      (clearing < SLIP.length ? "is-warn" : "is-ok");
  }

  updateSlipTotals();
});

/* Custom bet builder wiring. Each control only rebuilds what depends on it,
   so changing the line does not rebuild the stat list underneath the cursor --
   the same mistake that made the slip's price field unusable. */
["c-fixture", "c-team", "c-player", "c-period", "c-stat",
 "c-side", "c-line", "c-price"].forEach(id => {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener(id === "c-line" || id === "c-price" ? "input" : "change", () => {
    if (id === "c-fixture") fillCustomTeams();
    else if (id === "c-team") { fillCustomPlayers(); fillCustomStats(); }
    else if (id === "c-player") fillCustomStats();
    else if (id === "c-period") fillCustomStats();
    else customPreview();
  });
});

document.getElementById("c-add")?.addEventListener("click", () => {
  const r = customRow();
  if (!r) return;
  const price = parseFloat(document.getElementById("c-price").value) || 0;
  const key = rowKey(r);
  if (SLIP.some(s => s.key === key)) return;
  SLIP.push({ key, row: r, price });
  slipView();
  document.getElementById("slip-count").textContent =
    SLIP.length ? ` (${SLIP.length})` : "";
});

["rtarget", "rlegs"].forEach(id => {
  document.getElementById(id)?.addEventListener("input", recommendedSlip);
});

document.getElementById("rec-slip")?.addEventListener("click", e => {
  if (!e.target.closest("#rec-add")) return;
  let added = 0;
  (window.__recLegs || []).forEach(r => {
    const key = rowKey(r);
    if (SLIP.some(s => s.key === key)) return;
    SLIP.push({ key, row: r, price: 0 });
    added++;
  });
  if (added) {
    slipView();
    document.getElementById("slip-count").textContent =
      SLIP.length ? ` (${SLIP.length})` : "";
  }
});

document.getElementById("smin").addEventListener("input", standoutSoon);
document.getElementById("stop").addEventListener("input", standoutSoon);

/* Type a bookmaker's price and the row says whether it clears the bar.
   The verdict uses the conservative estimate, not the point estimate: it
   should be hard to get a yes, because most of what a scan like this turns
   up is noise wearing a good record. */
document.getElementById("standout").addEventListener("input", e => {
  const input = e.target.closest("input[data-price]");
  if (!input) return;

  const row = input.closest("tr");
  const cell = row.querySelector("[data-verdict]");
  const price = parseFloat(input.value);

  if (!price || price <= 1) {
    cell.textContent = "";
    cell.className = "verdict";
    return;
  }

  const pLow = parseFloat(row.dataset.plow);
  const minPrice = parseFloat(row.dataset.min);
  const fair = parseFloat(row.dataset.fair);
  const edge = (price * pLow - 1) * 100;

  if (price >= minPrice) {
    cell.className = "verdict yes";
    cell.textContent = `Clears, +${edge.toFixed(1)}%`;
  } else if (price >= fair) {
    cell.className = "verdict thin";
    cell.textContent = "Thin, sample too small";
  } else {
    cell.className = "verdict no";
    cell.textContent = "Under fair value";
  }
});

/* -------------------------------------------------------- filter drawer

   At rest the whole control area is one line: a plain-words summary of
   every active filter, which is itself the button that opens the panel.
   The panel holds every control, grouped by what it does. Sample decides
   which matches count; View decides how they are read.

   Closed must never mean silently active. Anything off its default is
   named in the line, highlighted, and named FIRST, so the ellipsis on a
   narrow phone can only ever eat the defaults. The count on the Filters
   word backs it up: it survives any truncation. */

const filterToggle = document.getElementById("filter-toggle");
const filterPanel = document.getElementById("filter-panel");

function setFiltersOpen(open) {
  filterPanel.hidden = !open;
  filterToggle.setAttribute("aria-expanded", String(open));
  try { sessionStorage.setItem("filtersOpen", open ? "1" : "0"); } catch (e) {}
}

filterToggle.addEventListener("click", () => setFiltersOpen(filterPanel.hidden));

// Reopening on return is a session convenience; closed is the resting state.
try {
  if (sessionStorage.getItem("filtersOpen") === "1") setFiltersOpen(true);
} catch (e) {}

function filterSummaryParts() {
  const parts = [];
  const push = (text, on) => parts.push({ text, on: !!on });

  if (source === "h2h") push("Head to head", true);
  push(games >= 99 ? "All matches" : "Last " + games, games !== 10);
  if (SPORT !== "darts")
    push(venue === "all" ? "All venues"
       : venue === "home" ? "Home only" : "Away only", venue !== "all");
  if (tier !== "all") {
    const b = document.querySelector(`[data-tier="${tier}"]`);
    push("vs " + (b ? b.textContent : tier), true);
  }
  if (SPORT !== "darts")
    push(period === "ALL" ? "Full match"
       : period === "1ST" ? "First half" : "Second half", period !== "ALL");
  if (focus === "both") push(SPORT === "darts" ? "Both players" : "Both teams", false);
  else push(escapeHtml((DATA.teams[+focus] || {}).name || "One team") + " only", true);
  if (measure !== "for") push(measure === "against" ? "Against" : "Matchup", true);
  push(scope === "core" ? "Main stats" : "All stats", scope !== "core");
  if (sort !== "default") push("Strongest first", true);
  if (strongOnly) push("Strong only", true);
  return parts;
}

function updateFilterSummary() {
  const el = document.getElementById("filter-summary");
  if (!el) return;
  const parts = filterSummaryParts();
  const on = parts.filter(p => p.on);
  const off = parts.filter(p => !p.on);
  const onHtml = on.map(p => `<span class="on">${p.text}</span>`).join(" \u00b7 ");
  const offHtml = off.map(p => p.text).join(" \u00b7 ");
  // The defaults are wrapped so a narrow screen can drop them: when space
  // runs out, what survives must be the filters that are actually biting.
  el.classList.toggle("has-active", on.length > 0);
  el.innerHTML = onHtml
    + (off.length ? `<span class="defaults">${on.length ? " \u00b7 " : ""}${offHtml}</span>` : "");

  const count = document.getElementById("filter-count");
  if (count) {
    count.textContent = on.length ? String(on.length) : "";
    count.hidden = !on.length;
  }
}

updateFilterSummary();

applyFixture();


/* ------------------------------------------------------- tucking the prose

   Every panel opens with a block of explanation -- what the scan is, what
   fair and need mean, why a hit rate is not an edge. It is all true and it
   all matters once, and then it sits between you and the numbers forever.

   So it collapses. The leading bold sentence becomes the summary, the rest
   goes behind it, and anyone who wants the argument can have it in a click.

   Done here rather than in the seven places that build these blocks, because
   seven edits to working render code to achieve one thing is how you break
   one of them. An observer catches whatever any panel renders, now or later,
   and the data-tuck flag stops it reacting to its own work. */
function tuckProse(root) {
  // .note catches the long footers under each board -- the paragraph about
  // dashed lines, shaded rows and what "proj" means -- which is the same kind
  // of read-once prose as the .caution blocks and just as permanent.
  const SEL = ".caution:not([data-tuck]), .note:not([data-tuck])";
  (root || document).querySelectorAll(SEL).forEach(el => {
    el.setAttribute("data-tuck", "1");
    if (el.textContent.trim().length < 240) return;

    // Prose only. Some of these blocks carry the thing itself rather than an
    // explanation of it -- the suggested slip is a .caution with a table and
    // Add buttons in it -- and folding those away hides a feature rather than
    // tidying a paragraph. Anything with structure or a control stays open.
    if (el.querySelector("table, ol, ul, button, input, select, .pick")) return;

    const lead = el.querySelector("strong");
    // Doubled backslash on purpose: the whole JS block is an ordinary Python
    // string, so a lone backslash-s in it is an invalid escape. It survives
    // today only because Python passes unknown escapes through unchanged,
    // with a warning that becomes an error in a future version -- at which
    // point this file stops importing at all.
    let title = lead ? lead.textContent.trim().replace(/[.:]\\s*$/, "") : "";
    if (lead && title) lead.remove();
    if (!title) title = "How to read this board";

    const box = document.createElement("details");
    box.className = "tuck";
    const head = document.createElement("summary");
    head.textContent = title;
    box.appendChild(head);
    const body = document.createElement("div");
    while (el.firstChild) body.appendChild(el.firstChild);
    box.appendChild(body);
    el.appendChild(box);
  });
}
new MutationObserver(() => tuckProse()).observe(
  document.body, { childList: true, subtree: true });
tuckProse();


/* ------------------------------------------------------------- dropdowns

   A native select cannot be styled where it matters. The closed box takes
   CSS; the list that drops out of it is drawn by the operating system, which
   is why it arrives as a blue slab that belongs to nothing else on the page.

   So the real select stays exactly where it is, keeps its name, its value and
   every listener already attached to it, and is covered by a button and a
   panel that can be styled. Choosing an option writes back to the select and
   fires the same change event it would have fired itself, so nothing
   downstream knows the difference. If this script fails the select is still
   there and still works, which is the whole reason for doing it this way
   round rather than replacing it.

   A search box appears past twelve options, because that is roughly where
   scanning a squad list stops being quicker than typing three letters. */
function enhanceSelects(root) {
  (root || document).querySelectorAll("select:not([data-combo])").forEach(sel => {
    sel.setAttribute("data-combo", "1");

    const wrap = document.createElement("div");
    wrap.className = "combo";
    sel.parentNode.insertBefore(wrap, sel);
    wrap.appendChild(sel);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "combo-btn";
    btn.setAttribute("aria-haspopup", "listbox");
    btn.setAttribute("aria-expanded", "false");
    wrap.appendChild(btn);

    const pop = document.createElement("div");
    pop.className = "combo-pop";
    pop.hidden = true;
    wrap.appendChild(pop);

    const label = () => {
      const o = sel.options[sel.selectedIndex];
      btn.innerHTML = `<span class="combo-val"></span><span class="combo-caret"></span>`;
      btn.firstChild.textContent = o ? o.textContent : "";
      btn.disabled = sel.disabled;
    };

    const close = () => {
      pop.hidden = true;
      btn.setAttribute("aria-expanded", "false");
    };

    const open = () => {
      const many = sel.options.length > 12;
      pop.innerHTML = "";
      if (many) {
        const box = document.createElement("input");
        box.type = "search";
        box.placeholder = "Search";
        box.className = "combo-search";
        pop.appendChild(box);
        box.addEventListener("input", () => paint(box.value));
        setTimeout(() => box.focus(), 0);
      }
      const list = document.createElement("div");
      list.className = "combo-list";
      pop.appendChild(list);

      function paint(filter) {
        const want = (filter || "").trim().toLowerCase();
        list.innerHTML = "";
        let shown = 0;
        [...sel.options].forEach(o => {
          if (want && !o.textContent.toLowerCase().includes(want)) return;
          shown++;
          const item = document.createElement("button");
          item.type = "button";
          item.className = "combo-item" + (o.selected ? " on" : "");
          item.textContent = o.textContent;
          item.addEventListener("click", () => {
            sel.value = o.value;
            sel.dispatchEvent(new Event("change", { bubbles: true }));
            label();
            close();
          });
          list.appendChild(item);
        });
        if (!shown) {
          const none = document.createElement("div");
          none.className = "combo-none";
          none.textContent = "Nothing matches";
          list.appendChild(none);
        }
      }
      paint("");
      pop.hidden = false;
      btn.setAttribute("aria-expanded", "true");
      const on = list.querySelector(".combo-item.on");
      if (on) on.scrollIntoView({ block: "nearest" });
    };

    btn.addEventListener("click", e => {
      e.stopPropagation();
      document.querySelectorAll(".combo-pop:not([hidden])").forEach(p => {
        if (p !== pop) { p.hidden = true;
          p.parentNode.querySelector(".combo-btn").setAttribute("aria-expanded", "false"); }
      });
      pop.hidden ? open() : close();
    });
    pop.addEventListener("click", e => e.stopPropagation());
    sel.addEventListener("change", label);
    label();
  });
}
document.addEventListener("click", () => {
  document.querySelectorAll(".combo-pop:not([hidden])").forEach(p => {
    p.hidden = true;
    const b = p.parentNode.querySelector(".combo-btn");
    if (b) b.setAttribute("aria-expanded", "false");
  });
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    document.querySelectorAll(".combo-pop:not([hidden])").forEach(p => { p.hidden = true; });
  }
});
new MutationObserver(() => enhanceSelects()).observe(
  document.body, { childList: true, subtree: true });
enhanceSelects();


/* ---------------------------------------------------------- number inputs

   The browser's own spinner is two arrows about six pixels tall, stacked, in
   the corner of the field. It is the smallest hit target on the page by a
   distance and on a phone it does not exist at all. The line controls already
   had real buttons; every other number on the page -- target price, minimum
   matches, your price -- still had the operating system's.

   Same approach as the dropdowns: the input keeps its type, its step, its min
   and max and every listener on it, and gets a button either side that calls
   stepUp and stepDown so the browser still enforces the bounds. Holding one
   repeats, because nudging a price from 1.01 to 2.40 a click at a time is not
   a control, it is a punishment.

   Anything already inside a .stepper is left alone -- it has buttons. */
function enhanceNumbers(root) {
  (root || document).querySelectorAll(
      "input[type=number]:not([data-spin])").forEach(input => {
    input.setAttribute("data-spin", "1");
    if (input.closest(".stepper")) return;

    const wrap = document.createElement("div");
    wrap.className = "numwrap";
    input.parentNode.insertBefore(wrap, input);

    const make = (dir, glyph, title) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "numbtn";
      b.textContent = glyph;
      b.title = title;
      b.tabIndex = -1;

      let timer = null, hold = null;
      const bump = () => {
        if (input.disabled) return;
        dir > 0 ? input.stepUp() : input.stepDown();
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      };
      const stop = () => { clearTimeout(hold); clearInterval(timer); timer = hold = null; };
      b.addEventListener("pointerdown", e => {
        e.preventDefault();
        bump();
        hold = setTimeout(() => { timer = setInterval(bump, 80); }, 420);
      });
      ["pointerup", "pointerleave", "pointercancel"].forEach(ev =>
        b.addEventListener(ev, stop));
      return b;
    };

    wrap.appendChild(make(-1, "−", "Down"));
    wrap.appendChild(input);
    wrap.appendChild(make(1, "+", "Up"));
  });
}
new MutationObserver(() => enhanceNumbers()).observe(
  document.body, { childList: true, subtree: true });
enhanceNumbers();
loadMarkets();
loadFModel();
loadUSModel();
"""


def site_calibration() -> dict:
    """fmodel/site_calib.json's maps for the Players tab's fallback (scorer_audit.py), or none."""
    try:
        maps = json.loads((Path(__file__).parent / "fmodel" / "site_calib.json").read_text())["maps"]
    except (OSError, ValueError, KeyError):
        return {}
    return {k: v for k, v in maps.items()
            if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v)}


def build_html(payload: dict) -> str:
    first = payload["fixtures"][0]
    fixture = first["fixture"]
    names = [team["name"] for team in first["teams"]]

    generated = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    # One report is one competition, so one sport. Both of these used to be
    # the football sets regardless, which is how "Shots" and "Assists" ended
    # up as markets on an NFL page reading zero all the way down.
    sport = ((payload["fixtures"][0].get("fixture") or {}).get("sport")
             or "football") if payload.get("fixtures") else "football"
    bettable = json.dumps(sorted(markets.stats_for(sport)
                                 | markets.player_stats_for(sport)))
    fill = markets.ZERO_FILL_BY_SPORT.get(sport)
    if fill is None:
        fill = hitrates.PLAYER_ZERO_FILL
    zero_fill = json.dumps(sorted(fill))
    # What the Best players scan is allowed to propose.
    #
    # Gridiron used to get the lot, on the reasoning that none of its markets
    # have a team pairing to gate on. True, and the wrong gate: giving it
    # everything meant the NFL shortlist filled up with "Dondrea Tillman 1+
    # defensive assist tackles" and "Pat Surtain II 3+ defensive combine
    # tackles", which are real records of things no bookmaker prices. Eleven
    # gridiron markets ladder and six do not, and the six were crowding out
    # the eleven -- the same failure as the first NFL market list, one level
    # down.
    #
    # Basketball was worse and silent. It fell through to football's
    # adjustment map, so the scan went looking for Shots and Goals in records
    # that have Points and Rebounds, found nothing, and showed an empty tab
    # with no indication anything was wrong.
    #
    # So: a market has to be one the sport sells AND one sold as a ladder.
    # Football is left on its own list deliberately -- those five are what it
    # has always scanned, they are all laddered anyway, and widening it is a
    # change to make on purpose with a backtest, not as a side effect of
    # fixing the other two.
    if sport == "football":
        allow = sorted(model.FOOTBALL_STAT_TO_TEAM)
    else:
        allow = sorted(set(markets.player_stats_for(sport)) & parlay.LADDERED)
    scan_allow = json.dumps(allow)
    min_minutes = json.dumps(model.min_minutes_for(sport))
    site_calib = json.dumps(site_calibration() if sport == "football" else {})
    count = len(payload["fixtures"])
    scope = f"{count} fixtures" if count > 1 else "1 fixture"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{fixture['home']} v {fixture['away']}: hit rates</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">

<div class="back-bar"><a class="back" href="../index.html">&lsaquo;&nbsp; All fixtures</a></div>

<header>
  <div class="header-line">
    <div class="header-id">
      <div class="competition" id="competition">{fixture.get('competition', 'Football')}</div>
      <h1 id="title">{fixture['home']} v {fixture['away']}</h1>
      <div class="kickoff" id="kickoff">{fixture.get('date', '')}</div>
      <div class="referee" id="referee" hidden></div>
    </div>
    <!-- Actions, not filters. Reset rewrites the lines and Theme repaints
         the page; neither changes which matches are counted, so neither
         belongs in the filter panel. -->
    <div class="header-actions">
      <button type="button" id="reset" title="Put every line back to its suggested value">Reset lines</button>
      <button type="button" id="theme">Theme</button>
    </div>
  </div>
  <!-- Navigation, not a filter: picking a fixture swaps the whole page,
       title and all, so it lives with the page identity. -->
  <div class="control-group" id="fixture-group">
    <span class="control-label">Fixture</span>
    <select id="fixture"></select>
    <div class="seg"><button type="button" id="show-past" aria-pressed="false">All upcoming</button></div>
  </div>
</header>

<div class="filter-bar">
  <button type="button" id="filter-toggle" aria-expanded="false" aria-controls="filter-panel">
    <span class="chev" aria-hidden="true">&#9656;</span>
    <span class="fword">Filters<span class="fcount" id="filter-count" hidden></span></span>
    <span id="filter-summary"></span>
  </button>
  <div class="legend">
    <span class="legend-item"><span class="swatch" style="background:var(--team-1)"></span><span id="legend-0">{names[0]}</span></span>
    <span class="legend-item"><span class="swatch" style="background:var(--team-2)"></span><span id="legend-1">{names[1]}</span></span>
  </div>
</div>

<div class="filter-panel" id="filter-panel" hidden>
  <div class="fgroup">
    <div class="fgroup-title">Sample</div>
    <div class="fgroup-body">
      <div class="control-group">
        <span class="control-label">Based on</span>
        <div class="seg">
          <button type="button" data-source="form" aria-pressed="true">Recent form</button>
          <button type="button" data-source="h2h" aria-pressed="false">Head to head</button>
        </div>
      </div>

      <div class="control-group">
        <span class="control-label">Matches</span>
        <div class="seg">
          <button type="button" data-games="5" aria-pressed="false">5</button>
          <button type="button" data-games="10" aria-pressed="false">10</button>
          <button type="button" data-games="99" aria-pressed="true">All</button>
        </div>
      </div>

      <div class="control-group">
        <span class="control-label">Venue</span>
        <div class="seg">
          <button type="button" data-venue="all" aria-pressed="true">All</button>
          <button type="button" data-venue="home" aria-pressed="false">Home</button>
          <button type="button" data-venue="away" aria-pressed="false">Away</button>
        </div>
      </div>

      <div class="control-group" id="tier-group" hidden>
        <span class="control-label">Opposition</span>
        <div class="seg">
          <button type="button" data-tier="all" aria-pressed="true">All</button>
          <button type="button" data-tier="top" aria-pressed="false"
                  title="Sides that finished in the top six last season">Top 6</button>
          <button type="button" data-tier="upper" aria-pressed="false"
                  title="Finished 7th to 11th last season">Upper</button>
          <button type="button" data-tier="lower" aria-pressed="false"
                  title="Finished 12th to 17th last season">Lower</button>
          <button type="button" data-tier="bottom" aria-pressed="false"
                  title="Finished 18th or below, plus every promoted side">Bottom</button>
        </div>
      </div>
    </div>
  </div>

  <div class="fgroup">
    <div class="fgroup-title">View</div>
    <div class="fgroup-body">
      <div class="control-group">
        <span class="control-label">Team</span>
        <div class="seg">
          <button type="button" data-focus="both" aria-pressed="true">Both</button>
          <button type="button" data-focus="0" aria-pressed="false" id="focus-0">Home</button>
          <button type="button" data-focus="1" aria-pressed="false" id="focus-1">Away</button>
        </div>
      </div>

      <div class="control-group">
        <span class="control-label">Measure</span>
        <div class="seg">
          <button type="button" data-measure="for" aria-pressed="true">For</button>
          <button type="button" data-measure="against" aria-pressed="false">Against</button>
          <button type="button" data-measure="matchup" aria-pressed="false">Matchup</button>
        </div>
      </div>

      <div class="control-group">
        <span class="control-label">Period</span>
        <div class="seg">
          <button type="button" data-period="ALL" aria-pressed="true">Full</button>
          <button type="button" data-period="1ST" aria-pressed="false">1st</button>
          <button type="button" data-period="2ND" aria-pressed="false">2nd</button>
        </div>
      </div>

      <div class="control-group">
        <span class="control-label">Stats</span>
        <div class="seg">
          <button type="button" data-scope="core" aria-pressed="true">Main</button>
          <button type="button" data-scope="all" aria-pressed="false">All</button>
        </div>
      </div>

      <div class="control-group">
        <span class="control-label">Order</span>
        <div class="seg">
          <button type="button" data-sort="default" aria-pressed="true">Standard</button>
          <button type="button" data-sort="strongest" aria-pressed="false">Strongest first</button>
        </div>
      </div>

      <div class="control-group">
        <div class="seg">
          <button type="button" id="strong-only" aria-pressed="false"
                  title="Only stats where a team is at 80% or above, or 20% or below">Strong only</button>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="odds-strip" hidden></div>
<div class="tabs" role="tablist">
  <button type="button" data-tab="team" aria-selected="true">Team stats</button>
  <button type="button" data-tab="players" aria-selected="false">Players</button>
  <button type="button" data-tab="lineups" aria-selected="false">Line-ups</button>
  <button type="button" data-tab="best-player" aria-selected="false">Best players</button>
  <button type="button" data-tab="best-team" aria-selected="false">Best teams</button>
  <button type="button" data-tab="standout" aria-selected="false">Standout lines</button>
  <button type="button" data-tab="value" aria-selected="false">Value</button>
  <button type="button" data-tab="slip" aria-selected="false">My slip<span id="slip-count"></span></button>
</div>

<div class="panel" data-panel="team">
  <div id="result"></div>
  <div id="mismatch"></div>
  <div class="seg tmode" id="tmode">
    <button type="button" data-tmode="cards" aria-pressed="true">Chart</button>
    <button type="button" data-tmode="table" aria-pressed="false">Table</button>
  </div>
  <div id="tcards"></div>
  <div class="board" id="board" hidden></div>
</div>

<div class="panel" data-panel="players" hidden>
  <div class="seg pp-mode" id="pp-mode">
    <button type="button" data-pmode="squads" aria-pressed="true">Squads</button>
    <button type="button" data-pmode="stat" aria-pressed="false">Compare by stat</button>
  </div>
  <div class="controls" id="pstat-controls" hidden>
    <div class="control-group">
      <span class="control-label">Stat</span>
      <select id="pstat"></select>
    </div>
    <div class="control-group">
      <span class="control-label">Over</span>
      <input class="num-input" id="pline" type="number" step="1" min="0.5" value="0.5"
             aria-label="Player line">
    </div>
    <div class="control-group">
      <span class="control-label">Min apps</span>
      <input class="num-input" id="pmin" type="number" step="1" min="1" value="3"
             aria-label="Minimum appearances">
    </div>
  </div>
  <p class="note" id="pstat-note" hidden>
    Full match only: SofaScore does not publish player numbers by half.
    Players who have left the club are excluded, and so is any match where they
    played under 45 minutes, because a bet on a player who does not appear is
    void rather than lost. Prices come from a rate per 90 multiplied by the
    minutes they are likely to get.
    The Matchup column is the other half of each case: what the opponent has
    allowed in that stat to players of the same position class, built from
    every team's player records in this report, or for fouls what the players
    he will be marking have drawn. SofaScore gives only G, D, M and F, so it
    cannot tell a winger from a striker. The sample and coverage are printed
    with it because not every match has the opposition's players on file, and
    because records exist only for players still at their clubs, a match
    rarely carries a full eleven. It is context beside the price, not part of
    it.
  </p>
  <p class="note" id="pnote" hidden></p>
  <div id="players"></div>
</div>

<div class="panel" data-panel="lineups" hidden>
  <div id="lineups"></div>
</div>

<div class="panel" data-panel="best" hidden>
  <div class="controls">
    <div class="control-group">
      <span class="control-label">Min matches each side</span>
      <input class="num-input" id="bmin" type="number" step="1" min="3" value="4"
             aria-label="Minimum matches on each side">
    </div>
    <div class="control-group">
      <span class="control-label">Per competition</span>
      <input class="num-input" id="btop" type="number" step="1" min="1" max="25" value="10"
             aria-label="How many per competition">
    </div>
    <div class="control-group">
      <span class="control-label">Scope</span>
      <div class="seg">
        <button type="button" data-scope2="fixture" aria-pressed="true"
                title="Only the fixture selected above">This fixture</button>
        <button type="button" data-scope2="round" aria-pressed="false"
                title="Every fixture in this report">Whole round</button>
      </div>
    </div>
    <div class="control-group">
      <span class="control-label">Min each side</span>
      <input class="num-input" id="bfloor" type="number" step="5" min="30" max="100" value="65"
             aria-label="Minimum hit rate on each side, per cent">
    </div>
    <div class="control-group">
      <span class="control-label">Max need</span>
      <input class="num-input" id="bneed" type="number" step="0.1" min="1.05" max="10"
             value="2" aria-label="Drop anything needing a longer price than this">
    </div>
    <div class="control-group">
      <span class="control-label">Order</span>
      <div class="seg">
        <button type="button" data-border="evidence" aria-pressed="true"
                title="Strongest combined record first">Evidence</button>
        <button type="button" data-border="likely" aria-pressed="false"
                title="Shortest price first: the biggest mismatches">Most likely</button>
        <button type="button" data-border="value" aria-pressed="false"
                title="Where the matchup says this lands more often than the raw form does, so the price on offer is too big">Best value</button>
      </div>
    </div>
  </div>

  <div id="rec-slip"></div>
  <div class="controls" id="rec-controls">
    <div class="control-group">
      <span class="control-label">Target price</span>
      <input class="num-input" id="rtarget" type="number" step="0.5" min="1.5" max="50"
             value="3.0" aria-label="Minimum combined price">
    </div>
    <div class="control-group">
      <span class="control-label">Legs</span>
      <input class="num-input" id="rlegs" type="number" step="1" min="2" max="6"
             value="3" aria-label="How many legs">
    </div>
    <div class="control-group">
      <span class="control-label">Min score</span>
      <input class="num-input" id="bbar" type="number" step="5" min="0" max="100"
             value="60"
             aria-label="Minimum score for a bet to earn a place in the slip">
    </div>
  </div>

  <div id="bestbets"></div>
</div>

<div class="panel" data-panel="value" hidden>
  <div id="valuetab"></div>
</div>

<div class="panel" data-panel="standout" hidden>
  <div class="controls">
    <div class="control-group">
      <span class="control-label">Min matches</span>
      <input class="num-input" id="smin" type="number" step="1" min="3" value="8"
             aria-label="Minimum matches">
    </div>
    <div class="control-group">
      <span class="control-label">Show</span>
      <input class="num-input" id="stop" type="number" step="5" min="5" value="20"
             aria-label="How many to show">
    </div>
    <div class="control-group">
      <div class="seg">
        <button type="button" id="include-mismatched" aria-pressed="false"
                title="Include teams whose record was built in another competition">
          Include other competitions</button>
      </div>
    </div>
  </div>
  <div id="standout"></div>
</div>

<div class="panel" data-panel="slip" hidden>
  <details id="custom-wrap">
    <summary>Add any bet</summary>
    <p class="note">
      Any stat this report tracks, at any line you like, for either side. The
      score is worked out the same way as everywhere else, from the same
      distribution, so a bet you build here is directly comparable with one the
      scan found. Markets outside these stats cannot be scored, because there
      is no record behind them to price against.
    </p>
    <div class="custom-row">
      <label>Fixture <select id="c-fixture"></select></label>
      <label>Team <select id="c-team"></select></label>
      <label>Player <select id="c-player"><option value="">Team stat</option></select></label>
      <label>Stat <select id="c-stat"></select></label>
      <label>Period <select id="c-period"></select></label>
      <label>Side <select id="c-side">
        <option value="over">Over</option>
        <option value="under">Under</option>
      </select></label>
      <label>Line <input id="c-line" type="number" step="0.5" value="1.5"></label>
      <label>Your price <input id="c-price" type="number" step="0.05" min="1.01"
                               placeholder="e.g. 2.10"></label>
      <button type="button" id="c-add" class="add-btn">Add to slip</button>
    </div>
    <div id="c-preview" class="note"></div>
  </details>

  <p class="note">
    Each selection scored out of 100 on four things: how far the price beats what
    the evidence supports (45), how much data sits behind it (25), whether the
    opponent-adjusted projection agrees (15), and whether the record was built
    against the right standard of opposition (15). The breakdown is always shown,
    because a score you cannot interrogate is just an opinion with a number on it.
  </p>
  <div id="slip"></div>
</div>

<footer>
  <span id="sample"></span>
  Dashed line on each chart marks the quoted line. Numbers run oldest to newest,
  left to right. Shaded rows are 80% or above, or 20% or below.
  Matchup puts the home side's own numbers against the away side's conceded ones,
  so you can see whether an attack meets a leak.
  Where shown, "proj" is what the fitted ratings expect in this fixture against
  this opponent, which is a different question from what the team has averaged.
  Built {generated} from SofaScore data, covering {scope}.
</footer>

</div>
<script>{JS.replace("__PAYLOAD__", json.dumps(payload)).replace("__BETTABLE__", bettable).replace("__ZERO_FILL__", zero_fill).replace("__PLAYER_SCAN_ALLOW__", scan_allow).replace("__MIN_MINUTES__", min_minutes).replace("__SITE_CALIB__", site_calib).replace("__SPORT__", json.dumps(sport))}</script>
</body>
</html>
"""


def _attach_darts(payload: dict) -> None:
    """Match markets for every darts fixture (darts_model.py): who wins, total
    legs, handicap, correct score and 180s. Worked out at build time from the
    cached results, so a rerender refreshes them with no requests. A failure
    here never costs the report."""
    fixtures = payload.get("fixtures") or []
    darts = [f for f in fixtures if (f.get("fixture") or {}).get("sport") == "darts"]
    if not darts:
        return
    try:
        import darts_model
        r = darts_model.ratings()
        formats = {m["id"]: m["fmt"] for m in darts_model.load_matches()}
    except Exception as exc:
        print(f"  darts match markets skipped: {type(exc).__name__}: {exc}")
        return
    # Exchange prices, if a fresh darts_prices.json is on disk (darts_market.py).
    try:
        import darts_market
        prices = darts_market.load()
        weight = darts_market.fit_weight() or darts_market.MARKET_WEIGHT
    except Exception:
        darts_market, prices, weight = None, None, None
    snapshots = []
    for f in darts:
        fx = f.get("fixture") or {}
        teams = f.get("teams") or []
        if len(teams) != 2:
            continue
        fmt = formats.get(fx.get("id"))
        if fmt is None:
            continue
        market = (darts_market.market_chance(prices, teams[0].get("name"), teams[1].get("name"))
                  if darts_market and prices else None)
        try:
            got = darts_model.markets(r, teams[0].get("id"), teams[1].get("id"), fmt, ts=fx.get("kickoff"))
            if got and market is not None:
                blended = darts_market.blend(got["modelWinA"], market, weight)
                got = darts_model.markets(r, teams[0].get("id"), teams[1].get("id"), fmt,
                                          ts=fx.get("kickoff"), win_override=blended)
                got.update({"marketWinA": round(market, 4), "marketWeight": weight,
                            "priced": prices.get("fetched"),
                            "flag": abs(got["modelWinA"] - market) > darts_market.FLAG})
                snapshots.append({"id": fx.get("id"), "fetched": prices.get("fetched"),
                                  "model": got["modelWinA"], "market": market})
        except Exception:
            got = None
        if got:
            f["dartsModel"] = got
    if snapshots and darts_market:
        try:
            darts_market.log_snapshot(snapshots)
        except OSError:
            pass


def _attach_team_lines(payload: dict) -> None:
    """The team model's numbers for the team lines in markets that passed
    teamline_backtest.py (TEAM-LINES.md): each side's expected count and
    spread on every football fixture, and the passed markets with their
    thresholds. teamValued() calls a team line take only from these. Nothing
    passed, nothing attached; a failure here never costs the report."""
    try:
        import teamlines
        gate = teamlines.page_gate()
    except Exception as exc:
        print(f"  team lines gate skipped: {type(exc).__name__}: {exc}")
        return
    payload["teamLineGate"] = gate
    if not gate["markets"]:
        return
    stats = sorted({k.split("|")[0] for k in gate["markets"]})
    for f in payload.get("fixtures") or []:
        if ((f.get("fixture") or {}).get("sport") or "football") != "football":
            continue
        try:
            models = teamlines.side_models(f, stats)
        except Exception as exc:
            print(f"  team model skipped: {type(exc).__name__}: {exc}")
            return
        if models:
            f["teamModel"] = models


def write_report(payload: dict, path: Path) -> Path:
    _attach_darts(payload)
    _attach_team_lines(payload)
    path.write_text(build_html(payload), encoding="utf-8")
    return path
