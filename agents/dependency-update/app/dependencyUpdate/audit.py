"""
Audit runner — executes pnpm/npm audit and parses JSON output.

Provides:
  - ``run_audit(workspace, pm)`` — run the audit command, return raw JSON dict.
  - ``count_vulns(audit_result, pm)`` — count vulnerabilities by severity.
  - ``extract_advisories(audit_result, pm)`` — normalize advisories from both
    pnpm and npm JSON shapes into a uniform list of dicts.
  - ``snapshot_lockfile_packages(workspace, pm)`` — {name: version} from lockfile.
  - ``diff_packages(before, after)`` — compute changes between two snapshots.
  - ``count_advisories_fixed(before, after)`` — advisory ID-set diff (issue #90).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field

from config import TOOL_COMMAND_TIMEOUT


@dataclass
class AuditResult:
    """Structured audit result with raw data and extracted metadata."""

    raw: dict = field(default_factory=dict)
    vuln_counts: dict[str, int] = field(default_factory=dict)
    total_vulns: int = 0
    advisories: list[dict] = field(default_factory=list)


@dataclass
class PackageChange:
    """A single package change between two snapshots."""

    name: str
    action: str  # "added" | "removed" | "updated"
    old_version: str | None = None
    new_version: str | None = None


def run_audit(workspace: str, pm: str) -> AuditResult:
    """
    Run ``pnpm audit --json`` or ``npm audit --json`` and return an AuditResult.

    The audit command exits non-zero when vulnerabilities are found, which is
    expected. We capture the JSON output regardless of exit code (only raise on
    actual execution failures like command not found).
    """
    cmd = ["pnpm", "audit", "--json"] if pm == "pnpm" else ["npm", "audit", "--json"]

    try:
        result = subprocess.run(
            cmd,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=TOOL_COMMAND_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Failed to run {pm} audit: {exc}") from exc

    # Parse JSON output (available on stdout even with non-zero exit code)
    raw: dict = {}
    if result.stdout.strip():
        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError:
            # If JSON parsing fails, return empty result
            return AuditResult()

    advisories = extract_advisories(raw, pm)
    vuln_counts = count_vulns(raw, pm)
    total = sum(vuln_counts.values())

    return AuditResult(
        raw=raw,
        vuln_counts=vuln_counts,
        total_vulns=total,
        advisories=advisories,
    )


def count_vulns(audit_result: dict, pm: str) -> dict[str, int]:
    """
    Count vulnerabilities by severity from the raw audit JSON.

    Handles both pnpm and npm JSON shapes:
      - pnpm: ``metadata.vulnerabilities`` → {severity: count}
      - npm: ``metadata.vulnerabilities`` → {severity: count}

    Both use the same path in recent versions.
    """
    metadata = audit_result.get("metadata", {})
    vulns = metadata.get("vulnerabilities", {})

    if not isinstance(vulns, dict):
        return {}

    # Both pnpm and npm use {severity: count} in metadata.vulnerabilities
    # but npm sometimes nests with "total" key per severity object
    counts: dict[str, int] = {}
    for severity, value in vulns.items():
        if isinstance(value, int):
            counts[severity] = value
        elif isinstance(value, dict):
            # npm v9+ may use {severity: {total: N, ...}}
            counts[severity] = value.get("total", 0)

    return counts


def extract_advisories(audit_result: dict, pm: str) -> list[dict]:
    """
    Extract and normalize advisories from audit JSON into a uniform shape.

    Normalized advisory dict keys:
      - id, module_name, severity, title, url, cves, patched_versions

    Handles:
      - pnpm: ``advisories`` dict keyed by advisory ID, each with nested data.
      - npm v7+: ``vulnerabilities`` dict keyed by package name, with ``via``
        entries that contain the advisory details.
    """
    if pm == "pnpm":
        return _extract_pnpm_advisories(audit_result)
    else:
        return _extract_npm_advisories(audit_result)


def _extract_pnpm_advisories(audit_result: dict) -> list[dict]:
    """
    Extract advisories from pnpm audit JSON.

    pnpm format (v8+):
      {
        "advisories": {
          "<id>": {
            "id": <int>,
            "module_name": "...",
            "severity": "...",
            "title": "...",
            "url": "...",
            "cves": [...],
            "patched_versions": ">=X.Y.Z",
            "findings": [{"version": "...", ...}],
            ...
          }
        }
      }
    """
    advisories_dict = audit_result.get("advisories", {})
    if not isinstance(advisories_dict, dict):
        return []

    result: list[dict] = []
    for _key, adv in advisories_dict.items():
        if not isinstance(adv, dict):
            continue
        result.append(
            {
                "id": adv.get("id", _key),
                "module_name": adv.get("module_name", "unknown"),
                "severity": adv.get("severity", "unknown"),
                "title": adv.get("title", ""),
                "url": adv.get("url", ""),
                "cves": adv.get("cves", []),
                "patched_versions": adv.get("patched_versions", ""),
            }
        )

    return result


def _extract_npm_advisories(audit_result: dict) -> list[dict]:
    """
    Extract advisories from npm audit JSON (v7+ format).

    npm v7+ format:
      {
        "vulnerabilities": {
          "<package-name>": {
            "name": "...",
            "severity": "...",
            "via": [
              {
                "source": <int>,
                "name": "...",
                "severity": "...",
                "title": "...",
                "url": "...",
                "range": "...",
                ...
              }
              // or just a string for transitive
            ],
            "range": "...",
            "fix": {"available": true, ...},
            ...
          }
        }
      }
    """
    vulns = audit_result.get("vulnerabilities", {})
    if not isinstance(vulns, dict):
        return []

    # Deduplicate by source ID (same advisory can appear in multiple packages)
    seen_sources: set[int | str] = set()
    result: list[dict] = []

    for pkg_name, vuln_info in vulns.items():
        if not isinstance(vuln_info, dict):
            continue

        via_list = vuln_info.get("via", [])
        if not isinstance(via_list, list):
            continue

        for via in via_list:
            # Skip string entries (transitive dependency references)
            if isinstance(via, str):
                continue
            if not isinstance(via, dict):
                continue

            source_id: int | str = via.get("source") or via.get("url") or ""
            if source_id in seen_sources:
                continue
            seen_sources.add(source_id)

            result.append(
                {
                    # Use the same source-or-url fallback as the dedup key so the
                    # advisory ID is stable and unique even when npm omits the
                    # numeric `source` — otherwise multiple such advisories would
                    # collapse to id="" and under-count in the ID-set diff (#90).
                    "id": via.get("source") or via.get("url") or "",
                    "module_name": via.get("name", pkg_name),
                    "severity": via.get("severity", vuln_info.get("severity", "unknown")),
                    "title": via.get("title", ""),
                    "url": via.get("url", ""),
                    "cves": via.get("cves", []),
                    "patched_versions": via.get("range", ""),
                }
            )

    return result


def snapshot_lockfile_packages(workspace: str, pm: str) -> dict[str, str]:
    """
    Return {package_name: version} across the whole install tree.

    Uses a workspace-aware, recursive listing so that in a monorepo/workspace
    layout the snapshot includes every workspace package's dependencies and the
    transitive dependencies the lockfile actually resolved — not just the root
    package's top-level deps (issue #90):

      - pnpm: ``pnpm list -r --depth Infinity --json`` (``-r`` traverses all
        workspace packages; ``--depth Infinity`` walks transitive deps).
      - npm:  ``npm list --all --json`` (``--all`` walks the full tree).

    The previous ``--depth 0`` listing saw none of the workspace or transitive
    changes on a turbo monorepo, so ``diff_packages`` reported zero changes.
    """
    if pm == "pnpm":
        cmd = ["pnpm", "list", "-r", "--depth", "Infinity", "--json"]
    else:
        cmd = ["npm", "list", "--all", "--json"]

    try:
        result = subprocess.run(
            cmd,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=TOOL_COMMAND_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Failed to run {pm} list: {exc}") from exc

    if not result.stdout.strip():
        return {}

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}

    return _parse_list_json(data, pm)


def _collect_deps(deps: dict, packages: dict[str, str]) -> None:
    """
    Recursively collect {name: version} from a nested dependencies mapping.

    Both pnpm (`list -r --depth Infinity`) and npm (`list --all`) nest transitive
    dependencies under a ``dependencies`` key on each dependency node. Walking
    that tree captures workspace-package and transitive changes the lockfile
    reconcile applied (issue #90). The first version seen for a name wins — the
    snapshot only needs presence + a representative version for the diff.
    """
    if not isinstance(deps, dict):
        return
    for name, info in deps.items():
        if not isinstance(info, dict):
            continue
        if "version" in info and name not in packages:
            packages[name] = str(info["version"])
        nested = info.get("dependencies")
        if isinstance(nested, dict):
            _collect_deps(nested, packages)


def _parse_list_json(data: dict | list, pm: str) -> dict[str, str]:
    """
    Parse the JSON output of pnpm/npm list into {name: version}.

    pnpm ``list -r --json`` returns a list of workspace entries:
      [{"name": "...", "dependencies": {"pkg": {"version": "...", "dependencies": {...}}}, ...}]

    npm ``list --all --json`` returns a single object with nested dependencies:
      {"name": "...", "dependencies": {"pkg": {"version": "...", "dependencies": {...}}}}

    Both are walked recursively so workspace-package and transitive dependencies
    are captured, not only the root's top-level deps (issue #90).
    """
    packages: dict[str, str] = {}

    entries: list = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        _collect_deps(entry.get("dependencies", {}), packages)
        _collect_deps(entry.get("devDependencies", {}), packages)

    return packages


def diff_packages(before: dict[str, str], after: dict[str, str]) -> list[PackageChange]:
    """
    Compute the difference between two package snapshots.

    Returns a list of PackageChange entries for added, removed, and updated packages.
    """
    changes: list[PackageChange] = []

    all_names = sorted(set(before.keys()) | set(after.keys()))
    for name in all_names:
        old_ver = before.get(name)
        new_ver = after.get(name)

        if old_ver is None and new_ver is not None:
            changes.append(PackageChange(name=name, action="added", new_version=new_ver))
        elif old_ver is not None and new_ver is None:
            changes.append(PackageChange(name=name, action="removed", old_version=old_ver))
        elif old_ver != new_ver:
            changes.append(
                PackageChange(name=name, action="updated", old_version=old_ver, new_version=new_ver)
            )

    return changes


def count_advisories_fixed(before: list[dict], after: list[dict]) -> int:
    """
    Count advisories resolved between the pre- and post-update audits (issue #90).

    Correct measure = the number of distinct advisory IDs present in the
    before-audit but absent in the after-audit. This deliberately replaces the
    old ``(in_range before) - (in_range after)`` bucket subtraction, which
    reported 0 on any repo where no advisory was ever classified ``in_range``
    (e.g. a monorepo whose advisories all land in the ``unknown`` bucket) even
    though real advisories disappeared across the update.

    Advisories that appear only in ``after`` (newly introduced) are ignored —
    they are not "fixed" — so the result is never negative. IDs are deduplicated
    before counting.

    Both arguments are the normalized advisory dicts produced by
    ``extract_advisories`` (each with an ``id`` key).
    """
    before_ids = {adv.get("id") for adv in before if adv.get("id")}
    after_ids = {adv.get("id") for adv in after if adv.get("id")}
    return len(before_ids - after_ids)
