# atlasian — One-Time Setup Guide

Read this file only during initial setup (or when the user asks to reconfigure `atlasian`).
Once `<wiki-root>` and `<wiki-root>/.llm-wiki/capture.json` exist (or auto-capture is explicitly disabled in `<wiki-root>/AGENTS.md`), do not open this file during normal wiki operations.

---

## Step 1: Ask the User 3 Quick Questions

Keep setup short and interactive. Ask only what you cannot detect automatically:

1. **Wiki location & name:** Where should the wiki folder live?
   - Default: `~/llm-wiki` (or `./llm-wiki` inside the current workspace). The user can choose any name or path.
2. **OKF v0.3 optional fields & page types:**
   - Read `references/okf-v0.3-fields.md` in this skill folder so you have the exact YAML format and meaning for every OKF v0.3 field.
   - Show the clean personal default (`type`, `title`, `description`, `tags`, `sources`, `generated`) and ask if the user wants to enable any extra optional fields (such as `status`, `superseded_by`, `stale_after`, `verified`, `resource`, `usage_window`, `license`, or computation fields) or remove any default optional field.
   - Show starter page types (`concept`, `project`, `goal`, `decision`, `person`, `source`) and tell the user they are 100% customizable—ask if they want to add, rename, or remove types in `<wiki-root>/AGENTS.md`.
3. **Auto-capture hooks:** Do you want automatic capture of chat notes into `inbox/` when sessions compact, reset, or end?
   - If **Yes**: Confirm which headless CLI, fast/cheap model, and low effort setting to use for the active harness (for example: `claude -p --model haiku`, `codex exec`, `hermes`, or `opencode run`).

---

## Step 2: Create the Wiki Folder & Starter Files

Create these folders if they do not exist (never overwrite existing user content):

```text
<wiki-root>/
├── .llm-wiki/
├── raw/
├── inbox/
└── wiki/
```

Create starter files only if missing:

### 1. `<wiki-root>/AGENTS.md`

Write the user's chosen preferences here:

```markdown
# Wiki Rules (AGENTS.md)

This folder is a living Markdown knowledge base managed by the `atlasian` skill.
Read this file first before any wiki action. Never modify files inside `raw/`.

## Enabled OKF v0.3 Frontmatter Fields
- Required: `type`
- Enabled optional fields: `title`, `description`, `tags`, `sources`, `generated`
<!-- Add or delete optional fields here anytime. For exact YAML syntax, see references/okf-v0.3-fields.md in the atlasian skill folder. -->

### Active Frontmatter Template
```yaml
---
type: <one of Preferred Page Types>
title: <Concise Page Title>
description: <One-line summary for index.md>
tags: [<tag-one>, <tag-two>]
sources:
  - resource: <raw/file.md or session:id>
generated:
  by: atlasian
  at: <YYYY-MM-DDTHH:MM:SSZ>
---
```

## Preferred Page Types
- `concept`, `project`, `goal`, `decision`, `person`, `source`

## Auto-Capture
- Status: enabled <!-- Change to "disabled" if skipping hook capture -->

## Personal Preferences
<!-- Add tone, language, folder preferences, or standing context here -->
```

### 2. `<wiki-root>/inbox/AGENTS.md`

```markdown
# Inbox Capture Rules (inbox/AGENTS.md)

Use this file to guide what belongs in `inbox/`.
`inbox/` holds rough staging items: auto-captured chat notes, brainstorms, voice transcripts, and drafts.

## Keep
- Architectural or product decisions and why they were made
- Reusable lessons learned, bugs fixed, and non-obvious discoveries
- Project ideas, goals, preferences, and contradictions with older ideas

## Ignore
- Greetings, routine command outputs, and temporary debugging chatter
- Generic facts easily looked up anywhere
```

### 3. `<wiki-root>/inbox/index.md`

```markdown
# Inbox Index

Active rough topic drafts waiting for `compile` into `wiki/`.

<!-- Entries are added as: - [Topic Title](./topic-slug.md) — One-line summary -->
```

### 4. `<wiki-root>/wiki/index.md`

```markdown
---
okf_version: "0.3"
---

# Wiki Index

Content map of compiled OKF pages. Read this file first when querying `wiki/`.
```

### 5. `<wiki-root>/wiki/log.md`

