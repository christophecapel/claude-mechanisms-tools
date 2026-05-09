"""Unit tests for scripts/error-audit.py.

Run: python3 -m unittest tests.test_error_audit -v
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "skills" / "error-audit" / "error-audit.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "error-audit"


def _load():
    spec = importlib.util.spec_from_file_location("error_audit", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["error_audit"] = mod
    spec.loader.exec_module(mod)
    return mod


ea = _load()


def _run_fixtures(fixture_names: list[str]) -> list:
    """Classify listed fixtures, return flat event list."""
    events = []
    for name in fixture_names:
        path = FIXTURES / f"{name}.jsonl"
        events.extend(ea.classify_session(path))
    return events


class TestClassifiers(unittest.TestCase):

    def test_tool_error(self):
        events = _run_fixtures(["tool_error"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].cls, "tool_error")
        self.assertEqual(events[0].tool_name, "Read")

    def test_validation_error(self):
        events = _run_fixtures(["validation_error"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].cls, "validation_error")
        self.assertIn("offset", events[0].signature)

    def test_permission_denial(self):
        events = _run_fixtures(["permission_denial"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].cls, "permission_denial")
        self.assertEqual(events[0].tool_name, "Bash")
        self.assertEqual(events[0].signature, "git")

    def test_hook_block(self):
        events = _run_fixtures(["hook_block"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].cls, "hook_block")
        self.assertEqual(events[0].tool_name, "Stop:response-linter")

    def test_bash_fail(self):
        events = _run_fixtures(["bash_fail"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].cls, "bash_fail")
        self.assertEqual(events[0].tool_name, "pytest")

    def test_read_before_edit(self):
        events = _run_fixtures(["read_before_edit"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].cls, "read_before_edit")

    def test_retry_storm_above_threshold(self):
        events = _run_fixtures(["retry_storm"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].cls, "retry_storm")

    def test_retry_storm_below_threshold(self):
        """Two overloaded_error records must NOT fire the storm event."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.jsonl"
            path.write_text(
                '{"type":"system","subtype":"api_error","error":{"tool_name":"Edit","error":{"type":"overloaded_error"}},"timestamp":"2026-04-20T10:00:00Z"}\n'
                '{"type":"system","subtype":"api_error","error":{"tool_name":"Edit","error":{"type":"overloaded_error"}},"timestamp":"2026-04-20T10:00:10Z"}\n'
            )
            events = ea.classify_session(path)
            self.assertEqual([e.cls for e in events], [])


class TestNormalisation(unittest.TestCase):

    def test_strip_tool_use_id(self):
        out = ea.normalise("error on toolu_01AbcXYZ123 failed")
        self.assertNotIn("toolu_01AbcXYZ123", out)
        self.assertIn("<X>", out)

    def test_strip_absolute_path(self):
        out = ea.normalise("File does not exist: /Users/christophe/myOS/x.md")
        self.assertNotIn("/Users/christophe", out)
        self.assertIn("<X>", out)

    def test_strip_iso_timestamp(self):
        out = ea.normalise("retry at 2026-04-20T10:30:45Z now")
        self.assertNotIn("2026-04-20T10:30:45", out)

    def test_strip_uuid(self):
        out = ea.normalise("session fixture-123e4567-e89b-12d3-a456-426614174000 failed")
        self.assertNotIn("123e4567-e89b-12d3-a456-426614174000", out)

    def test_truncates(self):
        out = ea.normalise("x" * 200, limit=80)
        self.assertEqual(len(out), 80)


