# OKF v0.3 Frontmatter Field Reference

Read this file during setup (`SETUP.md`) or whenever the user asks to add or change optional OKF v0.3 fields in `<wiki-root>/AGENTS.md`.
When enabling a field for a user, copy its exact YAML structure into `<wiki-root>/AGENTS.md` so future agent turns use valid OKF v0.3 syntax without guessing.

---

## Required Field (Every Concept Page in `wiki/`)

- **`type`** *(string, non-empty)* — Category of the page. Any word is valid (user-defined in `<wiki-root>/AGENTS.md`).

```yaml
type: concept
```

---

## Personal Wiki Defaults (Recommended)

- **`title`** *(string)* — Human-readable page title.
- **`description`** *(string)* — One-line summary copied into `wiki/index.md`.
- **`tags`** *(list of strings)* — YAML list of tags (never a comma-separated string).
- **`sources`** *(list of objects)* — Source files, URLs, or chat sessions this page derives from. Only `resource` is needed for simple use; extra sub-fields are optional.
- **`generated`** *(object)* — Records who created/updated the page (`by`) and when (`at`, ISO 8601 UTC).

```yaml
---
type: concept
title: Concise Page Title
description: One-line summary copied into index.md
tags: [tag-one, tag-two]
sources:
  - resource: raw/example.md
    # Optional sub-fields: id, title, author, usage_count, last_modified
generated:
  by: atlasian
  at: 2026-11-19T12:00:00Z
---
```

---

## Optional Concept Fields (Opt-In)

### Provenance & Trust
- **`resource`** *(string / URI)* — Direct external URL or canonical path that this page describes.
- **`usage_window`** *(object)* — Time range (`from`, `to`) for `usage_count` values inside `sources`.
- **`verified`** *(list of objects)* — Records who (`by`, e.g., `human:alice`) confirmed the page against its sources and when (`at`, ISO 8601 UTC).

```yaml
resource: https://example.com/system/orders
usage_window:
  from: 2026-10-01T00:00:00Z
  to: 2026-11-01T00:00:00Z
verified:
  - by: human:alice
    at: 2026-11-19T12:30:00Z
```

### Lifecycle & Freshness
- **`status`** *(string)* — `draft`, `stable`, or `deprecated`. *(If omitted, OKF treats the page as `stable`.)*
- **`superseded_by`** *(string)* — Path to the replacement page when `status: deprecated`.
- **`stale_after`** *(string, ISO 8601 UTC)* — Date/time after which this page should be reviewed or re-verified.

```yaml
status: deprecated
superseded_by: /decisions/new-architecture.md
stale_after: 2027-01-01T00:00:00Z
```

### Attested Computation (Advanced)
Use only when a page defines a runnable, verifiable computation:
- **`runtime`** *(string)* — Runtime environment needed to execute the computation.
- **`parameters`** *(list of objects)* — Typed inputs (`name`, `type`, `required`).
- **`computation`** *(string)* — Path to the computation code file.
- **`executor`** *(object)* — Execution target (`resource`) and required `receipt` fields.
- **`attester`** *(object)* — Deterministic verifier (`resource`) that checks receipts.

```yaml
runtime: python3
parameters:
  - name: start_date
    type: string
    required: true
computation: /computations/metrics.py
executor:
  resource: local-python
  receipt: [exit_code, output_hash]
attester:
  resource: /computations/verify.py
```

---

## Bundle-Root Only Fields (`wiki/index.md` Only)

Subfolder `index.md` files must omit frontmatter. Only root `wiki/index.md` may declare:
- **`okf_version`** *(string)* — Spec version (`"0.3"`).
- **`license`** *(string)* — SPDX license expression (e.g., `"MIT"`) or path to license file.

```yaml
---
okf_version: "0.3"
license: MIT
---
```
