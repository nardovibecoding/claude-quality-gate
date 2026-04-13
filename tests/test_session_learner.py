# Copyright (c) 2026 Nardo (nardovibecoding). AGPL-3.0 — see LICENSE
"""Tests for session_learner.py — stdlib unittest only."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import session_learner as sl


class TestSkipFilter(unittest.TestCase):

    def test_memory_dir_skipped(self):
        self.assertTrue(sl._skip("/home/user/project/memory/foo.md"))

    def test_memory_md_skipped(self):
        self.assertTrue(sl._skip("/home/user/.claude/MEMORY.md"))

    def test_plans_skipped(self):
        self.assertTrue(sl._skip("/Users/bernard/.claude/plans/my-plan.md"))

    def test_task_plan_skipped(self):
        self.assertTrue(sl._skip("/project/task_plan.md"))

    def test_tmp_skipped(self):
        self.assertTrue(sl._skip("/tmp/something.json"))

    def test_normal_py_not_skipped(self):
        self.assertFalse(sl._skip("/project/bot_base.py"))

    def test_normal_js_not_skipped(self):
        self.assertFalse(sl._skip("/project/app.js"))


class TestEditLogPath(unittest.TestCase):

    def test_with_session_id(self):
        path = sl._edit_log_path("abc123")
        self.assertEqual(path.name, "claude_edits_abc123.json")

    def test_without_session_id(self):
        path = sl._edit_log_path(None)
        self.assertEqual(path.name, "claude_edits_this_turn.json")

    def test_slashes_replaced(self):
        path = sl._edit_log_path("a/b/c")
        self.assertNotIn("/", path.name.replace(str(path.parent), ""))


class TestMain(unittest.TestCase):

    def _run_main(self, session_id, edits, learnings_file):
        """Helper: write edit log, run main, return learnings content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write edit log
            log_path = Path(tmpdir) / f"claude_edits_{session_id}.json"
            log_path.write_text(json.dumps(edits))

            with patch("session_learner._EDIT_LOG_DIR", Path(tmpdir)), \
                 patch("session_learner._LEARNINGS_FILE", learnings_file):
                try:
                    stdin_data = json.dumps({"session_id": session_id})
                    with patch("sys.stdin") as mock_stdin:
                        mock_stdin.read.return_value = stdin_data
                        sl.main()
                except SystemExit:
                    pass

    def test_fewer_than_3_edits_writes_nothing(self):
        edits = [
            {"file": "/proj/a.py", "functions": ["foo"], "ts": 1},
            {"file": "/proj/b.py", "functions": [], "ts": 2},
        ]
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            out = Path(f.name)
        try:
            self._run_main("sess1", edits, out)
            self.assertEqual(out.read_text(), "")
        finally:
            out.unlink(missing_ok=True)

    def test_3_or_more_edits_writes_entry(self):
        edits = [
            {"file": "/proj/a.py", "functions": ["handle_msg"], "ts": 1},
            {"file": "/proj/b.py", "functions": [], "ts": 2},
            {"file": "/proj/c.py", "functions": ["setup"], "ts": 3},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "session_learnings.md"
            out.touch()
            self._run_main("sess2", edits, out)
            content = out.read_text()
        self.assertIn("a.py", content)
        self.assertIn("handle_msg", content)
        self.assertIn("c.py", content)

    def test_memory_files_excluded_from_count(self):
        edits = [
            {"file": "/proj/memory/foo.md", "functions": [], "ts": 1},
            {"file": "/proj/memory/bar.md", "functions": [], "ts": 2},
            {"file": "/proj/a.py", "functions": [], "ts": 3},
            {"file": "/proj/b.py", "functions": [], "ts": 4},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "session_learnings.md"
            out.touch()
            self._run_main("sess3", edits, out)
            content = out.read_text()
        # Only 2 non-memory files → below threshold of 3 → nothing written
        self.assertEqual(content, "")

    def test_entry_has_date_header(self):
        edits = [
            {"file": f"/proj/{i}.py", "functions": [], "ts": i}
            for i in range(4)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "session_learnings.md"
            out.touch()
            self._run_main("sess4", edits, out)
            content = out.read_text()
        import re
        self.assertRegex(content, r"## \d{4}-\d{2}-\d{2}")

    def test_deduplicates_same_file(self):
        edits = [
            {"file": "/proj/a.py", "functions": ["v1"], "ts": 1},
            {"file": "/proj/a.py", "functions": ["v2"], "ts": 2},  # later wins
            {"file": "/proj/b.py", "functions": [], "ts": 3},
            {"file": "/proj/c.py", "functions": [], "ts": 4},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "session_learnings.md"
            out.touch()
            self._run_main("sess5", edits, out)
            content = out.read_text()
        # a.py should appear once
        self.assertEqual(content.count("a.py"), 1)
        self.assertIn("v2", content)

    def test_bad_stdin_exits_silently(self):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = "not json"
            try:
                sl.main()
            except SystemExit as e:
                self.assertEqual(e.code, 0)

    def test_missing_log_exits_silently(self):
        stdin_data = json.dumps({"session_id": "nonexistent_session_xyz"})
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = stdin_data
            try:
                sl.main()
            except SystemExit as e:
                self.assertEqual(e.code, 0)


if __name__ == "__main__":
    unittest.main()
