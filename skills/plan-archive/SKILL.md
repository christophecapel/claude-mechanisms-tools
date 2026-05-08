---
name: plan-archive
description: Archive completed plan-mode files in ~/.claude/plans/ by linking them to their merged PR. Use when plans accumulate and you want the list to show only active work.
---

# /plan-archive

Plans accumulate every time you enter plan mode. This skill groups them by the PR that executed them and moves the bundle into `~/.claude/plans/archive/by-pr/PR-<num>-<branch-slug>/` with a `_meta.yaml` linking back to PR + Linear tickets + commits.

## Usage

```bash
# Audit only — list active plans, flag orphans
python3 plan-archive.py --mode=audit

# Archive a specific merged PR
python3 plan-archive.py --mode=archive-pr --pr=123 --execute

# Backfill: scan recent merged PRs and archive matches
python3 plan-archive.py --mode=backfill --since=14d --execute
```

All modes default to `--dry-run`. Add `--execute` to actually move files.

## Configuration

| Env var | Purpose | Default |
|---|---|---|
| `CLAUDE_PLAN_REPO_PREFIXES` | Path prefixes treated as repo-relative when matching plan files to PR diffs | auto-detect via `git rev-parse --show-toplevel` |
| `CLAUDE_PLAN_PR_URL_TEMPLATE` | GitHub PR URL template with `{number}` placeholder | auto-detect from `git remote get-url origin` |

Both auto-detect from the cwd's git repo, so the defaults work in any repo. Set the env vars only if you need to override (e.g. running from outside a repo).

## Implements

Mechanism #5 — Deferred work needs persistent markers. See https://github.com/christophecapel/claude-mechanisms

## Related

- `plan-review-gate` (in this toolkit, `hooks/plan-review-gate.py`) — Phase 2 of the gate uses the same `plan_files_lib` parsing to match PR diffs to plans
