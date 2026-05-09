#!/usr/bin/env python3
"""Unit and system tests for plan-review-gate.py.

Tests feed synthetic plan files and hook JSON to the gate script and assert
expected output. Uses temp directories to simulate ~/.claude/plans/.

Run: python3 -m pytest tests/test_plan_review_gate.py -v
"""

import json
import os
# Pin REPO_PREFIXES for tests — fixtures use ~/myOS/ and /Users/christophe/myOS/ literals.
# Setting before plan_files_lib import below ensures auto-detect doesn't substitute toolkit paths.
os.environ["CLAUDE_PLAN_REPO_PREFIXES"] = "~/myOS/,/Users/christophe/myOS/"
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE_SCRIPT = REPO_ROOT / "hooks" / "plan-review-gate.py"
CWD = str(REPO_ROOT)


def run_gate(mode_args, hook_input, plans_dir=None, timeout=10):
    """Run the gate script with given mode and input, return (stdout, stderr, exit_code)."""
    cmd = [sys.executable, str(GATE_SCRIPT)] + mode_args
    env = os.environ.copy()
    if plans_dir:
        # We'll monkey-patch PLANS_DIR via env var -- need to add support in script
        # For now, use subprocess with modified HOME to control plans dir
        pass
    result = subprocess.run(
        cmd,
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=CWD,
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def parse_output(stdout):
    """Parse JSON output, return dict or None."""
    if not stdout:
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


def get_decision(output):
    """Extract permissionDecision from parsed output."""
    if not output:
        return None
    return output.get("hookSpecificOutput", {}).get("permissionDecision")


def get_reason(output):
    """Extract permissionDecisionReason from parsed output."""
    if not output:
        return ""
    return output.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


def get_context(output):
    """Extract additionalContext from parsed output."""
    if not output:
        return ""
    return output.get("hookSpecificOutput", {}).get("additionalContext", "")


# --- Import the module for direct testing ---
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "plan_review_gate",
    str(REPO_ROOT / "hooks" / "plan-review-gate.py"),
)
prg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prg)


COMPLETE_PLAN = textwrap.dedent("""\
    # Plan: Test Plan

    ## Context

    This is a test plan for the plan-review-gate.
    Phase 0 POC: dry-run the script locally before wiring.

    ## Pre-flight checks

    Checked all downstream consumers.

    ## Implementation

    Add a new script to scripts/foo.py.

    ## Files to create/modify

    1. **`~/myOS/scripts/foo.py`** (new)
    2. **`~/myOS/docs/changelog.md`** (modify)
    3. **`~/myOS/docs/session-learnings.md`** (modify)

    ## Docs

    Existing docs to update: docs/foo.md. No new docs to create.

    ## Tests

    1. test_foo -- basic test

    ## Verification

    1. Run tests
    2. Manual check

    ## PR body

    What/Why/How.

    Update mechanism_foo.md and docs/changelog.md and docs/session-learnings.md.
""")

DOCS_ONLY_PLAN = textwrap.dedent("""\
    # Plan: Docs Update

    ## Context

    Updating documentation only.

    ## Pre-flight checks

    No cascade -- docs only.

    ## Implementation

    Update README.md with new section.

    ## Files to create/modify

    1. **`~/myOS/README.md`** (modify)
    2. **`~/myOS/docs/architecture.md`** (modify)

    ## Tests

    No code changes, visual review only.

    ## Verification

    1. Read the docs and verify formatting
""")

MINIMAL_CODE_PLAN_MISSING_CHANGELOG = textwrap.dedent("""\
    # Plan: Code Change

    ## Context

    Fixing a bug in scripts/foo.py.

    ## Pre-flight checks

    No cascade.

    ## Implementation

    Fix the bug in scripts/foo.py.

    ## Files to create/modify

    1. **`~/myOS/scripts/foo.py`** (modify)

    ## Tests

    1. test_fix -- regression test

    ## Verification

    1. Run tests
""")


# ============================================================
# Phase 1 Tests
# ============================================================

class TestPhase1SectionChecks(unittest.TestCase):
    """Phase 1: required section presence with content."""

    def test_plan_with_all_sections(self):
        passed, missing, advisories = prg.phase1_check(COMPLETE_PLAN)
        self.assertTrue(passed)
        self.assertEqual(missing, [])

    def test_plan_missing_context(self):
        plan = COMPLETE_PLAN.replace("## Context\n\nThis is a test plan", "")
        passed, missing, _ = prg.phase1_check(plan)
        self.assertFalse(passed)
        self.assertIn("Context", missing)

    def test_plan_missing_tests(self):
        plan = COMPLETE_PLAN.replace("## Tests\n\n1. test_foo -- basic test", "")
        passed, missing, _ = prg.phase1_check(plan)
        self.assertFalse(passed)
        self.assertIn("Tests", missing)

    def test_plan_missing_preflight(self):
        plan = COMPLETE_PLAN.replace("## Pre-flight checks\n\nChecked all downstream consumers.", "")
        passed, missing, _ = prg.phase1_check(plan)
        self.assertFalse(passed)
        self.assertIn("Pre-flight checks", missing)

    def test_plan_missing_verification(self):
        plan = COMPLETE_PLAN.replace("## Verification\n\n1. Run tests\n2. Manual check", "")
        passed, missing, _ = prg.phase1_check(plan)
        self.assertFalse(passed)
        self.assertIn("Verification", missing)

    def test_plan_missing_files_section(self):
        plan = COMPLETE_PLAN.replace(
            "## Files to create/modify\n\n1. **`~/myOS/scripts/foo.py`** (new)\n"
            "2. **`~/myOS/docs/changelog.md`** (modify)\n"
            "3. **`~/myOS/docs/session-learnings.md`** (modify)",
            ""
        )
        passed, missing, _ = prg.phase1_check(plan)
        self.assertFalse(passed)
        self.assertIn("Files to create/modify", missing)

    def test_bare_heading_no_content(self):
        plan = textwrap.dedent("""\
            # Plan: Test

            ## Context

            Some context.

            ## Pre-flight checks

            Done.

            ## Implementation

            Do the thing.

            ## Files to create/modify

            1. **`~/myOS/scripts/foo.py`**

            ## Tests
            ## Verification

            1. Run tests

            Update mechanism and changelog and session-learnings.
        """)
        passed, missing, _ = prg.phase1_check(plan)
        self.assertFalse(passed)
        self.assertIn("Tests", missing)


class TestPhase1CodeTouchingChecks(unittest.TestCase):
    """Phase 1: changelog, session-learnings, mechanism checks for code-touching plans."""

    def test_code_plan_missing_changelog(self):
        plan = MINIMAL_CODE_PLAN_MISSING_CHANGELOG
        passed, missing, _ = prg.phase1_check(plan)
        self.assertFalse(passed)
        self.assertIn("changelog reference (code-touching plan)", missing)

    def test_code_plan_missing_session_learnings(self):
        plan = MINIMAL_CODE_PLAN_MISSING_CHANGELOG
        passed, missing, _ = prg.phase1_check(plan)
        self.assertIn("session-learnings reference (code-touching plan)", missing)

    def test_code_plan_missing_mechanism(self):
        plan = MINIMAL_CODE_PLAN_MISSING_CHANGELOG
        passed, missing, _ = prg.phase1_check(plan)
        self.assertIn("mechanism reference (code-touching plan)", missing)

    def test_docs_only_plan_no_changelog_ok(self):
        passed, missing, _ = prg.phase1_check(DOCS_ONLY_PLAN)
        self.assertTrue(passed)
        self.assertEqual(missing, [])

    def test_json_config_is_code(self):
        plan = DOCS_ONLY_PLAN.replace("README.md", "settings.json")
        self.assertTrue(prg.is_code_touching(plan))

    def test_scripts_dir_is_code(self):
        self.assertTrue(prg.is_code_touching("Update scripts/foo.py"))

    def test_agents_dir_is_code(self):
        self.assertTrue(prg.is_code_touching("Modify agents/retro.md"))

    def test_pure_docs_not_code(self):
        self.assertFalse(prg.is_code_touching("Update README.md and docs/architecture.md"))


