#!/usr/bin/env bash
# Idempotent installer for the worktree-edit-gate PreToolUse hook.
#
# Adds an entry to ~/.claude/settings.json under hooks.PreToolUse that runs
# worktree-edit-gate.py on Edit | Write | MultiEdit | NotebookEdit calls.
#
# Re-runs are safe — checks for an existing entry pointing at the script
# before adding. If found, exits without changes.
#
# Implements:
#   Mechanism #17 — Structural checks use hooks, not behavioral rules
#     https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/17-structural-checks-use-hooks.md

set -euo pipefail

SETTINGS="${HOME}/.claude/settings.json"
HOOK_PATH="$(cd "$(dirname "$0")" && pwd)/worktree-edit-gate.py"
MATCHER="Edit|Write|MultiEdit|NotebookEdit"

if [[ ! -f "${SETTINGS}" ]]; then
    mkdir -p "$(dirname "${SETTINGS}")"
    echo '{"hooks":{"PreToolUse":[]}}' > "${SETTINGS}"
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found in PATH. The worktree-edit-gate hook needs Python 3.8+." >&2
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq not found in PATH. Install jq (https://jqlang.github.io/jq/) and re-run." >&2
    exit 1
fi

# Check if the hook is already wired (matcher + command pointing at our script)
ALREADY_INSTALLED="$(jq --arg matcher "${MATCHER}" --arg path "${HOOK_PATH}" \
    '.hooks.PreToolUse // [] | map(select(.matcher == $matcher) | .hooks // [] | map(.command) | map(select(contains($path)))) | flatten | length' \
    "${SETTINGS}")"

if [[ "${ALREADY_INSTALLED}" -gt 0 ]]; then
    echo "OK: worktree-edit-gate already wired in ${SETTINGS}."
    exit 0
fi

# Add the hook entry
TMP="$(mktemp)"
jq --arg matcher "${MATCHER}" --arg cmd "python3 ${HOOK_PATH}" \
    '.hooks //= {} | .hooks.PreToolUse //= [] |
     .hooks.PreToolUse += [{matcher: $matcher, hooks: [{type: "command", command: $cmd}]}]' \
    "${SETTINGS}" > "${TMP}"
mv "${TMP}" "${SETTINGS}"

echo "OK: worktree-edit-gate added to ${SETTINGS}."
echo "    matcher: ${MATCHER}"
echo "    command: python3 ${HOOK_PATH}"
echo
echo "Next session start picks it up automatically. The hook is silent on pass —"
echo "you'll only see output when an absolute-path edit would land outside the active worktree."
