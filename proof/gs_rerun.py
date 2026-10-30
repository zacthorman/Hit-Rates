"""Rerun gs_backtest.py build and test without touching the committed fit.

    python3 -B proof/gs_rerun.py <outdir> <tag>

Same code as gs_backtest.py, but the dataset, gs_fit.json and GS_BACKTEST.md
go to <outdir>, and copies of the fit and report land in proof/ as
gs_fit.rerun-<tag>.json and GS_BACKTEST.rerun-<tag>.md. The fit the pages use
is left exactly as committed.
"""
import shutil, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import gs_backtest as G
out, tag = Path(sys.argv[1]), sys.argv[2]
out.mkdir(parents=True, exist_ok=True)
G.DATA, G.FIT, G.REPORT = out / "gs_dataset.json", out / "gs_fit.json", out / "GS_BACKTEST.md"
t = time.time(); G.build(); print(f"build done {time.time()-t:.0f}s", flush=True)
t = time.time(); G.test(); print(f"test done {time.time()-t:.0f}s", flush=True)
shutil.copy(G.FIT, ROOT / "proof" / f"gs_fit.rerun-{tag}.json")
shutil.copy(G.REPORT, ROOT / "proof" / f"GS_BACKTEST.rerun-{tag}.md")
print("copied", flush=True)
