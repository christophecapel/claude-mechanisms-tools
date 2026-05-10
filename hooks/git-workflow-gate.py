#!/usr/bin/env python3
"""Git workflow gate for Claude Code hooks — Atomic Git Workflow (slim subset).

Called by Claude Code hooks (PreToolUse, PostToolUse) on the Bash tool to
enforce git workflow rules. Non-git commands exit immediately (fast path).

Gates:
  Gate 0  — `cd <dir> && git ...` chain detection (PreToolUse)
  Gate 1  — Pre-commit (branch-not-main, commit-msg format)
  Gate 1b — Post-commit (unpushed-commits info nag)
  Gate 2  — Pre-push (rebase-required, frozen-branch on merged PR, force-push warn)
  Gate 3  — Pre-checkout (dirty-tree deny on branch switch)
  Gate 5  — Post-push (PR-existence nag)
  Gate 6  — Session-start (stale merged-branches digest, info nag)

Configuration:
  - Per-repo `.commit-types` file at the repo root overrides ALLOWED_COMMIT_TYPES
    (one type per line, # comments ignored)

Fail-closed: any unhandled exception produces a deny response, never silently passes.

Exit codes:
  0 = always (Claude Code parses stdout JSON on exit 0)
  stdout JSON with permissionDecision: "deny" = block the tool call
  no stdout = allow the tool call

Implements:
  Mechanism #1  — Discover and derive (paired with mechanism_commit_push_pr_atomic)
  Mechanism #11 — One branch, one scope (commit-on-main + frozen-branch + branch verify)
  Mechanism #17 — Structural checks use hooks, not behavioral rules

See https://github.com/christophecapel/claude-mechanisms

Extracted from myOS scripts/git-workflow-gate.py (~/myOS) — slim subset for
public toolkit use. The full myOS gate adds Linear / spec-doc / memory-index /
session-start / session-end / blocked-remotes / owner-pattern / cross-repo
checks that are myOS-specific.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# --- Configuration ---

# Generic Conventional-Commits-ish set. Per-repo `.commit-types` overrides.
ALLOWED_COMMIT_TYPES = {
    "fix", "refactor", "docs", "feat", "chore", "archive",
    "test", "style", "perf", "ci", "build", "revert",
}

SUBPROCESS_TIMEOUT = 5  # seconds per git/gh call


def get_allowed_commit_types(repo_root):
    """Get allowed commit types, checking for a repo-level .commit-types override.

    If <repo_root>/.commit-types exists, reads one type per line (ignoring blanks
    and # comments). Otherwise falls back to ALLOWED_COMMIT_TYPES.
    """
    commit_types_file = Path(repo_root) / ".commit-types"
    if commit_types_file.exists():
        try:
            types = set()
            for line in commit_types_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    types.add(line)
            if types:
                return types
        except OSError:
            pass
    return ALLOWED_COMMIT_TYPES


# --- Helpers ---

def run(cmd, cwd=None, timeout=SUBPROCESS_TIMEOUT):
    """Run a command, return CompletedProcess. Never raises on failure."""
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        class FakeResult:
            stdout = ""
            stderr = str(e)
            returncode = 1
        return FakeResult()


def get_repo_name(cwd):
    """Derive repo name from cwd (e.g., /Users/me/myproject -> myproject)."""
    path = Path(cwd)
    for parent in [path] + list(path.parents):
        if (parent / ".git").exists():
            return parent.name
    return path.name


def get_repo_root(cwd):
    """Find the git repo root from cwd."""
    result = run(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    if result.returncode == 0:
        return result.stdout.strip()
    return cwd


def get_current_branch(cwd):
    """Get current branch name."""
    result = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    return result.stdout.strip() if result.returncode == 0 else ""


# --- Response shapers ---

def deny(reason):
    """Output deny JSON and exit."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def warn(message):
    """Output warning via additionalContext (non-blocking)."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": message,
        }
    }))
    sys.exit(0)


def info(message, event_name="PostToolUse"):
    """Output informational additionalContext (non-blocking)."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": message,
        }
    }))
    sys.exit(0)


def allow():
    """Allow silently (no output)."""
    sys.exit(0)


# --- Parsers ---

def detect_cd_git_chain(command_str):
    """Detect `cd <dir> && git ...` (or `;`) chains.

    Chained `cd` leaks shell state and has caused wrong-directory commits.
    Use `git -C <dir> ...` or the Bash tool's `cwd` parameter instead.
    Returns the offending fragment if found, else None.
    """
    match = re.search(
        r'\bcd\s+\S+(?:\s*(?:&&|;)\s*[^&;\n]+?)*?\s*(?:&&|;)\s*git\b(?!\s+-C)[^\n;]*',
        command_str,
    )
    return match.group(0) if match else None


