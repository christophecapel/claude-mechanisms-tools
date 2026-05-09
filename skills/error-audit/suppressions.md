# Error-audit suppressions

Cluster keys marked "working as designed". `scripts/error-audit.py` hides these from `--human` output by default; `--show-suppressed` re-includes them. `--json` always tags every cluster with a `suppressed: true|false` field so downstream consumers (triage agent, health-check JSON embed) decide policy.

## Format

One cluster_key per line inside the fenced code block below, optionally followed by a tab or 2+ spaces and a one-line reason. Lines starting with `#` are comments and ignored by the parser. Keys are matched **exactly** — a new signature on the same hook still surfaces because it yields a different cluster_key.

The cluster_key format is `class:tool:signature_first_60_chars` (deterministic — strip paths to `<X>`, strip `toolu_*` IDs, strip UUIDs, strip ISO timestamps, collapse whitespace, truncate).

## Suppressions

```
# Plan-review-gate — blocking incomplete plans at ExitPlanMode. Working as designed.
permission_denial:ExitPlanMode:ExitPlanMode	plan-review-gate blocking plan approval until sections/keywords satisfy the gate
tool_error:ExitPlanMode:PLAN REVIEW GATE: [PASS] Context [FAIL] Implementation -- em	plan-review-gate flagging incomplete-section plan before approval

# Git-workflow-gate — enforcing branch/rebase/chain-cd discipline. Working as designed.
permission_denial:Bash:cd	chained-cd denial from Gate 0
tool_error:Bash:Uncommitted changes (1 file(s)). Commit or stash before swit	git-workflow-gate catching unstaged work before branch switch
tool_error:Bash:Branch is behind origin/main by 1 commit(s). Run: `git fetch	git-workflow-gate catching stale rebase state

# Content-workflow-gate — scope-locking content sessions. Working as designed.
tool_error:Bash:PreToolUse:Bash hook error: [python3 ~/myOS/scripts/content-	content-workflow-gate blocking Bash ops during content sessions
tool_error:Bash:Cannot start new scope -- other repos have uncommitted chang	content-workflow-gate scope-lock across repos
tool_error:Bash:CONTENT WORKFLOW GATE: branch switch blocked. Uncommitted co	content-workflow-gate catching unstaged content before switch
```

## Candidates to re-evaluate

Add clusters here when a triage classifies them as `newly-suppressible` but before moving them above. Allows human review before the scanner starts hiding them.

```
# (none yet)
```