class TestPhase1Advisories(unittest.TestCase):
    """Phase 1: advisory checks (warn, don't block)."""

    def test_spec_doc_advisory(self):
        # Plan touching code but no spec doc reference
        plan = COMPLETE_PLAN.replace("docs/changelog.md", "other/changelog.md")
        # Remove the docs/ path reference
        plan_no_spec = plan.replace("docs/session-learnings.md", "learnings.md")
        _, _, advisories = prg.phase1_check(plan_no_spec)
        # May or may not have advisory depending on detection
        # The key thing is it shouldn't be in missing (blocking)

    def test_pr_body_advisory(self):
        plan = COMPLETE_PLAN.replace("## PR body\n\nWhat/Why/How.", "")
        passed, missing, advisories = prg.phase1_check(plan)
        # PR body is advisory, shouldn't block
        self.assertTrue(passed)
        self.assertIn("no PR body template found", advisories)


class TestPhase1EdgeCases(unittest.TestCase):
    """Phase 1: edge cases and error handling."""

    def test_malformed_markdown(self):
        plan = "This is not valid markdown with no headings at all\njust text."
        passed, missing, _ = prg.phase1_check(plan)
        self.assertFalse(passed)
        # Should list all required sections as missing

    def test_empty_plan(self):
        passed, missing, _ = prg.phase1_check("")
        self.assertFalse(passed)
        self.assertEqual(len(missing), len(prg.REQUIRED_SECTIONS))


# ============================================================
# POC advisory + Docs audit (sprightly-willow patterns)
# ============================================================

# Plan that introduces new work (a new script) but omits POC language and
# docs-audit language. Used as the negative fixture for both checks.
NEW_WORK_NO_POC_NO_AUDIT = textwrap.dedent("""\
    # Plan: Build a new thing

    ## Context

    Building a new mechanism.

    ## Pre-flight checks

    Clean.

    ## Implementation

    Create scripts/foo.py with the new logic.

    ## Files to create/modify

    1. **`~/myOS/scripts/foo.py`** (new)
    2. **`~/myOS/docs/changelog.md`** (modify)
    3. **`~/myOS/docs/session-learnings.md`** (modify)

    ## Tests

    1. test_foo

    ## Verification

    1. Run tests

    Update mechanism_foo.md too.
""")

# Bug-fix plan: modifies an existing file, no "new" signals. Should NOT trigger
# POC advisory even without POC language. Prevents the advisory from over-firing.
BUG_FIX_NO_NEW_WORK = textwrap.dedent("""\
    # Plan: Fix existing bug

    ## Context

    Fix a bug in the existing parser.

    ## Pre-flight checks

    Clean.

    ## Implementation

    Adjust the regex in scripts/foo.py.

    ## Files to create/modify

    1. **`~/myOS/scripts/foo.py`** (modify)
    2. **`~/myOS/docs/changelog.md`** (modify)
    3. **`~/myOS/docs/session-learnings.md`** (modify)

    ## Docs

    Existing docs to update: none beyond changelog + session-learnings.

    ## Tests

    1. test_fix -- regression test

    ## Verification

    1. Run tests

    Update mechanism note.
""")

# Mirrors the sprightly-willow structure: explicit Phase 0 + documentation
# surfaces table. Used as the positive fixture for both checks.
SPRIGHTLY_STYLE_PLAN = textwrap.dedent("""\
    # Plan: Build a new cluster mechanism

    ## Context

    Build a new clusterer. POC-first because the heuristics are uncertain.

    ## Pre-flight checks

    Clean.

    ## Implementation

    ### Phase 0 -- POC

    Dry-run against real data; hard gate before production wiring.

    ### Phase 1 -- Production

    Wire the clusterer into the pipeline.

    ## Files to create/modify

    1. **`~/myOS/scripts/foo.py`** (new)
    2. **`~/myOS/docs/changelog.md`** (modify)
    3. **`~/myOS/docs/session-learnings.md`** (modify)

    ## Documentation surfaces by audience

    | Audience | Surface | What it says |
    |---|---|---|
    | Future-Claude | docs/foo.md | How to act on findings |
    | User | skill README | Trigger phrases |

    ## Tests

    1. test_foo

    ## Verification

    1. Run tests; mechanism_foo.md updated.
""")


class TestPhase1POCAdvisory(unittest.TestCase):
    """POC / validation advisory -- fires when code-touching plan introduces
    new work but lacks POC language. HWW #16 (smallest shippable first)."""

    POC_ADVISORY_TEXT = "No POC / validation step found"

    def test_code_plan_with_new_work_missing_poc_warns(self):
        """`(new)` file + no POC mention -> advisory fires."""
        _, _, advisories = prg.phase1_check(NEW_WORK_NO_POC_NO_AUDIT)
        self.assertTrue(
            any(self.POC_ADVISORY_TEXT in a for a in advisories),
            f"Expected POC advisory, got: {advisories}",
        )

    def test_code_plan_with_poc_mention_no_warn(self):
        """Plan containing 'POC' passes the POC check."""
        _, _, advisories = prg.phase1_check(COMPLETE_PLAN)
        self.assertFalse(
            any(self.POC_ADVISORY_TEXT in a for a in advisories),
            f"Did not expect POC advisory, got: {advisories}",
        )

    def test_code_plan_without_new_work_no_poc_warn(self):
        """Bug-fix style plan (no `(new)`, no 'new script') -> no POC advisory.

        Guards against over-firing on every code-touching plan.
        """
        _, _, advisories = prg.phase1_check(BUG_FIX_NO_NEW_WORK)
        self.assertFalse(
            any(self.POC_ADVISORY_TEXT in a for a in advisories),
            f"Bug-fix plan should not trigger POC advisory, got: {advisories}",
        )

    def test_docs_only_plan_no_poc_warn(self):
        """Pure docs plan is exempt from POC advisory."""
        _, _, advisories = prg.phase1_check(DOCS_ONLY_PLAN)
        self.assertFalse(
            any(self.POC_ADVISORY_TEXT in a for a in advisories),
        )

    def test_phase_0_heading_counts_as_poc(self):
        """`## Phase 0` heading alone satisfies the POC signal."""
        plan = NEW_WORK_NO_POC_NO_AUDIT.replace(
            "## Implementation",
            "## Implementation\n\n### Phase 0\n\nValidate first.",
        )
        has_new_work, has_poc, matches = prg.check_poc_signal(plan)
        self.assertTrue(has_new_work)
        self.assertTrue(has_poc)
        self.assertIn("Phase 0 heading", matches)

    def test_dry_run_counts_as_poc(self):
        """'dry-run' mention satisfies the POC signal (HWW #13)."""
        plan = NEW_WORK_NO_POC_NO_AUDIT.replace(
            "## Implementation\n\nCreate",
            "## Implementation\n\nDry-run against real data first. Create",
        )
        _, has_poc, matches = prg.check_poc_signal(plan)
        self.assertTrue(has_poc)
        self.assertIn("dry-run", matches)


