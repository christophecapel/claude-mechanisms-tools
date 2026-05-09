#!/usr/bin/env bash
# Idempotent installer for the feedback-memory-gate PostToolUse hook.
#
# Adds an entry to ~/.claude/settings.json under hooks.PostToolUse that runs
# feedback-memory-gate.py on Write tool calls. Fast-paths to silent on
# non-feedback-memory writes; emits an additionalContext warning when a
# feedback memory describing a bug is written without a Linear reference.
#
# Re-runs are safe — checks for an existing entry pointing at the script
# before adding. If found, exits without changes.
#
# Implements:
#   Mechanism #17 — Structural checks use hooks, not behavioral rules
#   Mechanism #5  — Deferred work needs persistent markers (Linear ref IS the marker)
#     https://github.com/christophecapel/claude-mechanisms

set -euo pipefail

SETTINGS="${HOME}/.claude/settings.json"
HOOK_PATH="$(cd "$(dirname "$0")" && pwd)/feedback-memory-gate.py"
MATCHER="Write"

if [[ ! -f "${SETTINGS}" ]]; then
    mkdir -p "$(dirname "${SETTINGS}")"
    echo '{"hooks":{"PostToolUse":[]}}' > "${SETTINGS}"
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found in PATH. feedback-memory-gate needs Python 3.8+." >&2
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq not found in PATH. Install jq (https://jqlang.github.io/jq/) and re-run." >&2
    exit 1
fi

# Check if the hook is already wired
ALREADY_INSTALLED="$(jq --arg matcher "${MATCHER}" --arg path "${HOOK_PATH}" \
    '.hooks.PostToolUse // [] | map(select(.matcher == $matcher) | .hooks // [] | map(.command) | map(select(contains($path)))) | flatten | length' \
    "${SETTINGS}")"

if [[ "${ALREADY_INSTALLED}" -gt 0 ]]; then
    echo "OK: feedback-memory-gate already wired in ${SETTINGS}."
    exit 0
fi

# Add the hook entry
TMP="$(mktemp)"
jq --arg matcher "${MATCHER}" --arg cmd "python3 ${HOOK_PATH}" \
    '.hooks //= {} | .hooks.PostToolUse //= [] |
     .hooks.PostToolUse += [{matcher: $matcher, hooks: [{type: "command", command: $cmd}]}]' \
    "${SETTINGS}" > "${TMP}"
mv "${TMP}" "${SETTINGS}"

echo "OK: feedback-memory-gate added to ${SETTINGS}."
echo "    matcher: ${MATCHER} (PostToolUse)"
echo "    command: python3 ${HOOK_PATH}"
echo
echo "Next session start picks it up automatically. The hook is silent on pass —"
echo "you'll only see output when a feedback memory describes a bug but has no"
echo "**Linear:** CC-NN reference (a nudge, not a hard block)."
