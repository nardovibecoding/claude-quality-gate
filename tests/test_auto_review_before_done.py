# Copyright (c) 2026 Nardo (nardovibecoding). AGPL-3.0 — see LICENSE
"""Tests for auto_review_before_done.py — uses stdlib unittest only."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import auto_review_before_done as ard


class TestEditLogPath(unittest.TestCase):

    def test_with_session_id_uses_session_file(self):
        p = ard._edit_log_path("abc123")
        self.assertEqual(p.name, "claude_edits_abc123.json")

    def test_none_falls_back_to_legacy(self):
        p = ard._edit_log_path(None)
        self.assertEqual(p.name, "claude_edits_this_turn.json")

    def test_sanitizes_slashes(self):
        p = ard._edit_log_path("a/b/c")
        self.assertNotIn("/", p.name.replace("claude_edits_", "").replace(".json", ""))

    def test_different_sessions_different_paths(self):
        self.assertNotEqual(ard._edit_log_path("s1"), ard._edit_log_path("s2"))


class TestLoadEdits(unittest.TestCase):

    def test_returns_empty_when_no_file(self):
        result = ard.load_edits("nonexistent_session_xyz_9999")
        self.assertEqual(result, [])

    def test_returns_edits_for_session(self):
        import tempfile, os
        data = [{"file": "a.py", "ts": 1000, "tests_passed": True}]
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False,
            dir="/tmp", prefix="claude_edits_test_"
        ) as f:
            json.dump(data, f)
            tmp = Path(f.name)
        session = tmp.name.removeprefix("claude_edits_").removesuffix(".json")
        try:
            result = ard.load_edits(session)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["file"], "a.py")
        finally:
            os.unlink(tmp)

    def test_handles_corrupt_json(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False,
            dir="/tmp", prefix="claude_edits_corrupt_"
        ) as f:
            f.write("{{not json}}")
            tmp = Path(f.name)
        session = tmp.name.removeprefix("claude_edits_").removesuffix(".json")
        try:
            result = ard.load_edits(session)
            self.assertEqual(result, [])
        finally:
            os.unlink(tmp)


class TestSkipPattern(unittest.TestCase):
    """Verify test/memory files are excluded from review."""

    def test_test_file_skipped(self):
        self.assertTrue(ard._SKIP.search("/project/tests/test_foo.py"))

    def test_test_file_same_dir_skipped(self):
        self.assertTrue(ard._SKIP.search("/project/test_foo.py"))

    def test_memory_file_skipped(self):
        self.assertTrue(ard._SKIP.search("/memory/some_file.md"))

    def test_source_file_not_skipped(self):
        self.assertIsNone(ard._SKIP.search("/project/foo.py"))

    def test_hook_file_not_skipped(self):
        self.assertIsNone(ard._SKIP.search("/hooks/auto_review_before_done.py"))


class TestSilentWhenAllGood(unittest.TestCase):
    """Hook exits 0 silently when tests passed or no testable files."""

    def _run_main_with_edits(self, edits, session="test_silent_session"):
        tmp = Path(f"/tmp/claude_edits_{session}.json")
        tmp.write_text(json.dumps(edits))
        inp = json.dumps({"session_id": session})
        try:
            with patch("sys.stdin") as mock_stdin, \
                 patch("sys.exit") as mock_exit:
                mock_stdin.read.return_value = inp
                # Patch load_edits to return our edits directly
                with patch.object(ard, "load_edits", return_value=edits):
                    try:
                        ard.main()
                    except SystemExit as e:
                        return e.code
        finally:
            tmp.unlink(missing_ok=True)
        return mock_exit.call_args[0][0] if mock_exit.called else 0

    def test_exits_0_when_tests_passed(self):
        edits = [{"file": "/project/foo.py", "ts": 1000,
                  "tests_passed": True, "needs_tests": True}]
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = json.dumps({"session_id": "s_pass"})
            with patch.object(ard, "load_edits", return_value=edits):
                with self.assertRaises(SystemExit) as ctx:
                    ard.main()
        self.assertEqual(ctx.exception.code, 0)

    def test_exits_2_when_tests_failed(self):
        edits = [{"file": "/project/foo.py", "ts": 1000,
                  "tests_passed": False, "needs_tests": True}]
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = json.dumps({"session_id": "s_fail"})
            with patch.object(ard, "load_edits", return_value=edits):
                with self.assertRaises(SystemExit) as ctx:
                    ard.main()
        self.assertEqual(ctx.exception.code, 2)

    def test_exits_0_when_no_edits(self):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = json.dumps({"session_id": "s_empty"})
            with patch.object(ard, "load_edits", return_value=[]):
                with self.assertRaises(SystemExit) as ctx:
                    ard.main()
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