class TestPhase1DocsAudit(unittest.TestCase):
    """Docs audit -- blocking check that code-touching plans explicitly
    enumerate docs to update/create (not just rely on the changelog/
    session-learnings/mechanism keyword checks)."""

    AUDIT_MISSING_LABEL = "docs audit (code-touching plan)"

    def test_code_plan_with_docs_heading_passes(self):
        """A `## Docs` heading satisfies the audit."""
        plan = NEW_WORK_NO_POC_NO_AUDIT.replace(
            "## Tests",
            "## Docs\n\nNo other docs beyond changelog + session-learnings.\n\n## Tests",
        )
        _, missing, _ = prg.phase1_check(plan)
        self.assertNotIn(self.AUDIT_MISSING_LABEL, missing)

    def test_code_plan_with_docs_audit_phrase_passes(self):
        """Body phrase 'existing docs' satisfies the audit."""
        plan = NEW_WORK_NO_POC_NO_AUDIT.replace(
            "## Implementation\n\nCreate",
            "## Implementation\n\nExisting docs to update: docs/foo.md. Create",
        )
        _, missing, _ = prg.phase1_check(plan)
        self.assertNotIn(self.AUDIT_MISSING_LABEL, missing)

    def test_code_plan_missing_docs_audit_fails(self):
        """Code plan with no docs-audit heading or phrase -> blocking miss."""
        passed, missing, _ = prg.phase1_check(NEW_WORK_NO_POC_NO_AUDIT)
        self.assertFalse(passed)
        self.assertIn(self.AUDIT_MISSING_LABEL, missing)

    def test_docs_only_plan_no_docs_audit_check(self):
        """Docs-only plans skip the docs-audit check entirely."""
        passed, missing, _ = prg.phase1_check(DOCS_ONLY_PLAN)
        self.assertNotIn(self.AUDIT_MISSING_LABEL, missing)

    def test_sprightly_willow_style_table_passes(self):
        """A plan following the sprightly-willow pattern (Phase 0 + docs
        surfaces table) passes both new checks."""
        passed, missing, advisories = prg.phase1_check(SPRIGHTLY_STYLE_PLAN)
        self.assertTrue(
            passed,
            f"Sprightly-style plan failed with missing: {missing}",
        )
        self.assertFalse(
            any("No POC" in a for a in advisories),
            f"Sprightly-style plan should not trigger POC advisory, got: {advisories}",
        )

    def test_checklist_renders_docs_audit_row(self):
        """format_phase1_checklist emits a [PASS] or [FAIL] row for docs audit."""
        _, missing, advisories = prg.phase1_check(NEW_WORK_NO_POC_NO_AUDIT)
        msg = prg.format_phase1_checklist(missing, advisories, True)
        self.assertIn("docs audit", msg)
        self.assertIn("[FAIL] docs audit", msg)

        _, missing2, advisories2 = prg.phase1_check(COMPLETE_PLAN)
        msg2 = prg.format_phase1_checklist(missing2, advisories2, True)
        self.assertIn("[PASS] docs audit", msg2)


# ============================================================
# Phase 2 Tests
# ============================================================

class TestPhase2FileExtraction(unittest.TestCase):
    """Phase 2: file path extraction from ## Files section."""

    def test_prose_path_extraction(self):
        repo_files, external, conditional = prg.extract_plan_files(COMPLETE_PLAN)
        self.assertIn("~/myOS/scripts/foo.py", repo_files)
        self.assertIn("~/myOS/docs/changelog.md", repo_files)

    def test_run_prefix_skipped(self):
        plan = textwrap.dedent("""\
            ## Files to create/modify

            1. **`~/myOS/scripts/foo.py`** (new)
            2. **Run:** `scripts/install-skills.sh`
        """)
        repo_files, _, _ = prg.extract_plan_files(plan)
        self.assertEqual(len(repo_files), 1)
        self.assertIn("~/myOS/scripts/foo.py", repo_files)

    def test_conditional_file_detected(self):
        plan = textwrap.dedent("""\
            ## Files to create/modify

            1. **`~/myOS/scripts/foo.py`** (new)
            2. **`~/myOS/scripts/bar.py`** (if date logic extracted)
        """)
        repo_files, _, conditional = prg.extract_plan_files(plan)
        self.assertEqual(len(repo_files), 1)
        self.assertEqual(len(conditional), 1)

    def test_external_path_detected(self):
        plan = textwrap.dedent("""\
            ## Files to create/modify

            1. **`~/myOS/scripts/foo.py`** (new)
            2. **`~/.claude/settings.json`** (modify)
        """)
        repo_files, external, _ = prg.extract_plan_files(plan)
        self.assertEqual(len(repo_files), 1)
        self.assertEqual(len(external), 1)
        self.assertIn("~/.claude/settings.json", external)

    def test_no_files_section(self):
        plan = "## Context\n\nSome plan without files section."
        repo_files, external, conditional = prg.extract_plan_files(plan)
        self.assertEqual(repo_files, [])
        self.assertEqual(external, [])
        self.assertEqual(conditional, [])


class TestPhase2PathNormalization(unittest.TestCase):
    """Phase 2: path normalization to repo-relative."""

    def test_tilde_myos_prefix(self):
        result = prg.normalize_to_repo_relative("~/myOS/scripts/foo.py", "/Users/christophe/myOS")
        self.assertEqual(result, "scripts/foo.py")

    def test_absolute_path(self):
        result = prg.normalize_to_repo_relative("/Users/christophe/myOS/scripts/foo.py", "/Users/christophe/myOS")
        self.assertEqual(result, "scripts/foo.py")

    def test_relative_path(self):
        result = prg.normalize_to_repo_relative("scripts/foo.py", "/Users/christophe/myOS")
        self.assertEqual(result, "scripts/foo.py")


# ============================================================
# System Tests (full script invocation)
# ============================================================

class TestPhase1HookIntegration(unittest.TestCase):
    """System test: full PreToolUse flow for ExitPlanMode."""

    def _run_with_plan(self, plan_content, mode_args=None):
        """Write a plan to a temp dir and run the gate against it."""
        if mode_args is None:
            mode_args = []
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_file = Path(tmpdir) / "test-plan.md"
            plan_file.write_text(plan_content)

            hook_input = {
                "tool_name": "ExitPlanMode",
                "tool_input": {"allowedPrompts": []},
                "cwd": CWD,
            }

            # Patch PLANS_DIR to use temp dir
            with patch.object(prg, 'PLANS_DIR', Path(tmpdir)):
                # Direct function test since subprocess won't pick up the patch
                plan_file_found = prg.find_plan_file()
                self.assertIsNotNone(plan_file_found)
                plan_text = plan_file_found.read_text()

                if not mode_args or mode_args == []:
                    return prg.phase1_check(plan_text)
        return None

    def test_complete_plan_passes(self):
        passed, missing, advisories = self._run_with_plan(COMPLETE_PLAN)
        self.assertTrue(passed)

    def test_incomplete_plan_fails(self):
        passed, missing, _ = self._run_with_plan(MINIMAL_CODE_PLAN_MISSING_CHANGELOG)
        self.assertFalse(passed)
        self.assertTrue(len(missing) > 0)


