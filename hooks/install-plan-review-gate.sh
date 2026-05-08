#!/usr/bin/env bash
# Idempotent installer for the plan-review-gate PreToolUse hooks.
#
# Wires two PreToolUse entries in ~/.claude/settings.json:
#   1. matcher "ExitPlanMode" — Phase 1: validates plan structure before approval
#   2. matcher "Bash"         — Phase 2: validates PR diff vs plan at `gh pr create` time
#
# Re-runs are safe — checks for existing entries pointing at this script before
# adding either one. If both are found, exits without changes.
#
# Implements:
#   Mechanism #14 — Trace the cascade
#   Mechanism #16 — Smallest shippable first
#   Mechanism #17 — Structural checks use hooks, not behavioral rules
#     https://github.com/christophecapel/claude-mechanisms

set -euo pipefail

SETTINGS="${HOME}/.claude/settings.json"
HOOK_PATH="$(cd "$(dirname "$0")" && pwd)/plan-review-gate.py"

if [[ ! -f "${SETTINGS}" ]]; then
    mkdir -p "$(dirname "${SETTINGS}")"
    echo '{"hooks":{"PreToolUse":[]}}' > "${SETTINGS}"
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found in PATH. plan-review-gate needs Python 3.8+." >&2
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq not found in PATH. Install jq (https://jqlang.github.io/jq/) and re-run." >&2
    exit 1
fi

install_phase() {
    local matcher="$1"
    local command="$2"
    local label="$3"

    local already
    already="$(jq --arg matcher "${matcher}" --arg path "${HOOK_PATH}" \
        '.hooks.PreToolUse // [] | map(select(.matcher == $matcher) | .hooks // [] | map(.command) | map(select(contains($path)))) | flatten | length' \
        "${SETTINGS}")"

    if [[ "${already}" -gt 0 ]]; then
        echo "OK: ${label} already wired in ${SETTINGS}."
        return 0
    fi

    local tmp
    tmp="$(mktemp)"
    jq --arg matcher "${matcher}" --arg cmd "${command}" \
        '.hooks //= {} | .hooks.PreToolUse //= [] |
         .hooks.PreToolUse += [{matcher: $matcher, hooks: [{type: "command", command: $cmd}]}]' \
        "${SETTINGS}" > "${tmp}"
    mv "${tmp}" "${SETTINGS}"

    echo "OK: ${label} added to ${SETTINGS}."
    echo "    matcher: ${matcher}"
    echo "    command: ${command}"
}

install_phase "ExitPlanMode" "python3 ${HOOK_PATH}" "plan-review-gate Phase 1 (ExitPlanMode)"
install_phase "Bash"         "python3 ${HOOK_PATH} --mode=pre-pr" "plan-review-gate Phase 2 (Bash / gh pr create)"

echo
echo "Both phases installed. Next session start picks them up automatically."
echo "The gate is silent on pass — you'll only see output when a plan is missing"
echo "required sections (Phase 1) or a PR diff misses planned files (Phase 2)."
