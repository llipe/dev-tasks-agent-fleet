---
version: 1.1
name: Ubiquitous Language
description: Canonical domain vocabulary, organized by bounded context. Append-only; terms are superseded, never deleted.
status: active
owner: product-engineer
---

# Ubiquitous Language

The canonical vocabulary of this repository. One term means one thing here, and
the name used in conversation is the name used in the code.

`status: unfilled` means no vocabulary has been established yet — never
permission to invent one. Terms arrive when a PRD or specification proposes them
and the user approves it; `product-engineer` appends them, one entry per term,
grouped under the bounded context they belong to. A term is never deleted: when
it is replaced, its `Status` records what superseded it, so a reader who meets
the old word in an old document can still find out what it meant.

Each term carries five fields — `Definition`, `Forbidden synonyms`, `Invariants`,
`Origin`, and `Status` — and every one of them is present, `none` included.
Bounded-context names resolve against the package map in `docs/tech.md`.

## Changelog

| Version | Date | Summary | Author |
| ------- | ---- | ------- | ------ |
| 1.1 | 2026-11-26 | Approval of `prd-repo-knowledge-views`: +knowledge artifact, +field guide, +dependency graph | product-engineer |

## Bounded Context: panel

### Knowledge artifact

- Definition: A repository-owned file committed at a fixed path that the panel reads live from GitHub and renders: a field guide or a dependency graph.
- Forbidden synonyms: doc snapshot, synced doc
- Invariants: Lives only in the repository's Git tree; the panel never copies it into Supabase and never edits it (repo-knowledge-views#D-06). Read from the default branch with a read-only token (repo-knowledge-views#D-14)
- Origin: `docs/requirements/prd-repo-knowledge-views.md`; repo-knowledge-views#D-16
- Status: active

### Field guide

- Definition: A derived, self-contained HTML guide to a repository under `docs/field-guide/` (entry `index.html`), following the field-guide contract and maintained by `technical-writer`; its sources win over it.
- Forbidden synonyms: wiki, handbook, portal docs
- Invariants: Rendered only inside a sandboxed frame without same-origin access (repo-knowledge-views#D-07). Never decides anything; when it and a source disagree, the source is correct (repo-knowledge-views#D-02)
- Origin: `docs/requirements/prd-repo-knowledge-views.md`; repo-knowledge-views#D-16
- Status: active

### Dependency graph

- Definition: graphify's code-only output at `docs/graph/graph.json`: files and symbols and their `imports`/`calls` relations, in NetworkX node-link format.
- Forbidden synonyms: knowledge graph, code map
- Invariants: Generated without an LLM (`GRAPHIFY_BACKEND=none`) and delivered by PR, never pushed to the default branch (repo-knowledge-views#D-09). Rendered only from a supported `schema_version` (repo-knowledge-views#D-08)
- Origin: `docs/requirements/prd-repo-knowledge-views.md`; repo-knowledge-views#D-16
- Status: active