class TestPhase2HookIntegration(unittest.TestCase):
    """System test: full PreToolUse flow for gh pr create."""

    def test_prepr_non_gh_pr_command(self):
        """Bash command that isn't gh pr create should allow immediately."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
            "cwd": CWD,
        }
        stdout, stderr, code = run_gate(["--mode=pre-pr"], hook_input)
        # Should produce no output (allow)
        self.assertEqual(stdout, "")
        self.assertEqual(code, 0)


class TestPlanFileDiscovery(unittest.TestCase):
    """Test plan file discovery logic."""

    def test_no_plan_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(prg, 'PLANS_DIR', Path(tmpdir)):
                result = prg.find_plan_file()
                self.assertIsNone(result)

    def test_missing_plans_directory(self):
        with patch.object(prg, 'PLANS_DIR', Path("/nonexistent/path")):
            result = prg.find_plan_file()
            self.assertIsNone(result)

    def test_picks_most_recent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_file = Path(tmpdir) / "old-plan.md"
            old_file.write_text("# Old Plan")
            import time
            time.sleep(0.05)
            new_file = Path(tmpdir) / "new-plan.md"
            new_file.write_text("# New Plan")

            with patch.object(prg, 'PLANS_DIR', Path(tmpdir)):
                result = prg.find_plan_file()
                self.assertEqual(result.name, "new-plan.md")


class TestFindPlanForDiff(unittest.TestCase):
    """CC-80: phase 2 picks the plan whose ## Files section best overlaps the diff,
    not the globally-newest plan. Prevents cross-session blocking when multiple
    Claude Code sessions write plans concurrently."""

    PLAN_A = textwrap.dedent("""\
        # Plan: session A
        ## Files
        - `~/myOS/scripts/foo.py`
        - `~/myOS/tests/test_foo.py`
        """)

    PLAN_B = textwrap.dedent("""\
        # Plan: session B
        ## Files
        - `~/myOS/docs/changelog.md`
        - `~/myOS/docs/session-learnings.md`
        """)

    PLAN_C = textwrap.dedent("""\
        # Plan: session C (partial overlap)
        ## Files
        - `~/myOS/scripts/foo.py`
        - `~/myOS/scripts/bar.py`
        """)

    def test_picks_best_overlap(self):
        """Plan B (2 files overlapping) beats Plan C (1 file overlapping)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "a.md").write_text(self.PLAN_A)
            (tmp / "b.md").write_text(self.PLAN_B)
            (tmp / "c.md").write_text(self.PLAN_C)
            diff = {"docs/changelog.md", "docs/session-learnings.md", "scripts/foo.py"}
            result = prg.find_plan_for_diff(diff, plans_dir=tmp)
            self.assertIsNotNone(result)
            self.assertEqual(result.name, "b.md")

    def test_no_overlap_returns_none(self):
        """If no plan has any overlap with the diff, return None so the gate skips."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "a.md").write_text(self.PLAN_A)
            (tmp / "b.md").write_text(self.PLAN_B)
            diff = {"README.md"}  # nothing in any plan
            result = prg.find_plan_for_diff(diff, plans_dir=tmp)
            self.assertIsNone(result)

    def test_ties_break_on_mtime(self):
        """When two plans have equal overlap, pick the newer one (backward-compatible
        with the old mtime-only behaviour when multiple plans come from the same
        session)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            older = tmp / "older.md"
            older.write_text(self.PLAN_A)
            import time
            time.sleep(0.05)
            newer = tmp / "newer.md"
            newer.write_text(self.PLAN_A)
            diff = {"scripts/foo.py"}
            result = prg.find_plan_for_diff(diff, plans_dir=tmp)
            self.assertIsNotNone(result)
            self.assertEqual(result.name, "newer.md")

    def test_empty_plans_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = prg.find_plan_for_diff({"a.py"}, plans_dir=Path(tmpdir))
            self.assertIsNone(result)

    def test_missing_plans_dir(self):
        result = prg.find_plan_for_diff({"a.py"}, plans_dir=Path("/nonexistent/path"))
        self.assertIsNone(result)

    def test_plan_without_files_section_skipped(self):
        """A plan with no ## Files section shouldn't win by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "no-files.md").write_text("# Plan with no files section\n\nJust prose.\n")
            (tmp / "has-files.md").write_text(self.PLAN_B)
            diff = {"docs/changelog.md"}
            result = prg.find_plan_for_diff(diff, plans_dir=tmp)
            self.assertIsNotNone(result)
            self.assertEqual(result.name, "has-files.md")

    def test_regression_cc80_cross_session_leak(self):
        """Exact CC-80 repro: session A's plan would block session B's PR.
        With the fix, session A's plan has zero overlap with session B's diff,
        so find_plan_for_diff returns session B's plan (or None if B has no plan)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # Session A (newest mtime) lists interview-coach files
            session_a = tmp / "session-a.md"
            session_a.write_text(textwrap.dedent("""\
                # Plan: interview coach work
                ## Files
                - `~/myOS/content/drafts/interview-coach-contribution/negotiation-protocol-draft.md`
                - `~/myOS/content/drafts/interview-coach-contribution/outline.md`
            """))
            import time
            time.sleep(0.05)
            # Session B (older, but matches diff) lists dispatcher script
            session_b = tmp / "session-b.md"
            session_b.write_text(textwrap.dedent("""\
                # Plan: dispatcher fix
                ## Files
                - `~/myOS/scripts/open-for-review.py`
            """))
            # Session B's diff
            diff = {"scripts/open-for-review.py"}

            # Old behaviour (find_plan_file) would pick session-b.md here since
            # it's newer; swap the mtimes to demonstrate the CC-80 bug:
            import os
            a_mtime = session_a.stat().st_mtime
            b_mtime = session_b.stat().st_mtime
            os.utime(session_a, (b_mtime, b_mtime))
            os.utime(session_b, (a_mtime, a_mtime))
            # Now session-a.md is the newest; old find_plan_file would return it
            # and the gate would block session B's PR.

            # With the fix: find_plan_for_diff picks by overlap, not mtime, so
            # session-b.md wins even though it's older.
            result = prg.find_plan_for_diff(diff, plans_dir=tmp)
            self.assertIsNotNone(result)
            self.assertEqual(result.name, "session-b.md",
                             "CC-80 regression: picked newest plan instead of best-overlap plan")


class TestOutputFormat(unittest.TestCase):
    """Test that output follows the always-visible format."""

    def test_pass_emits_summary(self):
        """Complete plan should produce PASS in additionalContext."""
        # We test the logic directly since subprocess can't see patched PLANS_DIR
        passed, missing, advisories = prg.phase1_check(COMPLETE_PLAN)
        self.assertTrue(passed)
        # The actual summary formatting happens in main(), so verify the components
        self.assertEqual(len(missing), 0)

    def test_pass_with_advisory_emits_warnings(self):
        plan = COMPLETE_PLAN.replace("## PR body\n\nWhat/Why/How.", "")
        passed, missing, advisories = prg.phase1_check(plan)
        self.assertTrue(passed)
        self.assertTrue(len(advisories) > 0)

    def test_error_emits_skipped(self):
        """Malformed stdin should produce SKIPPED via fail-open."""
        stdout, stderr, code = run_gate([], {"invalid": "no tool_name"})
        output = parse_output(stdout)
        # Should produce some output (SKIPPED or allow)
        self.assertEqual(code, 0)


