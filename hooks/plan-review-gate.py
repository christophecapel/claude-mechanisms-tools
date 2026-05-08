#!/usr/bin/env python3
"""Plan review gate for Claude Code hooks.

Phase 1 (PreToolUse on ExitPlanMode): Checks plan structural completeness
before approval -- required sections, code-vs-docs detection, keyword checks.

Phase 2 (PreToolUse on Bash/gh pr create): Compares plan's ## Files section
against actual git diff to catch execution gaps.

Fail-open: any unhandled exception allows with a SKIPPED warning.
Always-visible: emits a summary line on both pass and fail.
"""

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from plan_files_lib import (  # noqa: E402
    PLANS_DIR,
    extract_plan_files,
    find_best_plan_for_diff,
    normalize_to_repo_relative,
)

# Required sections for Phase 1 (heading pattern, label)
REQUIRED_SECTIONS = [
    (r"#{2,3}\s+Context", "Context"),
    (r"#{2,3}\s+Implementation", "Implementation"),
    (r"#{2,3}\s+.*[Tt]est", "Tests"),
    (r"#{2,3}\s+Verification", "Verification"),
    (r"#{2,3}\s+Pre-flight", "Pre-flight checks"),
    (r"#{2,3}\s+Files", "Files to create/modify"),
]

# Code-touching indicators: file extensions and directory paths
CODE_INDICATORS = re.compile(
    r'\.(py|js|ts|sh|json|yaml|yml|toml|zsh|bash)\b'
    r'|(?:scripts|tests|agents)/'
    r'|Dockerfile|Makefile|\.github/'
)

# Remediation tier detection (CC-75)
# Tier 1: instructions/memories as the fix
TIER1_SIGNALS = [
    (re.compile(r'feedback.memor', re.IGNORECASE), "feedback memory"),
    (re.compile(r'save.*memor', re.IGNORECASE), "save a memory"),
    (re.compile(r'remember\s+to\b', re.IGNORECASE), "remember to"),
    (re.compile(r'note\s+to\s+self', re.IGNORECASE), "note to self"),
    (re.compile(
        r'(?:add|update|new|create)\s+.*(?:CLAUDE\.md|How We Work).*(?:entry|rule|principle)',
        re.IGNORECASE
    ), "CLAUDE.md / How We Work entry"),
    (re.compile(r'claude-memory/feedback_\S+\.md', re.IGNORECASE), "feedback memory file"),
]

# Tier 2: mechanisms as the fix
TIER2_SIGNALS = [
    (re.compile(r'(?:add|create|build|implement|extend|write)\s+.*(?:test|hook|gate|script|check)', re.IGNORECASE), "create test/hook/gate/script"),
    (re.compile(r'tests/\S+\.py', re.IGNORECASE), "test file"),
    (re.compile(r'scripts/\S+\.py', re.IGNORECASE), "script file"),
    (re.compile(r'(?:pre-commit|pre-push|Stop hook|PreToolUse|PostToolUse)', re.IGNORECASE), "hook reference"),
    (re.compile(r'\.github/workflows/', re.IGNORECASE), "CI workflow"),
    (re.compile(r'test_\w+', re.IGNORECASE), "test function"),
]

# POC / validation signals (sourced from how-would-youadd-this-sprightly-willow.md).
# Plans that build new mechanisms should include a Phase 0 POC or equivalent
# validation gate before committing to production wiring (HWW #16).
POC_SIGNALS = [
    (re.compile(r'\bPOC\b'), "POC mention"),
    (re.compile(r'proof\s+of\s+concept', re.IGNORECASE), "proof of concept"),
    (re.compile(r'\b(?:spike|prototype|throwaway)\b', re.IGNORECASE), "spike/prototype/throwaway"),
    (re.compile(r'#{2,3}\s+Phase\s*0\b', re.IGNORECASE), "Phase 0 heading"),
    (re.compile(r'validation\s+gate', re.IGNORECASE), "validation gate"),
    (re.compile(r'\bdry.run\b', re.IGNORECASE), "dry-run"),
    (re.compile(r'smallest\s+shippable', re.IGNORECASE), "smallest shippable"),
    (re.compile(r'hard\s+gate\s+before', re.IGNORECASE), "hard gate before"),
]