def extract_git_commands(command_str):
    """Extract git sub-commands from a potentially compound command string.

    Splits on && and ; (not inside quotes), returns list of stripped sub-commands
    that start with 'git '.
    """
    parts = re.split(r'\s*(?:&&|;)\s*', command_str)
    git_cmds = []
    for part in parts:
        stripped = part.strip()
        # Match 'git ...' at the start, ignoring env var prefixes like VAR=val
        cleaned = re.sub(r'^(\w+=\S+\s+)*', '', stripped)
        if re.match(r'^git\s', cleaned):
            git_cmds.append(cleaned)
    return git_cmds


def parse_commit_message(git_cmd):
    """Extract the commit message from a git commit command string."""
    # HEREDOC case: -m "$(cat <<'EOF'\n...\nEOF\n)"
    if "<<" in git_cmd and ("EOF" in git_cmd or "eof" in git_cmd):
        lines = git_cmd.split('\n')
        for i, line in enumerate(lines):
            if "<<" in line:
                for j in range(i + 1, len(lines)):
                    stripped = lines[j].strip()
                    if stripped and stripped not in ("EOF", "eof", ")", '")'):
                        return stripped
        return None  # HEREDOC present but unparseable — skip validation
    # Simple case: -m "message" or -m 'message'
    match = re.search(r'''-m\s+["'](.+?)["']''', git_cmd)
    if match:
        return match.group(1)
    return None


def parse_push_remote(git_cmd):
    """Extract the remote name from a git push command. Returns None if not specified."""
    parts = git_cmd.split()
    i = 1
    if i < len(parts) and parts[i] == "push":
        i += 1
    else:
        return None
    while i < len(parts) and parts[i].startswith("-"):
        flag = parts[i]
        if flag in ("--repo", "--push-option", "-o", "--signed"):
            i += 2
            continue
        i += 1
    if i < len(parts) and not parts[i].startswith("-"):
        return parts[i]
    return None


def is_file_restore(git_cmd):
    """Check if a git checkout/switch/restore command is a file restore (not branch switch).

    Returns True for:
      git checkout -- <file>       (file restore)
      git checkout HEAD -- <file>  (file restore with ref)
      git restore <file>           (explicit restore command)
      git restore --staged <file>  (unstage)
    Returns False for:
      git checkout <branch>        (branch switch)
      git checkout -b <branch>     (branch creation)
      git switch <branch>          (branch switch)
    """
    parts = git_cmd.split()
    if len(parts) < 2:
        return False
    if parts[1] == "restore":
        return True
    if "--" in parts:
        return True
    return False


# --- Gates ---

def gate_pre_checkout(git_cmd, cwd):
    """Gate 3: Pre-Checkout dirty-tree deny (slim subset).

    Branch switching with modified or staged tracked files silently carries
    those changes onto the target branch — proven destructive in 2026-04-28
    incident (PR #450, ~1h edits across 7 files swept). myOS shipped this as
    `warn()` originally and promoted to `deny()` after warn-only proved
    insufficient under cognitive load (HWW #17).

    Skips (silent allow):
      - File-restoration forms (via `is_file_restore()`):
          git checkout -- <path> / git checkout <ref> -- <path> / git restore <path>
      - New-branch creation: `-c`/`-C` (git switch) / `-b`/`-B` (git checkout)
        — those legitimately move dirty work to a new branch
      - Untracked-only working tree — untracked files don't travel on switch

    Slim subset for v0.5.1: drops `RELATED_REPOS` cross-repo concurrency check
    and `.claude-session-lock` concurrent-session protocol (myOS-specific).
    """
    if is_file_restore(git_cmd):
        return

    parts = git_cmd.split()
    if any(flag in parts for flag in ("-b", "-B", "-c", "-C")):
        return

    repo_root = get_repo_root(cwd)
    result = run(["git", "status", "--porcelain"], cwd=repo_root)
    if result.returncode != 0:
        return

    tracked_dirty = [
        line for line in result.stdout.splitlines()
        if line and not line.startswith("??")
    ]
    if not tracked_dirty:
        return

    file_count = len(tracked_dirty)
    sample = ", ".join(line[3:] for line in tracked_dirty[:3])
    if file_count > 3:
        sample += f", and {file_count - 3} more"

    deny(
        f"Uncommitted changes ({file_count} file(s): {sample}). "
        f"Switching branches carries these onto the target branch and can sweep "
        f"in-progress edits silently. Commit or stash before switching: "
        f"`git stash push -m '<message>'` or `git add -A && git commit -m '<type>: <message>'`."
    )


