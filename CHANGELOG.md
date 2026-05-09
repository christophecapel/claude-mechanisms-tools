# Changelog

All notable changes to `claude-mechanisms-tools` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.4.0] — 2026-05-09 — Memory Discipline

One small tool. When a feedback memory describes a bug, it should link to a Linear ticket so the broken behavior is tracked toward remediation. This gate enforces that link as a structural check (not a behavioral rule the model has to remember).

### Added

- **`feedback-memory-gate`** — PostToolUse hook on `Write` matcher. Fast-paths to silent on non-feedback-memory writes. When a `claude-memory/feedback_*.md` file is written and its content matches bug indicators (`bug`, `broken`, `fails`, `error`, `wrong`, `fix`, `crash`, `missing`, etc.) but lacks a `**Linear:** CC-NN` reference, emits an `additionalContext` nudge to create one. **Soft warning, not a hard block** — fail-open on errors. 14 unit tests covering positive, negative, and edge fixtures (case-insensitive matching, fast-path behavior, exception handling).
- **`hooks/install-feedback-memory-gate.sh`** — idempotent installer. Re-runs are safe.

### Why this tool, this release

Battle-tested for 4+ weeks during memory-promotion work in myOS. Caught the missing `**Linear:** CC-NN` on `feedback_repo_pair_naming.md` during the v0.2 ship session itself, which led directly to capturing the rule in `feedback_options_table_not_open_questions.md`. Memory hygiene without a hook decays under cognitive load — exactly the failure mode mechanism #17 exists to prevent.

### Implements

- Mechanism #17 — Structural checks use hooks, not behavioral rules (third implementation alongside `worktree-edit-gate` v0.1 and `plan-review-gate` v0.2)
- Mechanism #5 — Deferred work needs persistent markers (Linear ticket IS the persistent marker linking the feedback to its remediation)

### Cross-repo changes

- `claude-mechanisms` v2.6 — extends `implementations:` on #17 with `feedback-memory-gate` (v0.4.0); adds `feedback-memory-gate` to #5.

[v0.4.0]: https://github.com/christophecapel/claude-mechanisms-tools/releases/tag/v0.4.0

## [v0.3.0] — 2026-05-09 — Detection & Audit

One tool that closes the loop between failure observation and pattern recognition. After a few weeks of working with Claude Code, errors stop being noise and start being signal — but only if you can cluster them by root cause and see which ones recur.

### Added

