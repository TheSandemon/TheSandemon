import sys
from datetime import datetime, timezone
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from update_lab import compute_state, six_month_start  # noqa: E402


CONFIG = {
    "profile_repo": "TheSandemon",
    "idle_max_contributions_7d": 0,
    "tinkering_max_contributions_7d": 12,
    "building_max_contributions_7d": 45,
    "focus_aliases": {},
}
NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


class LabTests(unittest.TestCase):
    def test_calendar_month_subtraction_at_short_month(self):
        self.assertEqual(six_month_start(NOW.date()).isoformat(), "2026-03-24")
        self.assertEqual(
            six_month_start(datetime(2026, 8, 31, tzinfo=timezone.utc).date()).isoformat(),
            "2026-02-28",
        )

    def test_backfills_entire_window_and_ignores_older_history(self):
        snapshot = {
            "contributions": [
                {"date": "2026-03-23", "count": 100},
                {"date": "2026-03-24", "count": 3},
                {"date": "2026-09-24", "count": 2},
            ],
            "events": [],
            "workflow": "success",
        }
        state = compute_state(snapshot, CONFIG, NOW)
        self.assertEqual(len(state["days"]), 185)
        self.assertEqual(state["days"][0], {"date": "2026-03-24", "count": 3})
        self.assertEqual(state["days"][-1], {"date": "2026-09-24", "count": 2})
        self.assertEqual(state["total_6mo"], 5)
        self.assertEqual(state["active_days"], 2)
        self.assertEqual(state["contributions_7d"], 2)

    def test_failed_workflow_marks_warning(self):
        snapshot = {
            "contributions": [{"date": "2026-09-24", "count": 2}],
            "events": [{"created_at": "2026-09-24T00:00:00Z", "repo": {"name": "TheSandemon/a&b"}}],
            "workflow": "failure",
        }
        self.assertEqual(compute_state(snapshot, CONFIG, NOW)["condition"], "WARNING")

if __name__ == "__main__":
    unittest.main()