class TestSilentOnPass(unittest.TestCase):
    """HWW #20: hooks emit nothing on a clean pass. Regression tests that guard
    plan-review-gate from reverting to verbose green-path `info()` output.

    Exercises the subprocess entry point with a controlled PLANS_DIR via HOME.
    """

    def _run_with_home(self, home_dir, mode_args, hook_input):
        env = os.environ.copy()
        env["HOME"] = str(home_dir)
        cmd = [sys.executable, str(GATE_SCRIPT)] + mode_args
        result = subprocess.run(
            cmd,
            input=json.dumps(hook_input),
            capture_output=True, text=True, timeout=10, cwd=CWD, env=env,
        )
        return result.stdout.strip(), result.returncode

    def _write_plan(self, home_dir, text):
        plans_dir = home_dir / ".claude" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plans_dir / "test-plan.md"
        plan_path.write_text(text)
        return plan_path

    def test_phase1_clean_pass_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self._write_plan(home, COMPLETE_PLAN)
            stdout, code = self._run_with_home(
                home, [], {"tool_name": "ExitPlanMode", "tool_input": {}}
            )
            self.assertEqual(code, 0)
            self.assertEqual(stdout, "",
                "Clean-pass phase 1 must emit no stdout (HWW #20). Got: " + stdout)

    def test_phase1_pass_with_advisories_emits_short_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            # Strip PR body advisory-triggering content
            plan = COMPLETE_PLAN.replace("## PR body\n\nWhat/Why/How.\n", "")
            self._write_plan(home, plan)
            stdout, code = self._run_with_home(
                home, [], {"tool_name": "ExitPlanMode", "tool_input": {}}
            )
            self.assertEqual(code, 0)
            output = parse_output(stdout)
            ctx = get_context(output)
            # Summary line, NOT the old verbose checklist
            self.assertIn("PLAN REVIEW: pass with", ctx,
                f"Expected short summary, got: {ctx!r}")
            self.assertNotIn("[PASS]", ctx,
                "Pass-with-advisories path must not emit full checklist")

    def test_phase1_fail_emits_full_checklist(self):
        """Deny path preserved — missing sections must surface with action detail."""
        broken = "# Broken\n\n## Context\n\nJust context.\n"
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self._write_plan(home, broken)
            stdout, code = self._run_with_home(
                home, [], {"tool_name": "ExitPlanMode", "tool_input": {}}
            )
            self.assertEqual(code, 0)
            output = parse_output(stdout)
            decision = get_decision(output)
            reason = get_reason(output)
            self.assertEqual(decision, "deny",
                "Broken plan must still deny (block-class event)")
            self.assertIn("[FAIL]", reason,
                "Fail output must include per-check FAIL markers for action")

    def test_phase2_non_pr_command_is_silent(self):
        stdout, stderr, code = run_gate(
            ["--mode=pre-pr"],
            {"tool_name": "Bash", "tool_input": {"command": "ls"}},
        )
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "",
            "Phase 2 on non-PR bash must be silent. Got: " + stdout)


class TestStdinParseError(unittest.TestCase):
    """Test handling of malformed stdin."""

    def test_empty_stdin(self):
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
            cwd=CWD,
        )
        self.assertEqual(result.returncode, 0)

    def test_invalid_json(self):
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            input="not json at all",
            capture_output=True,
            text=True,
            timeout=10,
            cwd=CWD,
        )
        self.assertEqual(result.returncode, 0)
        # Should produce SKIPPED message
        output = parse_output(result.stdout.strip())
        if output:
            ctx = get_context(output)
            self.assertIn("SKIPPED", ctx)


class TestH3HeadingSupport(unittest.TestCase):
    """Test that h3 (###) headings are recognized for sections and file extraction."""

    H3_PLAN = textwrap.dedent("""\
        # Plan: H3 Test

        ## Context

        Some context.

        ## Pre-flight checks

        Done.

        ## Implementation

        ### Files to create/modify

        **Code:**

        1. **`~/myOS/scripts/plan-review-gate.py`** (new)
           - Description of the script

        **Spec doc:**

        2. **`~/myOS/docs/plan-review-gate.md`** (new)

        **Bundled docs:**

        3. **`~/myOS/docs/changelog.md`** (modify)
        4. **`~/myOS/docs/session-learnings.md`** (modify)

        **Mechanism files:**

        5. **`~/myOS/claude-memory/mechanism_foo.md`** (update)

        ### Docs to update

        Existing docs to update: docs/plan-review-gate.md. Phase 0 POC first.

        ### Tests

        1. test_foo -- basic test

        ## Verification

        1. Run tests

        ## PR body

        What/Why/How.

        Update mechanism and changelog and session-learnings.
    """)

    def test_h3_files_section_extracted(self):
        repo_files, _, _ = prg.extract_plan_files(self.H3_PLAN)
        self.assertIn("~/myOS/scripts/plan-review-gate.py", repo_files)
        self.assertIn("~/myOS/docs/plan-review-gate.md", repo_files)
        self.assertIn("~/myOS/docs/changelog.md", repo_files)
        self.assertIn("~/myOS/docs/session-learnings.md", repo_files)
        self.assertIn("~/myOS/claude-memory/mechanism_foo.md", repo_files)
        self.assertEqual(len(repo_files), 5)

    def test_h3_files_stops_at_tests_section(self):
        """### Tests should terminate the ### Files section."""
        repo_files, _, _ = prg.extract_plan_files(self.H3_PLAN)
        # Should NOT include anything from the Tests section
        self.assertNotIn("test_foo", str(repo_files))

    def test_h3_section_has_content(self):
        """### Files heading with content should pass section check."""
        self.assertTrue(prg.section_has_content(self.H3_PLAN, r"#{2,3}\s+Files"))

    def test_h3_plan_passes_phase1(self):
        """A plan using ### headings should pass Phase 1."""
        passed, missing, _ = prg.phase1_check(self.H3_PLAN)
        self.assertTrue(passed, f"Plan failed with missing: {missing}")

    def test_h3_subsections_preserved(self):
        """Sub-headings like **Code:**, **Spec doc:** shouldn't break extraction."""
        repo_files, _, _ = prg.extract_plan_files(self.H3_PLAN)
        # Files from both Code and Spec doc sub-sections should be present
        self.assertTrue(len(repo_files) >= 2)


