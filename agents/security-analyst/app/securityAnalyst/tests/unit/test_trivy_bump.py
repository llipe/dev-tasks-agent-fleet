"""
Unit tests for `fixers/trivy_bump.py`'s pure, no-I/O helper functions (spec
S8.6, PRD requirement 27's second bullet, story S-136, task 12.7).

Covers the "Trivy bump target-version selection as a pure function"
requirement: `_bump_manifest_text()` takes manifest text in and returns
either the bumped text or `None`, with no file I/O or subprocess call, so
these cases are exercised directly against fixture strings -- mirroring
`test_trivy_runner.py`'s direct-unit-test convention for
`_lowest_fixed_version()`.
"""

from __future__ import annotations

from fixers.trivy_bump import _bump_line, _bump_manifest_text, _name_pattern


class TestNamePattern:
    def test_matches_exact_case_insensitive(self):
        pattern = _name_pattern("Requests")
        assert pattern.match("requests==2.25.0\n")

    def test_hyphen_underscore_interchangeable(self):
        pattern = _name_pattern("some-package")
        assert pattern.match('some_package = "1.0.0"\n')
        assert pattern.match("some-package==1.0.0\n")

    def test_does_not_match_substring_package(self):
        # "requests" must not match a line for an unrelated package whose
        # name merely contains it as a substring.
        pattern = _name_pattern("requests")
        assert pattern.match("requests-toolbelt==1.0.0\n") is None

    def test_does_not_match_unrelated_line(self):
        pattern = _name_pattern("requests")
        assert pattern.match("jinja2==3.0.0\n") is None


class TestBumpLine:
    def test_prefers_exact_current_version_match(self):
        result = _bump_line("requests==2.25.0\n", "2.25.0", "2.31.0")
        assert result == "requests==2.31.0\n"

    def test_falls_back_to_first_version_shaped_token_when_current_unknown(self):
        result = _bump_line('jinja2 = "^2.11.2"\n', None, "2.11.3")
        assert result == 'jinja2 = "^2.11.3"\n'

    def test_falls_back_when_current_version_not_present_on_line(self):
        # current_version doesn't literally appear (e.g. resolved elsewhere)
        # -- falls back to the generic version-shaped substring.
        result = _bump_line("pyyaml==5.3.0\n", "5.3", "5.4")
        assert result == "pyyaml==5.4.0\n"

    def test_returns_none_when_no_version_substring_present(self):
        # An unpinned Pipfile entry ("*") has nothing to bump.
        assert _bump_line('pyyaml = "*"\n', None, "5.4") is None


class TestBumpManifestText:
    def test_bumps_requirements_txt_pinned_line(self):
        text = "flask==2.0.0\nrequests==2.25.0\npyyaml==5.3\n"
        result = _bump_manifest_text(text, "requests", "2.25.0", "2.31.0")
        assert result == "flask==2.0.0\nrequests==2.31.0\npyyaml==5.3\n"

    def test_bumps_poetry_pyproject_dependency_line(self):
        text = '[tool.poetry.dependencies]\npython = "^3.13"\njinja2 = "^2.11.2"\n'
        result = _bump_manifest_text(text, "jinja2", "2.11.2", "2.11.3")
        assert result == ('[tool.poetry.dependencies]\npython = "^3.13"\njinja2 = "^2.11.3"\n')

    def test_bumps_pipfile_dependency_line(self):
        text = '[packages]\npyyaml = "==5.3"\n'
        result = _bump_manifest_text(text, "pyyaml", "5.3", "5.4")
        assert result == '[packages]\npyyaml = "==5.4"\n'

    def test_returns_none_when_package_absent_from_manifest(self):
        text = "flask==2.0.0\n"
        assert _bump_manifest_text(text, "requests", "2.25.0", "2.31.0") is None

    def test_returns_none_when_matched_line_has_no_bumpable_version(self):
        text = '[packages]\npyyaml = "*"\n'
        assert _bump_manifest_text(text, "pyyaml", None, "5.4") is None

    def test_only_edits_the_first_matching_line(self):
        # Defensive: a malformed manifest with an accidental duplicate
        # declaration only has its first occurrence edited, never both.
        text = "requests==2.25.0\nrequests==2.25.0\n"
        result = _bump_manifest_text(text, "requests", "2.25.0", "2.31.0")
        assert result == "requests==2.31.0\nrequests==2.25.0\n"

    def test_case_insensitive_and_normalized_package_name_match(self):
        text = "Some_Package==1.0.0\n"
        result = _bump_manifest_text(text, "some-package", "1.0.0", "2.0.0")
        assert result == "Some_Package==2.0.0\n"
