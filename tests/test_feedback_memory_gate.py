#!/usr/bin/env python3
"""Unit tests for feedback-memory-gate.py.

Tests feed synthetic JSON to the gate script via subprocess and assert
expected output. No real file writes are performed.

Run: python3 -m unittest tests.test_feedback_memory_gate -v
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE_SCRIPT = REPO_ROOT / "hooks" / "feedback-memory-gate.py"


def run_gate(hook_input, timeout=5):
    """Run the gate script with given input, return (stdout, stderr, exit_code)."""
    result = subprocess.run(
        [sys.executable, str(GATE_SCRIPT)],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def parse_output(stdout):
    """Parse JSON output, return dict or None if no output."""
    if not stdout:
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


def get_context(output):
    """Extract additionalContext from parsed output."""
    if not output:
        return None
    return output.get("hookSpecificOutput", {}).get("additionalContext")


def make_input(file_path, content):
    """Build a hook input dict for a Write tool call."""
    return {
        "tool_name": "Write",
        "tool_input": {
            "file_path": file_path,
            "content": content,
        },
    }


class TestFastPath(unittest.TestCase):
    """Non-feedback-memory files should exit silently."""

    def test_non_memory_file(self):
        """Writing to a non-memory file produces no output."""
        stdout, _, code = run_gate(make_input(
            "/Users/christophe/myOS/scripts/some-script.py",
            "some content"
        ))
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_non_feedback_memory(self):
        """Writing to a user or project memory produces no output."""
        stdout, _, code = run_gate(make_input(
            "/Users/christophe/myOS/claude-memory/user_profile.md",
            "user info with a bug mention"
        ))
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_empty_input(self):
        """Empty stdin should not crash."""
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            input="",
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_invalid_json(self):
        """Invalid JSON should not crash."""
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            input="not json",
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


class TestBugDetection(unittest.TestCase):
    """Feedback memories describing bugs should trigger a warning."""

    def test_bug_keyword_triggers_warning(self):
        """Content with 'bug' keyword and no Linear ref triggers warning."""
        stdout, _, code = run_gate(make_input(
            "/Users/christophe/myOS/claude-memory/feedback_some_issue.md",
            "---\nname: some issue\ntype: feedback\n---\n\n"
            "This is a bug in the retro agent."
        ))
        self.assertEqual(code, 0)
        output = parse_output(stdout)
        context = get_context(output)
        self.assertIsNotNone(context)
        self.assertIn("Linear issue", context)

    def test_broken_keyword_triggers_warning(self):
        """Content with 'broken' keyword triggers warning."""
        stdout, _, _ = run_gate(make_input(
            "/Users/christophe/myOS/claude-memory/feedback_broken_thing.md",
            "The session-start step is broken and needs fixing."
        ))
        output = parse_output(stdout)
        self.assertIsNotNone(get_context(output))

    def test_fails_keyword_triggers_warning(self):
        """Content with 'fails' keyword triggers warning."""
        stdout, _, _ = run_gate(make_input(
            "/Users/christophe/myOS/claude-memory/feedback_script_fails.md",
            "The fitbit script fails locally due to missing credentials."
        ))
        output = parse_output(stdout)
        self.assertIsNotNone(get_context(output))

    def test_error_keyword_triggers_warning(self):
        """Content with 'error' keyword triggers warning."""
        stdout, _, _ = run_gate(make_input(
            "/Users/christophe/myOS/claude-memory/feedback_error_handling.md",
            "The script produces an error when credentials are missing."
        ))
        output = parse_output(stdout)
        self.assertIsNotNone(get_context(output))

    def test_should_instead_triggers_warning(self):
        """Content with 'should X instead' triggers warning."""
        stdout, _, _ = run_gate(make_input(
            "/Users/christophe/myOS/claude-memory/feedback_pull_first.md",
            "Should pull from remote instead of running the script locally."
        ))
        output = parse_output(stdout)
        self.assertIsNotNone(get_context(output))

    def test_doesnt_work_triggers_warning(self):
        """Content with 'doesn't work' triggers warning."""
        stdout, _, _ = run_gate(make_input(
            "/Users/christophe/myOS/claude-memory/feedback_auth_broken.md",
            "The auth flow doesn't work when tokens expire."
        ))
        output = parse_output(stdout)
        self.assertIsNotNone(get_context(output))


class TestLinearRefSuppression(unittest.TestCase):
    """Feedback memories with Linear references should not trigger."""

    def test_linear_ref_suppresses_warning(self):
        """Bug-like content with **Linear:** CC-NN produces no warning."""
        stdout, _, code = run_gate(make_input(
            "/Users/christophe/myOS/claude-memory/feedback_with_linear.md",
            "---\nname: some bug\ntype: feedback\n---\n\n"
            "This is a bug in the retro agent.\n\n"
            "**Linear:** CC-20"
        ))
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_linear_ref_case_insensitive(self):
        """Linear ref matching is case-insensitive."""
        stdout, _, _ = run_gate(make_input(
            "/Users/christophe/myOS/claude-memory/feedback_case_test.md",
            "This fails badly.\n\n**linear:** CC-5"
        ))
        self.assertEqual(stdout, "")


class TestNonBugMemories(unittest.TestCase):
    """Feedback memories that are preferences/guidance should not trigger."""

    def test_preference_memory_silent(self):
        """User preference feedback produces no warning."""
        stdout, _, code = run_gate(make_input(
            "/Users/christophe/myOS/claude-memory/feedback_formatting.md",
            "---\nname: formatting prefs\ntype: feedback\n---\n\n"
            "Never use em dashes. Use double hyphens instead."
        ))
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")

    def test_workflow_preference_silent(self):
        """Workflow preference without bug language produces no warning."""
        stdout, _, code = run_gate(make_input(
            "/Users/christophe/myOS/claude-memory/feedback_weekly_over_daily.md",
            "---\nname: weekly planning\ntype: feedback\n---\n\n"
            "Weekly planning is the anchor. Daily plans are optional "
            "when weekly priorities are clear."
        ))
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")


if __name__ == "__main__":
    unittest.main()
