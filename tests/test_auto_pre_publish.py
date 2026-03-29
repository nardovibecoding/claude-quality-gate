# Copyright (c) 2026 Nardo (nardovibecoding). AGPL-3.0 — see LICENSE
"""Tests for auto_pre_publish.py — stdlib unittest only."""
import sys
import json
import unittest
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import auto_pre_publish as app


# ── check() ───────────────────────────────────────────────────────────────────

class TestCheck(unittest.TestCase):
    def _call(self, cmd):
        return app.check("Bash", {"command": cmd}, {})

    def test_visibility_public(self):
        self.assertTrue(self._call("gh repo edit nardovibecoding/foo --visibility public"))

    def test_create_public(self):
        self.assertTrue(self._call("gh repo create foo --public"))

    def test_visibility_private_ignored(self):
        self.assertFalse(self._call("gh repo edit foo --visibility private"))

    def test_non_bash_tool_ignored(self):
        self.assertFalse(app.check("Write", {"command": "gh repo edit foo --visibility public"}, {}))

    def test_empty_command_ignored(self):
        self.assertFalse(self._call(""))


# ── _find_repo_path() ─────────────────────────────────────────────────────────

class TestFindRepoPath(unittest.TestCase):
    def test_extracts_repo_name_from_cmd_and_finds_home_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "my-repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            with patch.object(Path, "home", return_value=Path(tmp)):
                result = app._find_repo_path("gh repo edit nardovibecoding/my-repo --visibility public")
            self.assertEqual(result, repo)

    def test_falls_back_to_git_rev_parse_when_no_match(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="/some/repo\n")
            result = app._find_repo_path("gh repo edit --visibility public")
        self.assertEqual(result, Path("/some/repo"))

    def test_returns_cwd_when_git_fails(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = app._find_repo_path("no match here")
        self.assertIsNotNone(result)


# ── _git_tracked_files() ──────────────────────────────────────────────────────

class TestGitTrackedFiles(unittest.TestCase):
    def test_returns_paths_for_tracked_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="foo.py\0bar.py\0")
                files = app._git_tracked_files(repo)
            self.assertEqual(len(files), 2)
            self.assertIn(repo / "foo.py", files)

    def test_returns_empty_on_git_failure(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            files = app._git_tracked_files(Path("/nonexistent"))
        self.assertEqual(files, [])


# ── action() — IP false-positive fix ─────────────────────────────────────────

class TestActionIPFalsePositive(unittest.TestCase):
    """Verify Chrome version numbers in User-Agent strings are not flagged as IPs."""

    def _run_action_on_content(self, filename, content, cmd="gh repo edit nardovibecoding/test-repo --visibility public"):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".git").mkdir()
            (repo / "LICENSE").write_text("GNU AGPL\n" * 20)
            (repo / "NOTICE").write_text("test-repo")
            (repo / ".gitignore").write_text(".env\nvenv/\n")
            (repo / "README.md").write_text(
                "# test-repo\nA tool.\n\n## Quick Start\n```bash\nrun\n```\n" * 5
            )
            f = repo / filename
            f.write_text(content)

            with patch("auto_pre_publish._find_repo_path", return_value=repo), \
                 patch("auto_pre_publish._git_tracked_files", return_value=[f, repo / "LICENSE", repo / "NOTICE", repo / ".gitignore", repo / "README.md"]), \
                 patch("subprocess.run") as mock_run:
                # Mock gh repo view for topics/description check
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps({"description": "ok", "repositoryTopics": [{"name": "mcp"}]})
                )
                return app.action("Bash", {"command": cmd}, {})

    def test_chrome_version_not_flagged_as_ip(self):
        ua = 'user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36"'
        result = self._run_action_on_content("browser_manager.py", ua)
        self.assertNotIn("131.0.0.0", result.get("reason", ""))
        # Should not be blocked for IP
        issues_text = result.get("reason", "")
        self.assertNotIn("SECRET: Hardcoded IP", issues_text)

    def test_real_ip_still_flagged(self):
        content = 'server = "203.0.113.1"  # hardcoded server IP (TEST-NET, RFC 5737)'
        result = self._run_action_on_content("config.py", content)
        self.assertIn("SECRET", result.get("reason", ""))
        self.assertEqual(result.get("decision"), "block")

    def test_loopback_not_flagged(self):
        content = 'host = "127.0.0.1"'
        result = self._run_action_on_content("server.py", content)
        issues = result.get("reason", "")
        self.assertNotIn("127.0.0.1", issues)


# ── action() — topics check ───────────────────────────────────────────────────

class TestActionTopics(unittest.TestCase):
    def _run_with_topics(self, topics):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".git").mkdir()
            (repo / "LICENSE").write_text("GNU AGPL\n" * 20)
            (repo / "NOTICE").write_text("test-repo")
            (repo / ".gitignore").write_text(".env\n")
            (repo / "README.md").write_text("# test-repo\nTool.\n\n## Quick Start\n```bash\nrun\n```\n" * 5)

            with patch("auto_pre_publish._find_repo_path", return_value=repo), \
                 patch("auto_pre_publish._git_tracked_files", return_value=[repo / "LICENSE", repo / "NOTICE", repo / ".gitignore", repo / "README.md"]), \
                 patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps({"description": "ok", "repositoryTopics": topics})
                )
                return app.action("Bash", {"command": "gh repo edit nardovibecoding/test-repo --visibility public"}, {})

    def test_no_topics_blocks(self):
        result = self._run_with_topics([])
        self.assertEqual(result["decision"], "block")
        self.assertIn("topics", result["reason"])

    def test_with_topics_passes(self):
        result = self._run_with_topics([{"name": "mcp"}])
        # Should not be blocked for topics
        self.assertNotIn("topics", result.get("reason", ""))


if __name__ == "__main__":
    unittest.main()
