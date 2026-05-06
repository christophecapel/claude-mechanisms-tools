"""Tests for hooks/worktree-edit-gate.py.

Run: python3 -m unittest tests.test_worktree_edit_gate -v
"""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


_SCRIPT = Path(__file__).resolve().parent.parent / "hooks" / "worktree-edit-gate.py"
_spec = importlib.util.spec_from_file_location("worktree_edit_gate", _SCRIPT)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


class FindWorktreeRootTests(unittest.TestCase):
    def test_inside_worktree(self):
        cwd = Path("/Users/x/myrepo/.claude/worktrees/feat-foo")
        self.assertEqual(gate.find_worktree_root(cwd), cwd)

    def test_subdir_of_worktree(self):
        cwd = Path("/Users/x/myrepo/.claude/worktrees/feat-foo/scripts")
        self.assertEqual(
            gate.find_worktree_root(cwd),
            Path("/Users/x/myrepo/.claude/worktrees/feat-foo"),
        )

    def test_main_checkout_returns_none(self):
        self.assertIsNone(gate.find_worktree_root(Path("/Users/x/myrepo")))

    def test_unrelated_dir_returns_none(self):
        self.assertIsNone(gate.find_worktree_root(Path("/tmp/foo")))

    def test_dotclaude_without_worktrees(self):
        self.assertIsNone(gate.find_worktree_root(Path("/Users/x/.claude/projects/foo")))


class EvaluateTests(unittest.TestCase):
    def setUp(self):
        self.cwd = Path("/Users/x/myrepo/.claude/worktrees/feat-foo")
        self.parent_repo = Path("/Users/x/myrepo")

    def _run(self, tool_name, file_path, cwd=None):
        with patch.object(gate, "find_parent_repo", return_value=self.parent_repo):
            return gate.evaluate(tool_name, file_path, cwd or self.cwd)

    def test_edit_inside_worktree_no_warning(self):
        target = "/Users/x/myrepo/.claude/worktrees/feat-foo/scripts/foo.py"
        self.assertIsNone(self._run("Edit", target))

    def test_edit_main_checkout_warns(self):
        target = "/Users/x/myrepo/scripts/foo.py"
        msg = self._run("Edit", target)
        self.assertIsNotNone(msg)
        self.assertIn("WORKTREE-EDIT WARNING", msg)
        self.assertIn(target, msg)
        self.assertIn(
            "/Users/x/myrepo/.claude/worktrees/feat-foo/scripts/foo.py",
            msg,
            msg="warning should suggest the worktree-relative equivalent",
        )

    def test_edit_external_path_no_warning(self):
        # ~/.claude/commands/check.md is outside the parent repo entirely
        target = "/Users/x/.claude/commands/check.md"
        self.assertIsNone(self._run("Edit", target))

    def test_write_main_checkout_warns(self):
        msg = self._run("Write", "/Users/x/myrepo/docs/foo.md")
        self.assertIsNotNone(msg)
        self.assertIn("Write target", msg)

    def test_multiedit_main_checkout_warns(self):
        msg = self._run("MultiEdit", "/Users/x/myrepo/docs/foo.md")
        self.assertIsNotNone(msg)

    def test_non_gated_tool_no_warning(self):
        self.assertIsNone(self._run("Bash", "/Users/x/myrepo/scripts/foo.py"))
        self.assertIsNone(self._run("Read", "/Users/x/myrepo/scripts/foo.py"))

    def test_relative_path_no_warning(self):
        # Relative paths are passed through; only absolute paths gate
        self.assertIsNone(self._run("Edit", "scripts/foo.py"))

    def test_outside_worktree_no_warning(self):
        # If cwd is not inside any worktree, never warn
        self.assertIsNone(self._run(
            "Edit",
            "/Users/x/myrepo/scripts/foo.py",
            cwd=Path("/Users/x/myrepo"),
        ))

    def test_empty_file_path_no_warning(self):
        self.assertIsNone(self._run("Edit", ""))


if __name__ == "__main__":
    unittest.main()
