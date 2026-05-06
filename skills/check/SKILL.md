---
name: check
description: Session-close audit — session-scoped manifest, two-section open items, decisive close signal. Runs the `/check` audit defined in `check.md`. Use when the user says "check", "audit this session", "close the session", "definition of done", or wants a clean-vs-blocked verdict before ending a session.
---

# /check — Session-Close Audit

This skill runs the session-close audit defined in [`check.md`](check.md).

## What it does

- Builds a **Session Manifest** from chat-context (PRs, commits, tickets, memory files, edited files) — derives scope FIRST, before any audit
- Walks 5 audit sections (Learnings, Changes, Docs, Issues, Memory) with a per-section emoji status (✅ / ⚠️ / ❌) reflecting **only Section A items**
- Routes open items into two sections:
  - **Section A — In-session** (blocks close if any row is `tackle now`)
  - **Section B — Adjacent context** (never blocks close, informational only)
- **Pre-render check:** validates PR-merge dependencies before flagging rows as `blocked by user`. If `gh pr view` shows the PR is already merged, the row auto-flips to `tackle now` and the dependent action gets executed in the same turn.
- Emits a **decisive verdict**: ✅ Ready to close / ❌ Not ready / ⚠️ Close with caveats. Re-running `/check` for the same state produces the same verdict.

## Why session-scoped

Earlier `/check` versions surfaced every open item across all sessions, projects, and pre-existing tracker tickets. That made every close run feel incomplete and triggered multi-`/check` loops to walk through items that didn't belong to the session. Session-scoped audit runs in one pass — items from other sessions land in Section B and never block close.

## Usage

Type `/check` at any point you want a clean-vs-blocked verdict on the current session. The skill follows `check.md` step by step.

## Implements mechanisms

- [#16 — Smallest shippable first](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/16-smallest-shippable-first.md)
- [#11 — One branch, one scope](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/11-one-branch-one-scope.md)
- [#1 — Discover and derive, never assume or ask](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/01-discover-and-derive.md)
