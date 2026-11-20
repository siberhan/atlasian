# Wiring `atlasian` Auto-Capture into Hermes Agent

Reference guide for configuring `atlasian` auto-capture hooks in Hermes Agent.

---

## 1. Which Hook System to Use

| System | Runs In | Use It? |
| :--- | :--- | :--- |
| Shell hooks (`hooks:` block in profile `config.yaml`) | CLI + Gateway + Desktop/TUI/dashboard chat | **Yes** |
| Gateway hooks (`~/.hermes/hooks/HOOK.yaml` + `handler.py`) | Gateway only | No — Desktop app never loads them |

Shell hooks are the only hook system that fires across CLI, Gateway, Desktop, TUI, and dashboard chat.

---

## 2. Events

```yaml
hooks:
  on_session_finalize:
    - command: python3 <profile>/agent-hooks/atlasian-capture.py
      timeout: 30
  on_session_reset:
    - command: python3 <profile>/agent-hooks/atlasian-capture.py
      timeout: 30
```

You can configure them with:

```bash
hermes config set hooks.<event> '[{"command": "python3 <profile>/agent-hooks/atlasian-capture.py", "timeout": 30}]'
```

---

## 3. Exporting Transcripts from `state.db`

Hermes sends `{hook_event_name, session_id, cwd, profile, extra}` on stdin (no transcript file path).

Because `capture_inbox.py` reads a transcript file, wire a thin wrapper script (for example at `<profile>/agent-hooks/atlasian-capture.py`) that:

1. Checks `ATLASIAN_CAPTURE_ACTIVE=1` first and exits `0` immediately (loop guard).
2. Reads the hook payload JSON from stdin and extracts `session_id`.
3. Appends new `user`/`assistant` rows from `$HERMES_HOME/state.db` (`SELECT id, role, content, _compressed_summary FROM messages ...`) to `<wiki-root>/.llm-wiki/transcripts/<session_id>.jsonl` as JSONL records `{"message": {"role": ..., "content": ...}}`, setting `"isCompactSummary": true` whenever `_compressed_summary` is truthy so `capture_inbox.py` labels it `[PRIOR COMPACTION SUMMARY — CONTEXT ONLY]`.
4. Tracks a per-session `max_id` cursor so the staged JSONL file stays **append-only** and the byte-offset watermark in `.llm-wiki/state.json` remains valid.
5. Invokes `capture_inbox.py --config <wiki-root>/.llm-wiki/capture.json --session-id <sid> --transcript <jsonl-path> --event <event>`.
6. Exits `0` on every error path so Hermes sessions never fail.

---

## 4. Hook Consent in Non-TTY Sessions

Desktop and TUI sessions are non-TTY, so unapproved shell hooks are skipped silently.
Either pre-approve the hook in `<HERMES_HOME>/shell-hooks-allowlist.json`:

```json
{
  "approvals": [
    {
      "event": "on_session_finalize",
      "command": "python3 /abs/path/atlasian-capture.py",
      "approved_at": "<ISO8601Z>",
      "script_mtime_at_approval": "<script mtime ISO8601Z>"
    }
  ]
}
```

…or set `hooks_auto_accept: true` in your Hermes config. After editing the wrapper script, re-approve it: Hermes records the script mtime and treats a modified script as a new hook.

---

## 5. Worker Command (`capture.json`)

```json
{
  "wiki_root": "<abs wiki root>",
  "prompt_file": "<atlasian>/prompts/inbox-triage.md",
  "command": [
    "hermes",
    "chat",
    "--query-file",
    "{payload_file}",
    "--oneshot",
    "-Q",
    "-m",
    "<user-chosen-model>",
    "--reasoning",
    "<user-chosen-level>",
    "-t",
    "file",
    "--yolo"
  ],
  "input_mode": "file",
  "timeout_seconds": 180,
  "max_retries": 3,
  "min_delta_chars": 80,
  "env": {
    "HERMES_HOME": "<abs profile home>"
  }
}
```

- `-t file` restricts the worker to file read/write tools only (no shell, no web).
- `--yolo` prevents the headless background worker from stalling on approval prompts.
- Omit `{prompt_file}` from `command` when using `"input_mode": "file"`—`capture_inbox.py` automatically prepends `prompts/inbox-triage.md` into `{payload_file}`.
- The worker runs with `cwd = <wiki-root>/inbox`.

---

## 6. Verification

```bash
python3 <atlasian>/scripts/capture_inbox.py --config <wiki-root>/.llm-wiki/capture.json --dry-run
hermes hooks list      # expect "✓ allowed"
hermes hooks doctor    # expect all ✓
cd <atlasian> && python3 -m unittest discover -s tests
```

End-to-end test from a persistent terminal shell:

```bash
echo '{"hook_event_name":"on_session_finalize","session_id":"<real-session-id>"}' | python3 <wrapper>
sleep 90 && tail -5 <wiki-root>/.llm-wiki/capture.log
```

---

## 7. Gotchas

- **Agent terminal cleanup:** A detached background worker started inside an agent's temporary `terminal` tool call may be killed when that tool call finishes. Run end-to-end tests from a normal shell or trigger a real session event.
- **Append-only staged transcripts:** `state.json` stores byte offsets. Always append to `<wiki-root>/.llm-wiki/transcripts/<session_id>.jsonl` rather than rewriting it in place (or clear that session's entry in `state.json` before re-testing).
- **Short tail turns:** `min_delta_chars` (default `80`) skips tiny turns automatically.
