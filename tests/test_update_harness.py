import json
import sys
from pathlib import Path
import unittest
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from update_harness import (  # noqa: E402
    build_scenes, extract_work_items, fun_facts, longest_streak, plan_steps, readme_block, render_chat,
    rotation, update_readme, wrap,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "profile-visuals.json").read_text(encoding="utf-8"))


def pull(number, title, body="", repo="TheSandemon/TheSandemon", merged="2026-09-20T00:00:00Z", files=()):
    return {
        "repo": repo, "number": number, "title": title, "body": body, "state": "closed",
        "merged_at": merged, "updated_at": "2026-09-21T00:00:00Z", "url": "",
        "files": [{"name": name, "additions": 3, "deletions": 1} for name in files],
    }


def commit(message, repo="TheSandemon/TheSandemon", date="2026-09-22T00:00:00Z", private=False, sha="abcdef1234"):
    return {"repo": repo, "private": private, "sha": sha, "message": message, "date": date, "url": ""}


def animations(svg):
    root = ElementTree.fromstring(svg)
    return [node for node in root.iter() if node.tag.rsplit("}", 1)[-1].startswith("animate")]


class ExtractionTests(unittest.TestCase):
    def test_plan_steps_prefer_bullets_and_strip_markdown(self):
        body = "## Summary\n- Add **bold** [link](http://x) step\n* Keep `code` names\n1. Third\n- Fourth"
        self.assertEqual(plan_steps(body), ["Add bold link step", "Keep code names", "Third"])
        self.assertEqual(plan_steps("One sentence. Two sentence."), ["One sentence.", "Two sentence."])

    def test_plan_steps_skip_attribution_and_lead_with_after(self):
        body = ('<!-- ccr-projects-attribution: {"x": 1} -->\n_Requested by **Sand** · [thread](http://x)_\n\n'
                "Before: the old lab.\n\nAfter: the new lab glows. It hums.\n\n🤖 Generated with Claude Code\n")
        self.assertEqual(plan_steps(body), ["The new lab glows.", "It hums."])

    def test_wrap_marks_truncation(self):
        lines = wrap("alpha beta gamma delta epsilon", 11, 2)
        self.assertEqual(lines[0], "alpha beta")
        self.assertTrue(lines[-1].endswith("…"))
        self.assertTrue(all(len(line) <= 11 for line in lines))

    def test_filters_ignored_private_and_aliases_repos(self):
        config = dict(CONFIG, ignored_repos=["secret-sauce"])
        snapshot = {
            "pulls": [pull(1, "Old work"), pull(7, "Ignored", repo="TheSandemon/secret-sauce"),
                      pull(3, "Upstream fix", repo="octo/tool", merged=None)],
            "commits": [
                commit("Update lab status"),
                commit("Private thing", private=True),
                commit("Merge pull request #4 from x/y"),
                commit("Real change\n\nlong body"),
            ],
        }
        work = extract_work_items(snapshot, config)
        self.assertEqual([t["title"] for t in work["tasks"]], ["Upstream fix", "Old work"])
        self.assertEqual(work["tasks"][0]["repo"], "octo/tool")
        self.assertEqual(work["tasks"][1]["repo"], "Sandemon's Lab")
        self.assertEqual([c["message"] for c in work["commits"]], ["Real change"])

    def test_featured_and_summary_overrides_win(self):
        config = dict(CONFIG, featured=["TheSandemon#1"], summaries={"TheSandemon#1": "Curated summary"})
        snapshot = {"pulls": [pull(2, "Newer", files=["a.py"]), pull(1, "Pinned", body="- raw step")], "commits": []}
        work = extract_work_items(snapshot, config)
        self.assertEqual(work["tasks"][0]["title"], "Pinned")
        self.assertEqual(work["tasks"][0]["steps"], ["Curated summary"])

    def test_commit_only_history_still_makes_a_task(self):
        work = extract_work_items({"pulls": [], "commits": [commit("Ship it")]}, CONFIG)
        self.assertEqual(work["tasks"][0]["state"], "pushed")
        self.assertEqual(work["tasks"][0]["title"], "Ship it")

    def test_nothing_left_after_filtering_is_an_error(self):
        with self.assertRaises(RuntimeError):
            extract_work_items({"pulls": [], "commits": [commit("Update lab status")]}, CONFIG)


LAB_STATE = {
    "activity": "BUILDING", "condition": "STABLE", "mode": "SHIPPING", "focus": "THE LAB",
    "machines": [{}, {}], "machine_slots": 5, "contributions_7d": 9, "contributions_24h": 2,
    "prs_7d": 3, "repos_touched_7d": 2, "workflow": "success", "total_6mo": 1234, "peak_day": 20,
    "active_days": 40, "days": [{"count": 1}, {"count": 2}, {"count": 0}, {"count": 3}, {"count": 4}, {"count": 5}],
}
LAB_SNAPSHOT = {"repos": [
    {"name": "godotion", "language": "GDScript", "fork": False, "pushed_at": "2026-08-10T00:00:00Z"},
    {"name": "TheSandemon", "language": "Python", "fork": False, "pushed_at": "2026-09-24T00:00:00Z"},
    {"name": "someones-game", "language": "TypeScript", "fork": True, "pushed_at": "2026-09-09T00:00:00Z"},
]}


