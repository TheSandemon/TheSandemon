import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from update_lab import compute_state, render_svg  # noqa: E402


CONFIG = {
    "profile_repo": "TheSandemon",
    "quiet_max_events_7d": 0,
    "tinkering_max_events_7d": 3,
    "building_max_events_7d": 12,
    "focus_aliases": {},
}
NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def event(days_ago=0, repo="TheSandemon/project"):
    return {
        "type": "PushEvent",
        "created_at": (NOW - timedelta(days=days_ago)).isoformat(),
        "repo": {"name": repo},
    }


class LabTests(unittest.TestCase):
    def test_activity_thresholds_and_old_events(self):
        expected = [(0, "SLEEPING"), (1, "TINKERING"), (3, "TINKERING"),
                    (4, "BUILDING"), (12, "BUILDING"), (13, "OVERCLOCKED")]
        for count, label in expected:
            with self.subTest(count=count):
                snapshot = {"events": [event()] * count + [event(days_ago=8)], "workflow": "success"}
                state = compute_state(snapshot, CONFIG, NOW)
                self.assertEqual(state["activity"], label)
                self.assertEqual(state["events_7d"], count)

    def test_warning_and_svg_text_escaping(self):
        snapshot = {"events": [event(repo="TheSandemon/a&b<test>")], "workflow": "failure"}
        state = compute_state(snapshot, CONFIG, NOW)
        self.assertEqual(state["condition"], "WARNING")
        svg = render_svg(state)
        self.assertIn("A&amp;B&lt;TEST&gt;", svg)
        self.assertNotIn("repeatCount=\"1\"", svg)
        ElementTree.fromstring(svg)


if __name__ == "__main__":
    unittest.main()