def gate_pre_commit(git_cmd, cwd):
    """Gate 1: Pre-Commit checks (branch-not-main + commit-msg format)."""
    branch = get_current_branch(cwd)
    repo_root = get_repo_root(cwd)

    # BLOCK: commit on main
    if branch in ("main", "master"):
        deny(
            "Cannot commit to main. Create a branch first: "
            "`git checkout -b <type>/<description>`"
        )

    # WARN: amend
    if "--amend" in git_cmd:
        warn("Amending previous commit. Verify this is intentional and not destroying prior work.")

    # BLOCK: commit message format
    allowed_types = get_allowed_commit_types(repo_root)
    message = parse_commit_message(git_cmd)
    if message:
        match = re.match(r'^(\w+)(?:\([^)]*\))?:\s+\S', message)
        if not match:
            deny(
                f"Commit message format invalid: '{message[:60]}...'. "
                f"Required format: '<type>: <description>'. "
                f"Allowed types: {', '.join(sorted(allowed_types))}"
            )
        commit_type = match.group(1)
        if commit_type not in allowed_types:
            deny(
                f"Unknown commit type '{commit_type}'. "
                f"Allowed types: {', '.join(sorted(allowed_types))}"
            )

    allow()


def gate_pre_push(git_cmd, cwd):
    """Gate 2: Pre-Push checks (rebase-required + frozen-branch + force-push warn).

    Slim subset for v0.5: drops blocked-remotes, owner-pattern, spec-doc-pairing
    (myOS-specific). Keeps the universally-applicable checks.
    """
    branch = get_current_branch(cwd)
    repo_root = get_repo_root(cwd)

    # WARN: force push
    if "--force" in git_cmd or re.search(r'\s-\w*f', git_cmd):
        warn("Force push detected. Verify this is intentional.")

    # BLOCK: branch behind origin/main (needs rebase)
    run(["git", "fetch", "origin", "main"], cwd=repo_root, timeout=10)
    result = run(["git", "rev-list", "--count", "HEAD..origin/main"], cwd=repo_root)
    if result.returncode == 0:
        try:
            behind = int(result.stdout.strip() or "0")
        except ValueError:
            behind = 0
        if behind > 0:
            deny(
                f"Branch is behind origin/main by {behind} commit(s). "
                f"Run: `git fetch origin main && git rebase origin/main` then retry push."
            )

    # BLOCK: branch has a merged PR (pushing to dead branch — frozen scope)
    if branch not in ("main", "master"):
        result = run(
            ["gh", "pr", "list", "--head", branch, "--state", "merged", "--json", "url"],
            cwd=repo_root,
        )
        if result.returncode == 0 and result.stdout.strip() not in ("", "[]"):
            deny(
                f"Branch '{branch}' already has a merged PR. "
                f"Create a new branch: `git checkout main && git pull --rebase && "
                f"git checkout -b <new-branch>`"
            )

    allow()


def gate_post_commit(git_cmd, cwd):
    """Gate 1b: Post-Commit informational reminder.

    After a successful git commit, checks if the branch has unpushed commits
    and reminds to push + create PR. Excludes --amend commits.
    """
    if "--amend" in git_cmd:
        return

    repo_root = get_repo_root(cwd)
    branch = get_current_branch(cwd)

    if not branch or branch in ("main", "master"):
        return

    # Check if remote tracking branch exists
    verify_result = run(
        ["git", "rev-parse", "--verify", f"origin/{branch}"],
        cwd=repo_root,
    )

    if verify_result.returncode != 0:
        # No remote tracking branch — all commits are unpushed (new branch)
        info(
            f"POST-COMMIT: Unpushed commits on '{branch}' (no remote tracking branch). "
            f"Remote is source of truth.\n"
            f"Run: `git push origin {branch}`, then create PR with `gh pr create`."
        )
        return

    # Remote exists — check for unpushed commits
    log_result = run(
        ["git", "log", f"origin/{branch}..HEAD", "--oneline"],
        cwd=repo_root,
    )
    if log_result.returncode == 0 and log_result.stdout.strip():
        count = len(log_result.stdout.strip().splitlines())
        info(
            f"POST-COMMIT: {count} unpushed commit(s) on '{branch}'. "
            f"Remote is source of truth.\n"
            f"Run: `git push origin {branch}`, then create PR with `gh pr create`."
        )


