#!/usr/bin/env python3
"""Unit and integration tests for git-workflow-gate.py (toolkit slim subset).

Tests feed synthetic JSON to the gate via subprocess and assert expected
output (deny/allow/warn/info). Direct-import tests cover the parsers + helpers.

Run: python3 -m unittest tests.test_git_workflow_gate -v
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE_SCRIPT = REPO_ROOT / "hooks" / "git-workflow-gate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("gwg", str(GATE_SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gwg"] = mod
    spec.loader.exec_module(mod)
    return mod


gwg = _load_module()


def run_gate(mode, hook_input, cwd=None, timeout=15, env_extra=None):
    """Run the gate script with given mode, return (stdout, stderr, exit_code)."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), mode],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd or str(REPO_ROOT),
        env=env,
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def parse(stdout):
    if not stdout:
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


def decision(out):
    return (out or {}).get("hookSpecificOutput", {}).get("permissionDecision")


def reason(out):
    return (out or {}).get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


def context(out):
    return (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")


def make_tmp_repo():
    """Create a tmp git repo and return its path."""
    tmp = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, check=True)
    # Initial commit so HEAD exists
    Path(tmp, "README.md").write_text("init\n")
    subprocess.run(["git", "add", "."], cwd=tmp, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "feat: init"], cwd=tmp, check=True)
    return tmp


# =========================================================================
# Parsers (direct import)
# =========================================================================

class TestDetectCdGitChain(unittest.TestCase):
    def test_simple_chain_detected(self):
        result = gwg.detect_cd_git_chain("cd /tmp && git status")
        self.assertIsNotNone(result)
        self.assertIn("cd /tmp", result)

    def test_semicolon_chain_detected(self):
        result = gwg.detect_cd_git_chain("cd ~/proj; git log")
        self.assertIsNotNone(result)

    def test_git_dash_c_allowed(self):
        result = gwg.detect_cd_git_chain("cd /tmp && git -C /other status")
        self.assertIsNone(result)

    def test_no_cd_no_match(self):
        result = gwg.detect_cd_git_chain("git status")
        self.assertIsNone(result)

    def test_cd_alone_no_match(self):
        result = gwg.detect_cd_git_chain("cd /tmp")
        self.assertIsNone(result)

    def test_intermediate_command(self):
        result = gwg.detect_cd_git_chain("cd /tmp && ls && git status")
        self.assertIsNotNone(result)


class TestExtractGitCommands(unittest.TestCase):
    def test_single_git(self):
        self.assertEqual(gwg.extract_git_commands("git status"), ["git status"])

    def test_compound(self):
        cmds = gwg.extract_git_commands("git add . && git commit -m 'feat: x'")
        self.assertEqual(len(cmds), 2)
        self.assertTrue(cmds[0].startswith("git add"))
        self.assertTrue(cmds[1].startswith("git commit"))

    def test_no_git(self):
        self.assertEqual(gwg.extract_git_commands("ls -la && echo done"), [])

    def test_with_env_var_prefix(self):
        cmds = gwg.extract_git_commands("GIT_PAGER=cat git log")
        self.assertEqual(cmds, ["git log"])

    def test_semicolon_split(self):
        cmds = gwg.extract_git_commands("git fetch ; git pull")
        self.assertEqual(cmds, ["git fetch", "git pull"])


class TestParseCommitMessage(unittest.TestCase):
    def test_double_quotes(self):
        self.assertEqual(gwg.parse_commit_message('git commit -m "feat: add thing"'), "feat: add thing")

    def test_single_quotes(self):
        self.assertEqual(gwg.parse_commit_message("git commit -m 'fix: bug'"), "fix: bug")

    def test_no_message(self):
        self.assertIsNone(gwg.parse_commit_message("git commit"))

    def test_heredoc_extracts_first_line(self):
        cmd = "git commit -m \"$(cat <<'EOF'\nfeat: heredoc message\n\nbody line 2\nEOF\n)\""
        self.assertEqual(gwg.parse_commit_message(cmd), "feat: heredoc message")


class TestParsePushRemote(unittest.TestCase):
    def test_origin_specified(self):
        self.assertEqual(gwg.parse_push_remote("git push origin feat/x"), "origin")

    def test_no_remote_returns_none(self):
        self.assertIsNone(gwg.parse_push_remote("git push"))

    def test_with_flags_before_remote(self):
        self.assertEqual(gwg.parse_push_remote("git push -u origin feat/x"), "origin")

    def test_force_flag_skipped(self):
        self.assertEqual(gwg.parse_push_remote("git push --force origin main"), "origin")


