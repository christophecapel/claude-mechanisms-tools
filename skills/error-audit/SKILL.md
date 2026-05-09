---
name: error-audit
description: Audit errors across Claude Code session transcripts. Scans ~/.claude/projects/*.jsonl for 7 error classes (tool_error, validation_error, permission_denial, hook_block, bash_fail, retry_storm, read_before_edit), clusters by root-cause signature, and surfaces top N with suggested remediation tiers. Use when the user says "error audit", "errors across sessions", "system health errors", or "/error-audit".
---

# /error-audit — Cross-session error audit

Scan every Claude Code session transcript for errors, cluster by root cause, surface the top offenders with suggested remediations.

## Usage

```bash
# Default: all sessions, top 20 clusters, human output
python3 error-audit.py

# Last 30 days only
python3 error-audit.py --since 30

# Show fewer clusters
python3 error-audit.py --top 10

# Machine-readable (for piping into other tools)
python3 error-audit.py --json

# Override the projects dir (useful for testing)
python3 error-audit.py --projects-dir /path/to/projects

# Override or disable suppressions
python3 error-audit.py --suppressions-path /path/to/suppressions.md
python3 error-audit.py --no-suppressions
python3 error-audit.py --show-suppressed
```

## Steps (when invoking via `/error-audit`)

1. Run `python3 <skill-path>/error-audit.py` with any arguments the user provided.
2. Display the output to the user exactly as printed (includes colour-coded counts and suggested remediation tiers).
3. For the top 3 clusters, propose a concrete action:
   - **Tier 1** (settings allowlist): show the exact `~/.claude/settings.json` entry to add, but do NOT auto-apply — user must review Bash allowlist changes.
   - **Tier 2** (hook or script fix): locate the hook/script and propose the edit.
   - **Tier 3** (instruction/memory): draft the feedback or mechanism memory entry.
4. Do NOT auto-apply any remediation. This skill surfaces and proposes; the user decides.

## Configuration

| Env var | Purpose | Default |
|---|---|---|
| `CLAUDE_ERROR_AUDIT_SUPPRESSIONS` | Suppressions file path (cluster_keys to hide as working-as-designed) | `<skill-dir>/suppressions.md` (ships with toolkit) |

The suppressions file ships with one entry by default: the plan-review-gate's intentional `permission_denial:ExitPlanMode` blocks. Add your own entries to silence known-good clusters.

## What counts as "actionable"

A cluster is actionable if the signature is concrete enough to map to a single fix:

- `permission_denial:Bash:git` → allowlist-adjacent, concrete
- `tool_error:Read:File does not exist: <X>/...` → behavioural, concrete ("Glob before Read")
- `hook_block:Stop:response-linter:Want me to` → specific linter rule, concrete

Clusters with vague signatures (single-count generic errors) are monitor-only until a pattern forms.

## Implements

- Mechanism #19 — Detection rules: more specific patterns, never broader allowlists
- Mechanism #21 — Structural intervention beats pattern N+1

See https://github.com/christophecapel/claude-mechanisms

## Out of scope (this release)

- `/error-audit-triage` (interactive remediation flow with Linear ticket creation) — myOS-coupled today, deferred to v0.3.1+ once the agent path + Linear flow are decoupled.
- `error-audit-post.py` (post findings to a GitHub health-check issue) — myOS-specific health-check format, stays myOS-only.
