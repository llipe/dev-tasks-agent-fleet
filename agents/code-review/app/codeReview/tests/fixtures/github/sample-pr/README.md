# Recorded GitHub fixtures — `sample-pr`

Responses for PR `acme/widgets#42`, in the GitHub REST v3 shapes the client
reads (spec §6.2). They were authored from the documented response schemas,
not captured from a live repository, and contain **no real tokens, SHAs, or
accounts**. `routes.json` maps each request (method, encoded path, query) to a
body file; `tests/helpers/github_stub.py::load_fixture("sample-pr")` turns it
into a `StubTransport`.

Contents of the sample:

- PR #42 (open, not draft), head `9f2c4e1…`, base `3a5c7e9…`, merge base `7e1d3c5…`.
- Five changed files: `src/app.py` (modified), `docs/notes with space.md` (added; a
  path with a space), `src/new_name.py` (renamed from `src/old_name.py`),
  `pnpm-lock.yaml` (lockfile), `assets/logo.png` (binary, no `patch`).
- Contents at the merge base and head for the reviewed files, `AGENTS.md`, one ADR,
  and a 404 for `workstream/specification-prd-widgets.md` and `workstream/`.
- `docs/adr` directory listing (two files, one subdirectory).
- Issue #41 (labels `prd:widgets`, `type:feature`; a `Task Checklist` heading) and
  issue #40, which is a pull request (`pull_request` key present, `body: null`).
- The `201 Created` response for the one allowed write, a comment on #42.

S-206–S-213 reuse this sample; add routes rather than editing existing ones.