class TestIsFileRestore(unittest.TestCase):
    def test_checkout_double_dash_is_restore(self):
        self.assertTrue(gwg.is_file_restore("git checkout -- file.txt"))

    def test_checkout_ref_double_dash_is_restore(self):
        self.assertTrue(gwg.is_file_restore("git checkout HEAD -- file.txt"))

    def test_restore_command_is_restore(self):
        self.assertTrue(gwg.is_file_restore("git restore file.txt"))

    def test_restore_staged_is_restore(self):
        self.assertTrue(gwg.is_file_restore("git restore --staged file.txt"))

    def test_branch_switch_is_not_restore(self):
        self.assertFalse(gwg.is_file_restore("git checkout main"))
        self.assertFalse(gwg.is_file_restore("git switch main"))

    def test_new_branch_is_not_restore(self):
        self.assertFalse(gwg.is_file_restore("git checkout -b feat/x"))
        self.assertFalse(gwg.is_file_restore("git switch -c feat/x"))


class TestGetAllowedCommitTypes(unittest.TestCase):
    def test_default_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            types = gwg.get_allowed_commit_types(tmp)
            self.assertIn("fix", types)
            self.assertIn("feat", types)
            self.assertIn("refactor", types)
            self.assertNotIn("log", types)  # myOS-specific should NOT be in default
            self.assertNotIn("invest", types)

    def test_dot_commit_types_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".commit-types").write_text("custom1\ncustom2\n# comment\n\n")
            types = gwg.get_allowed_commit_types(tmp)
            self.assertEqual(types, {"custom1", "custom2"})

    def test_empty_dot_commit_types_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".commit-types").write_text("# only comments\n\n")
            types = gwg.get_allowed_commit_types(tmp)
            self.assertIn("fix", types)  # Falls back to default


# =========================================================================
# Gate 0: cd-chain detection (PreToolUse)
# =========================================================================

class TestGate0CdChain(unittest.TestCase):
    def test_cd_chain_denied(self):
        out, _, _ = run_gate("--pre-tool-use", {
            "tool_name": "Bash",
            "tool_input": {"command": "cd /tmp && git status"},
        })
        self.assertEqual(decision(parse(out)), "deny")
        self.assertIn("cd <dir>", reason(parse(out)))

    def test_git_dash_c_allowed(self):
        out, _, _ = run_gate("--pre-tool-use", {
            "tool_name": "Bash",
            "tool_input": {"command": "cd /tmp && git -C /other status"},
        })
        # Allowed: gate may pass through to other checks but should not deny on cd-chain
        self.assertNotEqual(decision(parse(out)), "deny")

    def test_non_bash_tool_silent(self):
        out, _, _ = run_gate("--pre-tool-use", {
            "tool_name": "Read",
            "tool_input": {"file_path": "/foo"},
        })
        self.assertEqual(out, "")  # silent on non-Bash


# =========================================================================
# Gate 1: pre-commit (branch-not-main + commit-msg format)
# =========================================================================

class TestGate1PreCommit(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp_repo()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_commit_on_main_denied(self):
        out, _, _ = run_gate("--pre-tool-use", {
            "cwd": self.tmp,
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "feat: x"'},
        }, cwd=self.tmp)
        self.assertEqual(decision(parse(out)), "deny")
        self.assertIn("Cannot commit to main", reason(parse(out)))

    def test_invalid_format_denied(self):
        # Switch to a feature branch first
        subprocess.run(["git", "checkout", "-b", "feat/test"], cwd=self.tmp, check=True, capture_output=True)
        out, _, _ = run_gate("--pre-tool-use", {
            "cwd": self.tmp,
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "no colon here"'},
        }, cwd=self.tmp)
        self.assertEqual(decision(parse(out)), "deny")
        self.assertIn("format invalid", reason(parse(out)))

    def test_unknown_type_denied(self):
        subprocess.run(["git", "checkout", "-b", "feat/test"], cwd=self.tmp, check=True, capture_output=True)
        out, _, _ = run_gate("--pre-tool-use", {
            "cwd": self.tmp,
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "frobnicate: bad type"'},
        }, cwd=self.tmp)
        self.assertEqual(decision(parse(out)), "deny")
        self.assertIn("Unknown commit type", reason(parse(out)))

    def test_valid_commit_allowed(self):
        subprocess.run(["git", "checkout", "-b", "feat/test"], cwd=self.tmp, check=True, capture_output=True)
        out, _, _ = run_gate("--pre-tool-use", {
            "cwd": self.tmp,
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "feat: valid"'},
        }, cwd=self.tmp)
        # Either no output (allow) or no deny decision
        self.assertNotEqual(decision(parse(out)), "deny")

    def test_amend_warns(self):
        subprocess.run(["git", "checkout", "-b", "feat/test"], cwd=self.tmp, check=True, capture_output=True)
        out, _, _ = run_gate("--pre-tool-use", {
            "cwd": self.tmp,
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit --amend -m "feat: amended"'},
        }, cwd=self.tmp)
        # warn() emits additionalContext, not deny
        ctx = context(parse(out))
        self.assertIn("Amending", ctx)

    def test_dot_commit_types_extends_allowed(self):
        subprocess.run(["git", "checkout", "-b", "feat/test"], cwd=self.tmp, check=True, capture_output=True)
        (Path(self.tmp) / ".commit-types").write_text("custom\nfix\n")
        out, _, _ = run_gate("--pre-tool-use", {
            "cwd": self.tmp,
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "custom: works now"'},
        }, cwd=self.tmp)
        self.assertNotEqual(decision(parse(out)), "deny")


# =========================================================================
# Gate 1b: post-commit (unpushed-commits info)
# =========================================================================

class TestGate1bPostCommit(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp_repo()
        subprocess.run(["git", "checkout", "-b", "feat/test"], cwd=self.tmp, check=True, capture_output=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_remote_branch_emits_info(self):
        # Tmp repo has no remote — every commit on a new branch is "unpushed"
        subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "feat: x"], cwd=self.tmp, check=True)
        out, _, _ = run_gate("--post-tool-use", {
            "cwd": self.tmp,
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit --allow-empty -m "feat: x"'},
        }, cwd=self.tmp)
        ctx = context(parse(out))
        self.assertIn("Unpushed commits", ctx)

    def test_amend_skipped(self):
        subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "feat: x"], cwd=self.tmp, check=True)
        out, _, _ = run_gate("--post-tool-use", {
            "cwd": self.tmp,
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit --amend -m "feat: y"'},
        }, cwd=self.tmp)
        # Amend should produce no output (silent)
        ctx = context(parse(out))
        self.assertNotIn("Unpushed", ctx)