# Docs audit signals -- the plan must explicitly enumerate docs to update/create,
# not just rely on the changelog/session-learnings/mechanism keyword checks.
DOCS_AUDIT_SIGNALS = [
    (re.compile(r'#{2,3}\s+Doc(?:umentation|s)?\b', re.IGNORECASE), "Docs heading"),
    (re.compile(r'#{2,3}\s+Documentation\s+surfaces', re.IGNORECASE), "Documentation surfaces heading"),
    (re.compile(r'docs?\s+to\s+(?:update|create)', re.IGNORECASE), "docs to update/create phrase"),
    (re.compile(r'existing\s+docs?\b', re.IGNORECASE), "existing docs phrase"),
    (re.compile(r'docs?\s+audit', re.IGNORECASE), "docs audit phrase"),
    (re.compile(r'documentation\s+surfaces', re.IGNORECASE), "documentation surfaces phrase"),
]

# "New work" signals -- only advise POC when the plan actually builds something
# new. A bug-fix plan modifying existing files shouldn't be nagged about POC.
NEW_WORK_SIGNALS = [
    re.compile(r'\(new\)'),
    re.compile(r'\bnew\s+(?:script|mechanism|skill|agent|clusterer|hook|gate)\b', re.IGNORECASE),
    re.compile(r'\b(?:build|create|implement|introduce)\s+.*(?:script|mechanism|skill|agent|clusterer)', re.IGNORECASE),
]


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


