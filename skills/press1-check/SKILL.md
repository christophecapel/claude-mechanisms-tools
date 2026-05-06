---
name: press1-check
description: Audit which Bash commands required manual approval ("press 1") in Claude Code sessions. Use when the user says "press1-check", "press 1 check", "permission audit", or wants to review which commands need allow-listing.
---

# /press1-check -- Permission Audit

Audit which Bash commands triggered manual approval prompts in Claude Code sessions.

## How it runs

Two paths:

- **Manual:** type `/press1-check` to force a re-audit. Default mode is *since the last run* (state-tracked at `~/.claude/state/press1-check.json`), so the typical run only surfaces new ground.
- **Auto (optional):** the script supports `--auto-stop-hook` mode designed to be wired as a Claude Code `Stop` hook. State at `~/.claude/state/press1-check.json`. 6-hour cooldown bounds compute. When LOW-risk additions are found, a one-shot summary at `~/.claude/hooks-state/press1-check-pending.json` surfaces in the next session-start priority snapshot. See README for setup.

## Usage

- `/press1-check` -- since the last run (default, state-tracked)
- `/press1-check --days N` -- last N days across all project dirs
- `/press1-check --latest-session` -- only the single most recent session
- `/press1-check --all-recent` -- all sessions from the last 24h
- `/press1-check --since YYYY-MM-DD` -- all sessions since a date
- `/press1-check <session-id>` -- specific session

## Steps

1. Run: `python3 audit-permissions.py` with any arguments the user provided. Default audits since `~/.claude/state/press1-check.json#last_run_ts` (bootstraps to last 3 days when state is missing, e.g. on a new machine).
2. Display the output to the user exactly as printed (it includes color-coded risk levels).
3. If LOW-risk suggestions appear, add them to `~/.claude/settings.json` (read-only commands are safe). Skip env-var-prefix suggestions like `Bash(WT=*)` -- they don't generalize because the actual command follows the assignment.
4. Do NOT auto-add MEDIUM or HIGH risk commands without explicit approval.
5. After editing `~/.claude/settings.json`, re-run the audit and report before/after counts so the user can see the coverage delta.
6. Each successful interactive run updates the state file -- the next run is automatically scoped to "since now."
