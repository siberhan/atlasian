---
name: atlasian
description: Build, capture, compile, query, and maintain a living Markdown knowledge base (LLM Wiki) using Open Knowledge Format (OKF v0.3), immutable raw/ sources, an inbox/ staging layer for chat hooks and rough ideas, and customizable AGENTS.md user rules.
---

# atlasian — Living Markdown Knowledge Base (OKF v0.3)

Maintain a persistent, interlinked Markdown wiki that compounds knowledge over time without vector databases, embeddings, or vendor lock-in.

---

## 0. First Steps — Setup Check & Always Read `AGENTS.md`

1. **Locate `<wiki-root>`:** Use the user's configured wiki folder path (default: `llm-wiki`, customizable at setup).
2. **One-time setup gate:** If `<wiki-root>` does not exist, or if `<wiki-root>/.llm-wiki/capture.json` is missing (and `<wiki-root>/AGENTS.md` does not explicitly disable auto-capture), read `SETUP.md` in this skill folder and run setup first. Once configured, do not read `SETUP.md` again unless the user asks to reconfigure.
3. **Read `<wiki-root>/AGENTS.md` first:** Before performing any wiki operation (`ingest`, `compile`, `query`, `lint`), read `<wiki-root>/AGENTS.md` if it exists.
4. **User rules win (keep `AGENTS.md` global & slim):** `<wiki-root>/AGENTS.md` is the user's wiki-wide rulebook (enabled OKF fields, custom page types, tone, general layout rules). Whenever `<wiki-root>/AGENTS.md` conflicts with defaults in this `SKILL.md`, follow `<wiki-root>/AGENTS.md`. Do **not** list individual topic folders or folder-specific rules in root `AGENTS.md`—`wiki/index.md` is the folder map, and any folder-specific rules belong inside that folder's own `<folder>/index.md`.

---

## 1. Architecture (3 Layers)

```text
<wiki-root>/
├── AGENTS.md                 # Optional: user rules and OKF field preferences (read first)
├── .llm-wiki/
│   ├── capture.json          # Auto-capture config created during setup
│   └── state.json            # Per-session delta watermarks for hook capture
├── raw/                      # Immutable finished sources (articles, PDFs, web clips)
├── inbox/                    # Staging area: hook notes, brainstorms, voice transcripts
│   ├── AGENTS.md             # Optional: user filter rules for inbox/
│   ├── index.md              # Map of active rough topic drafts in inbox/
│   └── *.md                  # Rough notes waiting for compilation
└── wiki/                     # OKF v0.3 compiled knowledge base (LLM-owned)
    ├── index.md              # Content map of the wiki (read first on queries)
    └── log.md                # Append-only chronological activity log
```

- **`raw/` (Read-Only):** Curated, finished sources added by the user. **Never edit, rename, or delete files in `raw/`.**
- **`inbox/` (Staging Area):** Rough inputs not ready for `wiki/` yet—auto-captured notes from chat hooks (compaction, reset, session end), quick brainstorms, voice memo transcripts, and rough drafts. Cleaned after compilation.
- **`wiki/` (Compiled Knowledge):** Structured, cross-linked OKF Markdown pages maintained by the agent.

---

## 2. OKF v0.3 Format & 2-Step Reading

Every concept page in `wiki/` (excluding `index.md` and `log.md`) starts with YAML frontmatter. OKF v0.3 strictly requires only `type`:

```yaml
---
type: <user-defined page type>
---
```

### User-Controlled OKF v0.3 Optional Fields (`AGENTS.md`)

Do **not** invent or force optional frontmatter fields that the user did not enable.
- **Source of truth:** Follow the **Enabled OKF v0.3 Frontmatter Fields** and **Active Frontmatter Template** in `<wiki-root>/AGENTS.md` and write ONLY those fields.
- **Fallback (if `AGENTS.md` has no field list yet):** Use only `type`, `title`, and `description`.
- **To add or change optional fields later:** Read `references/okf-v0.3-fields.md` in this skill folder for exact OKF v0.3 YAML syntax, then update `<wiki-root>/AGENTS.md`.
- **To disable a field later:** Remove it from `<wiki-root>/AGENTS.md`.

### Links, Reading & Splitting

- **Standard Markdown relative links only:** Prefer relative Markdown links (`[Page Title](./page.md)`, `[Sub Page](./folder/page.md)`, `[Other](../other/page.md)`) inside `wiki/`—never `[[wikilinks]]`, and **never** prefix links with `/wiki/` (`wiki/` itself is the OKF bundle root, so relative links work everywhere: OKF viewers, Obsidian, GitHub, and all agents). Keep paths case-sensitive and percent-encode spaces if any exist.
- **2-Step Reading (Zero Embeddings):**
  1. **Step 1 — Map:** Read `wiki/index.md` first (and `<folder>/index.md` if that folder was split). Pick only matching pages. Use `rg` (ripgrep) across `wiki/` when searching tags, metadata, or exact terms.
  2. **Step 2 — Full Page:** Open full Markdown bodies only for the selected pages.
