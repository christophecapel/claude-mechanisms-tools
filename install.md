# Installation

Three install paths. Pick the one that matches how you already use Claude Code.

## Option 1: Install as a Claude Code plugin (one-liner)

```bash
git clone https://github.com/christophecapel/claude-mechanisms-tools.git ~/.claude/plugins/claude-mechanisms-tools
```

Skills (`/check`, `/press1-check`) auto-discover from the plugin path. The hook needs one extra step:

```bash
~/.claude/plugins/claude-mechanisms-tools/hooks/install-hook.sh
```

The install script idempotently adds the `worktree-edit-gate` PreToolUse matcher to your `~/.claude/settings.json`. Re-runs are safe.

## Option 2: Clone and pick what you want

```bash
git clone https://github.com/christophecapel/claude-mechanisms-tools.git
```

Each tool is self-contained in its own subdirectory. Symlink or copy whatever you want into `~/.claude/skills/` or `~/.claude/commands/`.

## Option 3: Copy individual tool

Browse [`skills/`](skills/) or [`hooks/`](hooks/), open the file you want, and copy it into your local config:

- `skills/check/check.md` → `~/.claude/commands/check.md`
- `skills/press1-check/SKILL.md` → `~/.claude/skills/press1-check/SKILL.md`
- `hooks/worktree-edit-gate.py` → wire as a `PreToolUse` hook (see [Hooks](#hooks-setup) below)

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

## Customization

These tools are opinionated. They reflect how one person works with Claude Code. Fork the repo, remove what doesn't fit, add your own. Each tool's `mechanism_ids:` in `tools.yaml` should reference a real mechanism in [`claude-mechanisms`](https://github.com/christophecapel/claude-mechanisms) — that's the cross-link discipline.
