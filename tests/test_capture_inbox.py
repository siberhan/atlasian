import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "capture_inbox.py"
PROMPT_PATH = REPO_ROOT / "prompts" / "inbox-triage.md"


class CaptureInboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.wiki_root = self.root / "llm-wiki"
        self.meta_dir = self.wiki_root / ".llm-wiki"
        self.inbox_dir = self.wiki_root / "inbox"
        self.meta_dir.mkdir(parents=True)
        self.inbox_dir.mkdir(parents=True)
        self.config_path = self.meta_dir / "capture.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_helper(self, name: str, code: str) -> Path:
        helper = self.root / name
        helper.write_text(textwrap.dedent(code).lstrip(), encoding="utf-8")
        return helper

    def write_config(self, command: list[str], **overrides: object) -> None:
        cfg: dict[str, object] = {
            "wiki_root": str(self.wiki_root),
            "prompt_file": str(PROMPT_PATH),
            "command": command,
            "input_mode": "stdin",
            "timeout_seconds": 10,
            "max_retries": 3,
            "retry_delay_seconds": 0,
            "min_delta_chars": 20,
            "env": {},
        }
        cfg.update(overrides)
        self.config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    def test_dry_run_valid_and_invalid(self) -> None:
        self.write_config([sys.executable, "-c", "pass"])
        res = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--config", str(self.config_path), "--dry-run"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("OK: valid capture config", res.stdout)

        # Invalid config (missing command)
        self.config_path.write_text(json.dumps({"wiki_root": str(self.wiki_root)}), encoding="utf-8")
        bad = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--config", str(self.config_path), "--dry-run"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(bad.returncode, 0)

    def test_loop_guard_blocks_nested_invocation(self) -> None:
        marker = self.root / "ran.txt"
        helper = self.write_helper(
            "worker.py",
            f"""
            from pathlib import Path
            Path({str(marker)!r}).write_text("ran", encoding="utf-8")
            """,
        )
        self.write_config([sys.executable, str(helper)])
        transcript = self.root / "chat.txt"
        transcript.write_text("We decided to use OKF v0.3 for our personal knowledge base.", encoding="utf-8")

        env = os.environ.copy()
        env["ATLASIAN_CAPTURE_ACTIVE"] = "1"
        res = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--config",
                str(self.config_path),
                "--session-id",
                "s1",
                "--transcript",
                str(transcript),
                "--foreground",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0)
        self.assertFalse(marker.exists())

    def test_watermark_and_compaction_summary_labeling(self) -> None:
        captured_file = self.root / "captured.jsonl"
        helper = self.write_helper(
            "record.py",
            f"""
            import json, os, sys
            from pathlib import Path
            data = sys.stdin.read()
            assert os.environ.get("ATLASIAN_CAPTURE_ACTIVE") == "1"
            with Path({str(captured_file)!r}).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({{"stdin": data}}) + "\\n")
            """,
        )
        self.write_config([sys.executable, str(helper)])

        transcript = self.root / "session.jsonl"
        turn1 = [
            {"type": "user", "message": {"role": "user", "content": "Let us design atlasian with raw, inbox, and wiki folders."}},
            {"type": "assistant", "message": {"role": "assistant", "content": "Agreed: raw is read-only, inbox is staging, wiki uses OKF v0.3."}},
        ]
        transcript.write_text("\n".join(json.dumps(x) for x in turn1) + "\n", encoding="utf-8")

        # Hook 1
        res1 = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--config",
                str(self.config_path),
                "--session-id",
                "sess-42",
                "--transcript",
                str(transcript),
                "--event",
                "PreCompact",
                "--foreground",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res1.returncode, 0, res1.stderr)

        # Hook 1b with no new data -> should skip
        res1b = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--config",
                str(self.config_path),
                "--session-id",
                "sess-42",
                "--transcript",
                str(transcript),
                "--event",
                "SessionEnd",
                "--foreground",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res1b.returncode, 0)

        # Compaction boundary + summary + new messages appended for Hook 2
        turn2 = [
            {"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted"},
            {"type": "user", "isCompactSummary": True, "message": {"role": "user", "content": "Summary: Designing atlasian 3-layer wiki."}},
            {"type": "user", "message": {"role": "user", "content": "Now add a 3-minute timeout and max 3 retries to capture_inbox.py."}},
        ]
        with transcript.open("a", encoding="utf-8") as fh:
            for item in turn2:
                fh.write(json.dumps(item) + "\n")

        # Hook 2 via stdin JSON payload (Claude Code style)
        hook_payload = json.dumps({
            "session_id": "sess-42",
            "transcript_path": str(transcript),
            "hook_event_name": "SessionEnd",
        })
        res2 = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--config",
                str(self.config_path),
                "--foreground",
            ],
            input=hook_payload,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res2.returncode, 0, res2.stderr)

        records = [json.loads(line)["stdin"] for line in captured_file.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 2)
        self.assertIn("raw, inbox, and wiki folders", records[0])
        self.assertNotIn("\n[PRIOR COMPACTION SUMMARY — CONTEXT ONLY]\n", records[0])

        # Hook 2 sees prior compaction summary tagged as context-only + ONLY new messages
        self.assertIn("\n[PRIOR COMPACTION SUMMARY — CONTEXT ONLY]\n", records[1])
        self.assertIn("Summary: Designing atlasian 3-layer wiki.", records[1])
        self.assertIn("3-minute timeout and max 3 retries", records[1])
        self.assertNotIn("raw, inbox, and wiki folders", records[1])

    def test_retry_succeeds_on_second_attempt(self) -> None:
        attempts_file = self.root / "attempts.txt"
        helper = self.write_helper(
            "flaky.py",
            f"""
            import sys
            from pathlib import Path
            p = Path({str(attempts_file)!r})
            count = int(p.read_text()) if p.exists() else 0
            count += 1
            p.write_text(str(count))
            sys.exit(0 if count >= 2 else 1)
            """,
        )
        self.write_config([sys.executable, str(helper)], max_retries=3, retry_delay_seconds=0)
        transcript = self.root / "chat.txt"
        transcript.write_text("Important project decision: keep inbox triage fast and safe.", encoding="utf-8")

        res = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--config",
                str(self.config_path),
                "--session-id",
                "retry-ok",
                "--transcript",
                str(transcript),
                "--foreground",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0)
        self.assertEqual(attempts_file.read_text(), "2")
        state = json.loads((self.meta_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["sessions"]["retry-ok"]["byte_offset"], transcript.stat().st_size)

    def test_timeout_retries_three_times_and_preserves_watermark(self) -> None:
        attempts_file = self.root / "timeout_attempts.txt"
        helper = self.write_helper(
            "slow.py",
            f"""
            import time
            from pathlib import Path
            p = Path({str(attempts_file)!r})
            count = int(p.read_text()) if p.exists() else 0
            count += 1
            p.write_text(str(count))
            time.sleep(5)
            """,
        )
        self.write_config([sys.executable, str(helper)], timeout_seconds=1, max_retries=3, retry_delay_seconds=0)
        transcript = self.root / "chat.txt"
        transcript.write_text("Important decision that must not be lost if worker times out.", encoding="utf-8")

        res = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--config",
                str(self.config_path),
                "--session-id",
                "retry-fail",
                "--transcript",
                str(transcript),
                "--foreground",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual(attempts_file.read_text(), "3")
        # Watermark must NOT advance after total failure
        self.assertFalse((self.meta_dir / "state.json").exists())

    def test_detached_spawn_is_non_blocking_and_lock_serializes(self) -> None:
        done_file = self.root / "detached_done.txt"
        helper = self.write_helper(
            "sleepy.py",
            f"""
            import time
            from pathlib import Path
            time.sleep(0.4)
            Path({str(done_file)!r}).write_text("done", encoding="utf-8")
            """,
        )
        self.write_config([sys.executable, str(helper)])
        transcript = self.root / "chat.txt"
        transcript.write_text("Brainstorm idea: support voice memo transcripts inside inbox.", encoding="utf-8")

        start = time.monotonic()
        res = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--config",
                str(self.config_path),
                "--session-id",
                "bg-1",
                "--transcript",
                str(transcript),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        elapsed = time.monotonic() - start
        self.assertEqual(res.returncode, 0)
        self.assertLess(elapsed, 0.35, f"Detached hook took too long: {elapsed:.2f}s")

        # Wait up to 3 seconds for background worker to complete
        deadline = time.monotonic() + 3.0
        while not done_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(done_file.exists(), "Detached background worker did not complete")

    def test_concurrent_lock_serializes_workers(self) -> None:
        events_file = self.root / "lock_events.log"
        helper = self.write_helper(
            "locked_worker.py",
            f"""
            import sys, time
            from pathlib import Path
            sid = sys.argv[1]
            p = Path({str(events_file)!r})
            with p.open("a", encoding="utf-8") as fh:
                fh.write(f"START:{{sid}}\\n")
            time.sleep(0.25)
            with p.open("a", encoding="utf-8") as fh:
                fh.write(f"END:{{sid}}\\n")
            """,
        )
        self.write_config([sys.executable, str(helper), "{session_id}"])
        t1 = self.root / "c1.txt"
        t2 = self.root / "c2.txt"
        t1.write_text("Session one architectural decision about lockfile safety.", encoding="utf-8")
        t2.write_text("Session two architectural decision about inbox serialization.", encoding="utf-8")

        p1 = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--config",
                str(self.config_path),
                "--session-id",
                "s1",
                "--transcript",
                str(t1),
                "--foreground",
            ]
        )
        p2 = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--config",
                str(self.config_path),
                "--session-id",
                "s2",
                "--transcript",
                str(t2),
                "--foreground",
            ]
        )
        self.assertEqual(p1.wait(timeout=10), 0)
        self.assertEqual(p2.wait(timeout=10), 0)

        lines = events_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 4)
        # First worker must END before second worker can START
        self.assertTrue(lines[0].startswith("START:"))
        self.assertEqual(lines[1], f"END:{lines[0].split(':')[1]}")
        self.assertTrue(lines[2].startswith("START:"))
        self.assertEqual(lines[3], f"END:{lines[2].split(':')[1]}")

    def test_min_delta_chars_skips_tiny_chat(self) -> None:
        marker = self.root / "tiny_ran.txt"
        helper = self.write_helper(
            "tiny.py",
            f"""
            from pathlib import Path
            Path({str(marker)!r}).write_text("ran", encoding="utf-8")
            """,
        )
        self.write_config([sys.executable, str(helper)], min_delta_chars=80)
        transcript = self.root / "tiny.txt"
        transcript.write_text("ok thanks!", encoding="utf-8")

        res = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--config",
                str(self.config_path),
                "--session-id",
                "tiny-1",
                "--transcript",
                str(transcript),
                "--foreground",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0)
        self.assertFalse(marker.exists())

    def test_strict_allowlist_drops_system_developer_meta_and_tools(self) -> None:
        captured_file = self.root / "filtered.txt"
        helper = self.write_helper(
            "dump.py",
            f"""
            import sys
            from pathlib import Path
            Path({str(captured_file)!r}).write_text(sys.stdin.read(), encoding="utf-8")
            """,
        )
        self.write_config([sys.executable, str(helper)])

        transcript = self.root / "mixed.jsonl"
        rows = [
            {"type": "system", "message": {"role": "system", "content": "SECRET_SYSTEM_PROMPT_DO_NOT_SEND"}},
            {"type": "developer", "message": {"role": "developer", "content": "SECRET_DEVELOPER_PROMPT"}},
            {"type": "user", "isMeta": True, "message": {"role": "user", "content": "INJECTED_META_SKILL_TEXT"}},
            {"type": "tool", "message": {"role": "tool", "content": "RAW_TOOL_STDOUT_NOISE"}},
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "text": "PRIVATE_THINKING_TRACE"},
                        {"type": "tool_use", "name": "bash", "text": "TOOL_CALL_PAYLOAD"},
                        {"type": "tool_result", "content": "TOOL_RESULT_PAYLOAD"},
                        {"type": "text", "text": "Clean assistant decision: use SQLite append-only export."},
                    ],
                },
            },
            {"type": "user", "message": {"role": "user", "content": "Great, keep only user and assistant text messages."}},
        ]
        transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

        res = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--config",
                str(self.config_path),
                "--session-id",
                "filter-1",
                "--transcript",
                str(transcript),
                "--foreground",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        out = captured_file.read_text(encoding="utf-8")
        self.assertIn("Clean assistant decision: use SQLite append-only export.", out)
        self.assertIn("Great, keep only user and assistant text messages.", out)
        for forbidden in (
            "SECRET_SYSTEM_PROMPT_DO_NOT_SEND",
            "SECRET_DEVELOPER_PROMPT",
            "INJECTED_META_SKILL_TEXT",
            "RAW_TOOL_STDOUT_NOISE",
            "PRIVATE_THINKING_TRACE",
            "TOOL_CALL_PAYLOAD",
            "TOOL_RESULT_PAYLOAD",
        ):
            self.assertNotIn(forbidden, out)

    def test_content_recursion_guard_and_stderr_tail_logging(self) -> None:
        marker = self.root / "recursive_ran.txt"
        helper = self.write_helper(
            "rec.py",
            f"""
            from pathlib import Path
            Path({str(marker)!r}).write_text("ran", encoding="utf-8")
            """,
        )
        self.write_config([sys.executable, str(helper)])

        # Simulate a harness that stripped ATLASIAN_CAPTURE_ACTIVE on hook spawn
        triage_transcript = self.root / "triage_session.jsonl"
        triage_transcript.write_text(
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": "<!-- ATLASIAN_TRIAGE_WORKER -->\n\n# Inbox Triage Agent Prompt\nSome long text...",
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        res = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--config",
                str(self.config_path),
                "--session-id",
                "worker-loop-1",
                "--transcript",
                str(triage_transcript),
                "--foreground",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0)
        self.assertFalse(marker.exists())
        log_text = (self.meta_dir / "capture.log").read_text(encoding="utf-8")
        self.assertIn("content recursion guard", log_text)

        # Verify stderr tail logging captures real error even after long startup warning
        err_helper = self.write_helper(
            "noisy_err.py",
            """
            import sys
            sys.stderr.write("STARTUP_WARNING " * 60 + "\\nREAL_ROOT_CAUSE_ERROR: invalid_params\\n")
            sys.exit(1)
            """,
        )
        self.write_config([sys.executable, str(err_helper)], max_retries=1)
        normal_transcript = self.root / "normal.txt"
        normal_transcript.write_text("Important decision about tail error logging in capture.log.", encoding="utf-8")
        fail = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--config",
                str(self.config_path),
                "--session-id",
                "err-tail-1",
                "--transcript",
                str(normal_transcript),
                "--foreground",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(fail.returncode, 0)
        log_text = (self.meta_dir / "capture.log").read_text(encoding="utf-8")
        self.assertIn("REAL_ROOT_CAUSE_ERROR: invalid_params", log_text)


if __name__ == "__main__":
    unittest.main()
