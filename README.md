![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Built for](https://img.shields.io/badge/Built%20for-Claude%20Code-orange.svg)
![Version](https://img.shields.io/badge/version-v1.0.0-blue.svg)
![Stability](https://img.shields.io/badge/stability-stable-brightgreen.svg)

> Tools that implement the operating mechanisms in [`claude-mechanisms`](https://github.com/christophecapel/claude-mechanisms).

`claude-mechanisms` (the why) ↔ `claude-mechanisms-tools` (the how).

Mechanisms describe how the work should be done. Tools enforce it. Each tool here implements one or more mechanisms from the catalog with a trigger, retry logic, and a failure path.

## Stability commitment (v1.0.0)

v1.0.0 marks the universal-applicability subset of the toolkit as **feature-complete and stable**. Five themes shipped (Session Hygiene, Plan Discipline, Detection & Audit, Memory Discipline, Atomic Git Workflow), 8 distinct tools, 231 tests.

**What stable means here:**

- Existing tool names, install paths (`~/.claude/plugins/claude-mechanisms-tools/`), hook commands (`python3 <toolkit>/hooks/<tool>.py --<mode>`), and CLI flags WILL NOT break in v1.x
- Existing `tools.yaml` entries (id, file, mechanism_ids) WILL NOT break in v1.x
- The cross-link contract with [`claude-mechanisms`](https://github.com/christophecapel/claude-mechanisms) (mechanism_id ↔ implementations path bidirectional) is permanent
- Hook output format (deny/allow/warn/info JSON shapes) WILL NOT break in v1.x

**What's still allowed:**

- New tools added (minor version bumps: v1.1, v1.2, ...)
- New gates within existing hooks (patch bumps: v1.0.1, v1.0.2, ...)
- Existing tools gain new modes / env vars (additive only)
- Hook stdout messages refined for clarity (the JSON shape stays; the prose in `permissionDecisionReason` may improve)
- Test coverage grows

Breaking changes ship as v2.0 with a deprecation cycle, never as a silent v1.x update.

**What's NOT promised:**

- That every release adds features. v1.x may go quiet — feature-complete means feature-complete.
- That myOS-specific features (Linear API, daily-plan, etc.) ever get extracted. Those stay myOS-only by design.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for how to propose new tools or extensions.

## v0.6 — Stale-branches digest (current)

Gate 6 added — a SessionStart hook that scans the current repo for local feature branches whose PRs have merged on GitHub but were never deleted. Surfaces a single info-nag listing cleanup commands once per Claude Code session. Surfaced from a real failure: 5 stale merged branches accumulated unnoticed in `claude-mechanisms` + `myOS` at v0.5.1 close.

## v0.5 — Atomic Git Workflow

One tool, seven gates (Gate 3 added in v0.5.1; Gate 6 added in v0.6.0). Don't commit to main, use the right commit-message format, don't switch branches with a dirty tree, don't push behind origin/main, don't push to a frozen branch, don't push without a PR, clean up merged branches at session start. Structural enforcement of the atomic commit→push→PR flow.

| Tool | What it does | Implements mechanism(s) |
|---|---|---|
| [`git-workflow-gate`](hooks/git-workflow-gate.py) | PreToolUse + PostToolUse hooks on `Bash` + SessionStart — Gate 0 (cd-chain block) + Gate 1 (pre-commit branch+format) + Gate 1b (post-commit unpushed nag) + Gate 2 (pre-push rebase+frozen+force) + Gate 3 (pre-checkout dirty-tree deny, v0.5.1) + Gate 5 (post-push PR nag) + Gate 6 (session-start stale-branches digest, v0.6.0) | [#1](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/01-discover-and-derive.md), [#11](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/11-one-branch-one-scope.md), [#17](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/17-structural-checks-use-hooks.md) |

## v0.4 — Memory Discipline

One tool. Feedback memories that describe bugs should link to a Linear ticket — otherwise the broken behavior is captured but not tracked toward remediation. This gate enforces the link as a structural check on every memory write.

| Tool | What it does | Implements mechanism(s) |
|---|---|---|
| [`feedback-memory-gate`](hooks/feedback-memory-gate.py) | PostToolUse hook on `Write` — when a `claude-memory/feedback_*.md` file describes a bug (`bug`, `broken`, `fails`, etc.) without a `**Linear:** CC-NN` reference, nudges to add one | [#17](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/17-structural-checks-use-hooks.md), [#5](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/05-deferred-work-needs-persistent-markers.md) |

## v0.3 — Detection & Audit

One tool. Cluster every error across every Claude Code session by root-cause signature, surface the top offenders, classify them by remediation tier (allowlist / hook / instruction). Suppress the working-as-designed ones so signal doesn't drown in noise.

| Tool | What it does | Implements mechanism(s) |
|---|---|---|
| [`/error-audit`](skills/error-audit/SKILL.md) | Scan every session transcript for 7 error classes, cluster by root-cause signature, surface top N with remediation tiers | [#19](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/19-detection-rules-specific-patterns.md), [#21](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/21-structural-intervention-beats-pattern-n-plus-1.md) |

## v0.2 — Plan Discipline

Two tools that turn plan-mode from a habit into a mechanism. The gate enforces the plan's structural contract on `ExitPlanMode` and its contract with the PR on `gh pr create`. The archiver links every plan file to its merged PR so the active list shows only live work.

| Tool | What it does | Implements mechanism(s) |
|---|---|---|
| [`plan-review-gate`](hooks/plan-review-gate.py) | Two-phase PreToolUse hook — Phase 1 blocks `ExitPlanMode` if required sections are missing; Phase 2 blocks `gh pr create` if the diff misses planned files | [#14](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/14-trace-the-cascade.md), [#16](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/16-smallest-shippable-first.md), [#17](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/17-structural-checks-use-hooks.md) |
| [`/plan-archive`](skills/plan-archive/) | Link plan-mode files to merged PRs — moves them into `~/.claude/plans/archive/by-pr/PR-<num>-<branch>/` with `_meta.yaml` cross-references | [#5](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/05-deferred-work-needs-persistent-markers.md) |

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

That gets you all the skills (`/check`, `/press1-check`, `/plan-archive`). For the hooks, run the install scripts once:

```bash
~/.claude/plugins/claude-mechanisms-tools/hooks/install-hook.sh                # worktree-edit-gate (v0.1)
~/.claude/plugins/claude-mechanisms-tools/hooks/install-plan-review-gate.sh    # plan-review-gate Phase 1 + Phase 2 (v0.2)
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
| v0.1 | Session Hygiene | `/check`, `worktree-edit-gate`, `/press1-check` |
| v0.2 | Plan Discipline | `plan-review-gate` (Phase 1 + Phase 2), `/plan-archive` |
| v0.3 | Detection & Audit | `/error-audit` |
| v0.4 | Memory Discipline | `feedback-memory-gate` |
| v0.5 | Atomic Git Workflow | `git-workflow-gate` (5 gates: cd-chain, pre-commit, post-commit, pre-push, post-push) |
| v0.5.1 | Dirty-tree pre-checkout patch | `git-workflow-gate` Gate 3 (CC-178) |
| v0.6 | Stale-branches digest | `git-workflow-gate` Gate 6 — SessionStart info-nag (CC-179) |
| **v1.0.0** (current) | **Stability release** | Public-repo polish + stability commitment (CC-180) |
| v1.x | TBD — only if real failure modes surface | Backlog: `BLOCKED_REMOTES` env-var, `OWNER_PATTERN` env-var |

Cadence: one post per release. No batching.

## About

Built by [Christophe Capel](https://github.com/christophecapel) — a product leader codifying the operating discipline that makes working with Claude Code stick.

If any of these save you time, I want to hear about it. If you have tools of your own that implement a mechanism not yet in `claude-mechanisms`, open a PR or an issue on either repo.

## License

MIT — see [LICENSE](LICENSE).
