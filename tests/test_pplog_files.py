"""pplog reads only its own month files, never other tools' logs in the folder."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pplog  # noqa: E402


class OwnFiles(unittest.TestCase):
    def test_team_and_pinnacle_logs_are_left_out(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "2026-11.jsonl").write_text(json.dumps({"event_id": 1, "player": "A"}) + "\n")
            (d / "team-2026-11.jsonl").write_text(json.dumps({"team": "X"}) + "\n")
            (d / "pinnacle-2026-11.jsonl").write_text(json.dumps({"gid": "1", "kind": "game"}) + "\n")
            keep, pplog.DIR = pplog.DIR, d
            try:
                self.assertEqual([p.name for p in pplog._files()], ["2026-11.jsonl"])
                self.assertEqual(len(pplog.all_rows()), 1)
            finally:
                pplog.DIR = keep


if __name__ == "__main__":
    unittest.main()
