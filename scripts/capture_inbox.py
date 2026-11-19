#!/usr/bin/env python3
"""
atlasian — Harness-agnostic auto-capture runner for inbox/.

Zero external dependencies (Python 3.9+ standard library only).

Built-in safety & reliability guarantees:
1. Infinite loop guard: Exits immediately when ATLASIAN_CAPTURE_ACTIVE=1.
2. Non-blocking spawn: Detaches a background worker and exits 0 quickly.
3. Exclusive lockfile: Serializes concurrent hooks via .llm-wiki/inbox.lock.
4. Delta watermark: Tracks processed byte offsets in .llm-wiki/state.json.
5. Compaction context tagging: Labels prior compaction summaries as context-only.
6. Timeout + retry loop: Default 180s timeout with up to 3 automatic attempts;
   watermark advances only after a successful run.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterator

LOOP_ENV_VAR = "ATLASIAN_CAPTURE_ACTIVE"
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY_SECONDS = 3
DEFAULT_MIN_DELTA_CHARS = 80


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def append_log(meta_dir: Path, message: str) -> None:
    try:
        meta_dir.mkdir(parents=True, exist_ok=True)
        log_path = meta_dir / "capture.log"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{utc_now_iso()}] {message}\n")
    except OSError:
        pass


@contextmanager
def exclusive_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.1)
            try:
                yield
            finally:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass


def read_stdin_payload() -> dict[str, Any]:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read().strip()
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def extract_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    parts.append(text)
            elif isinstance(item, dict):
                item_type = str(item.get("type", "")).lower()
                # Skip noisy tool results / binary / thinking blocks
                if item_type in {"tool_result", "tool_use", "image", "thinking"}:
                    continue
                text = item.get("text") or item.get("content")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts).strip()
    if isinstance(content, dict):
        text = content.get("text") or content.get("content")
        if isinstance(text, str):
            return text.strip()
    return ""


def parse_jsonl_record(record: dict[str, Any]) -> tuple[str, str] | None:
    """Return ('summary' | 'message', formatted_text) or None to skip."""
    rec_type = str(record.get("type", "")).lower()
    subtype = str(record.get("subtype", "")).lower()

    if subtype == "compact_boundary":
        return None

    is_summary = bool(
        record.get("isCompactSummary")
        or record.get("is_compact_summary")
        or rec_type in {"compact_summary", "compaction_summary", "summary"}
        or subtype in {"compact_summary", "compaction_summary"}
    )

    message = record.get("message")
    if isinstance(message, dict):
        role = str(message.get("role") or rec_type or "message").upper()
        text = extract_text_from_content(message.get("content"))
    else:
        role = str(record.get("role") or rec_type or "message").upper()
        text = extract_text_from_content(
            record.get("summary") if is_summary and record.get("summary") else record.get("content") or record.get("text")
        )

    if not text:
        return None

    if is_summary:
        return ("summary", text)

    if role in {"TOOL", "PROGRESS", "FILE-HISTORY-SNAPSHOT"}:
        return None

    return ("message", f"{role}: {text}")


def format_transcript_delta(raw_text: str) -> tuple[str, int]:
    """
    Parse raw delta bytes (JSONL, JSON, or plain text).

    Returns (formatted_delta, new_message_char_count), where new_message_char_count
    counts only new non-summary conversation characters for min_delta_chars checks.
    """
    stripped = raw_text.strip()
    if not stripped:
        return ("", 0)

    lines = [line for line in raw_text.splitlines() if line.strip()]
    summaries: list[str] = []
    messages: list[str] = []
    parsed_jsonl_count = 0

    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            parsed_jsonl_count += 1
            parsed = parse_jsonl_record(obj)
            if parsed is None:
                continue
            kind, text = parsed
            if kind == "summary":
                summaries.append(text)
            else:
                messages.append(text)

    if parsed_jsonl_count > 0:
        sections: list[str] = []
        if summaries:
            sections.append(
                "[PRIOR COMPACTION SUMMARY — CONTEXT ONLY]\n"
                + "\n\n".join(summaries)
                + "\n[END PRIOR COMPACTION SUMMARY]"
            )
        if messages:
            sections.append("[NEW MESSAGES]\n" + "\n\n".join(messages))
        new_chars = sum(len(m) for m in messages)
        return ("\n\n".join(sections).strip(), new_chars)

    # Fallback: single JSON document (array of messages or dict)
    try:
        doc = json.loads(stripped)
        if isinstance(doc, list):
            for item in doc:
                if isinstance(item, dict):
                    parsed = parse_jsonl_record(item)
                    if parsed is None:
                        continue
                    kind, text = parsed
                    if kind == "summary":
                        summaries.append(text)
                    else:
                        messages.append(text)
            sections = []
            if summaries:
                sections.append(
                    "[PRIOR COMPACTION SUMMARY — CONTEXT ONLY]\n"
                    + "\n\n".join(summaries)
                    + "\n[END PRIOR COMPACTION SUMMARY]"
                )
            if messages:
                sections.append("[NEW MESSAGES]\n" + "\n\n".join(messages))
            return ("\n\n".join(sections).strip(), sum(len(m) for m in messages))
    except json.JSONDecodeError:
        pass

    # Fallback: plain text / Markdown transcript
    return (f"[NEW MESSAGES]\n{stripped}", len(stripped))


def validate_config(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    wiki_root = config.get("wiki_root")
    if not isinstance(wiki_root, str) or not wiki_root.strip():
        errors.append("Missing or invalid 'wiki_root' in capture.json")
    command = config.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
        errors.append("Missing or invalid 'command' list in capture.json")
    prompt_file = config.get("prompt_file")
    if prompt_file is not None:
        if not isinstance(prompt_file, str) or not Path(prompt_file).expanduser().is_file():
            errors.append(f"'prompt_file' does not exist: {prompt_file}")
    input_mode = config.get("input_mode", "stdin")
    if input_mode not in {"stdin", "file", "arg"}:
        errors.append(f"Invalid 'input_mode': {input_mode} (expected 'stdin', 'file', or 'arg')")
    return errors


def build_triage_payload(
    *,
    wiki_root: Path,
    inbox_dir: Path,
    session_id: str,
    event_name: str,
    formatted_delta: str,
    inline_system_prompt: str | None,
) -> str:
    parts: list[str] = []
    if inline_system_prompt:
        parts.append(inline_system_prompt.strip())
        parts.append("---")
    parts.append(
        "\n".join(
            [
                f"Wiki root: {wiki_root}",
                f"Inbox directory: {inbox_dir}",
                f"Session ID: {session_id}",
                f"Event: {event_name or 'hook'}",
                f"UTC Date: {utc_today()}",
                "",
                "Task: Follow the inbox triage rules. Read inbox/AGENTS.md and inbox/index.md first.",
                "If the new messages contain no lasting signal, exit immediately without writing any file.",
            ]
        )
    )
    parts.append(formatted_delta)
    return "\n\n".join(parts).strip() + "\n"


def render_command(
    template: list[str],
    *,
    prompt_file: str,
    wiki_root: Path,
    inbox_dir: Path,
    session_id: str,
    payload_file: str,
    prompt_text: str,
) -> list[str]:
    replacements = {
        "{prompt_file}": prompt_file,
        "{wiki_root}": str(wiki_root),
        "{inbox_dir}": str(inbox_dir),
        "{session_id}": session_id,
        "{payload_file}": payload_file,
        "{prompt}": prompt_text,
    }
    rendered: list[str] = []
    for token in template:
        value = token
        for placeholder, target in replacements.items():
            if placeholder in value:
                value = value.replace(placeholder, target)
        rendered.append(value)
    return rendered


def run_worker(
    config_path: Path,
    session_id: str,
    transcript_path: Path,
    event_name: str,
) -> int:
    config = load_json_file(config_path)
    errors = validate_config(config)
    if errors:
        return 1

    wiki_root = Path(config["wiki_root"]).expanduser().resolve()
    inbox_dir = wiki_root / "inbox"
    meta_dir = wiki_root / ".llm-wiki"
    state_path = meta_dir / "state.json"
    lock_path = meta_dir / "inbox.lock"

    inbox_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    prompt_file_str = str(Path(config["prompt_file"]).expanduser().resolve()) if config.get("prompt_file") else ""
    command_template: list[str] = config["command"]
    input_mode: str = config.get("input_mode", "stdin")
    timeout_seconds = int(config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
    max_retries = max(1, int(config.get("max_retries", DEFAULT_MAX_RETRIES)))
    retry_delay_seconds = max(0.0, float(config.get("retry_delay_seconds", DEFAULT_RETRY_DELAY_SECONDS)))
    min_delta_chars = max(0, int(config.get("min_delta_chars", DEFAULT_MIN_DELTA_CHARS)))
    extra_env = config.get("env") if isinstance(config.get("env"), dict) else {}

    if not transcript_path.is_file():
        append_log(meta_dir, f"SKIP session={session_id}: transcript missing ({transcript_path})")
        return 0

    with exclusive_lock(lock_path):
        state = load_json_file(state_path)
        sessions = state.setdefault("sessions", {})
        session_state = sessions.get(session_id, {})
        saved_offset = int(session_state.get("byte_offset", 0)) if isinstance(session_state, dict) else 0

        file_size = transcript_path.stat().st_size
        start_offset = saved_offset if 0 <= saved_offset <= file_size else 0
        if start_offset >= file_size:
            append_log(meta_dir, f"SKIP session={session_id}: no new bytes (offset={start_offset})")
            return 0

        with transcript_path.open("rb") as fh:
            fh.seek(start_offset)
            raw_bytes = fh.read()
        end_offset = start_offset + len(raw_bytes)

        raw_text = raw_bytes.decode("utf-8", errors="replace")
        formatted_delta, new_chars = format_transcript_delta(raw_text)

        if new_chars < min_delta_chars:
            append_log(
                meta_dir,
                f"SKIP session={session_id}: new_chars={new_chars} < min_delta_chars={min_delta_chars}",
            )
            return 0

        uses_prompt_file_flag = any("{prompt_file}" in tok for tok in command_template)
        inline_system_prompt: str | None = None
        if prompt_file_str and not uses_prompt_file_flag:
            inline_system_prompt = Path(prompt_file_str).read_text(encoding="utf-8")

        payload_text = build_triage_payload(
            wiki_root=wiki_root,
            inbox_dir=inbox_dir,
            session_id=session_id,
            event_name=event_name,
            formatted_delta=formatted_delta,
            inline_system_prompt=inline_system_prompt,
        )

        payload_file_path: Path | None = None
        try:
            uses_payload_file = input_mode == "file" or any("{payload_file}" in tok for tok in command_template)
            if uses_payload_file:
                fd, tmp_payload = tempfile.mkstemp(prefix="atlasian-delta-", suffix=".txt", dir=str(meta_dir))
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(payload_text)
                payload_file_path = Path(tmp_payload)

            cmd = render_command(
                command_template,
                prompt_file=prompt_file_str,
                wiki_root=wiki_root,
                inbox_dir=inbox_dir,
                session_id=session_id,
                payload_file=str(payload_file_path) if payload_file_path else "",
                prompt_text=payload_text if input_mode == "arg" else "",
            )

            child_env = os.environ.copy()
            for key, val in extra_env.items():
                child_env[str(key)] = str(val)
            child_env[LOOP_ENV_VAR] = "1"

            stdin_data = payload_text if input_mode == "stdin" else None

            for attempt in range(1, max_retries + 1):
                try:
                    proc = subprocess.run(
                        cmd,
                        input=stdin_data,
                        cwd=str(inbox_dir),
                        env=child_env,
                        timeout=timeout_seconds,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if proc.returncode == 0:
                        sessions[session_id] = {
                            "byte_offset": end_offset,
                            "updated_at": utc_now_iso(),
                            "last_event": event_name or "hook",
                        }
                        atomic_write_json(state_path, state)
                        append_log(
                            meta_dir,
                            f"OK session={session_id} attempt={attempt}/{max_retries} "
                            f"bytes={start_offset}->{end_offset} new_chars={new_chars}",
                        )
                        return 0

                    stderr_excerpt = (proc.stderr or "").strip().replace("\n", " ")[:240]
                    append_log(
                        meta_dir,
                        f"RETRY session={session_id} attempt={attempt}/{max_retries} "
                        f"exit_code={proc.returncode} stderr={stderr_excerpt!r}",
                    )
                except subprocess.TimeoutExpired:
                    append_log(
                        meta_dir,
                        f"RETRY session={session_id} attempt={attempt}/{max_retries} "
                        f"timeout={timeout_seconds}s",
                    )
                except OSError as exc:
                    append_log(
                        meta_dir,
                        f"RETRY session={session_id} attempt={attempt}/{max_retries} os_error={exc}",
                    )

                if attempt < max_retries and retry_delay_seconds > 0:
                    time.sleep(retry_delay_seconds)

            append_log(
                meta_dir,
                f"FAILED session={session_id}: exhausted {max_retries} attempts; watermark preserved at {start_offset}",
            )
            return 1
        finally:
            if payload_file_path is not None:
                try:
                    payload_file_path.unlink(missing_ok=True)
                except OSError:
                    pass


def spawn_detached_worker(
    config_path: Path,
    session_id: str,
    transcript_path: Path,
    event_name: str,
) -> None:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--config",
        str(config_path),
        "--session-id",
        session_id,
        "--transcript",
        str(transcript_path),
        "--event",
        event_name,
    ]
    env = os.environ.copy()
    env[LOOP_ENV_VAR] = "1"

    popen_kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "env": env,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True

    subprocess.Popen(cmd, **popen_kwargs)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="atlasian harness-agnostic auto-capture hook runner."
    )
    parser.add_argument("--config", required=True, help="Path to <wiki-root>/.llm-wiki/capture.json")
    parser.add_argument("--session-id", default="", help="Session identifier (or read from stdin JSON)")
    parser.add_argument("--transcript", default="", help="Path to session transcript (or read from stdin JSON)")
    parser.add_argument("--event", default="", help="Hook event name (e.g., PreCompact, SessionEnd)")
    parser.add_argument("--dry-run", action="store_true", help="Validate config and paths without running")
    parser.add_argument("--foreground", action="store_true", help="Run synchronously instead of detaching")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    # Guard 1: Infinite loop (fork bomb) protection.
    # Allow execution only inside the explicitly spawned --worker child.
    if not args.worker and os.environ.get(LOOP_ENV_VAR) == "1":
        return 0

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        if args.dry_run:
            print(f"ERROR: config file not found: {config_path}", file=sys.stderr)
            return 1
        return 0

    config = load_json_file(config_path)
    errors = validate_config(config)
    if args.dry_run:
        if errors:
            for err in errors:
                print(f"ERROR: {err}", file=sys.stderr)
            return 1
        print(f"OK: valid capture config at {config_path}")
        print(f"  wiki_root: {Path(config['wiki_root']).expanduser().resolve()}")
        print(f"  timeout_seconds: {config.get('timeout_seconds', DEFAULT_TIMEOUT_SECONDS)}")
        print(f"  max_retries: {config.get('max_retries', DEFAULT_MAX_RETRIES)}")
        print(f"  min_delta_chars: {config.get('min_delta_chars', DEFAULT_MIN_DELTA_CHARS)}")
        return 0

    if errors:
        return 0

    stdin_payload = {} if args.worker else read_stdin_payload()

    # Resolve session_id (prefer old_session_id when Hermes reports in_place=false)
    session_id = args.session_id.strip()
    if not session_id:
        if stdin_payload.get("in_place") is False and stdin_payload.get("old_session_id"):
            session_id = str(stdin_payload["old_session_id"])
        elif stdin_payload.get("session_id"):
            session_id = str(stdin_payload["session_id"])

    transcript_str = args.transcript.strip()
    if not transcript_str:
        transcript_str = str(
            stdin_payload.get("transcript_path") or stdin_payload.get("transcript") or ""
        ).strip()

    event_name = args.event.strip() or str(
        stdin_payload.get("hook_event_name") or stdin_payload.get("event") or "hook"
    ).strip()

    if not session_id or not transcript_str:
        wiki_root = Path(config["wiki_root"]).expanduser().resolve()
        append_log(wiki_root / ".llm-wiki", "SKIP: missing session_id or transcript path")
        return 0

    transcript_path = Path(transcript_str).expanduser().resolve()

    if args.worker or args.foreground:
        return run_worker(config_path, session_id, transcript_path, event_name)

    # Guard 2: Non-blocking detached spawn.
    spawn_detached_worker(config_path, session_id, transcript_path, event_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
