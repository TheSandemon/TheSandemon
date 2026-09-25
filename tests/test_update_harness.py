import json
import sys
from pathlib import Path
import unittest
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from datetime import date  # noqa: E402

import chat_svg  # noqa: E402
from update_harness import (  # noqa: E402
    build_conversation, extract_work_items, fun_facts, longest_streak, md, plan_steps, readme_block,
    render_chat, update_readme, wrap,
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
        config = dict(CONFIG, ignored_repos=["secret-sauce"], repo_aliases={"TheSandemon": "Sandemon's Lab"})
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
    "activity": "BUILDING", "contributions_7d": 9, "prs_7d": 3, "total_6mo": 1234, "peak_day": 20,
    "active_days": 40, "days": [{"count": 1}, {"count": 2}, {"count": 0}, {"count": 3}, {"count": 4}, {"count": 5}],
}
LAB_SNAPSHOT = {"repos": [
    {"name": "godotion", "language": "GDScript", "fork": False, "pushed_at": "2026-08-10T00:00:00Z",
     "description": "Motion graphics for Godot", "stars": 2},
    {"name": "TheSandemon", "language": "Python", "fork": False, "pushed_at": "2026-09-24T00:00:00Z"},
    {"name": "someones-game", "language": "TypeScript", "fork": True, "pushed_at": "2026-09-09T00:00:00Z"},
    {"name": "hidden-thing", "language": "Go", "fork": False, "private": True, "description": "Top secret"},
]}
TODAY = date(2026, 9, 25)


class ChatCase(unittest.TestCase):
    def setUp(self):
        commits = [commit(f"Add change number {i} <b>&", repo=f"TheSandemon/repo{i % 3}", sha=f"{i:07d}abc",
                          date=f"2026-09-{10 + i}T22:30:00-05:00") for i in range(14)]
        pulls = [
            pull(9, "Tune <the> reactor & friends", body="- Plan A\n- Plan B",
                 files=["scripts/update_lab.py", "tests/test_update_lab.py", "README.md"]),
            pull(8, "Draft pipeline", body="- Build it", merged=None, files=["src/app.ts"]),
        ]
        pulls[1].update(state="draft", updated_at="2026-09-10T00:00:00Z")
        self.work = extract_work_items({"pulls": pulls, "commits": commits}, CONFIG)
        self.config = dict(CONFIG, fun_facts=["Hand-written fact one", "Hand-written fact two"])
        self.steps = build_conversation(self.work, self.config, LAB_STATE, LAB_SNAPSHOT, TODAY)
        self.svg = render_chat(self.steps, self.config, TODAY)

    def questions(self, steps):
        return [step[1] for step in steps if step[0] == "user"]


class ConversationTests(ChatCase):
    def test_intro_first_contact_last_and_middle_reshuffles_by_day(self):
        questions = self.questions(self.steps)
        by_id = {b["id"]: b for b in CONFIG["beats"]}
        self.assertEqual(questions[0], by_id["intro"]["question"])
        self.assertEqual(questions[-1], by_id["contact"]["question"])
        again = build_conversation(self.work, self.config, LAB_STATE, LAB_SNAPSHOT, TODAY)
        self.assertEqual(again, self.steps)
        orders = {tuple(self.questions(build_conversation(self.work, self.config, LAB_STATE, LAB_SNAPSHOT,
                                                          date(2026, 9, day)))) for day in range(1, 8)}
        self.assertGreater(len(orders), 1)

    def test_answers_come_from_real_work_config_and_linkedin(self):
        text = " ".join(
            "".join(t for t, _ in seg) for step in self.steps if step[0] in ("say", "bullets") for seg in step[1]
        )
        self.assertIn("Tune <the> reactor & friends", text)
        self.assertIn("Plan A", text)
        self.assertIn(CONFIG["about"]["name"], text)
        self.assertIn(CONFIG["about"]["career"][0]["org"], text)
        self.assertIn("Motion graphics for Godot", text)
        self.assertIn("Hand-written fact two", text)
        self.assertNotIn("Top secret", text)
        self.assertNotIn("someones-game", text)
        self.assertIn("<the>", "".join(str(s) for s in self.steps))
        self.assertNotIn("<the>", self.svg)
        self.assertIn(">&lt;the&gt; <", self.svg)

    def test_empty_beats_are_skipped(self):
        steps = build_conversation(self.work, dict(CONFIG, fun_facts=[]), {}, {}, TODAY)
        joined = str(steps)
        self.assertNotIn("contributions, 6 mo", joined)
        fun = next(b for b in CONFIG["beats"] if b["id"] == "fun")
        self.assertNotIn(fun["questions"][0], self.questions(steps))
        with self.assertRaises(RuntimeError):
            build_conversation(self.work, dict(CONFIG, beats=[]), {}, {}, TODAY)

    def test_fun_facts_come_from_real_activity(self):
        facts = fun_facts(self.work, LAB_STATE, LAB_SNAPSHOT, dict(CONFIG, fun_facts=["Hand-written fact"]))
        self.assertEqual(facts[0], "Hand-written fact")
        self.assertIn("Night-owl index: 100% of commits arrive after 9pm.", facts)
        self.assertIn("Longest streak in six months: 3 days in a row.", facts)
        self.assertEqual(longest_streak([]), 0)
        self.assertTrue(any(f.startswith("Speaks GDScript, Python") for f in facts))

    def test_pinned_and_hand_written_answers(self):
        config = dict(CONFIG, beats=[
            {"id": "intro", "question": "first"},
            {"id": "a", "type": "qa", "question": "pinned second", "pinned": True, "say": ["**Yes.**"]},
            *[{"id": f"q{i}", "type": "qa", "question": f"loose {i}", "say": [f"answer {i}"]} for i in range(6)],
            {"id": "empty", "type": "qa", "question": "nothing to say"},
            {"id": "contact", "question": "last"},
        ])
        for day in range(1, 6):
            questions = self.questions(build_conversation(self.work, config, {}, {}, date(2026, 9, day)))
            self.assertEqual(questions[:2], ["first", "pinned second"])
            self.assertEqual(questions[-1], "last")
            self.assertNotIn("nothing to say", questions)
        steps = build_conversation(self.work, config, {}, {}, TODAY)
        self.assertIn(("say", [[("Yes.", "b")]]), steps)

    def test_markdown_segments(self):
        self.assertEqual(md("a **b** `c` d"), [("a ", "r"), ("b", "b"), (" ", "r"), ("c", "m"), (" d", "r")])


