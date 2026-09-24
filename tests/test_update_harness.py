import json
import sys
from pathlib import Path
import unittest
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from update_harness import (  # noqa: E402
    extract_work_items, plan_steps, readme_block, render_panels, update_readme, wrap,
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


class RenderTests(unittest.TestCase):
    def setUp(self):
        commits = [commit(f"Change number {i} <b>&", repo=f"TheSandemon/repo{i % 3}", sha=f"{i:07d}abc")
                   for i in range(14)]
        pulls = [
            pull(9, "Tune <the> reactor & friends", body="- Plan A\n- Plan B",
                 files=["scripts/update_lab.py", "tests/test_update_lab.py", "README.md"]),
            pull(8, "Draft pipeline", body="- Build it", merged=None,
                 files=["src/app.ts", "src/app.test.ts"]),
        ]
        pulls[1].update(state="draft", updated_at="2026-09-10T00:00:00Z")
        self.work = extract_work_items({"pulls": pulls, "commits": commits}, CONFIG)
        self.panels = render_panels(self.work, CONFIG)

    def test_every_panel_is_valid_escaped_and_loops_forever(self):
        self.assertEqual([p["id"] for p, _ in self.panels], ["chat", "terminal", "flow"])
        for panel, svg in self.panels:
            with self.subTest(panel=panel["id"]):
                self.assertNotIn("<the>", svg)
                self.assertNotIn("<b>", svg)
                motion = animations(svg)
                self.assertGreaterEqual(len(motion), 3)
                self.assertTrue(all(node.attrib.get("repeatCount") == "indefinite" for node in motion))

    def test_panels_show_real_work_text(self):
        chat, terminal, flow = (svg for _, svg in self.panels)
        self.assertIn("Tune &lt;the&gt; reactor &amp; friends", chat)
        self.assertIn("Plan A", chat)
        self.assertIn("Change number 0", terminal)
        self.assertIn("animateTransform", terminal)  # a long commit list scrolls in a loop
        self.assertIn("Draft pipeline", flow)
        self.assertIn("app.test.ts", flow)

    def test_panel_order_and_hidden_panels_follow_config(self):
        config = dict(CONFIG, panels=[{"id": "flow", "type": "flow"}, {"id": "chat", "type": "chat", "hidden": True}])
        self.assertEqual([p["id"] for p, _ in render_panels(self.work, config)], ["flow"])
        with self.assertRaises(RuntimeError):
            render_panels(self.work, dict(CONFIG, panels=[{"id": "../x", "type": "chat"}]))

    def test_readme_block_replaces_only_marked_section(self):
        readme = "top\n<!-- harness:start -->\nold\n<!-- harness:end -->\nbottom\n"
        updated = update_readme(readme, readme_block(self.panels))
        self.assertTrue(updated.startswith("top\n<!-- harness:start -->\n<img src=\"assets/harness-chat.svg\""))
        self.assertTrue(updated.endswith("<!-- harness:end -->\nbottom\n"))
        self.assertNotIn("old", updated)
        self.assertEqual(update_readme(updated, readme_block(self.panels)), updated)
        with self.assertRaises(RuntimeError):
            update_readme("no markers", readme_block(self.panels))

    def test_committed_readme_matches_committed_panels(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for panel in CONFIG["panels"]:
            self.assertIn(f"assets/harness-{panel['id']}.svg", readme)
            self.assertTrue((ROOT / "assets" / f"harness-{panel['id']}.svg").exists())


if __name__ == "__main__":
    unittest.main()