- **Lazy Splitting & Folder Rules:** Start flat with a single root `wiki/index.md` (unless `<wiki-root>/AGENTS.md` specifies a folder-per-topic layout). Do not create empty subfolder `index.md` files upfront; add `<folder>/index.md` when a folder grows past ~25–30 files (or when the user creates a dedicated topic folder), keeping a one-line summary + link in root `wiki/index.md`. Keep any folder-specific rules (what belongs in the folder, subfolder conventions) inside `<folder>/index.md`—never duplicate them in root `AGENTS.md`—and always read `<folder>/index.md` before writing inside that folder.

---

## 3. Core Operations

### Ingest (`raw/` → `wiki/`)
1. Read `<wiki-root>/AGENTS.md` and the new source file(s) in `raw/`. Never modify `raw/`.
2. If working interactively, summarize key takeaways and confirm what to emphasize (or batch-ingest if the user asks).
3. Create or update relevant pages in `wiki/` using the user's configured OKF frontmatter and standard Markdown cross-links.
4. Update `wiki/index.md` (or the relevant subfolder `index.md`) and append an entry to `wiki/log.md`.

### Compile (`inbox/` → `wiki/`)
1. Read `<wiki-root>/AGENTS.md` (and `inbox/AGENTS.md` if present). If `<wiki-root>/.llm-wiki/failed.json` exists with pending failed captures, offer to recover them first (`python3 <atlasian>/scripts/capture_inbox.py --config <wiki-root>/.llm-wiki/capture.json --retry-failed`). Then inspect `inbox/index.md` and all pending items in `inbox/` (auto-captured chat notes, brainstorms, voice transcripts, rough drafts).
2. Filter aggressively: discard conversational noise, dead ends, and low-value chatter.
3. Integrate surviving ideas, decisions, and facts into existing or new OKF pages in `wiki/`, recording provenance in `sources` or `resource` (for example `session:<session_id>` or `inbox/<file>.md`).
4. Update `wiki/index.md` and `wiki/log.md`. Remove or clear compiled items from `inbox/` and refresh `inbox/index.md`.

### Query (`wiki/` → Answer)
1. Read `<wiki-root>/AGENTS.md`. Scan `wiki/index.md` (and use `rg` if needed) to find candidate pages.
2. Open only the relevant pages and synthesize a direct answer with standard Markdown links to cited pages.
3. **Compound good answers:** If the query produces valuable synthesis (a comparison, trade-off analysis, or newly discovered connection), offer to file it into `wiki/` as a new OKF page and update `index.md` and `log.md`.

### Lint (Health Check)
- **Passive (Boy Scout Rule):** Whenever you open a page during normal work, fix small broken links, stale descriptions, or missing `index.md` entries you notice.
- **Active (On Request):** Audit `wiki/` for contradictions between pages, outdated claims (`stale_after` or superseded facts), orphan pages with no inbound links, missing cross-references, and folders ready for lazy splitting. Record the audit in `wiki/log.md`.

---

## 4. Knowledge Quality Principles

- **Signal over volume:** Do not bloat `wiki/` with trivia or easily re-derivable boilerplate.
- **Resolve conflicts, do not pile them up:** When new evidence contradicts an older claim, update the claim clearly, mark deprecated pages with `status: deprecated` / `superseded_by` (if enabled), or flag the conflict explicitly.
- **Preserve nuance:** Patch targeted sections instead of rewriting an entire page and losing subtle details.

---

## 5. Logging (`wiki/log.md`)

Keep `wiki/log.md` as an append-only chronological log with a consistent heading prefix so simple CLI tools (`grep "^## \[" wiki/log.md | tail -5`) can parse it:

```markdown
## [YYYY-MM-DD] ingest | Short Title
- Summary of pages created or updated and key links added.
```

Use operation tags: `ingest`, `compile`, `query`, `lint`, `setup`.

---

## 6. Modularity

Everything beyond the core contract (`AGENTS.md` first, immutable `raw/`, OKF frontmatter + standard Markdown links, `index.md` + `log.md`) is optional. Adapt folder structure, page types, optional OKF fields, output formats, and local search tools (such as `rg` or `qmd` at large scale) in `<wiki-root>/AGENTS.md` as the wiki grows.
