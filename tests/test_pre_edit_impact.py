# Copyright (c) 2026 Nardo (nardovibecoding). AGPL-3.0 — see LICENSE
"""Tests for pre_edit_impact.py — stdlib unittest only."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import pre_edit_impact as pei


class TestCheck(unittest.TestCase):

    def test_edit_py_triggers(self):
        self.assertTrue(pei.check("Edit", {"file_path": "/proj/bot_base.py"}, {}))

    def test_edit_ts_triggers(self):
        self.assertTrue(pei.check("Edit", {"file_path": "/proj/index.ts"}, {}))

    def test_edit_tsx_triggers(self):
        self.assertTrue(pei.check("Edit", {"file_path": "/proj/App.tsx"}, {}))

    def test_edit_js_triggers(self):
        self.assertTrue(pei.check("Edit", {"file_path": "/proj/main.js"}, {}))

    def test_write_py_triggers(self):
        self.assertTrue(pei.check("Write", {"file_path": "/proj/new.py"}, {}))

    def test_non_source_skips(self):
        self.assertFalse(pei.check("Edit", {"file_path": "/proj/README.md"}, {}))

    def test_json_skips(self):
        self.assertFalse(pei.check("Edit", {"file_path": "/proj/config.json"}, {}))

    def test_bash_skips(self):
        self.assertFalse(pei.check("Bash", {"command": "python3 main.py"}, {}))

    def test_empty_path_skips(self):
        self.assertFalse(pei.check("Edit", {"file_path": ""}, {}))


class TestAction(unittest.TestCase):

    def _action(self, fp, refs):
        with patch("pre_edit_impact._count_importers", return_value=(len(refs), refs)):
            return pei.action("Edit", {"file_path": fp}, {})

    def test_zero_importers_silent(self):
        self.assertIsNone(self._action("/proj/utils.py", []))

    def test_one_importer_low(self):
        result = self._action("/proj/utils.py", ["/proj/main.py"])
        assert result is not None
        self.assertIn("LOW", result)
        self.assertIn("utils.py", result)

    def test_three_importers_low(self):
        refs = ["/proj/a.py", "/proj/b.py", "/proj/c.py"]
        result = self._action("/proj/utils.py", refs)
        assert result is not None
        self.assertIn("LOW", result)

    def test_four_importers_high(self):
        refs = [f"/proj/{i}.py" for i in range(4)]
        result = self._action("/proj/utils.py", refs)
        assert result is not None
        self.assertIn("HIGH", result)
        self.assertIn("Check callers", result)

    def test_nine_importers_high(self):
        refs = [f"/proj/{i}.py" for i in range(9)]
        result = self._action("/proj/utils.py", refs)
        assert result is not None
        self.assertIn("HIGH", result)

    def test_ten_importers_critical(self):
        refs = [f"/proj/{i}.py" for i in range(10)]
        result = self._action("/proj/utils.py", refs)
        assert result is not None
        self.assertIn("CRITICAL", result)
        self.assertIn("blast radius", result)

    def test_critical_shows_top_callers(self):
        refs = [f"/proj/module_{i}.py" for i in range(12)]
        result = self._action("/proj/utils.py", refs)
        assert result is not None
        self.assertIn("module_0.py", result)

    def test_empty_file_path_returns_none(self):
        with patch("pre_edit_impact._count_importers", return_value=(5, ["/a.py"] * 5)):
            result = pei.action("Edit", {"file_path": ""}, {})
        self.assertIsNone(result)


class TestCountImporters(unittest.TestCase):

    def test_deduplicates_results(self):
        # grep returning the same file from two search dirs should deduplicate
        import subprocess
        fake_output = "/proj/a.py\n/proj/a.py\n/proj/b.py\n"
        with patch("pre_edit_impact.subprocess.run") as mock_run, \
             patch("pre_edit_impact._SEARCH_DIRS", ["/proj"]), \
             patch("pre_edit_impact.Path.exists", return_value=True):
            mock_run.return_value = subprocess.CompletedProcess(
                [], 0, stdout=fake_output, stderr=""
            )
            _, refs = pei._count_importers("/proj/utils.py")
        self.assertEqual(len(set(refs)), len(refs))  # no duplicates

    def test_excludes_pycache(self):
        import subprocess
        fake_output = "/proj/__pycache__/utils.cpython-311.pyc\n/proj/main.py\n"
        with patch("pre_edit_impact.subprocess.run") as mock_run, \
             patch("pre_edit_impact._SEARCH_DIRS", ["/proj"]), \
             patch("pre_edit_impact.Path.exists", return_value=True):
            mock_run.return_value = subprocess.CompletedProcess(
                [], 0, stdout=fake_output, stderr=""
            )
            _, refs = pei._count_importers("/proj/utils.py")
        self.assertNotIn("/proj/__pycache__/utils.cpython-311.pyc", refs)

    def test_excludes_self(self):
        import subprocess
        fp = "/proj/utils.py"
        fake_output = f"{fp}\n/proj/main.py\n"
        with patch("pre_edit_impact.subprocess.run") as mock_run, \
             patch("pre_edit_impact._SEARCH_DIRS", ["/proj"]), \
             patch("pre_edit_impact.Path.exists", return_value=True):
            mock_run.return_value = subprocess.CompletedProcess(
                [], 0, stdout=fake_output, stderr=""
            )
            count, refs = pei._count_importers(fp)
        self.assertNotIn(fp, refs)

    def test_timeout_returns_empty(self):
        import subprocess
        with patch("pre_edit_impact.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("grep", 5)), \
             patch("pre_edit_impact._SEARCH_DIRS", ["/proj"]), \
             patch("pre_edit_impact.Path.exists", return_value=True):
            count, refs = pei._count_importers("/proj/utils.py")
        self.assertEqual(count, 0)
        self.assertEqual(refs, [])


if __name__ == "__main__":
    unittest.main()
