# atlasian — One-Time Setup Guide

Read this file only during initial setup (or when the user asks to reconfigure `atlasian`).
Once `<wiki-root>` and `<wiki-root>/AGENTS.md` exist, do not open this file during normal wiki operations.

**Never edit files inside the `atlasian` skill folder during setup.** Keep the cloned skill repo clean so `git pull` updates never conflict. Write all user rules and content inside `<wiki-root>`.

---

## Step 1: Ask the User Before Creating Any Files

**IMPORTANT — Interactive Gate:** Do **NOT** assume defaults or create any folder or file yet. Ask the user both questions below, then **STOP and wait for their answers** before running Step 2.

1. **Wiki location & name:** Where should the wiki folder live?
   - Default suggestion: `~/llm-wiki` (or `./llm-wiki` inside the current workspace). The user can choose any name or path.
2. **OKF v0.3 optional fields & page types:**
   - First read `references/okf-v0.3-fields.md` in this skill folder so you have the exact YAML format and meaning for every OKF v0.3 field.
   - Show the personal starter set (`type`, `title`, `description`, `tags`, `sources`, `generated`) and ask which optional fields the user wants to keep, remove, or add (such as `status`, `superseded_by`, `stale_after`, `verified`, `resource`, `usage_window`, `license`, or computation fields).
   - Show starter page types (`concept`, `project`, `goal`, `decision`, `person`, `source`), explain that types are 100% customizable, and ask what types they want in `<wiki-root>/AGENTS.md`.

> **STOP HERE** until the user answers both questions above. Only then continue to Step 2.

---

## Step 2: Create the Wiki Folder & Starter Files

Create these folders if they do not exist (never overwrite existing user content):

```text
<wiki-root>/
├── raw/
├── inbox/
└── wiki/
```

Create starter files only if missing:

### 1. `<wiki-root>/AGENTS.md`

Write the user's chosen preferences here (adjust enabled fields, template, and page types to match the user's exact answers from Step 1):

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

## Personal Preferences
<!-- Add wiki-wide tone, language, or general layout preferences here.
     Keep folder-specific rules inside each folder's own index.md, not here. -->
```

### 2. `<wiki-root>/inbox/AGENTS.md`

```markdown
# Inbox Rules (inbox/AGENTS.md)

Use this file to guide what belongs in `inbox/`.
`inbox/` holds rough staging items: brainstorms, voice transcripts, quick chat saves, and rough drafts.

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

## Step 3: Finish

Tell the user setup is complete and show them where `<wiki-root>/AGENTS.md` and `<wiki-root>/inbox/AGENTS.md` live so they can edit their rules anytime. Remind them they can drop finished files into `raw/`, drop rough brainstorms or voice transcripts into `inbox/`, or simply tell their agent *"save this decision to my wiki"* whenever something is worth keeping.
