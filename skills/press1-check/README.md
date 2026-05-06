# /press1-check

Audit which Bash commands triggered manual approval prompts ("press 1") in Claude Code sessions, and propose safe LOW-risk additions to your `~/.claude/settings.json` allow-list.

> **Note:** this tool was previously the standalone repo `claude-code-press1-check` (archived 2026-05-08). It now lives here as one of three Session Hygiene tools in `claude-mechanisms-tools` v0.1. The script is unchanged.

## Files

- [`audit-permissions.py`](audit-permissions.py) — the script (single file, no dependencies beyond Python 3.8+ stdlib)
- [`SKILL.md`](SKILL.md) — Claude Code skill wrapper for the `/press1-check` slash command

## Usage

```bash
/press1-check                       # since the last run (default, state-tracked)
/press1-check --days N              # last N days across all project dirs
/press1-check --latest-session      # only the single most recent session
/press1-check --all-recent          # all sessions from the last 24h
/press1-check --since YYYY-MM-DD    # all sessions since a date
/press1-check <session-id>          # specific session
```

State is tracked at `~/.claude/state/press1-check.json` so re-runs only surface new ground.

## Auto mode

The script supports `--auto-stop-hook` mode for wiring as a Claude Code `Stop` hook. 6-hour cooldown bounds compute. When LOW-risk additions are found, a one-shot summary at `~/.claude/hooks-state/press1-check-pending.json` surfaces in the next session-start priority snapshot.

## Risk classification

- **HIGH** — destructive or hard to reverse. Keep gated; never auto-add.
- **MEDIUM** — side effects. Review case-by-case.
- **LOW** — read-only. Safe to allow-list automatically.

The script never auto-adds MEDIUM or HIGH risk commands. LOW-risk additions are surfaced for confirmation.

## Implements mechanisms

- [#21 — Structural intervention beats pattern N+1](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/21-structural-intervention-beats-pattern-n-plus-1.md)
- [#19 — Detection rules: more specific patterns, never broader allowlists](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/19-detection-rules-specific-patterns.md)

The audit pattern is the structural answer to the press-1 fatigue loop — the alternative was either approve-each-time (manual rule, fails under load) or blanket allow-list (risk regression). State-tracked surfacing of LOW-risk-only candidates is the third path.

## Install

This sub-tool installs as part of the parent toolkit. See the parent [`install.md`](../../install.md) for full setup.