class RenderTests(ChatCase):
    def test_every_animation_loops_forever_on_one_cycle(self):
        motion = animations(self.svg)
        self.assertTrue(motion)
        self.assertTrue(all(node.attrib.get("repeatCount") == "indefinite" for node in motion))
        cycles = {node.attrib["dur"] for node in motion if "keyTimes" in node.attrib and node.attrib.get("calcMode") == "discrete"}
        self.assertEqual(len(cycles), 1)

    def test_loop_seam_scrolls_exactly_one_conversation(self):
        items, scroll, inputs, total, cycle = chat_svg.layout(self.steps)
        self.assertEqual(scroll[0], (0.0, 0.0))
        self.assertEqual(scroll[-1], (cycle, total))
        self.assertEqual(len(inputs), len(self.questions(self.steps)))
        self.assertIn(f'translate(0 {-total:.1f})', self.svg)
        offsets = [offset for _, offset in scroll]
        self.assertEqual(offsets, sorted(offsets))

    def test_lines_fit_and_words_stream_in_order(self):
        items, _, _, _, _ = chat_svg.layout(self.steps)
        lines = [item for item in items if item["kind"] == "line"]
        self.assertTrue(lines)
        for line in lines:
            end = max(x + chat_svg.width(t.rstrip(), s) for t, s, x in line["tokens"])
            self.assertLessEqual(line["x0"] - chat_svg.TX + end, chat_svg.TMAX + 0.5)
            times = [t for t, _ in line["stamps"]]
            self.assertEqual(times, sorted(times))

    def test_text_only_uses_embedded_glyphs(self):
        self.assertEqual(chat_svg.safe("café ✨ naïve"), "café  naïve")
        self.assertIn("@font-face{font-family:SandSans", self.svg)
        ElementTree.fromstring(self.svg)

    def test_readme_block_replaces_only_marked_section(self):
        readme = "top\n<!-- harness:start -->\nold\n<!-- harness:end -->\nbottom\n"
        updated = update_readme(readme, readme_block(self.svg))
        self.assertTrue(updated.startswith("top\n<!-- harness:start -->\n<img src=\"assets/harness-chat.svg\""))
        self.assertTrue(updated.endswith("<!-- harness:end -->\nbottom\n"))
        self.assertNotIn("old", updated)
        self.assertEqual(update_readme(updated, readme_block(self.svg)), updated)
        with self.assertRaises(RuntimeError):
            update_readme("no markers", readme_block(self.svg))

    def test_committed_readme_shows_only_the_chat(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("assets/harness-chat.svg", readme)
        self.assertNotIn("lab.svg", readme)
        self.assertTrue((ROOT / "assets" / "harness-chat.svg").exists())
        self.assertFalse((ROOT / "assets" / "lab.svg").exists())


if __name__ == "__main__":
    unittest.main()
