#!/usr/bin/env bash
# Idempotent installer for the git-workflow-gate PreToolUse + PostToolUse + SessionStart hooks.
#
# Wires three entries in ~/.claude/settings.json:
#   PreToolUse   on Bash matcher — runs gate with --pre-tool-use mode
#                  (Gate 0 cd-chain, Gate 1 pre-commit, Gate 2 pre-push, Gate 3 pre-checkout)
#   PostToolUse  on Bash matcher — runs gate with --post-tool-use mode
#                  (Gate 1b post-commit info, Gate 5 post-push PR-existence)
#   SessionStart (no matcher)    — runs gate with --session-start mode
#                  (Gate 6 stale-branches digest)
#
# Re-runs are safe — checks for an existing entry pointing at this script
# before adding any of them.
#
# Implements:
#   Mechanism #1  — Discover and derive
#   Mechanism #11 — One branch, one scope
#   Mechanism #17 — Structural checks use hooks
#     https://github.com/christophecapel/claude-mechanisms

set -euo pipefail

SETTINGS="${HOME}/.claude/settings.json"
HOOK_PATH="$(cd "$(dirname "$0")" && pwd)/git-workflow-gate.py"

if [[ ! -f "${SETTINGS}" ]]; then
    mkdir -p "$(dirname "${SETTINGS}")"
    echo '{"hooks":{"PreToolUse":[]}}' > "${SETTINGS}"
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found in PATH. git-workflow-gate needs Python 3.8+." >&2
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq not found in PATH. Install jq (https://jqlang.github.io/jq/) and re-run." >&2
    exit 1
fi

install_phase() {
    local event="$1"     # PreToolUse | PostToolUse
    local matcher="$2"   # Bash
    local command="$3"
    local label="$4"

    local already
    already="$(jq --arg event "${event}" --arg matcher "${matcher}" --arg path "${HOOK_PATH}" \
        '.hooks[$event] // [] | map(select(.matcher == $matcher) | .hooks // [] | map(.command) | map(select(contains($path)))) | flatten | length' \
        "${SETTINGS}")"

    if [[ "${already}" -gt 0 ]]; then
        echo "OK: ${label} already wired in ${SETTINGS}."
        return 0
    fi

    local tmp
    tmp="$(mktemp)"
    jq --arg event "${event}" --arg matcher "${matcher}" --arg cmd "${command}" \
        '.hooks //= {} | .hooks[$event] //= [] |
         .hooks[$event] += [{matcher: $matcher, hooks: [{type: "command", command: $cmd}]}]' \
        "${SETTINGS}" > "${tmp}"
    mv "${tmp}" "${SETTINGS}"

    echo "OK: ${label} added to ${SETTINGS}."
    echo "    event:   ${event}"
    echo "    matcher: ${matcher}"
    echo "    command: ${command}"
}

install_session_start() {
    # SessionStart hooks have no matcher — different jq shape.
    local command="$1"
    local label="$2"

    local already
    already="$(jq --arg path "${HOOK_PATH}" \
        '.hooks.SessionStart // [] | map(.hooks // [] | map(.command) | map(select(contains($path)))) | flatten | length' \
        "${SETTINGS}")"

    if [[ "${already}" -gt 0 ]]; then
        echo "OK: ${label} already wired in ${SETTINGS}."
        return 0
    fi

    local tmp
    tmp="$(mktemp)"
    jq --arg cmd "${command}" \
        '.hooks //= {} | .hooks.SessionStart //= [] |
         .hooks.SessionStart += [{hooks: [{type: "command", command: $cmd}]}]' \
        "${SETTINGS}" > "${tmp}"
    mv "${tmp}" "${SETTINGS}"

    echo "OK: ${label} added to ${SETTINGS}."
    echo "    event:   SessionStart"
    echo "    command: ${command}"
}

install_phase        "PreToolUse"  "Bash" "python3 ${HOOK_PATH} --pre-tool-use"  "git-workflow-gate (PreToolUse)"
install_phase        "PostToolUse" "Bash" "python3 ${HOOK_PATH} --post-tool-use" "git-workflow-gate (PostToolUse)"
install_session_start                     "python3 ${HOOK_PATH} --session-start" "git-workflow-gate (SessionStart)"

echo
echo "All three phases installed. Next session start picks them up automatically."
echo "The gate is silent on pass — you'll only see output when:"
echo "  - You try to chain 'cd <dir> && git ...' (deny)"
echo "  - You try to commit on main (deny)"
echo "  - Commit message format is invalid (deny)"
echo "  - You're behind origin/main (deny — needs rebase)"
echo "  - You try to push to a branch with a merged PR (deny — frozen scope)"
echo "  - You try to switch branches with a dirty tree (deny — commit/stash first)"
echo "  - You force-push (warn)"
echo "  - You commit but haven't pushed yet (info nag)"
echo "  - You push but no PR exists (info nag)"
echo "  - Session starts in a repo with merged branches awaiting cleanup (info nag)"
echo
echo "Per-repo override: drop a .commit-types file at the repo root with one"
echo "type per line to extend or replace the default ALLOWED_COMMIT_TYPES."
