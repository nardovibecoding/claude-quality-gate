# Copyright (c) 2026 Nardo (nardovibecoding). AGPL-3.0 — see LICENSE
"""Tests for vps_setup_guard.py — stdlib unittest only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import vps_setup_guard as vsg


class TestCheck(unittest.TestCase):

    def _check(self, cmd):
        return vsg.check("Bash", {"command": cmd}, {})

    def test_heredoc_over_ssh_triggers(self):
        self.assertTrue(self._check('ssh vps "cat > /tmp/x.service << EOF\nfoo\nEOF"'))

    def test_base64_pipe_triggers(self):
        self.assertTrue(self._check("ssh vps \"echo ABC123xyz | base64 -d > /tmp/x\""))

    def test_printf_multiple_newlines_triggers(self):
        self.assertTrue(self._check(r"ssh vps \"printf '[Unit]\nDesc\nAfter\nExec\n' > x\""))

    def test_long_ssh_command_triggers(self):
        long_cmd = "ssh bernard@157.180.28.14 \"" + "x" * 300 + "\""
        self.assertTrue(self._check(long_cmd))

    def test_short_ssh_command_skips(self):
        self.assertFalse(self._check("ssh vps \"systemctl --user status camofox\""))

    def test_non_ssh_bash_skips(self):
        self.assertFalse(self._check("git push origin main"))

    def test_non_bash_tool_skips(self):
        self.assertFalse(vsg.check("Edit", {"file_path": "/tmp/x.sh"}, {}))

    def test_empty_command_skips(self):
        self.assertFalse(self._check(""))

    def test_local_heredoc_no_ssh_skips(self):
        self.assertFalse(self._check("cat > /tmp/x.sh << EOF\nfoo\nEOF"))


class TestAction(unittest.TestCase):

    def _action(self, cmd):
        return vsg.action("Bash", {"command": cmd}, {})

    def test_heredoc_message_mentions_heredoc(self):
        result = self._action('ssh vps "cat << EOF\nfoo\nEOF"')
        assert result is not None
        self.assertIn("heredoc", result)

    def test_base64_message_mentions_base64(self):
        result = self._action("ssh vps \"echo ABC | base64 -d > /tmp/x\"")
        assert result is not None
        self.assertIn("base64", result)

    def test_action_always_suggests_script(self):
        result = self._action("ssh vps \"echo ABC | base64 -d > /tmp/x\"")
        assert result is not None
        self.assertIn("scripts/setup_", result)
        self.assertIn("commit", result)

    def test_long_ssh_message_mentions_long(self):
        long_cmd = "ssh vps \"" + "x" * 300 + "\""
        result = self._action(long_cmd)
        assert result is not None
        self.assertIn("SSH", result)


if __name__ == "__main__":
    unittest.main()
