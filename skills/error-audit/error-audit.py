#!/usr/bin/env python3
"""Audit errors across Claude Code session transcripts.

Scans JSONL transcripts under ~/.claude/projects/, classifies errors into 7
classes, normalises signatures, clusters by class + signature, and surfaces
top clusters with suggested remediation tiers.

Suppressions (claude-memory/error-audit-suppressions.md) mark known
"working-as-designed" cluster_keys as suppressed. Default --human output
hides them; --show-suppressed re-includes them; --json always includes
them with a `suppressed: true|false` field.

Usage:
    error-audit.py                       # all sessions, human output
    error-audit.py --since 30            # last 30 days
    error-audit.py --json                # JSON for health-check issue embed
    error-audit.py --top 20              # top N clusters (default 20)
    error-audit.py --projects-dir <path> # override (default ~/.claude/projects)
    error-audit.py --show-suppressed     # show suppressed clusters in human output
    error-audit.py --no-suppressions     # ignore suppressions file entirely

Exit codes:
    0  scanner ran, clusters returned (possibly zero)
    2  usage error

Classes detected:
    tool_error         is_error:true on a tool result (excluding denials)
    validation_error   <tool_use_error>InputValidationError
    permission_denial  "The user doesn't want to proceed"
    hook_block         attachment.type == hook_failure (or Stop/PreToolUse blocker)
    bash_fail          attachment.exitCode != 0 (Bash)
    retry_storm        >=3 consecutive overloaded_error records in one session
    read_before_edit   "File has not been read yet. Read it first"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"
# Default suppressions file lives next to this script in the toolkit.
# Override with --suppressions-path or CLAUDE_ERROR_AUDIT_SUPPRESSIONS env var.
import os as _os
_env_supp = _os.environ.get("CLAUDE_ERROR_AUDIT_SUPPRESSIONS", "").strip()
if _env_supp:
    DEFAULT_SUPPRESSIONS_PATH = Path(_env_supp).expanduser()
else:
    DEFAULT_SUPPRESSIONS_PATH = Path(__file__).resolve().parent / "suppressions.md"
TOP_N_DEFAULT = 20
RETRY_STORM_THRESHOLD = 3


@dataclass
class ErrorEvent:
    cls: str
    tool_name: str
    signature: str
    session: str
    cwd: str = ""
    ts: str = ""
    raw: str = ""


@dataclass
class Cluster:
    cls: str
    tool_name: str
    signature: str
    count: int = 0
    sessions: list[str] = field(default_factory=list)
    example_cwd: str = ""
    example_ts: str = ""
    example_raw: str = ""
    suppressed: bool = False
    suppression_reason: str = ""

    @property
    def key(self) -> str:
        return f"{self.cls}:{self.tool_name}:{self.signature[:60]}"


# --- Normalisation ---

_ID_PATTERNS = [
    re.compile(r"toolu_[A-Za-z0-9]+"),
    re.compile(r"msg_[A-Za-z0-9]+"),
    re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
    re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z?"),
    re.compile(r"/Users/[^/\s]+"),
    re.compile(r"/tmp/[^\s]+"),
    re.compile(r":\d+:\d+"),
    re.compile(r"\blines?\s+\d+(-\d+)?\b", re.IGNORECASE),
    re.compile(r"\b0x[0-9a-fA-F]+\b"),
]


def normalise(text: str, limit: int = 80) -> str:
    s = text or ""
    for pat in _ID_PATTERNS:
        s = pat.sub("<X>", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


# --- Suppressions ---

_SUPPRESSION_FENCE_RE = re.compile(r"```\s*\n(.*?)\n```", re.DOTALL)


def load_suppressions(path: Path = DEFAULT_SUPPRESSIONS_PATH) -> dict[str, str]:
    """Parse error-audit-suppressions.md.

    Format: cluster_keys inside fenced code blocks. Each line is either:
      - a comment starting with `#`
      - a cluster_key, optionally followed by tab or 2+ spaces and a reason

    Returns a dict of cluster_key -> reason (empty string if no reason given).
    Missing file returns empty dict (no suppressions active).
    """
    try:
        content = path.read_text()
    except (OSError, FileNotFoundError):
        return {}
    suppressions: dict[str, str] = {}
    for match in _SUPPRESSION_FENCE_RE.finditer(content):
        for raw_line in match.group(1).splitlines():
            line = raw_line.rstrip()
            if not line or line.lstrip().startswith("#"):
                continue
            parts = re.split(r"\t+|\s{2,}", line, maxsplit=1)
            key = parts[0].strip()
            reason = parts[1].strip() if len(parts) > 1 else ""
            if key:
                suppressions[key] = reason
    return suppressions


def apply_suppressions(clusters: list["Cluster"], suppressions: dict[str, str]) -> None:
    """Mark clusters whose key matches a suppression entry."""
    for c in clusters:
        reason = suppressions.get(c.key)
        if reason is not None:
            c.suppressed = True
            c.suppression_reason = reason


# --- Classification helpers ---

DENIAL_PREFIX = "The user doesn't want to proceed"
READ_BEFORE_EDIT = "File has not been read yet"
VALIDATION_MARKER = "InputValidationError"


def _iter_records(path: Path):
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        return


def _extract_tool_name_from_prior_use(prior_tool_uses: dict, tool_use_id: str) -> str:
    return prior_tool_uses.get(tool_use_id, "unknown")


def _extract_content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict):
                parts.append(p.get("text") or p.get("content") or "")
            else:
                parts.append(str(p))
        return " ".join(str(x) for x in parts)
    return str(content or "")


def classify_session(path: Path) -> list[ErrorEvent]:
    events: list[ErrorEvent] = []
    session = path.stem
    prior_tool_uses: dict[str, str] = {}
    cwd = ""
    retry_counter = 0
    retry_tool = ""
    retry_day = ""
    bash_command_by_id: dict[str, str] = {}

    for rec in _iter_records(path):
        if not isinstance(rec, dict):
            continue

        if "cwd" in rec and isinstance(rec.get("cwd"), str):
            cwd = rec["cwd"]
        ts = rec.get("timestamp", "")

        # Track tool_use assistant blocks to map tool_use_id → tool name
        rtype = rec.get("type")
        if rtype == "assistant":
            for block in (rec.get("message", {}) or {}).get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tid = block.get("id") or block.get("tool_use_id")
                    name = block.get("name", "unknown")
                    if tid:
                        prior_tool_uses[tid] = name
                    if name == "Bash":
                        cmd = (block.get("input") or {}).get("command", "")
                        if tid:
                            bash_command_by_id[tid] = cmd

        # Retry-storm detection via overloaded_error
        if rtype == "system":
            sub = rec.get("subtype") or ""
            err = rec.get("error") or {}
            err_inner = err.get("error") or {}
            if sub == "api_error" and err_inner.get("type") == "overloaded_error":
                day = (ts or "")[:10]
                tool = err.get("tool_name") or "unknown"
                if day == retry_day and tool == retry_tool:
                    retry_counter += 1
                else:
                    retry_day, retry_tool, retry_counter = day, tool, 1
                if retry_counter == RETRY_STORM_THRESHOLD:
                    events.append(ErrorEvent(
                        cls="retry_storm",
                        tool_name=tool,
                        signature=f"{day}:{tool}",
                        session=session,
                        cwd=cwd,
                        ts=ts,
                        raw=f"{RETRY_STORM_THRESHOLD}+ overloaded_error in one day",
                    ))
                continue

        # Hook failures surface via attachment records (type attachment, hook_failure)
        if rtype == "attachment":
            att = rec.get("attachment") or {}
            atype = att.get("type")
            if atype == "hook_failure":
                hook_name = att.get("hookName", "unknown")
                stderr = att.get("stderr", "") or att.get("stdout", "")
                sig = normalise(stderr or att.get("command", ""))
                events.append(ErrorEvent(
                    cls="hook_block",
                    tool_name=hook_name,
                    signature=sig or "hook_failure",
                    session=session,
                    cwd=cwd,
                    ts=ts,
                    raw=(stderr or "")[:200],
                ))
                continue
            # Bash non-zero exit
            exit_code = att.get("exitCode")
            command = att.get("command", "")
            if isinstance(exit_code, int) and exit_code != 0:
                first_word = (command.strip().split() or ["unknown"])[0]
                if "=" in first_word and not first_word.startswith("-"):
                    first_word = first_word.split("=", 1)[0] + "="
                stderr = att.get("stderr", "")[:200]
                events.append(ErrorEvent(
                    cls="bash_fail",
                    tool_name=first_word,
                    signature=normalise(stderr or f"exit={exit_code}"),
                    session=session,
                    cwd=cwd,
                    ts=ts,
                    raw=(stderr or command)[:200],
                ))
                continue

        # Tool errors arrive as user-role messages with tool_result blocks
        if rtype == "user":
            msg = rec.get("message") or {}
            content_blocks = msg.get("content") or []
            if not isinstance(content_blocks, list):
                continue
            for block in content_blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_result":
                    continue
                if not block.get("is_error"):
                    continue
                tid = block.get("tool_use_id", "")
                tool_name = prior_tool_uses.get(tid, "unknown")
                content_text = _extract_content_text(block.get("content"))

                if content_text.startswith(DENIAL_PREFIX):
                    cmd = bash_command_by_id.get(tid, "") if tool_name == "Bash" else ""
                    prefix = ""
                    if cmd:
                        first_word = (cmd.strip().split() or [""])[0]
                        prefix = first_word.split("=", 1)[0] + "=" if "=" in first_word else first_word
                    events.append(ErrorEvent(
                        cls="permission_denial",
                        tool_name=tool_name,
                        signature=prefix or tool_name,
                        session=session,
                        cwd=cwd,
                        ts=ts,
                        raw=content_text[:200],
                    ))
                    continue

                if VALIDATION_MARKER in content_text:
                    m = re.search(r"parameter `([^`]+)`", content_text)
                    param_issue = m.group(1) if m else "unknown-param"
                    events.append(ErrorEvent(
                        cls="validation_error",
                        tool_name=tool_name,
                        signature=f"{tool_name}:{param_issue}",
                        session=session,
                        cwd=cwd,
                        ts=ts,
                        raw=content_text[:200],
                    ))
                    continue

                if READ_BEFORE_EDIT in content_text:
                    events.append(ErrorEvent(
                        cls="read_before_edit",
                        tool_name=tool_name,
                        signature="read_before_edit",
                        session=session,
                        cwd=cwd,
                        ts=ts,
                        raw=content_text[:200],
                    ))
                    continue

                events.append(ErrorEvent(
                    cls="tool_error",
                    tool_name=tool_name,
                    signature=normalise(content_text),
                    session=session,
                    cwd=cwd,
                    ts=ts,
                    raw=content_text[:200],
                ))

    return events


# --- Clustering ---

def cluster_events(events: list[ErrorEvent]) -> list[Cluster]:
    buckets: dict[tuple[str, str, str], Cluster] = {}
    for e in events:
        key = (e.cls, e.tool_name, e.signature)
        c = buckets.get(key)
        if c is None:
            c = Cluster(cls=e.cls, tool_name=e.tool_name, signature=e.signature,
                        example_cwd=e.cwd, example_ts=e.ts, example_raw=e.raw)
            buckets[key] = c
        c.count += 1
        if e.session not in c.sessions and len(c.sessions) < 3:
            c.sessions.append(e.session)
    return sorted(buckets.values(), key=lambda x: x.count, reverse=True)


# --- Remediation tier suggestion ---

def suggest(cluster: Cluster) -> tuple[int, bool, str]:
    """Return (tier, auto_fixable, remediation_text)."""
    cls, tool, sig = cluster.cls, cluster.tool_name, cluster.signature
    if cls == "permission_denial":
        if tool == "Bash" and sig and sig != "Bash":
            return (1, False, f"Consider adding Bash({sig}:*) to ~/.claude/settings.json allow list (review first)")
        return (3, False, f"Recurring denial on {tool}; add feedback memory or CLAUDE.md line clarifying when NOT to use it")
    if cls == "bash_fail":
        return (2, False, f"Recurring Bash failure for '{tool}'; fix the caller or add a PreToolUse hook to catch earlier")
    if cls == "hook_block":
        return (2, False, f"Hook '{tool}' blocking repeatedly on same pattern; tune the hook or add specific exclusion")
    if cls == "validation_error":
        return (3, False, f"Repeated schema mistakes calling {tool}; add mechanism memory reminding of correct param types")
    if cls == "read_before_edit":
        return (3, False, "Pattern: Edit called before Read. Already covered by tool validation — monitor only")
    if cls == "retry_storm":
        return (3, False, f"API overload on {tool}; consider batching or spreading load")
    if cls == "tool_error":
        return (3, False, f"Recurring {tool} error; add behavioural memory covering the failure mode")
    return (3, False, "Unknown cluster type")


# --- Filtering ---

def session_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def find_transcripts(projects_dir: Path, since_days: int | None) -> list[Path]:
    files = list(projects_dir.glob("*/*.jsonl"))
    if since_days is None:
        return files
    cutoff = time.time() - since_days * 86400
    return [p for p in files if session_mtime(p) >= cutoff]


# --- Output ---

COLOR = {
    "red": "\033[91m", "yellow": "\033[93m", "green": "\033[92m",
    "cyan": "\033[96m", "dim": "\033[2m", "reset": "\033[0m",
}


def tier_colour(count: int) -> str:
    if count >= 10:
        return COLOR["red"]
    if count >= 3:
        return COLOR["yellow"]
    return COLOR["green"]


def print_human(clusters: list[Cluster], top: int, show_suppressed: bool = False) -> None:
    visible = clusters if show_suppressed else [c for c in clusters if not c.suppressed]
    if not visible:
        if clusters and not show_suppressed:
            print(f"No actionable errors. {sum(1 for c in clusters if c.suppressed)} suppressed clusters hidden (use --show-suppressed).")
        else:
            print("No errors found in the scanned window.")
        return

    total = sum(c.count for c in visible)
    by_cls: dict[str, int] = defaultdict(int)
    for c in visible:
        by_cls[c.cls] += c.count

    suppressed_count = sum(1 for c in clusters if c.suppressed)
    suppressed_events = sum(c.count for c in clusters if c.suppressed)

    print(f"\n{'=' * 72}")
    print(f"ERROR AUDIT  ·  {total} events  ·  {len(visible)} clusters"
          + (f"  ·  ({suppressed_count} suppressed = {suppressed_events} events hidden)" if suppressed_count and not show_suppressed else ""))
    print(f"{'=' * 72}")
    summary = "  ".join(f"{k}={v}" for k, v in sorted(by_cls.items(), key=lambda x: -x[1]))
    print(f"By class:  {summary}\n")

    print(f"{'#':>3}  {'count':>5}  {'class':<18} {'tool':<14}  suggested")
    print("-" * 72)
    for i, c in enumerate(visible[:top], start=1):
        tier, _auto, remediation = suggest(c)
        colour = tier_colour(c.count)
        tag = f"  {COLOR['dim']}[SUPPRESSED]{COLOR['reset']}" if c.suppressed else ""
        print(f"{i:>3}  {colour}{c.count:>5}{COLOR['reset']}  "
              f"{c.cls:<18} {c.tool_name[:14]:<14}  tier {tier}{tag}")
        sig_display = c.signature[:64] + ("…" if len(c.signature) > 64 else "")
        print(f"       {COLOR['dim']}sig:{COLOR['reset']} {sig_display}")
        print(f"       {COLOR['dim']}fix:{COLOR['reset']} {remediation}")
        if c.suppressed and c.suppression_reason:
            print(f"       {COLOR['dim']}why-suppressed:{COLOR['reset']} {c.suppression_reason}")
        if c.sessions:
            print(f"       {COLOR['dim']}ex:{COLOR['reset']}  {c.sessions[0]}")
        print()


def to_json(clusters: list[Cluster]) -> list[dict]:
    out = []
    for c in clusters:
        tier, auto, remediation = suggest(c)
        description = f"{c.cls} · {c.tool_name} · ×{c.count} — {c.signature[:80]}"
        out.append({
            "id": f"error-cluster-{c.cls}-{c.tool_name.lower()}-{hash(c.signature) & 0xffff:04x}",
            "category": "error-audit",
            "description": description,
            "fix": {
                "type": "manual",
                "note": remediation,
            },
            "idempotent": False,
            "requires_review": True,
            "type": "error_cluster",
            "cluster_key": c.key,
            "class": c.cls,
            "tool_name": c.tool_name,
            "signature": c.signature,
            "count": c.count,
            "example_session": c.sessions[0] if c.sessions else "",
            "sessions": c.sessions,
            "suggested_tier": tier,
            "suggested_remediation": remediation,
            "auto_fixable": auto,
            "suppressed": c.suppressed,
            "suppression_reason": c.suppression_reason,
        })
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--since", type=int, default=None, help="restrict to last N days (default: all)")
    p.add_argument("--top", type=int, default=TOP_N_DEFAULT, help="show top N clusters (default: 20)")
    p.add_argument("--json", action="store_true", help="emit JSON instead of human output")
    p.add_argument("--projects-dir", type=Path, default=DEFAULT_PROJECTS_DIR,
                   help=f"projects dir (default {DEFAULT_PROJECTS_DIR})")
    p.add_argument("--suppressions-path", type=Path, default=DEFAULT_SUPPRESSIONS_PATH,
                   help=f"suppressions file (default {DEFAULT_SUPPRESSIONS_PATH})")
    p.add_argument("--show-suppressed", action="store_true",
                   help="include suppressed clusters in --human output (JSON always includes them)")
    p.add_argument("--no-suppressions", action="store_true",
                   help="ignore suppressions file entirely (show everything)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    files = find_transcripts(args.projects_dir, args.since)
    events: list[ErrorEvent] = []
    for f in files:
        events.extend(classify_session(f))
    clusters = cluster_events(events)
    if not args.no_suppressions:
        suppressions = load_suppressions(args.suppressions_path)
        apply_suppressions(clusters, suppressions)
    if args.json:
        json.dump(to_json(clusters[:args.top]), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print_human(clusters, args.top, show_suppressed=args.show_suppressed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
