# Installation

Three install paths. Pick the one that matches how you already use Claude Code.

## Option 1: Install as a Claude Code plugin (one-liner)

```bash
git clone https://github.com/christophecapel/claude-mechanisms-tools.git ~/.claude/plugins/claude-mechanisms-tools
```

Skills (`/check`, `/press1-check`, `/plan-archive`, `/error-audit`) auto-discover from the plugin path. The hooks need one extra step each:

```bash
~/.claude/plugins/claude-mechanisms-tools/hooks/install-hook.sh                       # worktree-edit-gate (v0.1)
~/.claude/plugins/claude-mechanisms-tools/hooks/install-plan-review-gate.sh           # plan-review-gate Phase 1 + Phase 2 (v0.2)
~/.claude/plugins/claude-mechanisms-tools/hooks/install-feedback-memory-gate.sh       # feedback-memory-gate (v0.4)
```

All install scripts idempotently add their hook matchers to `~/.claude/settings.json`. Re-runs are safe.

## Option 2: Clone and pick what you want

```bash
git clone https://github.com/christophecapel/claude-mechanisms-tools.git
```

Each tool is self-contained in its own subdirectory. Symlink or copy whatever you want into `~/.claude/skills/` or `~/.claude/commands/`.

## Option 3: Copy individual tool

Browse [`skills/`](skills/) or [`hooks/`](hooks/), open the file you want, and copy it into your local config:

- `skills/check/check.md` → `~/.claude/commands/check.md`
- `skills/press1-check/SKILL.md` → `~/.claude/skills/press1-check/SKILL.md`
- `skills/plan-archive/SKILL.md` → `~/.claude/skills/plan-archive/SKILL.md`
- `hooks/worktree-edit-gate.py` → wire as a `PreToolUse` hook (see [Hooks](#hooks-setup) below)
- `hooks/plan-review-gate.py` + `lib/plan_files_lib.py` → wire as two `PreToolUse` hooks (Phase 1 on `ExitPlanMode`, Phase 2 on `Bash`)
- `hooks/feedback-memory-gate.py` → wire as a `PostToolUse` hook on `Write`

## Hooks setup

The `worktree-edit-gate.py` hook needs to be wired into `~/.claude/settings.json` as a `PreToolUse` matcher for `Edit | Write | MultiEdit | NotebookEdit`. The included `install-hook.sh` does this idempotently:

```bash
~/.claude/plugins/claude-mechanisms-tools/hooks/install-hook.sh
```

Or wire it manually — add this entry under `hooks.PreToolUse`:

```json
{
  "matcher": "Edit|Write|MultiEdit|NotebookEdit",
  "hooks": [
    {
      "type": "command",
      "command": "python3 ~/.claude/plugins/claude-mechanisms-tools/hooks/worktree-edit-gate.py"
    }
  ]
}
```

The hook is silent on pass (Mechanism [#20](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/20-hooks-silent-on-pass.md)). It only emits an `additionalContext` warning when an absolute-path edit would land outside the active worktree.

### feedback-memory-gate (v0.4)

PostToolUse on `Write` matcher. The included `install-feedback-memory-gate.sh` wires it idempotently:

```bash
~/.claude/plugins/claude-mechanisms-tools/hooks/install-feedback-memory-gate.sh
```

Or manually — add this entry under `hooks.PostToolUse`:

```json
{
  "matcher": "Write",
  "hooks": [
    {
      "type": "command",
      "command": "python3 ~/.claude/plugins/claude-mechanisms-tools/hooks/feedback-memory-gate.py"
    }
  ]
}
```

The hook fast-paths to silent on non-feedback-memory writes. It only emits an `additionalContext` nudge when a `claude-memory/feedback_*.md` file describes a bug (matched against bug-indicator keywords) without a `**Linear:** CC-NN` reference.

### plan-review-gate (v0.2)

Two PreToolUse entries — Phase 1 on `ExitPlanMode`, Phase 2 on `Bash` (matches `gh pr create`). The included `install-plan-review-gate.sh` wires both idempotently:

```bash
~/.claude/plugins/claude-mechanisms-tools/hooks/install-plan-review-gate.sh
```

Or manually — add these two entries under `hooks.PreToolUse`:

```json
{
  "matcher": "ExitPlanMode",
  "hooks": [
    {
      "type": "command",
      "command": "python3 ~/.claude/plugins/claude-mechanisms-tools/hooks/plan-review-gate.py"
    }
  ]
},
{
  "matcher": "Bash",
  "hooks": [
    {
      "type": "command",
      "command": "python3 ~/.claude/plugins/claude-mechanisms-tools/hooks/plan-review-gate.py --mode=pre-pr"
    }
  ]
}
```

Optional configuration via env vars (see also `lib/plan_files_lib.py` and `skills/plan-archive/SKILL.md`):

| Env var | Purpose | Default |
|---|---|---|
| `CLAUDE_PLAN_REPO_PREFIXES` | Path prefixes treated as repo-relative when matching plan files to PR diffs | auto-detect via `git rev-parse --show-toplevel` |
| `CLAUDE_PLAN_PR_URL_TEMPLATE` | GitHub PR URL template with `{number}` placeholder | auto-detect from `git remote get-url origin` |

## Customization

These tools are opinionated. They reflect how one person works with Claude Code. Fork the repo, remove what doesn't fit, add your own. Each tool's `mechanism_ids:` in `tools.yaml` should reference a real mechanism in [`claude-mechanisms`](https://github.com/christophecapel/claude-mechanisms) — that's the cross-link discipline.