def gate_session_start_stale_branches(cwd):
    """Gate 6: SessionStart — list local merged branches awaiting cleanup.

    Scans `git branch --merged main` for the current repo, then for each
    candidate checks `gh pr list --head <branch> --state merged` to confirm
    the branch's PR has merged on GitHub. Emits a single info-nag listing
    cleanup commands. Fires once per Claude Code session via the
    SessionStart hook event.

    Behavior:
      - Caps inspection at 20 branches (avoid scaling issues in large repos)
      - Skips main / master from candidate list
      - Silent on pass (HWW #20) — no merged branches found, no output
      - Info-only — never auto-deletes (HWW #18: safest path first)

    Slim subset for v0.6.0: drops Linear / daily-plan / bot-issues /
    repo-pair-drift / error-audit-triage digests (myOS-specific).
    """
    repo_root = get_repo_root(cwd)

    # List local branches reachable from main
    result = run(
        ["git", "branch", "--merged", "main", "--format=%(refname:short)"],
        cwd=repo_root,
    )
    if result.returncode != 0:
        return  # Not a git repo, no main branch, or other error

    candidates = [
        line.strip() for line in result.stdout.splitlines()
        if line.strip() and line.strip() not in ("main", "master")
    ][:20]

    if not candidates:
        return

    # For each candidate, check whether a merged PR exists on GitHub
    merged = []
    for branch in candidates:
        pr_result = run(
            ["gh", "pr", "list", "--head", branch, "--state", "merged",
             "--limit", "1", "--json", "number"],
            cwd=repo_root,
        )
        if pr_result.returncode == 0 and pr_result.stdout.strip() not in ("", "[]"):
            merged.append(branch)

    if not merged:
        return

    count = len(merged)
    cleanup_cmds = "\n  ".join(f"git branch -d {b}" for b in merged[:5])
    if count > 5:
        cleanup_cmds += f"\n  # ... and {count - 5} more"

    info(
        f"STALE BRANCHES: {count} merged branch(es) awaiting cleanup in this repo. "
        f"Run:\n  {cleanup_cmds}\n"
        f"Reflog preserves recovery (~90d).",
        event_name="SessionStart",
    )


def gate_post_push(git_cmd, cwd):
    """Gate 5: Post-Push informational checks (PR-existence only — slim subset).

    Drops changelog / session-learnings / memory-index / spec-doc checks
    (all myOS-specific) — they ship in the full myOS gate, not here.
    """
    repo_root = get_repo_root(cwd)
    branch = get_current_branch(cwd)

    if branch in ("main", "master"):
        info("Pushed to main.")
        return

    # Check if PR exists
    result = run(
        ["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "url"],
        cwd=repo_root,
    )
    if result.returncode == 0 and result.stdout.strip() in ("", "[]"):
        info(
            f"ACTION REQUIRED: No PR for branch '{branch}'. "
            f"Create one now with `gh pr create`."
        )
    else:
        allow()


# --- Main dispatch ---

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""

    try:
        stdin_data = sys.stdin.read()
        hook_input = json.loads(stdin_data) if stdin_data.strip() else {}
    except json.JSONDecodeError:
        hook_input = {}

    cwd = hook_input.get("cwd", os.getcwd())

    # SessionStart mode has no tool_name — handle before the Bash check
    if mode == "--session-start":
        gate_session_start_stale_branches(cwd)
        allow()

    tool_name = hook_input.get("tool_name") or hook_input.get("toolName", "")
    tool_input = hook_input.get("tool_input") or hook_input.get("toolInput", {})

    # PreToolUse and PostToolUse: only care about Bash tool
    if tool_name != "Bash":
        allow()

    command = tool_input.get("command", "")
    if not command:
        allow()

    # Gate 0: BLOCK `cd <dir> && git ...` chains (PreToolUse only)
    if mode == "--pre-tool-use":
        offender = detect_cd_git_chain(command)
        if offender:
            deny(
                f"Do not chain `cd <dir> && git ...`. Found: `{offender}`. "
                f"Use `git -C <dir> ...` or the Bash tool's `cwd` parameter "
                f"instead. Chained `cd` leaks shell state and has caused "
                f"wrong-directory commits."
            )

    # Fast path: no git commands in this command string
    git_cmds = extract_git_commands(command)
    if not git_cmds:
        allow()

    if mode == "--pre-tool-use":
        for git_cmd in git_cmds:
            if re.match(r'^git\s+commit\b', git_cmd):
                gate_pre_commit(git_cmd, cwd)  # exits on deny/allow
            elif re.match(r'^git\s+push\b', git_cmd):
                gate_pre_push(git_cmd, cwd)
            elif re.match(r'^git\s+(checkout|switch|restore)\b', git_cmd):
                gate_pre_checkout(git_cmd, cwd)
        allow()

    elif mode == "--post-tool-use":
        for git_cmd in git_cmds:
            if re.match(r'^git\s+commit\b', git_cmd):
                gate_post_commit(git_cmd, cwd)
            elif re.match(r'^git\s+push\b', git_cmd):
                gate_post_push(git_cmd, cwd)
        allow()

    else:
        allow()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Fail-closed: output deny JSON on any exception
        sys.stderr.write(f"git-workflow-gate error: {e}\n")
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"Gate script error: {e}. Fix before proceeding.",
            }
        }))
        sys.exit(0)
