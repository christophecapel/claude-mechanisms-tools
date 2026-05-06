#!/usr/bin/env python3
"""Audit which Bash commands required manual approval in Claude Code sessions.

Usage:
  audit-permissions.py                    # since the last run (default)
  audit-permissions.py --auto-stop-hook   # Stop-hook mode: silent unless LOW findings
  audit-permissions.py --latest-session   # only the most recently modified session
  audit-permissions.py --all-recent       # all sessions from last 24h
  audit-permissions.py --since 2026-04-10 # all sessions since date
  audit-permissions.py --days 7           # last N days
  audit-permissions.py <session-id>       # specific session
  audit-permissions.py --help             # show this help

Default mode reads ~/.claude/state/press1-check.json for `last_run_ts` and
audits all sessions modified after that timestamp across ALL project
directories under ~/.claude/projects/. On completion the state file is
updated. If the state file is missing (first run on this machine), falls
back to the last 3 days.

`--auto-stop-hook` is the recurring path wired into the Claude Code Stop
hook chain: 6-hour cooldown, silent when there's nothing actionable, and
when LOW-risk additions are suggested it writes a pending summary to
~/.claude/hooks-state/press1-check-pending.json so the next session-start
hook can surface a one-line nudge.
"""

import argparse
import calendar
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
STATE_DIR = Path.home() / ".claude" / "state"
STATE_FILE = STATE_DIR / "press1-check.json"
HOOKS_STATE_DIR = Path.home() / ".claude" / "hooks-state"
PENDING_FILE = HOOKS_STATE_DIR / "press1-check-pending.json"

# Cooldown for --auto-stop-hook: don't re-audit if last run was within this
# window. Sessions chain rapidly; running on every Stop event would spam the
# state file and cost CPU for no signal. 6h covers a typical work block.
AUTO_STOP_COOLDOWN_SECONDS = 6 * 3600
AUTO_STOP_BOOTSTRAP_DAYS = 3

# --- Risk classification ---

# HIGH: destructive or hard to reverse. Keep gated.
HIGH_RISK_PATTERNS = [
    "rm ", "rm\t", "rmdir",
    "git reset", "git clean", "git push --force", "git push -f",
    "git branch -D", "git branch -d",
    "git checkout -- ", "git restore",
    "chmod", "chown",
    "kill", "pkill",
    "sudo",
    "curl.*POST", "curl.*PUT", "curl.*DELETE",
    "gh issue close", "gh pr close", "gh pr merge",
    "DROP ", "DELETE FROM", "TRUNCATE",
]

# MEDIUM: side effects outside local repo. Review before allowing.
MEDIUM_RISK_PATTERNS = [
    "gh release", "gh pr create", "gh issue create",
    "git push",
    "curl", "wget",
    "open ",  # opens apps/URLs
    "ssh", "scp", "rsync",
    "pip install", "npm install", "brew install",
    "docker", "kubectl",
]

# LOW: read-only or local-only. Safe to auto-approve.
# Everything not matching HIGH or MEDIUM is LOW by default.


def classify_risk(command: str) -> str:
    """Classify a command's risk level."""
    cmd_lower = command.lower()
    for pattern in HIGH_RISK_PATTERNS:
        if pattern.lower() in cmd_lower:
            return "HIGH"
    for pattern in MEDIUM_RISK_PATTERNS:
        if pattern.lower() in cmd_lower:
            return "MEDIUM"
    return "LOW"


RISK_LABELS = {
    "HIGH": "\033[91mHIGH\033[0m",    # red
    "MEDIUM": "\033[93mMEDIUM\033[0m",  # yellow
    "LOW": "\033[92mLOW\033[0m",        # green
}

RISK_ADVICE = {
    "HIGH": "KEEP GATED -- destructive or hard to reverse",
    "MEDIUM": "REVIEW -- has side effects outside local repo",
    "LOW": "SAFE TO ADD -- read-only or local-only",
}

RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def find_sessions_dir() -> Path:
    """Auto-detect the Claude Code sessions directory.

    Strategy:
    1. Encode CWD the way Claude Code does (/ -> -) and check for that project dir.
    2. Fall back to the project dir with the most recently modified .jsonl file.
    """
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        print(f"Claude Code projects directory not found: {projects_dir}")
        sys.exit(1)

    # Try CWD-based encoding first
    cwd = str(Path.cwd())
    encoded = cwd.replace("/", "-")
    candidate = projects_dir / encoded
    if candidate.exists() and any(candidate.glob("*.jsonl")):
        return candidate

    # Fallback: find project dir with most recent session
    best = None
    best_mtime = 0
    for d in projects_dir.iterdir():
        if not d.is_dir():
            continue
        for f in d.glob("*.jsonl"):
            mt = f.stat().st_mtime
            if mt > best_mtime:
                best_mtime = mt
                best = d
            break
    if best:
        return best

    print("No Claude Code sessions found.")
    sys.exit(1)


def find_all_sessions_dirs() -> list[Path]:
    """Return all project dirs under ~/.claude/projects that contain sessions."""
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        print(f"Claude Code projects directory not found: {projects_dir}")
        sys.exit(1)
    dirs = []
    for d in projects_dir.iterdir():
        if not d.is_dir():
            continue
        if any(d.rglob("*.jsonl")):
            dirs.append(d)
    return dirs