def info(message):
    """Output informational context (non-blocking) and exit."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": message,
        }
    }))
    sys.exit(0)


def allow():
    """Allow silently."""
    sys.exit(0)


def find_plan_file():
    """Find the most recently modified plan file in ~/.claude/plans/."""
    if not PLANS_DIR.exists():
        return None
    plan_files = list(PLANS_DIR.glob("*.md"))
    if not plan_files:
        return None
    return max(plan_files, key=lambda f: f.stat().st_mtime)


def section_has_content(plan_text, heading_pattern):
    """Check if a section heading exists AND has at least one non-empty line of content."""
    lines = plan_text.split("\n")
    in_section = False
    section_level = None
    for line in lines:
        stripped = line.strip()
        if re.match(heading_pattern, stripped):
            in_section = True
            # Determine heading level (## = 2, ### = 3)
            section_level = len(re.match(r"^(#+)", stripped).group(1))
            continue
        if in_section:
            # Next heading at same or higher level means section ended without content
            heading_match = re.match(r"^(#+)\s+", stripped)
            if heading_match and len(heading_match.group(1)) <= section_level:
                return False
            if stripped:
                return True
    return False


def is_code_touching(plan_text):
    """Determine if the plan touches code files (not docs-only).

    Default assumption is code-touching. A plan is docs-only only if every
    file path referenced is a .md file outside scripts/, tests/, agents/.
    """
    return bool(CODE_INDICATORS.search(plan_text))


def check_remediation_tier(plan_text):
    """Check if the plan's primary remediation is tier 1 (instructions) without tier 2 (mechanism).

    Returns (has_tier1: bool, has_tier2: bool, tier1_matches: list[str]).
    """
    tier1_matches = []
    for pattern, label in TIER1_SIGNALS:
        if pattern.search(plan_text):
            if label not in tier1_matches:
                tier1_matches.append(label)

    has_tier2 = any(pattern.search(plan_text) for pattern, _ in TIER2_SIGNALS)

    return bool(tier1_matches), has_tier2, tier1_matches


def check_poc_signal(plan_text):
    """Return (has_new_work, has_poc, matches).

    Advisory fires only when the plan introduces new work AND lacks POC language.
    """
    has_new_work = any(p.search(plan_text) for p in NEW_WORK_SIGNALS)
    matches = []
    for pattern, label in POC_SIGNALS:
        if pattern.search(plan_text) and label not in matches:
            matches.append(label)
    return has_new_work, bool(matches), matches


def check_docs_audit(plan_text):
    """Return (has_audit, matches).

    Blocking check for code-touching plans: plan must include an explicit
    docs-audit heading or phrase (enumerating docs to update/create).
    """
    matches = []
    for pattern, label in DOCS_AUDIT_SIGNALS:
        if pattern.search(plan_text) and label not in matches:
            matches.append(label)
    return bool(matches), matches


def phase1_check(plan_text):
    """Phase 1: Check plan structural completeness.

    Returns (passed: bool, missing: list[str], advisories: list[str]).
    """
    missing = []
    advisories = []

    # Check required sections with content
    for pattern, label in REQUIRED_SECTIONS:
        if not section_has_content(plan_text, pattern):
            missing.append(label)

    # Code-touching checks
    if is_code_touching(plan_text):
        if "changelog" not in plan_text.lower():
            missing.append("changelog reference (code-touching plan)")
        if "session-learnings" not in plan_text.lower():
            missing.append("session-learnings reference (code-touching plan)")
        if "mechanism" not in plan_text.lower():
            missing.append("mechanism reference (code-touching plan)")
        # Docs audit (blocking): force explicit enumeration of docs to update/create.
        has_audit, _ = check_docs_audit(plan_text)
        if not has_audit:
            missing.append("docs audit (code-touching plan)")

    # Advisory checks (warn, don't block)
    if is_code_touching(plan_text):
        has_spec_doc = bool(
            re.search(r"spec.doc", plan_text, re.IGNORECASE)
            or re.search(r"docs/\S+\.md", plan_text)
        )
        if not has_spec_doc:
            advisories.append("no spec-doc reference found")

    has_pr_body = bool(
        re.search(r"##\s+PR", plan_text)
        or "PR body" in plan_text
    )
    if not has_pr_body:
        advisories.append("no PR body template found")

    # Remediation tier check (CC-75): warn when primary fix is tier 1 without tier 2
    if is_code_touching(plan_text):
        has_tier1, has_tier2, tier1_matches = check_remediation_tier(plan_text)
        if has_tier1 and not has_tier2:
            detected = ", ".join(tier1_matches)
            advisories.append(
                f"Primary remediation is tier 1 (instructions). "
                f"Consider a mechanism (hook/gate/test) first per HWW #7 + #17. "
                f"Detected: {detected}"
            )

    # POC advisory: only fires on code-touching plans that introduce new work
    # and lack any POC / validation-gate language. HWW #16 (smallest shippable first).
    if is_code_touching(plan_text):
        has_new_work, has_poc, _ = check_poc_signal(plan_text)
        if has_new_work and not has_poc:
            advisories.append(
                "No POC / validation step found. Consider Phase 0 POC "
                "(dry-run, throwaway, hard gate) before production wiring per HWW #16."
            )

    passed = len(missing) == 0
    return passed, missing, advisories


def parse_head_branch(command):
    """Extract the value of --head / -H / --head=<branch> from a gh command.

    `gh pr create --head <branch>` (and the short form `-H <branch>`, plus the
    `--head=<branch>` equals form) explicitly names the branch the PR is being
    created for. When present, the gate must compute its diff against that
    branch, not against HEAD-of-cwd — those can disagree when the gate runs
    from a worktree or main checkout that is on a different branch than the
    one being PR'd. CC-174.

    Returns the branch name, or None if not specified.
    """
    if not command:
        return None
    eq_match = re.search(r"--head=(\S+)", command)
    if eq_match:
        return eq_match.group(1)
    space_match = re.search(r"(?:--head|-H)\s+(\S+)", command)
    if space_match:
        return space_match.group(1)
    return None


def is_pr_create_command(command):
    """Return True iff the Bash command actually invokes `gh pr create` or `gh pr edit`.

    Substring match against the raw command string falsely fires on commit
    messages and PR bodies that mention the trigger phrases as text.
    Token-aware match only fires when the command actually invokes the gh
    subcommand. CC-175.

    Tokenizes with shlex; quoted strings (HEREDOC bodies, --body=... args)
    become single opaque tokens that cannot match the (`gh`,`pr`,`create`)
    triple. Walks every position so prefixes (env vars, &&-chains,
    `;`-separated commands, leading `cd ...`) don't break detection.

    Falls back to the legacy substring check on shlex parse error
    (unbalanced quotes etc.) — preserves prior behaviour for malformed
    input rather than failing closed.
    """
    if not command:
        return False
    try:
        tokens = shlex.split(command, comments=False, posix=True)
    except ValueError:
        return "gh pr create" in command or "gh pr edit" in command
    for i in range(len(tokens) - 2):
        if tokens[i] == "gh" and tokens[i + 1] == "pr" and tokens[i + 2] in ("create", "edit"):
            return True
    return False


def get_diff_files(cwd, head_ref=None):
    """Compute the set of changed files for the diff target relative to origin/main.

    When `head_ref` is provided (parsed from `gh pr create --head <branch>`),
    diff against that branch only. When `head_ref` is None, fall back to the
    legacy behaviour: HEAD plus unstaged/staged/untracked from cwd. The legacy
    path is what `gh pr create` (no --head) implies — the current branch in cwd
    is what gets pushed.

    The named-head path deliberately omits unstaged/staged/untracked files:
    those are cwd state, irrelevant to a PR for an explicitly-named branch
    (which may live in a different worktree). Mixing them in is exactly the
    false-overlap path CC-174 fixes.

    Returns (diff_files: set[str], skip_reason: str|None). If skip_reason is
    non-None, callers should skip the file audit entirely (fail-open)."""
    # Repo root
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, cwd=cwd, timeout=5
        )
        if result.returncode != 0:
            return set(), "not in a git repo -- skipping file audit"
        repo_root = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return set(), "git not available -- skipping file audit"

    diff_target = head_ref if head_ref else "HEAD"

    # If head_ref was supplied, validate it actually resolves before using it.
    # If the named branch doesn't resolve (typo, deleted, never pushed), fall
    # back to legacy HEAD-of-cwd behaviour rather than failing closed.
    if head_ref:
        try:
            check = subprocess.run(
                ["git", "rev-parse", "--verify", f"{head_ref}^{{commit}}"],
                capture_output=True, text=True, cwd=repo_root, timeout=5
            )
            if check.returncode != 0:
                diff_target = "HEAD"
                head_ref = None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            diff_target = "HEAD"
            head_ref = None

    # Merge base
    try:
        result = subprocess.run(
            ["git", "merge-base", diff_target, "origin/main"],
            capture_output=True, text=True, cwd=repo_root, timeout=5
        )
        base = result.stdout.strip() if result.returncode == 0 else "origin/main"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        base = "origin/main"

    # Committed diff
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...{diff_target}"],
            capture_output=True, text=True, cwd=repo_root, timeout=10
        )
        if result.returncode != 0:
            return set(), "git diff failed -- skipping file audit"
        diff_files = set(result.stdout.strip().split("\n")) if result.stdout.strip() else set()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return set(), "git diff failed -- skipping file audit"

    # Best-effort: unstaged, staged, untracked.
    # Skip when head_ref is explicit -- those are cwd state, not PR state.
    if head_ref is None:
        for args in (["diff", "--name-only", "HEAD"],
                     ["diff", "--name-only", "--cached"],
                     ["ls-files", "--others", "--exclude-standard"]):
            try:
                result = subprocess.run(
                    ["git"] + args,
                    capture_output=True, text=True, cwd=repo_root, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    diff_files.update(result.stdout.strip().split("\n"))
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

    return diff_files, None


def find_plan_for_diff(diff_files, plans_dir=None):
    """Backwards-compatible wrapper — delegates to plan_files_lib.find_best_plan_for_diff."""
    return find_best_plan_for_diff(set(diff_files), plans_dir)


def phase2_check(plan_text, cwd, diff_files=None):
    """Phase 2: Compare plan's file list against actual git diff.

    If `diff_files` is supplied, use it; otherwise compute it from `cwd`.
    (Main() supplies the set it already computed when picking the matching
    plan, avoiding a redundant git call.)

    Returns (passed: bool, missing: list[str], external_warnings: list[str]).
    """
    repo_files, external_files, conditional_files = extract_plan_files(plan_text)

    if not repo_files and not external_files:
        return True, [], ["no files listed in plan's ## Files section"]

    if diff_files is None:
        diff_files, skip_reason = get_diff_files(cwd)
        if skip_reason:
            return True, [], [skip_reason]

    # Compare plan files against diff
    missing = []
    for path_str in repo_files:
        relative = normalize_to_repo_relative(path_str, None)
        if relative not in diff_files:
            missing.append(path_str)

    # External files are advisory only
    external_warnings = []
    for path_str in external_files:
        external_warnings.append(f"{path_str} (external -- verify manually)")

    return len(missing) == 0, missing, external_warnings


CODE_KEYWORD_CHECKS = [
    ("changelog", "changelog keyword"),
    ("session-learnings", "session-learnings keyword"),
    ("mechanism", "mechanism keyword"),
    ("docs audit", "docs audit"),
]


def format_phase1_checklist(missing, advisories, code_touching):
    """Format Phase 1 results as a per-check checklist."""
    lines = ["PLAN REVIEW GATE:"]

    # Section checks
    for _, label in REQUIRED_SECTIONS:
        if label in missing:
            lines.append(f"  [FAIL] {label} -- empty or missing")
        else:
            lines.append(f"  [PASS] {label}")

    # Code-touching keyword checks
    if code_touching:
        for keyword, label in CODE_KEYWORD_CHECKS:
            # docs audit uses a different missing-label format (signal check,
            # not a keyword-substring check)
            if keyword == "docs audit":
                missing_label = "docs audit (code-touching plan)"
            else:
                missing_label = f"{keyword} reference (code-touching plan)"
            if missing_label in missing:
                lines.append(f"  [FAIL] {label} -- missing")
            else:
                lines.append(f"  [PASS] {label}")

    # Advisories
    for adv in advisories:
        lines.append(f"  [WARN] {adv}")

    # Summary
    fail_count = sum(1 for l in lines if "[FAIL]" in l)
    warn_count = sum(1 for l in lines if "[WARN]" in l)
    pass_count = sum(1 for l in lines if "[PASS]" in l)
    total = pass_count + fail_count

    if fail_count > 0:
        summary = f"  RESULT: FAIL ({fail_count} blocking"
        if warn_count > 0:
            summary += f", {warn_count} advisory"
        summary += ")"
        lines.append(summary)
        if code_touching:
            lines.append("  Ensure plan specifies *when* to write session-learnings (during implementation, not deferred).")
    else:
        summary = f"  RESULT: PASS ({total}/{total} checks"
        if warn_count > 0:
            summary += f", {warn_count} advisory"
        summary += ")"
        lines.append(summary)

    return "\n".join(lines)


def format_phase2_checklist(plan_text, missing, warnings):
    """Format Phase 2 results as a per-file checklist."""
    repo_files, external_files, conditional_files = extract_plan_files(plan_text)
    lines = ["PRE-PR AUDIT:"]

    # Repo files
    for path_str in repo_files:
        relative = normalize_to_repo_relative(path_str, "")
        if path_str in missing:
            lines.append(f"  [FAIL] {relative} -- not in diff")
        else:
            lines.append(f"  [PASS] {relative}")

    # External files
    for path_str in external_files:
        lines.append(f"  [WARN] {path_str} (external -- verify manually)")

    # Conditional files
    for path_str in conditional_files:
        relative = normalize_to_repo_relative(path_str, "")
        lines.append(f"  [SKIP] {relative} (conditional)")

    # Summary
    fail_count = sum(1 for l in lines if "[FAIL]" in l)
    warn_count = sum(1 for l in lines if "[WARN]" in l)
    pass_count = sum(1 for l in lines if "[PASS]" in l)
    total_repo = len(repo_files)

    if fail_count > 0:
        summary = f"  RESULT: FAIL ({fail_count} planned file(s) not in diff)"
        lines.append(summary)
    else:
        summary = f"  RESULT: PASS ({total_repo}/{total_repo} repo files in diff"
        if warn_count > 0:
            summary += f", {warn_count} external to verify"
        summary += ")"
        lines.append(summary)

    return "\n".join(lines)


def main():
    mode = "phase1"  # default
    if "--mode=pre-pr" in sys.argv:
        mode = "phase2"

    try:
        stdin_data = sys.stdin.read()
        hook_input = json.loads(stdin_data) if stdin_data.strip() else {}
    except (json.JSONDecodeError, Exception) as e:
        if mode == "phase1":
            info(f"PLAN REVIEW GATE: SKIPPED (stdin parse error: {e})")
        # Phase 2: allow silently for non-pr commands
        allow()

    tool_name = hook_input.get("tool_name") or hook_input.get("toolName", "")
    tool_input = hook_input.get("tool_input") or hook_input.get("toolInput", {})
    cwd = hook_input.get("cwd", os.getcwd())

    if mode == "phase2":
        # CC-175: token-aware match. Substring match falsely fired on commit
        # messages and PR bodies that referenced the trigger phrases as text.
        if not is_pr_create_command(tool_input.get("command", "")):
            allow()

    if mode == "phase1":
        plan_file = find_plan_file()
        if not plan_file:
            info("PLAN REVIEW GATE: SKIPPED (no plan file found)")
            allow()

        try:
            plan_text = plan_file.read_text()
        except Exception as e:
            info(f"PLAN REVIEW GATE: SKIPPED (error reading plan: {e})")
            allow()

        passed, missing, advisories = phase1_check(plan_text)
        code_touching = is_code_touching(plan_text)
        if not passed:
            msg = format_phase1_checklist(missing, advisories, code_touching)
            deny(msg)
        elif advisories:
            info(f"PLAN REVIEW: pass with {len(advisories)} advisories")
        else:
            allow()

    elif mode == "phase2":
        # CC-80: pick the plan by best overlap with the actual diff, not by
        # global mtime -- prevents cross-session blocking when multiple Claude
        # Code sessions have written plans to ~/.claude/plans/.
        # CC-174: parse --head from the gh command so the diff reflects the
        # branch being PR'd, not whatever HEAD happens to be in cwd.
        command = tool_input.get("command", "")
        head_ref = parse_head_branch(command)
        diff_files, skip_reason = get_diff_files(cwd, head_ref=head_ref)
        if skip_reason:
            info(f"PRE-PR AUDIT: SKIPPED ({skip_reason})")
            allow()

        plan_file = find_plan_for_diff(diff_files)
        if not plan_file:
            info(
                "PRE-PR AUDIT: SKIPPED -- no plan in ~/.claude/plans/ overlaps "
                "this diff. Either the PR's changes pre-date any plan, or this "
                "session never filed one. Not blocking."
            )
            allow()

        try:
            plan_text = plan_file.read_text()
        except Exception as e:
            info(f"PRE-PR AUDIT: SKIPPED (error reading plan {plan_file.name}: {e})")
            allow()

        passed, missing, warnings = phase2_check(plan_text, cwd, diff_files=diff_files)
        if not passed:
            msg = format_phase2_checklist(plan_text, missing, warnings)
            deny(msg)
        elif warnings:
            info(f"PRE-PR AUDIT: pass with {len(warnings)} warnings")
        else:
            allow()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Fail-open: never block on unexpected errors
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": f"PLAN REVIEW GATE: SKIPPED (error: {e})",
            }
        }), file=sys.stdout)
        print(f"plan-review-gate.py error: {e}", file=sys.stderr)
        sys.exit(0)