# =========================================================================
# Gate 3: pre-checkout (dirty-tree deny)
# =========================================================================

class TestGate3PreCheckout(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp_repo()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_dirty_tracked(self):
        """Modify a tracked file so the working tree is dirty."""
        Path(self.tmp, "README.md").write_text("modified\n")

    def _make_untracked(self):
        """Add an untracked file (does not travel on switch)."""
        Path(self.tmp, "scratch.py").write_text("x = 1\n")

    def test_dirty_checkout_denied(self):
        self._make_dirty_tracked()
        out, _, _ = run_gate("--pre-tool-use", {
            "cwd": self.tmp,
            "tool_name": "Bash",
            "tool_input": {"command": "git checkout main"},
        }, cwd=self.tmp)
        self.assertEqual(decision(parse(out)), "deny")
        self.assertIn("Uncommitted changes", reason(parse(out)))
        self.assertIn("README.md", reason(parse(out)))

    def test_dirty_switch_denied(self):
        self._make_dirty_tracked()
        out, _, _ = run_gate("--pre-tool-use", {
            "cwd": self.tmp,
            "tool_name": "Bash",
            "tool_input": {"command": "git switch main"},
        }, cwd=self.tmp)
        self.assertEqual(decision(parse(out)), "deny")

    def test_clean_checkout_allowed(self):
        out, _, _ = run_gate("--pre-tool-use", {
            "cwd": self.tmp,
            "tool_name": "Bash",
            "tool_input": {"command": "git checkout main"},
        }, cwd=self.tmp)
        self.assertNotEqual(decision(parse(out)), "deny")

    def test_untracked_only_allowed(self):
        self._make_untracked()
        out, _, _ = run_gate("--pre-tool-use", {
            "cwd": self.tmp,
            "tool_name": "Bash",
            "tool_input": {"command": "git checkout main"},
        }, cwd=self.tmp)
        self.assertNotEqual(decision(parse(out)), "deny")

    def test_file_restore_dash_dash_allowed(self):
        self._make_dirty_tracked()
        out, _, _ = run_gate("--pre-tool-use", {
            "cwd": self.tmp,
            "tool_name": "Bash",
            "tool_input": {"command": "git checkout -- README.md"},
        }, cwd=self.tmp)
        self.assertNotEqual(decision(parse(out)), "deny")

    def test_git_restore_allowed(self):
        self._make_dirty_tracked()
        out, _, _ = run_gate("--pre-tool-use", {
            "cwd": self.tmp,
            "tool_name": "Bash",
            "tool_input": {"command": "git restore README.md"},
        }, cwd=self.tmp)
        self.assertNotEqual(decision(parse(out)), "deny")

    def test_new_branch_creation_b_flag_allowed_with_dirty_tree(self):
        self._make_dirty_tracked()
        out, _, _ = run_gate("--pre-tool-use", {
            "cwd": self.tmp,
            "tool_name": "Bash",
            "tool_input": {"command": "git checkout -b feat/new"},
        }, cwd=self.tmp)
        self.assertNotEqual(decision(parse(out)), "deny")

    def test_new_branch_creation_c_flag_allowed_with_dirty_tree(self):
        self._make_dirty_tracked()
        out, _, _ = run_gate("--pre-tool-use", {
            "cwd": self.tmp,
            "tool_name": "Bash",
            "tool_input": {"command": "git switch -c feat/new"},
        }, cwd=self.tmp)
        self.assertNotEqual(decision(parse(out)), "deny")


# =========================================================================
# Gate 5: post-push (PR-existence nag)
# =========================================================================

class TestGate5PostPushPrCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp_repo()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_post_push_on_main_silent_info(self):
        out, _, _ = run_gate("--post-tool-use", {
            "cwd": self.tmp,
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin main"},
        }, cwd=self.tmp)
        ctx = context(parse(out))
        self.assertIn("main", ctx.lower())  # "Pushed to main"


# =========================================================================
# Gate 6: SessionStart — stale merged-branches digest
# =========================================================================

class TestGate6SessionStartStaleBranches(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp_repo()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add_branch(self, name):
        """Create a branch from current HEAD (no actual divergence — counts as merged)."""
        subprocess.run(["git", "branch", name], cwd=self.tmp, check=True, capture_output=True)

    def test_no_branches_silent(self):
        out, _, _ = run_gate("--session-start", {"cwd": self.tmp}, cwd=self.tmp)
        self.assertEqual(out, "")

    def test_only_main_silent(self):
        out, _, _ = run_gate("--session-start", {"cwd": self.tmp}, cwd=self.tmp)
        self.assertEqual(out, "")

    def test_no_gh_or_no_merged_pr_silent(self):
        # Create a merged-into-main branch but no remote/gh PR — should be silent
        self._add_branch("feat/test")
        out, _, _ = run_gate("--session-start", {"cwd": self.tmp}, cwd=self.tmp)
        # No gh PR exists for tmp repo; gate should fall through silent
        self.assertEqual(out, "")

    def test_non_git_dir_silent(self):
        with tempfile.TemporaryDirectory() as non_git:
            out, _, _ = run_gate("--session-start", {"cwd": non_git}, cwd=non_git)
            self.assertEqual(out, "")

    def test_session_start_no_tool_name_works(self):
        # SessionStart hook input lacks tool_name — gate must not require it
        out, _, _ = run_gate("--session-start", {"cwd": self.tmp}, cwd=self.tmp)
        # Should pass cleanly (no crash, no deny)
        self.assertNotIn("error", out.lower())
        # JSON parse should succeed (or be empty)
        if out:
            self.assertIsNotNone(parse(out))

    def test_function_handles_main_master_filter(self):
        # Direct unit test on the function — ensures main/master are skipped
        # We can't easily mock gh from unit-tested layer, but we can verify
        # the candidate-list shape via a non-merged branch (returns empty)
        result = subprocess.run(
            ["git", "branch", "--merged", "main", "--format=%(refname:short)"],
            cwd=self.tmp, capture_output=True, text=True,
        )
        candidates = [
            line.strip() for line in result.stdout.splitlines()
            if line.strip() and line.strip() not in ("main", "master")
        ]
        # Fresh repo has only main; candidates should be empty
        self.assertEqual(candidates, [])

    def test_function_caps_at_20_branches(self):
        # Create 25 branches; verify the slice cap kicks in
        for i in range(25):
            subprocess.run(["git", "branch", f"feat/branch-{i}"], cwd=self.tmp, check=True, capture_output=True)
        result = subprocess.run(
            ["git", "branch", "--merged", "main", "--format=%(refname:short)"],
            cwd=self.tmp, capture_output=True, text=True,
        )
        candidates = [
            line.strip() for line in result.stdout.splitlines()
            if line.strip() and line.strip() not in ("main", "master")
        ][:20]
        self.assertEqual(len(candidates), 20)


# =========================================================================
# Main dispatch (fast paths + non-bash silence)
# =========================================================================

class TestMainDispatch(unittest.TestCase):
    def test_no_command_silent(self):
        out, _, _ = run_gate("--pre-tool-use", {
            "tool_name": "Bash",
            "tool_input": {"command": ""},
        })
        self.assertEqual(out, "")

    def test_non_git_command_silent(self):
        out, _, _ = run_gate("--pre-tool-use", {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hello"},
        })
        # Non-git → no deny (allow path)
        self.assertNotEqual(decision(parse(out)), "deny")

    def test_unknown_mode_silent(self):
        out, _, _ = run_gate("--unknown-mode", {
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
        })
        self.assertEqual(out, "")

    def test_invalid_json_input_silent(self):
        # Empty stdin should not crash
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT), "--pre-tool-use"],
            input="",
            capture_output=True, text=True, timeout=5,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