class TestChecklistFormatting(unittest.TestCase):
    """Test checklist output formatting for Phase 1 and Phase 2."""

    # --- Phase 1 ---

    def test_phase1_all_pass_format(self):
        """Complete plan produces [PASS] for all items and RESULT: PASS."""
        _, missing, advisories = prg.phase1_check(COMPLETE_PLAN)
        msg = prg.format_phase1_checklist(missing, advisories, True)
        self.assertIn("PLAN REVIEW GATE:", msg)
        self.assertIn("[PASS] Context", msg)
        self.assertIn("[PASS] Pre-flight checks", msg)
        self.assertIn("[PASS] Implementation", msg)
        self.assertIn("[PASS] Files to create/modify", msg)
        self.assertIn("[PASS] Tests", msg)
        self.assertIn("[PASS] Verification", msg)
        self.assertIn("[PASS] changelog keyword", msg)
        self.assertIn("[PASS] session-learnings keyword", msg)
        self.assertIn("[PASS] mechanism keyword", msg)
        self.assertIn("RESULT: PASS", msg)
        self.assertNotIn("[FAIL]", msg)

    def test_phase1_fail_format(self):
        """Missing section shows [FAIL] with detail."""
        plan = COMPLETE_PLAN.replace("## Tests\n\n1. test_foo -- basic test", "")
        _, missing, advisories = prg.phase1_check(plan)
        msg = prg.format_phase1_checklist(missing, advisories, True)
        self.assertIn("[FAIL] Tests -- empty or missing", msg)
        self.assertIn("RESULT: FAIL", msg)

    def test_phase1_keyword_fail_format(self):
        """Missing keyword shows [FAIL] with keyword label."""
        _, missing, advisories = prg.phase1_check(MINIMAL_CODE_PLAN_MISSING_CHANGELOG)
        msg = prg.format_phase1_checklist(missing, advisories, True)
        self.assertIn("[FAIL] changelog keyword -- missing", msg)
        self.assertIn("[FAIL] session-learnings keyword -- missing", msg)
        self.assertIn("[FAIL] mechanism keyword -- missing", msg)
        self.assertIn("RESULT: FAIL", msg)

    def test_phase1_advisory_format(self):
        """Advisory produces [WARN] line."""
        plan = COMPLETE_PLAN.replace("## PR body\n\nWhat/Why/How.", "")
        _, missing, advisories = prg.phase1_check(plan)
        msg = prg.format_phase1_checklist(missing, advisories, True)
        self.assertIn("[WARN] no PR body template found", msg)

    def test_phase1_docs_only_no_keywords(self):
        """Docs-only plan omits keyword lines entirely."""
        _, missing, advisories = prg.phase1_check(DOCS_ONLY_PLAN)
        msg = prg.format_phase1_checklist(missing, advisories, False)
        self.assertNotIn("changelog keyword", msg)
        self.assertNotIn("session-learnings keyword", msg)
        self.assertNotIn("mechanism keyword", msg)
        self.assertIn("RESULT: PASS", msg)

    def test_phase1_mixed_fail_warn_count(self):
        """RESULT line has correct blocking and advisory counts."""
        plan = MINIMAL_CODE_PLAN_MISSING_CHANGELOG
        _, missing, advisories = prg.phase1_check(plan)
        msg = prg.format_phase1_checklist(missing, advisories, True)
        fail_count = msg.count("[FAIL]")
        warn_count = msg.count("[WARN]")
        self.assertIn(f"{fail_count} blocking", msg)
        if warn_count > 0:
            self.assertIn(f"{warn_count} advisory", msg)

    def test_phase1_fail_includes_session_learnings_nudge(self):
        """Code-touching FAIL includes session-learnings nudge."""
        _, missing, advisories = prg.phase1_check(MINIMAL_CODE_PLAN_MISSING_CHANGELOG)
        msg = prg.format_phase1_checklist(missing, advisories, True)
        self.assertIn("session-learnings (during implementation, not deferred)", msg)

    # --- Phase 2 ---

    def test_phase2_all_pass_format(self):
        """All repo files in diff produces [PASS] lines and RESULT: PASS."""
        msg = prg.format_phase2_checklist(COMPLETE_PLAN, [], [])
        self.assertIn("PRE-PR AUDIT:", msg)
        self.assertIn("[PASS]", msg)
        self.assertIn("RESULT: PASS", msg)
        self.assertNotIn("[FAIL]", msg)

    def test_phase2_missing_file_format(self):
        """Missing file produces [FAIL] with detail."""
        msg = prg.format_phase2_checklist(
            COMPLETE_PLAN,
            ["~/myOS/scripts/foo.py"],
            []
        )
        self.assertIn("[FAIL] scripts/foo.py -- not in diff", msg)
        self.assertIn("RESULT: FAIL", msg)

    def test_phase2_external_warn_format(self):
        """External file produces [WARN]."""
        plan = textwrap.dedent("""\
            ## Files to create/modify

            1. **`~/myOS/scripts/foo.py`** (new)
            2. **`~/.claude/settings.json`** (modify)
        """)
        msg = prg.format_phase2_checklist(plan, [], ["~/.claude/settings.json (external -- verify manually)"])
        self.assertIn("[WARN] ~/.claude/settings.json (external -- verify manually)", msg)

    def test_phase2_conditional_skip_format(self):
        """Conditional file produces [SKIP]."""
        plan = textwrap.dedent("""\
            ## Files to create/modify

            1. **`~/myOS/scripts/foo.py`** (new)
            2. **`~/myOS/scripts/bar.py`** (if needed)
        """)
        msg = prg.format_phase2_checklist(plan, [], [])
        self.assertIn("[SKIP]", msg)
        self.assertIn("(conditional)", msg)

    def test_phase2_no_files_format(self):
        """Empty files section produces PASS with zero count."""
        plan = "## Context\n\nSome plan without files section."
        msg = prg.format_phase2_checklist(plan, [], [])
        self.assertIn("RESULT: PASS (0/0 repo files in diff)", msg)


# ============================================================
# Remediation Tier Check Tests (CC-75)
# ============================================================

