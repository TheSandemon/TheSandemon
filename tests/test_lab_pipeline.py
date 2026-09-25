import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from update_lab import compute_state, fetch_stage  # noqa: E402


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

    def test_state_survives_json_round_trip(self):
        state = compute_state(json.loads(FIXTURE.read_text()), CONFIG, NOW)
        self.assertEqual(json.loads(json.dumps(state, default=str))["total_6mo"], state["total_6mo"])

    def test_fetch_keeps_public_repo_descriptions_for_the_chat(self):
        raw = {"name": "godotion", "pushed_at": "2026-08-10T00:00:00Z", "language": "GDScript", "fork": False,
               "archived": False, "private": False, "description": "Timeline editor", "stargazers_count": 1}
        self.assertEqual(fetch_stage.trim_repo(raw)["description"], "Timeline editor")
        self.assertEqual(fetch_stage.trim_repo(raw)["stars"], 1)
        self.assertEqual(fetch_stage.trim_repo({"name": "x"})["description"], "")

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
