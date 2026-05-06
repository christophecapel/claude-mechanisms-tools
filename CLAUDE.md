# claude-mechanisms-tools — AI session context

This repo packages three Claude Code tools that implement mechanisms from [`claude-mechanisms`](https://github.com/christophecapel/claude-mechanisms). Tools live in `skills/` (markdown skills) and `hooks/` (PreToolUse Python hooks).

## Where things live

- `skills/check/` — `/check` session-close audit
- `skills/press1-check/` — `/press1-check` Bash permission audit
- `hooks/worktree-edit-gate.py` — PreToolUse hook for Edit/Write/MultiEdit/NotebookEdit
- `hooks/install-hook.sh` — idempotent JSON merge into `~/.claude/settings.json`
- `tools.yaml` — manifest with `mechanism_ids:` cross-links
- `tests/` — Python unittest suite for the hook

## Cross-link discipline

Every tool entry in `tools.yaml` has a `mechanism_ids:` array. Every entry must resolve in `claude-mechanisms/mechanisms.yaml`. When adding a new tool, update both repos' manifests in the same atomic ship. Drift between the two manifests is detectable by `repo-pair-drift-gate.py` in the private myOS repo (v0.1.1 will add a `cross_manifest_id_match` strategy; v0.1 verifies manually at PR review).

## Versioning

Semantic Versioning. Each release gets a `vN.M.P` tag and a GitHub Release with body sourced from `CHANGELOG.md`. One release per "theme" (Session Hygiene, Git Workflow, Planning Audit, Content Pipeline). One LinkedIn post per release.

## When changing tools

- Edit the tool file
- Update `tools.yaml` entry if the mechanism_ids change
- Update CHANGELOG.md under `## [Unreleased]`
- Tests pass: `python3 -m unittest tests.test_worktree_edit_gate -v`
