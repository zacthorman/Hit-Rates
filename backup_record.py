"""Nightly copy of the bet record to iCloud Drive.

pplog/ and linelog/ are gitignored, so before 16 Nov 2026 the paper-trade
record existed only on this Mac. update.py runs this first thing every
morning, before anything settles or rewrites them. Never fatal.

Writes ~/Library/Mobile Documents/com~apple~CloudDocs/Hit-Rates backups/
hit-rates-bet-record-YYYY-MM-DD.tar.gz and keeps the newest KEEP of them.
Override the folder with HITRATES_BACKUP_DIR.
"""
from __future__ import annotations

import os
import sys
import tarfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
KEEP = 14
FOLDERS = ["pplog", "linelog", "selections"]
DEST = Path(os.environ.get(
    "HITRATES_BACKUP_DIR",
    Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Hit-Rates backups"))


def main() -> int:
    icloud = DEST.parent
    if "HITRATES_BACKUP_DIR" not in os.environ and not icloud.exists():
        print(f"backup: iCloud Drive not found at {icloud}, nothing copied")
        return 1
    DEST.mkdir(parents=True, exist_ok=True)
    out = DEST / f"hit-rates-bet-record-{date.today().isoformat()}.tar.gz"
    tmp = out.with_suffix(".partial")
    with tarfile.open(tmp, "w:gz") as tar:
        for name in FOLDERS:
            if (ROOT / name).exists():
                tar.add(ROOT / name, arcname=name)
    tmp.replace(out)
    print(f"backup: {out.name}, {out.stat().st_size / 1e6:.1f} MB to iCloud Drive")
    old = sorted(DEST.glob("hit-rates-bet-record-*.tar.gz"))[:-KEEP]
    for f in old:
        try:
            f.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