class TestRemediationTierCheck(unittest.TestCase):
    """Test tier 1 vs tier 2 remediation detection."""

    def test_tier1_only_feedback_memory(self):
        """Plan proposing only a feedback memory should trigger advisory."""
        plan = textwrap.dedent("""\
            # Plan: Fix Agent Pattern

            ## Context

            Claude keeps skipping a step in agents/retro.md.

            ## Pre-flight checks

            Checked agents/ for the pattern.

            ## Implementation

            Create a feedback memory to remember this pattern next time.

            ## Files to create/modify

            1. **`~/myOS/claude-memory/feedback_retro_step.md`** (new)
            2. **`~/myOS/careerOS/agents/retro.md`** (modify -- add comment)

            ## Tests

            Visual review only.

            ## Verification

            1. Check memory file exists.

            Update changelog and session-learnings and mechanism docs.
        """)
        passed, missing, advisories = prg.phase1_check(plan)
        tier_advisories = [a for a in advisories if "tier 1" in a]
        self.assertTrue(len(tier_advisories) > 0, f"Expected tier 1 advisory, got: {advisories}")

    def test_tier1_only_claude_md_entry(self):
        """Plan proposing only a CLAUDE.md rule should trigger advisory."""
        plan = textwrap.dedent("""\
            # Plan: Add CLAUDE.md Rule

            ## Context

            Claude keeps forgetting to do X in agents/retro.md.

            ## Pre-flight checks

            Checked CLAUDE.md for existing rules and agents/ for the pattern.

            ## Implementation

            Add new entry to CLAUDE.md How We Work principle to remember this.
            Update How We Work with a new rule entry.

            ## Files to create/modify

            1. **`~/myOS/CLAUDE.md`** (modify)
            2. **`~/myOS/claude-memory/feedback_remember_x.md`** (new)

            ## Tests

            Visual review of CLAUDE.md.

            ## Verification

            1. Read CLAUDE.md and verify the entry.

            Update mechanism and changelog and session-learnings.
        """)
        passed, missing, advisories = prg.phase1_check(plan)
        tier_advisories = [a for a in advisories if "tier 1" in a]
        self.assertTrue(len(tier_advisories) > 0, f"Expected tier 1 advisory, got: {advisories}")

    def test_tier1_plus_tier2_bundled(self):
        """Plan with both memory and test/script should NOT trigger advisory."""
        plan = COMPLETE_PLAN.replace(
            "Add a new script to scripts/foo.py.",
            "Create a feedback memory and add a test to enforce the check."
        )
        passed, missing, advisories = prg.phase1_check(plan)
        tier_advisories = [a for a in advisories if "tier 1" in a]
        self.assertEqual(len(tier_advisories), 0, f"Unexpected tier 1 advisory: {advisories}")

    def test_tier2_only_mechanism(self):
        """Plan with only mechanism work should NOT trigger advisory."""
        passed, missing, advisories = prg.phase1_check(COMPLETE_PLAN)
        tier_advisories = [a for a in advisories if "tier 1" in a]
        self.assertEqual(len(tier_advisories), 0, f"Unexpected tier 1 advisory: {advisories}")

    def test_no_remediation_signals(self):
        """Plan with no tier 1 signals should NOT trigger advisory."""
        plan = textwrap.dedent("""\
            # Plan: New Dashboard Feature

            ## Context

            Adding a new widget to the dashboard.

            ## Pre-flight checks

            Checked existing dashboard code.

            ## Implementation

            Add new chart component to os-dashboard.py.

            ## Files to create/modify

            1. **`~/myOS/scripts/os-dashboard.py`** (modify)
            2. **`~/myOS/tests/test_dashboard.py`** (modify)

            ## Tests

            1. test_new_widget -- basic rendering test

            ## Verification

            1. Run tests and check dashboard output.

            Update changelog and session-learnings and mechanism docs.
        """)
        passed, missing, advisories = prg.phase1_check(plan)
        tier_advisories = [a for a in advisories if "tier 1" in a]
        self.assertEqual(len(tier_advisories), 0, f"Unexpected tier 1 advisory: {advisories}")

    def test_feedback_file_in_files_section(self):
        """Plan listing only feedback_*.md files (no test/script) should trigger advisory."""
        plan = textwrap.dedent("""\
            # Plan: Fix Pattern

            ## Context

            Claude keeps doing X wrong.

            ## Pre-flight checks

            Checked agents/ for relevant code.

            ## Implementation

            Save a feedback memory so Claude remembers next time.
            Update agents/retro.md with a reminder.

            ## Files to create/modify

            1. **`~/myOS/claude-memory/feedback_do_x_right.md`** (new)
            2. **`~/myOS/careerOS/agents/retro.md`** (modify)

            ## Tests

            Manual review.

            ## Verification

            1. Check memory file exists.

            Update changelog and session-learnings and mechanism docs.
        """)
        passed, missing, advisories = prg.phase1_check(plan)
        tier_advisories = [a for a in advisories if "tier 1" in a]
        self.assertTrue(len(tier_advisories) > 0, f"Expected tier 1 advisory, got: {advisories}")

    def test_memory_file_with_test_file(self):
        """Plan with both feedback memory and test file should NOT trigger advisory."""
        plan = textwrap.dedent("""\
            # Plan: Fix Pattern with Mechanism

            ## Context

            Claude keeps doing X wrong.

            ## Pre-flight checks

            Checked agents/ for relevant code.

            ## Implementation

            Add a test to catch X automatically. Also save a feedback memory as documentation.

            ## Files to create/modify

            1. **`~/myOS/tests/test_x_check.py`** (new)
            2. **`~/myOS/scripts/x-checker.py`** (new)
            3. **`~/myOS/claude-memory/feedback_do_x_right.md`** (new)

            ## Tests

            1. test_x_detected -- catches the pattern

            ## Verification

            1. Run tests.

            Update changelog and session-learnings and mechanism docs.
        """)
        passed, missing, advisories = prg.phase1_check(plan)
        tier_advisories = [a for a in advisories if "tier 1" in a]
        self.assertEqual(len(tier_advisories), 0, f"Unexpected tier 1 advisory: {advisories}")

    def test_regression_devstats_text(self):
        """Real-world text from the devstats session should trigger advisory."""
        plan = textwrap.dedent("""\
            # Plan: Fix Devstats Counter

            ## Context

            Devstats counter in devstats.py was frozen at 15.

            ## Pre-flight checks

            Checked config.

            ## Implementation

            Proposed a feedback memory as the fix. Save a memory to track this.
            Update CLAUDE.md with a note to self to check agent dirs.

            ## Files to create/modify

            1. **`~/myOS/claude-memory/feedback_check_agent_dirs.md`** (new)
            2. **`~/myOS/CLAUDE.md`** (modify)

            ## Tests

            Visual review.

            ## Verification

            1. Check memory exists.

            Update changelog and session-learnings and mechanism docs.
        """)
        passed, missing, advisories = prg.phase1_check(plan)
        tier_advisories = [a for a in advisories if "tier 1" in a]
        self.assertTrue(len(tier_advisories) > 0, f"Expected tier 1 advisory for devstats regression, got: {advisories}")

    def test_docs_only_exempt(self):
        """Docs-only plan updating CLAUDE.md should NOT trigger advisory (not code-touching)."""
        plan = textwrap.dedent("""\
            # Plan: Update CLAUDE.md Docs

            ## Context

            Updating CLAUDE.md with correct threshold values.

            ## Pre-flight checks

            Checked current thresholds.

            ## Implementation

            Update CLAUDE.md How We Work entry with corrected wording.

            ## Files to create/modify

            1. **`~/myOS/CLAUDE.md`** (modify)
            2. **`~/myOS/README.md`** (modify)

            ## Tests

            Visual review.

            ## Verification

            1. Read updated files.
        """)
        passed, missing, advisories = prg.phase1_check(plan)
        tier_advisories = [a for a in advisories if "tier 1" in a]
        self.assertEqual(len(tier_advisories), 0,
                         f"Docs-only plan should not trigger tier advisory: {advisories}")

    def test_save_memory_pattern(self):
        """'save a memory' text should be detected as tier 1."""
        has_tier1, _, matches = prg.check_remediation_tier("save a memory to track this pattern")
        self.assertTrue(has_tier1)
        self.assertIn("save a memory", matches)

    def test_remember_to_pattern(self):
        """'remember to' text should be detected as tier 1."""
        has_tier1, _, matches = prg.check_remediation_tier("remember to check this next time")
        self.assertTrue(has_tier1)
        self.assertIn("remember to", matches)


class TestRemediationTierFunction(unittest.TestCase):
    """Direct tests for check_remediation_tier() function."""

    def test_no_signals(self):
        has_tier1, has_tier2, matches = prg.check_remediation_tier("Add a new dashboard widget")
        self.assertFalse(has_tier1)
        self.assertFalse(has_tier2)
        self.assertEqual(matches, [])

    def test_tier2_signals_detected(self):
        text = "Create tests/test_foo.py and scripts/gate.py with PreToolUse hook"
        has_tier1, has_tier2, matches = prg.check_remediation_tier(text)
        self.assertFalse(has_tier1)
        self.assertTrue(has_tier2)

    def test_both_tiers_detected(self):
        text = "Create tests/test_foo.py and a feedback memory for documentation"
        has_tier1, has_tier2, matches = prg.check_remediation_tier(text)
        self.assertTrue(has_tier1)
        self.assertTrue(has_tier2)

    def test_feedback_file_path_detected(self):
        text = "Create claude-memory/feedback_check_dirs.md"
        has_tier1, _, matches = prg.check_remediation_tier(text)
        self.assertTrue(has_tier1)
        self.assertIn("feedback memory file", matches)