class RenderTests(unittest.TestCase):
    def setUp(self):
        commits = [commit(f"Add change number {i} <b>&", repo=f"TheSandemon/repo{i % 3}", sha=f"{i:07d}abc",
                          date=f"2026-09-{10 + i}T22:30:00-05:00") for i in range(14)]
        pulls = [
            pull(9, "Tune <the> reactor & friends", body="- Plan A\n- Plan B",
                 files=["scripts/update_lab.py", "tests/test_update_lab.py", "README.md"]),
            pull(8, "Draft pipeline", body="- Build it", merged=None,
                 files=["src/app.ts", "src/app.test.ts"]),
        ]
        pulls[1].update(state="draft", updated_at="2026-09-10T00:00:00Z")
        self.work = extract_work_items({"pulls": pulls, "commits": commits}, CONFIG)
        self.scenes = build_scenes(self.work, CONFIG, LAB_STATE, LAB_SNAPSHOT)
        self.svg = render_chat(self.scenes, self.work, CONFIG, LAB_STATE)

    def test_one_chat_rotates_through_every_configured_scene(self):
        self.assertEqual([s["id"] for s in self.scenes], [s["id"] for s in CONFIG["scenes"]])
        root = ElementTree.fromstring(self.svg)
        motion = animations(self.svg)
        self.assertTrue(all(node.attrib.get("repeatCount") == "indefinite" for node in motion))
        cycle = f"{7 * len(self.scenes):g}s"
        rotating = [node for node in motion if node.attrib.get("dur") == cycle]
        self.assertEqual(len(rotating), 3 * len(self.scenes))  # scene, sidebar topic and progress dot
        self.assertIsNotNone(root)

    def test_first_frame_shows_only_the_first_scene(self):
        self.assertIn('values="1;1;0;0;1"', rotation(0, 3, 21))
        self.assertIn('values="0;0;1;1;0;0"', rotation(1, 3, 21))
        self.assertIn('values="0;0;1;1;0"', rotation(2, 3, 21))
        self.assertEqual(rotation(0, 1, 7), "")

    def test_chat_mixes_real_work_and_fun_about_sand(self):
        self.assertNotIn("<the>", self.svg)
        self.assertNotIn("<b>", self.svg)
        self.assertIn("Tune &lt;the&gt; reactor &amp; friends", self.svg)
        self.assertIn("Plan A", self.svg)
        self.assertIn("Add change number 13", self.svg)
        self.assertIn("Draft pipeline", self.svg)
        self.assertIn("app.test.ts", self.svg)
        self.assertIn(CONFIG["about"]["name"], self.svg)
        self.assertIn("godotion", self.svg)
        self.assertIn("forked for fun: someones-game", self.svg)
        self.assertIn("2 of 5 machine bays lit", self.svg)
        self.assertIn('"add" (14 times)', self.svg)

    def test_fun_facts_come_from_real_activity(self):
        facts = fun_facts(self.work, LAB_STATE, LAB_SNAPSHOT, dict(CONFIG, fun_facts=["Hand-written fact"]))
        self.assertEqual(facts[0], "Hand-written fact")
        self.assertIn("Night-owl index: 100% of commits arrive after 9pm.", facts)
        self.assertIn("Longest streak in six months: 3 days in a row.", facts)
        self.assertEqual(longest_streak([]), 0)
        self.assertTrue(any(f.startswith("Speaks GDScript, Python") for f in facts))

    def test_scene_order_hidden_scenes_and_missing_lab_data(self):
        config = dict(CONFIG, scenes=[{"id": "shipped"}, {"id": "building", "hidden": True}, {"id": "lab"}, {"id": "nope"}])
        self.assertEqual([s["id"] for s in build_scenes(self.work, config, {}, {})], ["shipped"])
        with self.assertRaises(RuntimeError):
            build_scenes(self.work, dict(CONFIG, scenes=[]), {}, {})

    def test_no_line_overflows_the_bubble(self):
        for scene in self.scenes:
            for kind, value in scene["lines"]:
                if kind != "stages":
                    self.assertLessEqual(len(value), 98, value)

    def test_readme_block_replaces_only_marked_section(self):
        readme = "top\n<!-- harness:start -->\nold\n<!-- harness:end -->\nbottom\n"
        updated = update_readme(readme, readme_block(self.svg))
        self.assertTrue(updated.startswith("top\n<!-- harness:start -->\n<img src=\"assets/harness-chat.svg\""))
        self.assertTrue(updated.endswith("<!-- harness:end -->\nbottom\n"))
        self.assertNotIn("old", updated)
        self.assertEqual(update_readme(updated, readme_block(self.svg)), updated)
        with self.assertRaises(RuntimeError):
            update_readme("no markers", readme_block(self.svg))

    def test_committed_readme_points_at_the_single_chat(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("assets/harness-chat.svg", readme)
        self.assertNotIn("harness-terminal", readme)
        self.assertNotIn("harness-flow", readme)
        self.assertTrue((ROOT / "assets" / "harness-chat.svg").exists())


if __name__ == "__main__":
    unittest.main()
