# Copyright (c) 2026 Nardo (nardovibecoding). AGPL-3.0 — see LICENSE
"""Tests for impact tier labels added to auto_dependency_grep.py (Mode 1)."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import auto_dependency_grep as adg


class TestTierLabels(unittest.TestCase):
    """Test that Mode 1 (file move/delete) outputs correct tier labels."""

    def _run_bash_action(self, refs):
        """Simulate Mode 1 action with a given list of ref paths.

        Mode 1 greps two search dirs. We return refs on the first call,
        empty on the second, to avoid inflating counts.
        """
        fake_stdout = "\n".join(refs) + "\n" if refs else ""
        responses = [
            subprocess.CompletedProcess([], 0, stdout=fake_stdout, stderr=""),
            subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ]
        with patch("auto_dependency_grep.subprocess.run", side_effect=responses):
            return adg.action(
                "Bash",
                {"command": "rm /project/utils.py"},
                {}
            )

    def test_zero_refs_returns_none(self):
        result = self._run_bash_action([])
        self.assertIsNone(result)

    def test_one_ref_is_low(self):
        result = self._run_bash_action(["/proj/main.py"])
        self.assertIsNotNone(result)
        self.assertIn("[LOW]", result)

    def test_three_refs_is_low(self):
        result = self._run_bash_action([f"/proj/{i}.py" for i in range(3)])
        assert result is not None
        self.assertIn("[LOW]", result)

    def test_four_refs_is_high(self):
        result = self._run_bash_action([f"/proj/{i}.py" for i in range(4)])
        assert result is not None
        self.assertIn("[HIGH]", result)

    def test_nine_refs_is_high(self):
        result = self._run_bash_action([f"/proj/{i}.py" for i in range(9)])
        assert result is not None
        self.assertIn("[HIGH]", result)

    def test_ten_refs_is_critical(self):
        result = self._run_bash_action([f"/proj/{i}.py" for i in range(10)])
        assert result is not None
        self.assertIn("[CRITICAL]", result)

    def test_twelve_refs_is_critical(self):
        result = self._run_bash_action([f"/proj/{i}.py" for i in range(12)])
        assert result is not None
        self.assertIn("[CRITICAL]", result)

    def test_ref_count_shown_in_output(self):
        refs = [f"/proj/{i}.py" for i in range(5)]
        result = self._run_bash_action(refs)
        assert result is not None
        self.assertIn("5", result)

    def test_filename_shown_in_output(self):
        result = self._run_bash_action(["/proj/main.py"])
        assert result is not None
        self.assertIn("utils.py", result)


class TestCheckUnchanged(unittest.TestCase):
    """Ensure existing check() logic is unaffected by tier changes."""

    def test_bash_mv_triggers(self):
        self.assertTrue(adg.check("Bash", {"command": "mv foo.py bar.py"}, {}))

    def test_bash_rm_triggers(self):
        self.assertTrue(adg.check("Bash", {"command": "rm utils.py"}, {}))

    def test_edit_known_file_triggers(self):
        self.assertTrue(adg.check("Edit", {"file_path": "/project/config.py"}, {}))

    def test_edit_unknown_file_skips(self):
        self.assertFalse(adg.check("Edit", {"file_path": "/project/random.py"}, {}))

    def test_non_bash_non_edit_skips(self):
        self.assertFalse(adg.check("Read", {"file_path": "utils.py"}, {}))


if __name__ == "__main__":
    unittest.main()