class ParseHeadBranchTests(unittest.TestCase):
    """CC-174: parse the --head value out of a gh pr create command string."""

    def test_long_form_with_space(self):
        cmd = "gh pr create --base main --head feat/foo --title 'x'"
        self.assertEqual(prg.parse_head_branch(cmd), "feat/foo")

    def test_short_form_with_space(self):
        cmd = "gh pr create -B main -H feat/foo -t 'x'"
        self.assertEqual(prg.parse_head_branch(cmd), "feat/foo")

    def test_equals_form(self):
        cmd = "gh pr create --head=feat/foo --base=main"
        self.assertEqual(prg.parse_head_branch(cmd), "feat/foo")

    def test_no_head(self):
        cmd = "gh pr create --base main --title 'x'"
        self.assertIsNone(prg.parse_head_branch(cmd))

    def test_empty_command(self):
        self.assertIsNone(prg.parse_head_branch(""))

    def test_none_command(self):
        self.assertIsNone(prg.parse_head_branch(None))

    def test_branch_with_slashes_and_hyphens(self):
        cmd = "gh pr create --head fix/cc-174-plan-gate-head-branch"
        self.assertEqual(prg.parse_head_branch(cmd), "fix/cc-174-plan-gate-head-branch")

    def test_dash_h_does_not_collide_with_help(self):
        # `-h` (help, lowercase) should not match `-H` (head, uppercase)
        cmd = "gh pr create -h"
        self.assertIsNone(prg.parse_head_branch(cmd))

    def test_head_value_appears_in_branch_substring(self):
        # If --head is followed by other args, only the value is captured
        cmd = "gh pr create --head feat/main-fixes --base main"
        self.assertEqual(prg.parse_head_branch(cmd), "feat/main-fixes")


class IsPrCreateCommandTests(unittest.TestCase):
    """CC-175: token-aware match. Substring containment falsely fired on
    commit messages and PR bodies that mentioned the trigger phrases as text.
    """

    # --- Positive (gate should fire) ---

    def test_plain_pr_create(self):
        self.assertTrue(prg.is_pr_create_command("gh pr create --title x"))

    def test_plain_pr_edit(self):
        self.assertTrue(prg.is_pr_create_command("gh pr edit 5 --body y"))

    def test_chained_with_cd(self):
        self.assertTrue(prg.is_pr_create_command("cd /tmp && gh pr create --title x"))

    def test_env_var_prefix(self):
        self.assertTrue(prg.is_pr_create_command("EDITOR=vim gh pr create"))

    def test_equals_form_args(self):
        self.assertTrue(prg.is_pr_create_command("gh pr create --title=x --body=y"))

    # --- Negative (gate should NOT fire) ---

    def test_phrase_in_quoted_body(self):
        # Quoted strings tokenize as single opaque tokens.
        self.assertFalse(prg.is_pr_create_command(
            'git commit -m "discusses gh pr create in body"'
        ))

    def test_phrase_in_gh_api_body_arg(self):
        # gh api with --body arg containing the phrase as a value.
        self.assertFalse(prg.is_pr_create_command(
            'gh api /repos/x/y/pulls -X POST -f body="mentions gh pr create"'
        ))

    def test_phrase_in_echo(self):
        self.assertFalse(prg.is_pr_create_command('echo "gh pr create"'))

    def test_wrong_subcommand(self):
        self.assertFalse(prg.is_pr_create_command("gh pr list"))

    def test_incomplete_gh_pr(self):
        self.assertFalse(prg.is_pr_create_command("gh pr"))

    # --- Edge cases ---

    def test_empty_string(self):
        self.assertFalse(prg.is_pr_create_command(""))

    def test_none(self):
        self.assertFalse(prg.is_pr_create_command(None))

    def test_malformed_quotes_falls_back_to_substring(self):
        # When shlex raises (unbalanced quote), fall back to legacy substring
        # match — preserves the positive case for malformed input rather
        # than failing closed.
        self.assertTrue(prg.is_pr_create_command(
            'gh pr create --title "missing close'
        ))


class GetDiffFilesHeadRefTests(unittest.TestCase):
    """CC-174: get_diff_files honors an explicit head_ref over cwd HEAD.

    These tests run real git commands against the repo. They verify behavior
    with the current branch's HEAD vs an explicit ref.
    """

    def test_legacy_path_includes_unstaged(self):
        # No head_ref → legacy path should include unstaged/staged/untracked
        # files. We can't easily synthesize them in a unit test without a temp
        # repo, but at minimum the function should return without errors and
        # produce a set.
        diff_files, skip_reason = prg.get_diff_files(CWD, head_ref=None)
        self.assertIsInstance(diff_files, set)
        # Either we got files or a skip reason — never both unset
        if skip_reason:
            self.assertEqual(diff_files, set())

    def test_named_head_resolves_for_real_branch(self):
        # Skip when the diff itself can't be computed (e.g. GitHub Actions
        # shallow clone via actions/checkout@v5 default fetch-depth: 1). In
        # that environment `origin/main` may exist as a ref but have no
        # shared ancestry with HEAD, so `git merge-base` fails and any
        # `git diff origin/main...<branch>` returns non-zero. Skip when the
        # diff precondition isn't met. Local dev with full history runs the
        # test as designed.
        try:
            mb_check = subprocess.run(
                ["git", "merge-base", "origin/main", "HEAD"],
                capture_output=True, text=True, cwd=CWD, timeout=5
            )
            if mb_check.returncode != 0:
                self.skipTest(
                    "no merge-base between origin/main and HEAD "
                    "(shallow clone?)"
                )
        except Exception:
            self.skipTest("git merge-base failed in test environment")
        # The current branch should always resolve. Run with the actual branch
        # name (read from the worktree) — get_diff_files should not skip with
        # "git diff failed."
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, cwd=CWD, timeout=5
            )
            current_branch = result.stdout.strip()
        except Exception:
            self.skipTest("git rev-parse failed in test environment")
        if not current_branch or current_branch == "HEAD":
            self.skipTest("not on a named branch")
        diff_files, skip_reason = prg.get_diff_files(CWD, head_ref=current_branch)
        self.assertIsInstance(diff_files, set)
        # The named-head path drops unstaged/staged/untracked. Since this test
        # repo's HEAD == current_branch, the result should match the committed
        # diff exactly. We don't assert the contents (env-dependent), only the
        # type and that no skip reason fired.
        self.assertIsNone(skip_reason, f"unexpected skip: {skip_reason}")

    def test_named_head_falls_back_when_branch_missing(self):
        # An explicit head_ref that doesn't resolve should NOT cause a fail —
        # the function falls back to legacy HEAD-of-cwd behaviour.
        diff_files, skip_reason = prg.get_diff_files(
            CWD,
            head_ref="this/branch/definitely/does/not/exist/anywhere"
        )
        self.assertIsInstance(diff_files, set)
        # Same fail-open expectation as the legacy path
        if skip_reason:
            self.assertEqual(diff_files, set())


if __name__ == "__main__":
    unittest.main()
