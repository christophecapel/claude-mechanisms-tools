![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Built for](https://img.shields.io/badge/Built%20for-Claude%20Code-orange.svg)
![Version](https://img.shields.io/badge/version-v0.1.0-blue.svg)

> Tools that implement the operating mechanisms in [`claude-mechanisms`](https://github.com/christophecapel/claude-mechanisms).

`claude-mechanisms` (the why) ↔ `claude-mechanisms-tools` (the how).

Mechanisms describe how the work should be done. Tools enforce it. Each tool here implements one or more mechanisms from the catalog with a trigger, retry logic, and a failure path.

## v0.1 — Session Hygiene

Three tools. The "definition of done" toolkit: did you actually finish, did your edits land where you think, did you allow-list the right commands.

| Tool | What it does | Implements mechanism(s) |
|---|---|---|
| [`/check`](skills/check/) | Session-close audit — session-scoped manifest, two-section open items, decisive close signal | [#16](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/16-smallest-shippable-first.md), [#11](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/11-one-branch-one-scope.md), [#1](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/01-discover-and-derive.md) |
| [`worktree-edit-gate`](hooks/) | PreToolUse hook — warns when an absolute-path edit would land outside the active worktree | [#17](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/17-structural-checks-use-hooks.md), [#11](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/11-one-branch-one-scope.md) |
| [`/press1-check`](skills/press1-check/) | Bash permission audit — surface LOW-risk commands that should be allow-listed | [#21](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/21-structural-intervention-beats-pattern-n-plus-1.md), [#19](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/19-detection-rules-specific-patterns.md) |

The full manifest is [`tools.yaml`](tools.yaml).

## Quick start

**Option 1 — Install as a Claude Code plugin (one-liner)**

```bash
git clone https://github.com/christophecapel/claude-mechanisms-tools.git ~/.claude/plugins/claude-mechanisms-tools
```

That gets you the skills (`/check`, `/press1-check`). For the hook, run the install script once:

```bash
~/.claude/plugins/claude-mechanisms-tools/hooks/install-hook.sh
```

**Option 2 — Clone and pick what you want**

```bash
git clone https://github.com/christophecapel/claude-mechanisms-tools.git
```

Each tool is self-contained in its own subdirectory with a SKILL.md or script.

**Option 3 — Copy individual tool**

Browse [`skills/`](skills/) or [`hooks/`](hooks/), open the file you want, copy it into your local `~/.claude/commands/` or your project config.

See [`install.md`](install.md) for full setup including the hook wiring.

## Why a paired toolkit, not solo repos

Three solo repos for three tools is the N+1 anti-pattern (Mechanism [#21](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/21-structural-intervention-beats-pattern-n-plus-1.md)). One umbrella with versioned releases is the structural answer:

- One `git clone`. Each release adds tools, never breaks existing ones.
- Cross-links flow both ways. `mechanisms.yaml` references the tools that implement each mechanism; `tools.yaml` references the mechanisms each tool enforces. Pick a tool → find the mechanism. Pick a mechanism → find the tool.
- One install path. Plugin install or per-tool copy — same model as `claude-mechanisms`.

## Roadmap

| Release | Theme | Tools |
|---|---|---|
| **v0.1** (current) | Session Hygiene | `/check`, `worktree-edit-gate`, `/press1-check` |
| v0.2 | Git Workflow Discipline | Worktree-or-bust, atomic commit-push-PR, branch-contamination gate |
| v0.3 | Planning + Execution Audit | `plan-review-gate`, execution-audit |
| v0.4 | Content Pipeline | `/brief`, `/draft`, `/review`, `/audit`, `/publish-finalize` |

Cadence: one post per release. No batching.

## About

Built by [Christophe Capel](https://github.com/christophecapel) — a product leader codifying the operating discipline that makes working with Claude Code stick.

If any of these save you time, I want to hear about it. If you have tools of your own that implement a mechanism not yet in `claude-mechanisms`, open a PR or an issue on either repo.

## License

MIT — see [LICENSE](LICENSE).
