# Fidelity-report fixtures (S-208)

Inputs for `context/verifier.py` (`tests/unit/test_verifier_candidates.py`,
`tests/unit/test_properties_verifier.py`). Load them with
`tests.helpers.reports.report_text(<file name>)`, which reads the bytes and
decodes UTF-8, so the line endings are exactly the ones on disk.

| File | Shape | Expected |
| --- | --- | --- |
| `fidelity-report-S-170.md` | Byte copy of `workstream/fidelity-report-S-170.md` (real verifier output): `## Drift` with `# \| Finding \| Type \| Impact` columns | `parsed`, 0 candidates, 3 other drift |
| `fidelity-report-ac7.md` | Synthetic AC-7 report: `## Drift catalog` with one `Critical`+`Unintended` row and one `Major`+`Unintended` row; a qualifying row in a later `## Recommendations` table | `parsed`, 1 candidate (row 1), 1 other drift |
| `fidelity-report-no-heading.md` | No drift heading; a qualifying row under `## Findings` | `not_parseable` |
| `fidelity-report-empty.md` | Empty file | `not_parseable` |
| `fidelity-report-no-table.md` | `## Drift` with a bullet list, no table | `parsed`, 0 candidates, 0 other drift |
| `fidelity-report-numbered.md` | `## 3. Drift catalog` (the numbered verifier template) | `parsed`, 1 candidate (D-44 numeric prefix) |
| `fidelity-report-S-207.md` | Byte copy of `workstream/fidelity-report-S-207.md` (real, numbered): `## 3. Drift catalog`, 10 Minor rows | `parsed`, 0 candidates, 10 other drift (D-44) |

The synthetic reports are not verifier output; they exist to pin the parser.
