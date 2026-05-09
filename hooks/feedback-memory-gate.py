#!/usr/bin/env python3
"""Feedback memory gate for Claude Code hooks.

PostToolUse hook (Write matcher). Fires after a feedback memory file is written.
If the content describes a bug but has no Linear issue reference, warns Claude
to create one.

Non-feedback-memory writes exit immediately (fast path).
"""

import json
import re
import sys

# Keywords that suggest the feedback memory describes a bug or broken behavior.
# Matched case-insensitively against the file content.
BUG_INDICATORS = [
    r"\bbug\b",
    r"\bbroken\b",
    r"\bfails?\b",
    r"\bfailing\b",
    r"\berror\b",
    r"\bwrong\b",
    r"\bshould .+ instead\b",
    r"\bfix\b",
    r"\bcrash",
    r"\bmissing\b",
    r"\bnever\b.*\bshould\b",
    r"\bdoesn'?t work\b",
    r"\bincorrect\b",
]

BUG_PATTERN = re.compile("|".join(BUG_INDICATORS), re.IGNORECASE)

LINEAR_REF_PATTERN = re.compile(r"\*\*Linear:\*\*\s*CC-\d+", re.IGNORECASE)

FEEDBACK_PATH_PATTERN = re.compile(r"claude-memory/feedback_.*\.md$")


def info(message):
    """Output informational context (non-blocking)."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": message,
        }
    }))
    sys.exit(0)


def allow():
    """Allow silently (no output)."""
    sys.exit(0)


def main():
    try:
        stdin_data = sys.stdin.read()
        hook_input = json.loads(stdin_data) if stdin_data.strip() else {}
    except json.JSONDecodeError:
        allow()

    tool_input = hook_input.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    # Fast path: not a feedback memory file
    if not FEEDBACK_PATH_PATTERN.search(file_path):
        allow()

    content = tool_input.get("content", "")

    # Already has a Linear reference
    if LINEAR_REF_PATTERN.search(content):
        allow()

    # Check for bug indicators
    if BUG_PATTERN.search(content):
        info(
            "FEEDBACK MEMORY GATE: This feedback memory describes a bug or "
            "broken behavior but has no Linear issue reference. Create a "
            "Linear issue (label: Bug, appropriate project) and add "
            "'**Linear:** CC-NN' to this file."
        )

    # Not bug-like, exit silently
    allow()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Fail-open: hook errors should not block the user
        sys.stderr.write(f"feedback-memory-gate error: {e}\n")
        sys.exit(0)
