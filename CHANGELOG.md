# Changelog

All notable changes to `claude-mechanisms-tools` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.1.0] — 2026-05-08 — Session Hygiene

Initial release. Three tools that close the most common silent failure modes around the end of a Claude Code session.

### Added

- **`/check`** — session-close audit skill. Builds a session-scoped manifest from chat-context (PRs, commits, Linear tickets, memory files, edited files), then routes open items into two sections: in-session (blocks close) and adjacent context (informational only). Emits a decisive close signal (✅ ready / ❌ not ready / ⚠️ caveat). Pre-render check validates PR-merge dependencies before flagging rows as blocked. Implements mechanisms #16, #11, #1.
- **`worktree-edit-gate`** — PreToolUse hook for `Edit | Write | MultiEdit | NotebookEdit`. Warns when an absolute-path edit targets a location inside the parent repo but outside the currently active worktree. Catches the silent-miss failure where edits intended for a worktree branch land in the main checkout instead. Warn-only mode for v0.1; promote to block in a later release after warnings accumulate. Implements mechanisms #17, #11.
- **`/press1-check`** — Bash permission audit. Scans Claude Code session logs for commands that triggered manual approval prompts and proposes safe LOW-risk additions to `~/.claude/settings.json`. State-tracked to avoid re-surfacing already-reviewed commands. Absorbs the previously standalone `claude-code-press1-check` repo (archived 2026-05-08). Implements mechanisms #21, #19.
- **`tools.yaml`** — declarative manifest of every tool in this repo with bidirectional cross-links to the mechanisms it implements. Mirrors `mechanisms.yaml` in `claude-mechanisms`.
- **Plugin install path** — `git clone … ~/.claude/plugins/claude-mechanisms-tools` mirrors the install model in `claude-mechanisms`. Skills auto-discover; hooks need a one-liner setup script.

### Cross-repo changes

- `claude-mechanisms` v1.6 — adds `implementations:` field to `mechanisms.yaml` for #1, #11, #16, #17, #19, #21. Each implementation entry points to the corresponding tool here.
- `claude-code-press1-check` — archived. README updated with one-line move notice. Zero adoption confirmed via Traffic API (0 stars, 0 forks, 1 unique viewer over 14 days).

[v0.1.0]: https://github.com/christophecapel/claude-mechanisms-tools/releases/tag/v0.1.0