def load_allow_prefixes() -> list[str]:
    """Extract Bash allow prefixes from settings.json."""
    try:
        settings = json.loads(SETTINGS_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    prefixes = []
    for rule in settings.get("permissions", {}).get("allow", []):
        if rule.startswith("Bash(") and rule.endswith(")"):
            pattern = rule[5:-1]  # strip Bash( and )
            if pattern.endswith(":*"):
                pattern = pattern[:-2]  # strip :*
            elif pattern.endswith("*"):
                pattern = pattern[:-1]  # strip *
            prefixes.append(pattern)
    return prefixes


def collect_jsonls(sessions_dir: Path) -> list[Path]:
    """Collect all main + subagent JSONL files under one project dir."""
    jsonl_files = list(sessions_dir.glob("*.jsonl"))
    for d in sessions_dir.iterdir():
        if d.is_dir():
            sub_dir = d / "subagents"
            if sub_dir.exists():
                jsonl_files.extend(sub_dir.glob("*.jsonl"))
    return jsonl_files


def find_sessions(session_id: str = None, all_recent: bool = False,
                  since: str = None, days: int = None,
                  latest_session: bool = False) -> list[Path]:
    """Find session JSONL files to audit across ALL project directories.

    Default mode (no flags) audits since the last recorded run from
    ~/.claude/state/press1-check.json, falling back to the last 3 days
    when state is missing.
    """
    if session_id:
        results = []
        for sdir in find_all_sessions_dirs():
            path = sdir / f"{session_id}.jsonl"
            if path.exists():
                results.append(path)
            else:
                results.extend(sdir.glob(f"{session_id}*.jsonl"))
        if not results:
            print(f"Session not found: {session_id}")
            sys.exit(1)
        for r in list(results):
            sub_dir = r.parent / r.stem / "subagents"
            if sub_dir.exists():
                results.extend(sub_dir.glob("*.jsonl"))
        return results

    if latest_session:
        sessions_dir = find_sessions_dir()
        jsonl_files = sorted(collect_jsonls(sessions_dir),
                             key=lambda p: p.stat().st_mtime, reverse=True)
        main_files = [f for f in jsonl_files if "/subagents/" not in str(f)]
        if main_files:
            latest = main_files[0]
            results = [latest]
            sub_dir = sessions_dir / latest.stem / "subagents"
            if sub_dir.exists():
                results.extend(sub_dir.glob("*.jsonl"))
            return results
        print("No sessions found.")
        sys.exit(1)

    # Default + --since + --all-recent + --days: scan ALL project dirs.
    all_jsonls = []
    for sdir in find_all_sessions_dirs():
        all_jsonls.extend(collect_jsonls(sdir))
    all_jsonls = sorted(all_jsonls, key=lambda p: p.stat().st_mtime, reverse=True)

    if since:
        cutoff = datetime.strptime(since, "%Y-%m-%d").timestamp()
    elif all_recent:
        cutoff = time.time() - 86400
    elif days is not None:
        cutoff = time.time() - days * 86400
    else:
        # Default: since the last recorded run. Bootstrap to 3 days when state
        # is missing so first-run on a new machine still produces useful output.
        state = read_state()
        last_run_ts = state.get("last_run_ts") if state else None
        if last_run_ts:
            cutoff = _parse_iso_utc(last_run_ts)
            if cutoff == float("-inf"):
                cutoff = time.time() - AUTO_STOP_BOOTSTRAP_DAYS * 86400
        else:
            cutoff = time.time() - AUTO_STOP_BOOTSTRAP_DAYS * 86400

    return [f for f in all_jsonls if f.stat().st_mtime > cutoff]


# --- State (since-last-run + auto-stop-hook cooldown) ---

def _parse_iso_utc(ts: str) -> float:
    """Parse our state ISO-8601-Z timestamp into a UTC Unix timestamp.

    `datetime.strptime().timestamp()` interprets the result as LOCAL time,
    which silently shifts UTC strings by the local tz offset. Use
    `calendar.timegm` on the time tuple to keep the value in UTC. Returns
    -inf on parse failure so cooldown checks fail open.
    """
    try:
        dt = datetime.strptime(ts.rstrip("Z"), "%Y-%m-%dT%H:%M:%S")
    except (ValueError, AttributeError):
        return float("-inf")
    return calendar.timegm(dt.timetuple())


def read_state() -> dict:
    """Return state file content or {} when missing/corrupt."""
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def write_state(payload: dict) -> None:
    """Atomic state file update."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(STATE_FILE)


def write_pending_summary(summary: dict) -> None:
    """Drop a one-shot summary file for the next session-start hook."""
    HOOKS_STATE_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps(summary, indent=2))


def cooldown_active(state: dict, now: float = None) -> bool:
    """True when the last run was within AUTO_STOP_COOLDOWN_SECONDS."""
    last_run_ts = state.get("last_run_ts") if state else None
    if not last_run_ts:
        return False
    last = _parse_iso_utc(last_run_ts)
    if last == float("-inf"):
        return False
    now = now if now is not None else time.time()
    return (now - last) < AUTO_STOP_COOLDOWN_SECONDS


def is_subagent(path: Path) -> bool:
    """Check if a session file is from a subagent."""
    return "/subagents/" in str(path) or "\\subagents\\" in str(path)


def session_display_name(path: Path) -> str:
    """Get a display name for a session file."""
    if is_subagent(path):
        parent_id = path.parent.parent.name[:12]
        return f"{parent_id} [subagent: {path.stem[:16]}]"
    return path.stem


def audit_session(path: Path, prefixes: list[str]) -> list[dict]:
    """Find Bash commands that aren't covered by the allow list."""
    needs_approval = []
    subagent = is_subagent(path)

    with open(path) as f:
        for line in f:
            try:
                d = json.loads(line.strip())
            except (json.JSONDecodeError, ValueError):
                continue

            if d.get("type") != "assistant":
                continue

            msg = d.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "Bash":
                    cmd = block.get("input", {}).get("command", "")
                    if not cmd:
                        continue
                    cmd_stripped = cmd.strip()
                    matched = any(cmd_stripped.startswith(p) for p in prefixes)
                    if not matched:
                        risk = classify_risk(cmd_stripped)
                        needs_approval.append({
                            "command": cmd_stripped[:200],
                            "session": session_display_name(path),
                            "risk": risk,
                            "subagent": subagent,
                        })

    return needs_approval


def suggest_rules(commands: list[dict]) -> list[str]:
    """Suggest allow rules for unmatched commands."""
    suggestions = {}
    for item in commands:
        cmd = item["command"]
        first_word = cmd.split()[0] if cmd.split() else cmd
        # Handle env var prefixes like GIT_DIR=...
        if "=" in first_word and not first_word.startswith("-"):
            rule = f'Bash({first_word.split("=")[0]}=*)'
        else:
            rule = f'Bash({first_word}:*)'
        # Keep the highest risk level for each suggestion
        if rule not in suggestions or RISK_ORDER[item["risk"]] > RISK_ORDER[suggestions[rule]]:
            suggestions[rule] = item["risk"]
    return sorted(suggestions.items(), key=lambda x: RISK_ORDER[x[1]])


def main():
    parser = argparse.ArgumentParser(
        description="Audit which Bash commands required manual approval in Claude Code sessions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  %(prog)s                         since the last run, all project dirs (default)
  %(prog)s --days 7                last 7 days
  %(prog)s --latest-session        only the single most recent session
  %(prog)s --all-recent            all sessions from last 24h
  %(prog)s --since 2026-04-10      all sessions since April 10
  %(prog)s abc123                   specific session (prefix match OK)""",
    )
    parser.add_argument("session_id", nargs="?", help="specific session ID (prefix match OK)")
    parser.add_argument("--all-recent", action="store_true", help="audit all sessions from the last 24h")
    parser.add_argument("--since", metavar="YYYY-MM-DD", help="audit all sessions since this date")
    parser.add_argument("--days", type=int, help="audit sessions from the last N days")
    parser.add_argument("--latest-session", action="store_true",
                        help="audit only the single most recent session (old default)")
    parser.add_argument("--auto-stop-hook", action="store_true",
                        help="Stop-hook mode: 6h cooldown, silent on no findings, "
                             "writes pending summary on LOW additions")
    args = parser.parse_args()

    prefixes = load_allow_prefixes()
    if not prefixes and not args.auto_stop_hook:
        print("Warning: no allow prefixes found in settings.json")

    state = read_state()

    # --auto-stop-hook: cooldown gate. Silent exit when nothing to do.
    if args.auto_stop_hook and cooldown_active(state):
        return

    sessions = find_sessions(args.session_id, args.all_recent, args.since,
                             args.days, args.latest_session)
    all_needs = []

    current_session = None
    for path in sessions:
        needs = audit_session(path, prefixes)
        if needs:
            display = session_display_name(path)
            main_id = path.stem if not is_subagent(path) else path.parent.parent.name
            if main_id != current_session:
                current_session = main_id
                if not args.auto_stop_hook:
                    print(f"\n{'='*60}")
                    print(f"Session: {main_id}")
                    print(f"{'='*60}")
            for item in needs:
                if not args.auto_stop_hook:
                    label = RISK_LABELS[item["risk"]]
                    tag = " [subagent]" if item["subagent"] else ""
                    print(f"  [{label}]{tag} {item['command'][:120]}")
            all_needs.extend(needs)

    by_risk = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for item in all_needs:
        by_risk[item["risk"]] += 1

    is_interactive = not args.auto_stop_hook
    now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    findings_summary = (
        f"{by_risk['LOW']} low, {by_risk['MEDIUM']} medium, {by_risk['HIGH']} high"
    )

    if args.auto_stop_hook:
        # Only surface when LOW additions are worth pasting in. MEDIUM/HIGH
        # are intentionally gated, so they're not actionable background-fires.
        suggestions = suggest_rules(all_needs)
        low_suggestions = [(r, k) for r, k in suggestions if k == "LOW"]
        if low_suggestions:
            write_pending_summary({
                "ts": now_iso,
                "low_count": by_risk["LOW"],
                "medium_count": by_risk["MEDIUM"],
                "high_count": by_risk["HIGH"],
                "low_suggestions": [r for r, _ in low_suggestions],
                "summary": findings_summary,
            })
            write_state({
                "last_run_ts": now_iso,
                "last_run_mode": "auto-stop-hook",
                "last_run_findings": findings_summary,
            })
        return

    if not all_needs:
        print("All Bash commands were covered by the allow list.")
        if is_interactive:
            write_state({
                "last_run_ts": now_iso,
                "last_run_mode": "interactive",
                "last_run_findings": "0 low, 0 medium, 0 high",
            })
        return

    print(f"\n{'='*60}")
    summary_line = f"SUMMARY: {findings_summary}"
    subagent_count = sum(1 for item in all_needs if item["subagent"])
    if subagent_count:
        summary_line += f" ({subagent_count} from subagents)"
    print(summary_line)
    print(f"{'='*60}")

    suggestions = suggest_rules(all_needs)
    print(f"\nSUGGESTED ADDITIONS to ~/.claude/settings.json:")
    print(f"(sorted by risk -- add LOW freely, review MEDIUM, skip HIGH)\n")
    for rule, risk in suggestions:
        label = RISK_LABELS[risk]
        advice = RISK_ADVICE[risk]
        print(f'  [{label}] "{rule}",  -- {advice}')

    if is_interactive:
        write_state({
            "last_run_ts": now_iso,
            "last_run_mode": "interactive",
            "last_run_findings": findings_summary,
        })


if __name__ == "__main__":
    main()