```markdown
# Wiki Log

## [YYYY-MM-DD] setup | Initialized wiki
- Created `raw/`, `inbox/`, and `wiki/` structure with OKF v0.3 configuration.
```

---

## Step 3: Configure Auto-Capture (Skip if User Disabled It)

If the user disabled auto-capture, ensure `<wiki-root>/AGENTS.md` states `auto_capture: disabled` and stop here.

Otherwise, write `<wiki-root>/.llm-wiki/capture.json`:

```json
{
  "wiki_root": "/absolute/path/to/<wiki-root>",
  "prompt_file": "/absolute/path/to/atlasian/prompts/inbox-triage.md",
  "command": [
    "<headless-cli>",
    "<model-and-effort-flags>",
    "<system-prompt-flag-if-supported>",
    "{prompt_file}"
  ],
  "input_mode": "stdin",
  "timeout_seconds": 180,
  "max_retries": 3,
  "min_delta_chars": 80,
  "env": {}
}
```

### Config Notes
- **Restricted permissions (recommended):** If your harness supports tool allowlists, path scoping, or a custom subagent profile, restrict the headless worker to **`Read` and `Write`/`Edit` (plus folder listing if required) inside `<wiki-root>/inbox/` only**. Disable shell, web, and writes to `raw/` or `wiki/`.
- **Built-in defaults (no extra setup questions):** `timeout_seconds` defaults to `180` (3 minutes), `max_retries` defaults to `3` (automatic retry if a run fails or times out), and `min_delta_chars` defaults to `80`. Advanced users can edit `.llm-wiki/capture.json` anytime later.
- **Placeholders supported in `command`:**
  - `{prompt_file}` — Absolute path to `prompts/inbox-triage.md`
  - `{wiki_root}` — Absolute path to `<wiki-root>`
  - `{inbox_dir}` — Absolute path to `<wiki-root>/inbox`
  - `{payload_file}` — Temp file containing the triage instructions + transcript delta
  - `{prompt}` — Inline triage prompt + delta (when `input_mode` is `"arg"`)
- **`input_mode`:**
  - `"stdin"` (default): Pipes the triage request + transcript delta to the command's stdin.
  - `"file"`: Passes `{payload_file}` in `command` (no stdin).
  - `"arg"`: Substitutes `{prompt}` in `command`.

---

## Step 4: Wire a Thin One-Line Hook in Your Harness

Keep all logic inside `scripts/capture_inbox.py`, never inside the hook itself.
Wire your harness's native lifecycle hooks (compaction and session end/reset) to call:

```bash
python3 /absolute/path/to/atlasian/scripts/capture_inbox.py \
  --config /absolute/path/to/<wiki-root>/.llm-wiki/capture.json \
  --event "<event-name>" \
  --session-id "<session-id>" \
  --transcript "<transcript-path>"
```

*(If your harness passes hook payload JSON on stdin—such as `session_id` and `transcript_path`—you may omit `--session-id` and `--transcript`; `capture_inbox.py` reads them automatically from stdin JSON.)*

### Harness-Specific Reminders
- **Pre-compaction vs Post-compaction:** Prefer **pre-compaction** hooks (such as `PreCompact`) when your harness supports them, because raw messages are still intact before summarization drops details. If your harness only provides an **after-compaction** hook (such as Hermes `session:compress`), wire that hook instead. Always also hook session end/reset so short sessions that never compact are still captured.
- **Hermes Agent:**
  - In `session:compress`, check `in_place`: when `in_place` is `false`, pass the `old_session_id` transcript so raw messages are not missed.
  - Gateway hooks (`~/.hermes/hooks/`) run for Gateway sessions; for standalone CLI sessions, wire the Plugin/Observer hooks (`on_session_finalize`, `on_session_reset`).
- **Claude Code / Codex / OpenCode / Others:** Use the harness's native hook config (e.g., `PreCompact` and `SessionEnd`) pointing to the single `python3 .../capture_inbox.py` command above.

---

## Step 5: Verify Setup

Run a non-destructive dry run to validate paths and config:

```bash
python3 /absolute/path/to/atlasian/scripts/capture_inbox.py \
  --config /absolute/path/to/<wiki-root>/.llm-wiki/capture.json \
  --dry-run
```

Confirm it exits with code `0`, then tell the user setup is complete and show them where `<wiki-root>/AGENTS.md` and `<wiki-root>/inbox/AGENTS.md` live so they can edit their rules anytime.