class TestClustering(unittest.TestCase):

    def test_same_signature_clusters(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "s.jsonl"
            block = (
                '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"toolu_X","name":"Read","input":{}}]}}\n'
                '{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_X","content":"File does not exist: /Users/christophe/x.md","is_error":true}]}}\n'
            )
            p.write_text(block * 3)
            events = ea.classify_session(p)
            clusters = ea.cluster_events(events)
            self.assertEqual(len(clusters), 1)
            self.assertEqual(clusters[0].count, 3)

    def test_sorted_by_count_desc(self):
        events = [
            ea.ErrorEvent(cls="tool_error", tool_name="A", signature="a", session="s1"),
            ea.ErrorEvent(cls="tool_error", tool_name="A", signature="a", session="s1"),
            ea.ErrorEvent(cls="tool_error", tool_name="B", signature="b", session="s1"),
        ]
        clusters = ea.cluster_events(events)
        self.assertEqual(clusters[0].count, 2)
        self.assertEqual(clusters[1].count, 1)


class TestOutput(unittest.TestCase):

    def test_json_schema(self):
        events = _run_fixtures([
            "tool_error", "validation_error", "permission_denial",
            "hook_block", "bash_fail", "retry_storm", "read_before_edit",
        ])
        clusters = ea.cluster_events(events)
        out = ea.to_json(clusters)
        required = {
            "id", "category", "description", "fix", "idempotent", "requires_review",
            "type", "cluster_key", "class", "tool_name", "signature",
            "count", "example_session", "sessions", "suggested_tier",
            "suggested_remediation", "auto_fixable",
            "suppressed", "suppression_reason",
        }
        for entry in out:
            self.assertEqual(set(entry.keys()), required)
            self.assertEqual(entry["type"], "error_cluster")
            self.assertEqual(entry["category"], "error-audit")
            self.assertEqual(entry["fix"]["type"], "manual")
            self.assertFalse(entry["idempotent"])
            self.assertTrue(entry["requires_review"])
            self.assertIn(entry["suggested_tier"], {1, 2, 3})
            self.assertIsInstance(entry["auto_fixable"], bool)
            self.assertIsInstance(entry["suppressed"], bool)
            self.assertIsInstance(entry["suppression_reason"], str)


class TestSinceFilter(unittest.TestCase):

    def test_respects_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sub = root / "sess"
            sub.mkdir()
            old = sub / "old.jsonl"
            new = sub / "new.jsonl"
            old.write_text("{}\n")
            new.write_text("{}\n")
            old_time = time.time() - 60 * 86400
            os.utime(old, (old_time, old_time))
            files = ea.find_transcripts(root, since_days=7)
            names = {p.name for p in files}
            self.assertIn("new.jsonl", names)
            self.assertNotIn("old.jsonl", names)


class TestSuppressions(unittest.TestCase):

    def _write_suppressions(self, tmp: Path, body: str) -> Path:
        path = tmp / "error-audit-suppressions.md"
        path.write_text(body)
        return path

    def test_load_basic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_suppressions(Path(tmp), (
                "# Intro prose\n\n"
                "## Suppressions\n\n"
                "```\n"
                "# comment ignored\n"
                "permission_denial:ExitPlanMode:ExitPlanMode\treason-one\n"
                "tool_error:Bash:Uncommitted changes\treason-two\n"
                "```\n"
            ))
            supp = ea.load_suppressions(path)
            self.assertEqual(len(supp), 2)
            self.assertEqual(supp["permission_denial:ExitPlanMode:ExitPlanMode"], "reason-one")
            self.assertEqual(supp["tool_error:Bash:Uncommitted changes"], "reason-two")

    def test_load_missing_file_returns_empty(self):
        supp = ea.load_suppressions(Path("/nonexistent/path/to/suppressions.md"))
        self.assertEqual(supp, {})

    def test_multiple_fenced_blocks_parsed(self):
        """Seed file has two code fences (active + candidates); both should be scanned."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_suppressions(Path(tmp), (
                "## Active\n\n```\nkey-a\treason-a\n```\n\n"
                "## Candidates\n\n```\nkey-b\treason-b\n```\n"
            ))
            supp = ea.load_suppressions(path)
            self.assertEqual(set(supp.keys()), {"key-a", "key-b"})

    def test_filter_hides_by_default(self):
        """print_human default output skips suppressed clusters."""
        import io
        import contextlib
        c_sup = ea.Cluster(cls="tool_error", tool_name="Bash", signature="suppressed-sig", count=50, suppressed=True, suppression_reason="gate")
        c_vis = ea.Cluster(cls="tool_error", tool_name="Read", signature="visible-sig", count=5)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ea.print_human([c_sup, c_vis], top=10, show_suppressed=False)
        out = buf.getvalue()
        self.assertIn("visible-sig", out)
        self.assertNotIn("suppressed-sig", out)
        self.assertIn("suppressed", out.lower())  # note about hidden count

    def test_show_suppressed_flag_reincludes(self):
        import io
        import contextlib
        c_sup = ea.Cluster(cls="tool_error", tool_name="Bash", signature="suppressed-sig", count=50, suppressed=True, suppression_reason="gate")
        c_vis = ea.Cluster(cls="tool_error", tool_name="Read", signature="visible-sig", count=5)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ea.print_human([c_sup, c_vis], top=10, show_suppressed=True)
        out = buf.getvalue()
        self.assertIn("suppressed-sig", out)
        self.assertIn("[SUPPRESSED]", out)
        self.assertIn("gate", out)  # reason printed

    def test_precise_key_match(self):
        """A different signature on the same (class, tool) pair is NOT suppressed."""
        suppressions = {"tool_error:Bash:exact-match-sig": "gate"}
        clusters = [
            ea.Cluster(cls="tool_error", tool_name="Bash", signature="exact-match-sig", count=10),
            ea.Cluster(cls="tool_error", tool_name="Bash", signature="different-sig", count=5),
        ]
        ea.apply_suppressions(clusters, suppressions)
        self.assertTrue(clusters[0].suppressed)
        self.assertFalse(clusters[1].suppressed)

    def test_seed_file_parses(self):
        """The repo's own error-audit-suppressions.md file parses without error."""
        seed = REPO_ROOT / "claude-memory" / "error-audit-suppressions.md"
        if not seed.exists():
            self.skipTest("seed file not yet in repo")
        supp = ea.load_suppressions(seed)
        self.assertGreater(len(supp), 0, "seed suppressions must be non-empty")
        # Every key should have the cluster_key shape: class:tool:signature
        for key in supp:
            self.assertGreaterEqual(key.count(":"), 2, f"malformed cluster_key: {key}")


@unittest.skip("integration test against myOS health-check-execute.py — out of scope for toolkit")
class TestHealthCheckIntegration(unittest.TestCase):
    """Confirms error-audit JSON schema is compatible with
    health-check-execute.py's filter_executable. Lives in myOS only — the
    health-check-execute.py script is myOS infra not part of the toolkit."""

    def test_findings_route_to_skipped(self):
        pass


class TestEndToEnd(unittest.TestCase):

    def test_run_against_fixtures_dir(self):
        """Scanner run on fixtures dir surfaces all 7 classes."""
        import io
        import contextlib

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "p"
            sess = proj / "s"
            sess.mkdir(parents=True)
            for f in FIXTURES.glob("*.jsonl"):
                shutil.copy(f, sess)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = ea.main(["--projects-dir", str(proj), "--json"])
            self.assertEqual(rc, 0)
            clusters = json.loads(buf.getvalue())
            classes = {c["class"] for c in clusters}
            self.assertEqual(classes, {
                "tool_error", "validation_error", "permission_denial",
                "hook_block", "bash_fail", "retry_storm", "read_before_edit",
            })


if __name__ == "__main__":
    unittest.main()
