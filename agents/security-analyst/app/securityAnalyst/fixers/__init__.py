"""Mechanical fix application (spec S8.6, PRD S7.6, story S-136).

Package for the two deterministic fixers -- ``semgrep_autofix.py`` (Semgrep
native-patch application) and ``trivy_bump.py`` (Trivy version-bump
application) -- that make up the first half of `fix` mode's write path.
Both are pure-workspace, single-invocation functions; neither is wired into
the full ``scan -> classify -> fix -> rescan -> open_pr`` orchestration loop
yet (S-140's scope), and neither invokes the LLM escape hatch (``fix_agent.py``,
S-138) -- an unresolved finding is simply reported in ``FixOutcome.unresolved``
for a later story to hand off.
"""

from __future__ import annotations
