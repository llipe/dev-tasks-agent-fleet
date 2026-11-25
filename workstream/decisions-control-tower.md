# Decision Log: control-tower

| ID | Phase | Branch | Question | Recommended | Answer | Accepted rec. | Supersedes | Author | Date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D-01 | WHAT | context/parallel-lanes | What is "parallel-lanes"? | — | A dev-tasks working mode (skill `parallel-lanes` in `llipe/dev-tasks`) that enables persistent multi-agent workflows: a permanent crew (danny coordinator, rusty prep, linus/basher/yen execution), one lane per worktree, live state in `workstream/lanes/` on an unmerged `coordination` branch. Control Tower must work with and without it. | n/a | — | @llipe / product-engineer | 2026-11-25 |
| D-02 | WHAT | context/prior-art | Is there prior art for this view? | — | Yes. `llipe/dev-tasks` `prd-factory-board.md` (parked 2026-10-20, `projects-tracking#D-01`): `dev-tasks board` static page from PRDs, roadmap, workstream and GitHub; excluded agent activity (`factory-board#D-04`). `prd-projects-tracking` waves 1–3 are Done (PRD/wave tracking issues, sub-issues, status comments). Found by reading the dev-tasks repo. | n/a | — | product-engineer | 2026-11-25 |
