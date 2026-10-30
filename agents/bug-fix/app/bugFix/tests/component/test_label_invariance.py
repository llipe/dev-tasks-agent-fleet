"""RT-13: labels have no effect (FR-3; AC-2; S-185 business rule; D-90, D-93).

Property-based, on the request log of the in-repo GitHub double (DF-186-02).
For each refusal fixture and the proceed fixture, a random label set on the
issue leaves the verdict, the outcome and the ordered GitHub writes (method and
path) equal to the zero-label control. No request path contains ``/labels``,
and no request body carries a label name.

Replay: ``make test PYTEST_ADDOPTS="--hypothesis-seed=<seed> -k test_label_invariance"``.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.component.test_refusal import _check, _gh_for, _params_for, _write_templates

FIXTURES = ("proceed", "pull_request", "closed", "linked_pr", "active_run", "invalid_params")

_ALPHABET_LABELS = st.sampled_from(
    [
        "status: in-progress",
        "status: blocked",
        "status: ready",
        "type: bug",
        "wontfix",
        "bug-fix:claimed",
        "🐛 bug",
        "x" * 50,
    ]
)
# Random names carry a prefix no fixed reply text contains, so the body oracle
# below holds for every drawn label.
_LABEL = st.one_of(_ALPHABET_LABELS, st.text(max_size=50).map(lambda s: f"lbl~{s}"))
_LABELS = st.lists(_LABEL, max_size=20, unique=True)

_CONTROL: dict[str, tuple] = {}


def _control(code: str) -> tuple:
    if code not in _CONTROL:
        gh, sb = _gh_for(code)
        out = _check(gh, sb, params=_params_for(code))
        _CONTROL[code] = (out.status, out.outcome, out.reason, _write_templates(gh))
    return _CONTROL[code]


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.sampled_from(FIXTURES), _LABELS)
def test_label_invariance(code, labels):
    gh, sb = _gh_for(code, labels=tuple(labels))
    out = _check(gh, sb, params=_params_for(code))
    assert (out.status, out.outcome, out.reason, _write_templates(gh)) == _control(code)
    assert not any("/labels" in path for path in gh.paths())
    for call in gh.writes():
        body = str(call.json)
        for label in labels:
            assert label not in body
