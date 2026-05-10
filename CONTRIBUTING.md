# Contributing to claude-mechanisms-tools

This repo packages tools that implement operating mechanisms from [`claude-mechanisms`](https://github.com/christophecapel/claude-mechanisms). Every tool here should map to one or more mechanisms in that catalog with a clear trigger, retry logic, and failure path.

## Before opening a PR

1. **Pair the tool with a mechanism.** Every tool's `mechanism_ids:` in [`tools.yaml`](tools.yaml) must resolve in [`claude-mechanisms/mechanisms.yaml`](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms.yaml). If your tool implements a mechanism that doesn't yet exist in the catalog, open an issue or PR there first.
2. **Battle-test before extracting.** Tools here are extracted from real use, not built speculatively. The minimum bar: 4+ weeks of in-anger usage in a private setup before extraction. If you're proposing a brand-new tool, document the failure mode it prevents and the evidence it works.
3. **Keep it slim.** Tools should be the universally-applicable subset. myOS-specific concerns (Linear API, internal repo lists, custom file conventions) stay private. Use env vars with auto-detect fallbacks for any configurable surface (see `CLAUDE_PLAN_REPO_PREFIXES`, `CLAUDE_ERROR_AUDIT_SUPPRESSIONS` in existing tools for the pattern).

## PR shape

Bundle code, tests, and docs in a single commit per [`mechanism_bundle_docs_with_code`](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/05-deferred-work-needs-persistent-markers.md):

- **Code** — the tool itself in `hooks/` (for hooks) or `skills/` (for slash commands)
- **Install script** — idempotent, in `hooks/install-<tool>.sh` (hooks only)
- **Tests** — in `tests/test_<tool>.py`; CI runs Python 3.9-3.12
- **Manifest** — new entry in `tools.yaml` with `mechanism_ids:`
- **Docs** — `CHANGELOG.md` entry, `README.md` row in the relevant version section, `install.md` install snippet

## Mechanism cross-link

Each new tool extends the `## Implementations` table in the relevant mechanism file in `claude-mechanisms`. Open a paired PR there before merging the toolkit PR. The cross-link integrity check is currently manual at PR review; v0.1.1+ will add automated verification.

## Testing locally

```bash
python3 -m unittest discover tests
```

All tests must pass on Python 3.9 through 3.12. Hooks should fail-closed (deny on any unhandled exception) and be silent on pass (per [mechanism #20](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/20-hooks-silent-on-pass.md)).

## Reporting bugs / proposing features

Use the issue templates. For bugs, include the gate output, your `~/.claude/settings.json` hook entry (redacted as needed), and the failing command. For features, describe the failure mode the tool would prevent, not just the tool.

## Code of conduct

See [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). Contributor Covenant 2.1.
