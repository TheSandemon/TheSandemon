import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import unittest
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from update_lab import compute_state, fetch_stage, render_svg  # noqa: E402


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "snapshot.json"
CONFIG = {
    "username": "TheSandemon",
    "profile_repo": "TheSandemon",
    "idle_max_contributions_7d": 0,
    "tinkering_max_contributions_7d": 12,
    "building_max_contributions_7d": 45,
    "focus_aliases": {"TheSandemon": "THE LAB"},
    "machine_slots": 5,
    "ignore_repos": ["noise"],
}
NOW = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)


def busy_snapshot() -> dict:
    return {
        "contributions": [{"date": "2026-09-23", "count": 60}],
        "workflow": "failure",
        "repos": [
            {"name": "quiet-tool", "pushed_at": "2026-09-15T00:00:00Z", "language": "Go"},
            {"name": "old-thing", "pushed_at": "2026-01-01T00:00:00Z", "language": "C"},
        ],
        "events": [
            {"type": "PushEvent", "created_at": "2026-09-23T10:00:00Z", "repo": "TheSandemon/alpha", "size": 6},
            {"type": "PullRequestEvent", "created_at": "2026-09-22T10:00:00Z", "repo": "TheSandemon/beta",
             "action": "closed", "merged": True},
            {"type": "PushEvent", "created_at": "2026-09-21T10:00:00Z", "repo": "TheSandemon/noise", "size": 99},
            {"type": "PushEvent", "created_at": "2026-08-01T10:00:00Z", "repo": "TheSandemon/ancient", "size": 9},
        ],
    }


class PipelineTests(unittest.TestCase):
    def test_machines_follow_recent_repos_and_skip_ignored_or_stale(self):
        state = compute_state(busy_snapshot(), CONFIG, NOW)
        repos = [machine["repo"] for machine in state["machines"]]
        self.assertEqual(repos, ["alpha", "beta", "quiet-tool"])
        self.assertEqual(state["machines"][0]["energy"], 4)
        self.assertEqual(state["machines"][-1]["language"], "GO")
        self.assertEqual(state["activity"], "OVERCLOCKED")
        self.assertEqual(state["condition"], "CRITICAL")
        self.assertEqual(state["mode"], "SHIPPING")
        self.assertTrue(state["log"][0].startswith("09-23 PUSH"))

    def test_state_survives_json_round_trip_and_log_loops_seamlessly(self):
        state = compute_state(json.loads(FIXTURE.read_text()), CONFIG, NOW)
        svg = render_svg(json.loads(json.dumps(state, default=str)))
        root = ElementTree.fromstring(svg)
        animations = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1].startswith("animate")]
        self.assertTrue(all(node.attrib.get("repeatCount") == "indefinite" for node in animations))
        self.assertIn("1/5 BAYS ONLINE", svg)
        self.assertEqual(svg.count("BAY OFFLINE"), 4)
        self.assertIn("THE LAB", svg)

    def test_every_condition_and_activity_renders(self):
        base = compute_state(json.loads(FIXTURE.read_text()), CONFIG, NOW)
        for activity in ("SLEEPING", "TINKERING", "BUILDING", "OVERCLOCKED"):
            for condition in ("STABLE", "ENERGIZED", "WARNING", "CRITICAL"):
                ElementTree.fromstring(render_svg({**base, "activity": activity, "condition": condition}))

    def test_fetch_trims_events_to_the_fields_the_lab_reads(self):
        raw = {
            "type": "PushEvent", "created_at": "2026-09-24T00:00:00Z",
            "repo": {"name": "TheSandemon/alpha", "url": "https://example.invalid"},
            "actor": {"login": "TheSandemon"}, "payload": {"size": 3, "commits": [{}, {}, {}]},
        }
        self.assertEqual(
            fetch_stage.trim_event(raw),
            {"type": "PushEvent", "created_at": "2026-09-24T00:00:00Z", "repo": "TheSandemon/alpha", "size": 3},
        )
        self.assertIsNone(fetch_stage.trim_event({"type": "PushEvent"}))


if __name__ == "__main__":
    unittest.main()
