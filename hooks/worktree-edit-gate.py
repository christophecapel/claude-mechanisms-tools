#!/usr/bin/env python3
"""Worktree edit gate for Claude Code PreToolUse hook.

Warns when an Edit/Write/MultiEdit/NotebookEdit tool call targets a path inside
the active worktree's parent repo but OUTSIDE the active worktree itself.
Catches the silent-miss failure mode where edits to absolute repo paths
land in the main checkout despite EnterWorktree having switched the session
into a worktree (symlink and absolute-path variants).

Allows:
- paths inside the active worktree
- paths outside the parent repo entirely (e.g. ~/.claude/commands/...)
- any non-gated tool

Mode: warn-only via additionalContext. Promote to block after warnings catch
real failures. Implements Mechanism #16 (smallest shippable first).

Implements:
  Mechanism #17 — Structural checks use hooks, not behavioral rules
    https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/17-structural-checks-use-hooks.md
  Mechanism #11 — One branch, one scope
    https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/11-one-branch-one-scope.md

Exit codes: 0 always. additionalContext JSON to stdout when warning.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

GATED_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def emit_warning(msg: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": msg,
        }
    }))


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def find_worktree_root(cwd: Path) -> Optional[Path]:
    parts = cwd.parts
    try:
        idx = parts.index(".claude")
    except ValueError:
        return None
    if idx + 2 >= len(parts) or parts[idx + 1] != "worktrees":
        return None
    return Path(*parts[: idx + 3])


def find_parent_repo(worktree_root: Path) -> Optional[Path]:
    try:
        result = subprocess.run(
            ["git", "-C", str(worktree_root), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, check=True, timeout=5,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = (worktree_root / common).resolve()
    return common.parent


def evaluate(tool_name: str, file_path: str, cwd: Path) -> Optional[str]:
    """Return warning message string, or None if no warning."""
    if tool_name not in GATED_TOOLS:
        return None
    if not file_path or not os.path.isabs(file_path):
        return None

    cwd = cwd.resolve()
    worktree_root = find_worktree_root(cwd)
    if worktree_root is None:
        return None

    parent_repo = find_parent_repo(worktree_root)
    if parent_repo is None:
        return None

    target = Path(file_path).resolve()
    if is_inside(target, worktree_root):
        return None
    if not is_inside(target, parent_repo):
        return None

    suggested = worktree_root / target.relative_to(parent_repo)
    return (
        f"WORKTREE-EDIT WARNING: {tool_name} target\n"
        f"  {target}\n"
        f"is inside the parent repo {parent_repo}\n"
        f"but OUTSIDE the active worktree {worktree_root}.\n"
        f"This edit will land in the main checkout, not the worktree — "
        f"the worktree's `git status` will stay empty.\n"
        f"Fix: use the worktree-relative path instead:\n"
        f"  {suggested}\n"
        f"Or `cp` the file into the worktree after editing, before staging."
    )


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path", "")
    cwd = Path(os.getcwd())

    msg = evaluate(tool_name, file_path, cwd)
    if msg:
        emit_warning(msg)


if __name__ == "__main__":
    main()
