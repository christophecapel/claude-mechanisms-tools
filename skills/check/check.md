---
description: Session-close audit — session-scoped manifest, two-section open items, decisive close signal
---

Audit this session before we close it. Answer with evidence, not assertions.

The first job is to **scope this audit to this session only**. Items from other sessions, future tracker-tracked work, or out-of-scope user tasks must NOT block close.

---

## 0. Session Manifest (derive scope FIRST, before any audit)

Before running sections 1–5 below, derive what is in-session. Anything outside this manifest is out-of-session and NEVER blocks close — it lands in Section B at most.

Build the manifest from chat-context (this conversation), not git alone:

- **PRs opened this session** — every `gh pr create` you ran (track from your tool calls)
- **Commits authored this session** — `git log --author="$(git config user.email)" --since=4h`
- **Issues filed this session** — every issue tracker create call (capture the IDs from the responses)
- **Memory / context files touched this session** — `git log --since=4h -- <memory-dir>/` filtered to your commits
- **Files edited this session** — your Edit/Write tool calls in this conversation

Render as a one-line summary at the top of the audit: `Session manifest: N PRs, M commits, K tickets (...), J memory files, I files edited.`

If the manifest is empty (purely a read-only / chat session with no writes), Section A is empty by definition; skip directly to ✅ Ready.

---

## 1–5. Per-section status (with section emoji)

**Per-section status emoji — reflects Section A items only.** A section with only Section B context is ✅. Prefix each section heading with one of:
- ✅ clean / nothing in-session needed / all in-session done
- ⚠️ attention — in-session ambiguity you can't resolve (genuinely blocked by user)
- ❌ blocker — in-session unfinished work, uncommitted in-scope edits, in-scope errors

1. **Learnings captured** — Were any non-obvious decisions, gotchas, or insights surfaced this session? If yes, are they captured durably (memory, CLAUDE.md, commit message, issue, doc)? If not, name what should be captured and where.
2. **Changes landed** — `git status` and `git log --oneline @{u}.. 2>/dev/null || git log --oneline -5`. Are all in-session changes committed? Any stray uncommitted in-scope edits? Anything staged/unpushed that should be?
3. **Docs updated** — Did in-session code, commands, schemas, or workflows change in a way that needs doc updates (README, CLAUDE.md, reference files, skill frontmatter)? Done or pending?
4. **Issues addressed** — Any in-session errors, blocked tool calls, pending TODOs, or unresolved threads? List each and its status (done / deferred to ticket / genuinely dropped).
5. **Memory hygiene** — Anything from this session worth saving to persistent memory that isn't yet? Anything stale that should be updated/removed?

---

## 📋 Open Items — TWO sections

**Critical:** every ⚠️ or ❌ from sections 1–5 MUST appear in the right table below. Items don't get to hide in prose.

### Section A — In-session items (blocks close if any row is `tackle now`)

Items mapped to the Session Manifest. These are work this session originated, owns, or must complete.

| # | Item | Status | Action this turn | Owner |
|---|------|--------|------------------|-------|
| 1 | [one-line description] | `done` / `deferred (ticket-ID)` / `tackle now` / `blocked by user` | `none` / specific verb you'll execute below / `none — tracker tracks it` | `Claude` / `<user>` / `external` |

If empty, write: `None — no in-session items.`

**Status definitions:**
- `done` — completed in this session, no follow-up needed
- `deferred (ticket-ID)` — explicitly handed to a tracker ticket for a future session. Once a ticket exists, the item is done from this session's perspective.
- `tackle now` — must be resolved this turn. Blocks ✅.
- `blocked by user` — needs a destructive/external/ambiguous decision only the user can make. Triggers ⚠️. **If the only blocker is a PR merge, run the pre-render PR-merge-state check below first — the row may auto-flip to `tackle now`.**

#### Pre-render: validate PR-merge dependencies before marking rows `blocked by user`

If a Section A row's blocker is a PR merge (text mentions "after PR #N merges", "awaits merge", "blocked on PR #N", "merge of #N", or similar `#NNN`-near-merge-vocabulary patterns), check the PR's state once, before rendering:

1. Identify each referenced PR. Default repo = current; explicit `<repo>#NNN` mentions (e.g. `myrepo#506`) override.
2. Run `gh pr view <num> --repo <owner>/<repo> --json state,mergedAt` once per referenced PR.
3. If ANY referenced PR is `OPEN` or `CLOSED` (closed-without-merge) — dependency holds, row stays `blocked by user`.
4. If ALL referenced PRs are `MERGED` — dependency is gone, row flips to `tackle now`. Name the dependent action; **execute it in the same turn** (Mechanism [#1](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/01-discover-and-derive.md)).

One check, not a poll. Don't re-query mid-render. Heuristic limited to `#NNN`-mention rows; a row that says `blocked by user` without a PR number doesn't fire the check.

### Section B — Adjacent context (NEVER blocks close, informational only)

Items mentioned this session but NOT in the manifest: other sessions' commits, future-tomorrow user tasks, tracker tickets filed in earlier sessions, repos/branches you only read.

| # | Item | Why it's not in-session | Action this session |
|---|------|--------------------------|---------------------|
| 1 | [one-line description] | concurrent session / user's morning task / pre-existing tracker ticket / read-only reference | `none` |

If empty, write: `None — no adjacent context surfaced.`

`Action this session` is **always `none`** for Section B. If it ever isn't, the row belongs in Section A.

### Proposed actions (Section A only)

For each Section A row that isn't `done`, `deferred`, or `blocked by user`, state in one line what you're about to do and **execute it in the same turn** — don't ask permission for reversible work. For `deferred` rows, the ticket ID must already exist (file the ticket as part of the action if it doesn't, then the row becomes `deferred`).

Section B never produces actions. If you find yourself proposing an action for a Section B row, that row was misclassified — move it to Section A or drop it.

---

## Idempotency rule

If `/check` is re-run later in the same session, items previously marked `deferred (ticket-ID)` and not subsequently touched are **not re-listed**. Once filed and explicitly deferred, they're done from this session's perspective. Re-listing them is exactly the multi-`/check` loop this design exists to kill.

---

## Final verdict

Verdict is driven by **Section A only**. Section B never affects the verdict.

- ✅ **Ready to close** — Section A is empty OR every row is `done` or `deferred (ticket-ID)`. Brief summary of what shipped this session.
- ❌ **Not ready** — Section A has at least one `tackle now` row. List those rows + recommended next action for each.
- ⚠️ **Close with caveats** — Reserved for the rare case where Section A has a `blocked by user` row (genuine, named ambiguity). NOT for tracker-deferred work. NOT for adjacent context. NOT a default fallback.

Be direct. If something was skipped, say so. If something is genuinely ambiguous, name the ambiguity rather than papering over it. The verdict is authoritative — re-running `/check` for the same state will produce the same verdict.

---

Implements [Mechanism #16 — Smallest shippable first](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/16-smallest-shippable-first.md), [Mechanism #11 — One branch, one scope](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/11-one-branch-one-scope.md), and [Mechanism #1 — Discover and derive, never assume or ask](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/01-discover-and-derive.md).