- **`/error-audit`** — scans every Claude Code session transcript under `~/.claude/projects/*.jsonl` for 7 error classes (`tool_error`, `validation_error`, `permission_denial`, `hook_block`, `bash_fail`, `retry_storm`, `read_before_edit`), normalises signatures (strips paths, IDs, UUIDs, timestamps), clusters by `class:tool:signature`, and surfaces top N with suggested remediation tiers. Default output is human-readable; `--json` is machine-readable for piping into other tools. 26 unit tests covering all 7 classes + clustering + suppression handling. Implements mechanisms #19, #21.
- **`skills/error-audit/suppressions.md`** — ships with one default entry (the plan-review-gate's intentional `permission_denial:ExitPlanMode` blocks). Add your own to silence known-good clusters.

### Configuration

| Env var | Purpose | Default |
|---|---|---|
| `CLAUDE_ERROR_AUDIT_SUPPRESSIONS` | Suppressions file path | `skills/error-audit/suppressions.md` (ships with toolkit) |

CLI flags: `--projects-dir`, `--suppressions-path`, `--no-suppressions`, `--show-suppressed`, `--since`, `--top`, `--json`. All path defaults are CLI-overridable.

### Cross-repo changes

- `claude-mechanisms` v2.5 — extends `implementations:` on #19 and #21 to include `/error-audit` alongside the existing `/press1-check` from v0.1.0.

### Out of scope

- `error-audit-post.py` (myOS-specific GitHub health-check issue format) — stays myOS-only.
- `/error-audit-triage` (interactive remediation flow with Linear ticket creation) — agent-path + Linear flow coupling, deferred to v0.3.1+.

[v0.3.0]: https://github.com/christophecapel/claude-mechanisms-tools/releases/tag/v0.3.0

## [v0.2.0] — 2026-05-08 — Plan Discipline

Two tools that turn plan-mode from a habit into a mechanism. Phase 1 enforces the plan's own structural contract; Phase 2 enforces the plan's contract with the PR.

### Added

- **`plan-review-gate`** — two-phase PreToolUse hook. Phase 1 (matcher: `ExitPlanMode`) blocks plan approval if required sections are missing (`Context`, `Implementation`, `Tests`, `Verification`, `Pre-flight`, `Files`). Phase 2 (matcher: `Bash`, `--mode=pre-pr`) blocks `gh pr create` if the PR diff is missing files the plan claimed it would touch. Hardened in CC-174 (`parse_head_branch` + `head_ref` for accurate diff resolution against `--head` branches) and CC-175 (token-aware command matcher via `shlex.split`, eliminates substring false-fires when commit/PR bodies mention `gh pr create` verbatim). 24 new unit tests covering positive, negative, and edge fixtures. Implements mechanisms #14, #16, #17.
- **`/plan-archive`** — link plan-mode files to their merged PRs. Plans accumulate on every `ExitPlanMode`; this skill groups them by the PR that executed them and moves the bundle into `~/.claude/plans/archive/by-pr/PR-<num>-<branch-slug>/` with `_meta.yaml` linking back to the PR + Linear tickets + commits. Modes: `--mode=audit` (read-only listing), `--mode=archive-pr --pr=N`, `--mode=backfill --since=14d`. All modes default to `--dry-run`; `--execute` actually moves files. Implements mechanism #5.
- **`lib/plan_files_lib.py`** — shared parsing for plan-review-gate (Phase 2) and plan-archive. Single source of truth for `## Files` section extraction so the two tools can never disagree on which files a plan declares.

### Configuration

Both tools auto-detect repo context from cwd's git metadata:

| Env var | Purpose | Default |
|---|---|---|
| `CLAUDE_PLAN_REPO_PREFIXES` | Path prefixes treated as repo-relative when matching plan files to PR diffs | auto-detect via `git rev-parse --show-toplevel` |
| `CLAUDE_PLAN_PR_URL_TEMPLATE` | GitHub PR URL template with `{number}` placeholder, used in `plan-archive`'s `_meta.yaml` | auto-detect from `git remote get-url origin` |

### Cross-repo changes

- `claude-mechanisms` — adds `implementations:` field to `mechanisms.yaml` for #5, #14, #16, #17. Each entry points back to the corresponding tool here.

[v0.2.0]: https://github.com/christophecapel/claude-mechanisms-tools/releases/tag/v0.2.0

## [v0.1.0] — 2026-05-08 — Session Hygiene

Initial release. Three tools that close the most common silent failure modes around the end of a Claude Code session.

### Added

- **`/check`** — session-close audit skill. Builds a session-scoped manifest from chat-context (PRs, commits, Linear tickets, memory files, edited files), then routes open items into two sections: in-session (blocks close) and adjacent context (informational only). Emits a decisive close signal (✅ ready / ❌ not ready / ⚠️ caveat). Pre-render check validates PR-merge dependencies before flagging rows as blocked. Implements mechanisms #16, #11, #1.
- **`worktree-edit-gate`** — PreToolUse hook for `Edit | Write | MultiEdit | NotebookEdit`. Warns when an absolute-path edit targets a location inside the parent repo but outside the currently active worktree. Catches the silent-miss failure where edits intended for a worktree branch land in the main checkout instead. Warn-only mode for v0.1; promote to block in a later release after warnings accumulate. Implements mechanisms #17, #11.
- **`/press1-check`** — Bash permission audit. Scans Claude Code session logs for commands that triggered manual approval prompts and proposes safe LOW-risk additions to `~/.claude/settings.json`. State-tracked to avoid re-surfacing already-reviewed commands. Absorbs the previously standalone `claude-code-press1-check` repo (archived 2026-05-08). Implements mechanisms #21, #19.
- **`tools.yaml`** — declarative manifest of every tool in this repo with bidirectional cross-links to the mechanisms it implements. Mirrors `mechanisms.yaml` in `claude-mechanisms`.
- **Plugin install path** — `git clone … ~/.claude/plugins/claude-mechanisms-tools` mirrors the install model in `claude-mechanisms`. Skills auto-discover; hooks need a one-liner setup script.

### Cross-repo changes

- `claude-mechanisms` v1.6 — adds `implementations:` field to `mechanisms.yaml` for #1, #11, #16, #17, #19, #21. Each implementation entry points to the corresponding tool here.
- `claude-code-press1-check` — archived. README updated with one-line move notice. Zero adoption confirmed via Traffic API (0 stars, 0 forks, 1 unique viewer over 14 days).

[v0.1.0]: https://github.com/christophecapel/claude-mechanisms-tools/releases/tag/v0.1.0
