"""AgentCore Runtime entrypoint: autonomous dependency updater."""

import json
import os
import subprocess
import tempfile
import threading
import time
from datetime import UTC, datetime

import boto3
import requests
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent, tool

from emission import emit_span_attributes, map_result
from logging_json import JsonLogger
from outcome_store import stamp_outcome
from payload import PayloadError, parse_payload

# ─────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────

MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6")
SECRET_ID = os.environ.get("GITHUB_SECRET_ID", "dep-agent/github-pat")
TEST_TIMEOUT = int(os.environ.get("TEST_TIMEOUT", "600"))

# Set per-invocation. Tools read it instead of taking a path argument,
# so the model cannot wander outside the checkout.
_workspace: str | None = None

# Module-level logger, initialized per invocation in _run_pipeline.
_log: JsonLogger | None = None


def _ws() -> str:
    if _workspace is None:
        raise RuntimeError("workspace not initialised")
    return _workspace


def _safe_path(rel: str) -> str:
    """Resolve a caller-supplied path and refuse anything outside the workspace."""
    root = os.path.realpath(_ws())
    target = os.path.realpath(os.path.join(root, rel))
    if target != root and not target.startswith(root + os.sep):
        raise ValueError(f"path escapes workspace: {rel}")
    return target


# ─────────────────────────────────────────────────────────────────
# Tools for the fix agent
# ─────────────────────────────────────────────────────────────────


@tool
def shell(command: str) -> str:
    """Run a shell command inside the repository checkout.

    Args:
        command: The shell command to run, e.g. 'pnpm test' or 'pnpm why react'.
    """
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        cwd=_ws(),
        timeout=180,
        check=False,
    )
    out = f"[exit {result.returncode}]\n"
    if result.stdout:
        out += result.stdout[-3000:]
    if result.stderr:
        out += "\n--- stderr ---\n" + result.stderr[-1500:]
    return out


@tool
def read_file(path: str) -> str:
    """Read a file from the repository, relative to the repo root.

    Args:
        path: Repo-relative file path, e.g. 'src/index.ts'.
    """
    with open(_safe_path(path)) as f:
        content = f.read()
    return content[:8000] + "\n... [truncated]" if len(content) > 8000 else content


@tool
def write_file(path: str, content: str) -> str:
    """Overwrite a file in the repository with new content.

    Args:
        path: Repo-relative file path.
        content: The complete new file contents.
    """
    full = _safe_path(path)
    parent = os.path.dirname(full)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(full, "w") as f:
        f.write(content)
    return f"wrote {len(content)} bytes to {path}"


@tool
def find_files(pattern: str) -> str:
    """Find files by name pattern, skipping node_modules.

    Args:
        pattern: A filename glob, e.g. '*.test.ts'.
    """
    result = subprocess.run(
        ["find", ".", "-name", pattern, "-not", "-path", "*/node_modules/*"],
        capture_output=True,
        text=True,
        cwd=_ws(),
        timeout=30,
        check=False,
    )
    lines = result.stdout.splitlines()[:30]
    return "\n".join(lines) or "no files found"


@tool
def grep_code(pattern: str, file_glob: str = "*.ts") -> str:
    """Search source files for a pattern. Use to locate a deprecated API call site.

    Args:
        pattern: The literal text or regex to search for.
        file_glob: Restrict to files matching this glob. Defaults to '*.ts'.
    """
    result = subprocess.run(
        [
            "grep",
            "-rn",
            "--include",
            file_glob,
            "--exclude-dir",
            "node_modules",
            pattern,
            ".",
        ],
        capture_output=True,
        text=True,
        cwd=_ws(),
        timeout=60,
        check=False,
    )
    lines = result.stdout.splitlines()[:20]
    return "\n".join(lines) or "no matches"


# ─────────────────────────────────────────────────────────────────
# Deterministic pipeline (no LLM, no tokens)
# ─────────────────────────────────────────────────────────────────


def get_github_token() -> str:
    """Read the GitHub token from Secrets Manager."""
    sm = boto3.client("secretsmanager")
    raw = sm.get_secret_value(SecretId=SECRET_ID)["SecretString"]
    data = json.loads(raw)
    if "token" in data:  # PAT
        return str(data["token"])
    return _installation_token(data)  # GitHub App


def _installation_token(secret: dict) -> str:  # type: ignore[type-arg]
    """Exchange GitHub App credentials for a short-lived installation token."""
    import jwt

    now = int(time.time())
    assertion = jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": secret["app_id"]},
        secret["private_key"],
        algorithm="RS256",
    )
    resp = requests.post(
        f"https://api.github.com/app/installations/{secret['installation_id']}/access_tokens",
        headers={
            "Authorization": f"Bearer {assertion}",
            "Accept": "application/vnd.github+json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["token"]  # type: ignore[no-any-return]


def _run(
    cmd: list[str], cwd: str, timeout: int = 300, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def clone_repo(repo_url: str, workspace: str, token: str) -> None:
    """Clone with a token, then scrub the token out of .git/config."""
    authed = repo_url.replace("https://", f"https://x-access-token:{token}@")
    _run(["git", "clone", "--depth", "1", authed, workspace], cwd="/tmp")
    # Never leave the credential on disk in the remote URL.
    _run(["git", "remote", "set-url", "origin", repo_url], cwd=workspace)
    # A container has no git identity; commit would fail without this.
    _run(["git", "config", "user.name", "dep-update-agent"], cwd=workspace)
    _run(
        ["git", "config", "user.email", "dep-update-agent@users.noreply.github.com"],
        cwd=workspace,
    )


def _detect_pnpm_version(workspace: str) -> str | None:
    """Detect the pnpm major version the project expects.

    Checks packageManager field in package.json, then infers from lockfileVersion.
    Returns a version spec like '9' or '9.15.4', or None if indeterminate.
    """
    pkg_path = os.path.join(workspace, "package.json")
    try:
        with open(pkg_path) as f:
            pkg = json.load(f)
        pm: str = pkg.get("packageManager", "")
        if pm.startswith("pnpm@"):
            return pm.split("@")[1]
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Infer from lockfileVersion
    lock_path = os.path.join(workspace, "pnpm-lock.yaml")
    try:
        with open(lock_path) as f:
            for line in f:
                if line.startswith("lockfileVersion:"):
                    ver = line.split(":")[1].strip().strip("'\"")
                    # lockfileVersion 9.0 -> pnpm 9, 6.0 -> pnpm 8, 5.4 -> pnpm 7
                    major = ver.split(".")[0]
                    mapping = {"9": "9", "6": "8", "5": "7"}
                    return mapping.get(major)
                break
    except FileNotFoundError:
        pass
    return None


def _ensure_pnpm_version(workspace: str) -> None:
    """If the project expects a different pnpm major, install it globally."""
    target = _detect_pnpm_version(workspace)
    if not target:
        return
    # Get current pnpm major
    result = _run(["pnpm", "--version"], cwd=workspace, check=False)
    current_major = result.stdout.strip().split(".")[0] if result.returncode == 0 else ""
    target_major = target.split(".")[0]
    if current_major == target_major:
        return
    if _log:
        _log.info(
            "project expects different pnpm version, switching",
            expected=target,
            current=result.stdout.strip(),
        )
    _run(["npm", "install", "-g", f"pnpm@{target_major}"], cwd=workspace, timeout=120)
    ver_result = _run(["pnpm", "--version"], cwd=workspace, check=False)
    if _log:
        _log.info("pnpm version switched", version=ver_result.stdout.strip())


def install_deps(workspace: str, frozen: bool = True) -> None:
    """Install node_modules. Required before audit and before tests.

    When frozen=True, attempts --frozen-lockfile first. If that fails (e.g.
    lockfile version mismatch with the container's pnpm), falls back to a
    regular install — acceptable because the agent is about to mutate the
    lockfile via `pnpm update` anyway.
    """
    if frozen:
        result = _run(
            ["pnpm", "install", "--frozen-lockfile"],
            cwd=workspace,
            timeout=600,
            check=False,
        )
        if result.returncode == 0:
            return
        # Frozen install failed; fall through to a regular install.
    _run(["pnpm", "install"], cwd=workspace, timeout=600)


def run_audit(workspace: str) -> dict:  # type: ignore[type-arg]
    """pnpm audit exits non-zero when vulnerabilities exist, so check=False."""
    result = _run(["pnpm", "audit", "--json"], cwd=workspace, check=False)
    try:
        return json.loads(result.stdout)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return {"parse_failed": True, "raw": result.stdout[:2000]}


def count_vulns(audit: dict) -> int:  # type: ignore[type-arg]
    vulns = audit.get("metadata", {}).get("vulnerabilities", {})
    return sum(v for v in vulns.values() if isinstance(v, int))


def extract_advisories(audit: dict) -> list[dict]:  # type: ignore[type-arg]
    """Extract CVE/advisory details from the pnpm audit JSON."""
    advisories: list[dict] = []  # type: ignore[type-arg]
    # pnpm audit --json has an "advisories" dict keyed by advisory ID
    raw = audit.get("advisories", {})
    for _id, adv in raw.items():
        advisories.append(
            {
                "id": adv.get("id", _id),
                "module": adv.get("module_name", "unknown"),
                "severity": adv.get("severity", "unknown"),
                "title": adv.get("title", ""),
                "url": adv.get("url", ""),
                "cves": adv.get("cves", []),
                "patched_versions": adv.get("patched_versions", ""),
            }
        )
    return advisories


def snapshot_lockfile_packages(workspace: str) -> dict[str, str]:
    """Parse pnpm-lock.yaml to get a {name: version} snapshot.

    Uses `pnpm list --json --depth 0` which is more reliable across lockfile
    versions than parsing the YAML directly.
    """
    result = _run(
        ["pnpm", "list", "--json", "--depth", "0"],
        cwd=workspace,
        timeout=120,
        check=False,
    )
    packages: dict[str, str] = {}
    try:
        data = json.loads(result.stdout)
        # pnpm list --json returns an array of projects
        for project in data if isinstance(data, list) else [data]:
            for dep_type in ("dependencies", "devDependencies"):
                deps = project.get(dep_type, {})
                for name, info in deps.items():
                    ver = info.get("version", "") if isinstance(info, dict) else str(info)
                    packages[name] = ver
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return packages


def diff_packages(before: dict[str, str], after: dict[str, str]) -> list[dict[str, str]]:
    """Compare two package snapshots. Returns list of {name, from, to}."""
    changes: list[dict[str, str]] = []
    for name in sorted(set(before) | set(after)):
        old_ver = before.get(name)
        new_ver = after.get(name)
        if old_ver != new_ver:
            changes.append(
                {
                    "name": name,
                    "from": old_ver or "(new)",
                    "to": new_ver or "(removed)",
                }
            )
    return changes


def update_packages(workspace: str) -> str:
    """pnpm update: patch + minor within existing semver ranges. No majors.

    After updating, runs `pnpm install` to reconcile the lockfile metadata
    (especially pnpm.overrides config hash). Without this, CI's
    --frozen-lockfile fails with ERR_PNPM_LOCKFILE_CONFIG_MISMATCH.
    """
    result = _run(["pnpm", "update"], cwd=workspace, timeout=600, check=False)
    # Reconcile lockfile: ensures overrides/settings metadata is up to date.
    _run(
        ["pnpm", "install", "--no-frozen-lockfile"],
        cwd=workspace,
        timeout=600,
        check=False,
    )
    return (result.stdout + result.stderr)[:2000]


def has_changes(workspace: str) -> bool:
    result = _run(["git", "status", "--porcelain"], cwd=workspace)
    return bool(result.stdout.strip())


def run_tests(workspace: str) -> tuple[int, str]:
    try:
        result = _run(["pnpm", "test"], cwd=workspace, timeout=TEST_TIMEOUT, check=False)
        return result.returncode, result.stdout + "\n" + result.stderr
    except subprocess.TimeoutExpired:
        return 124, f"test suite exceeded {TEST_TIMEOUT}s and was killed"


def run_lint(workspace: str) -> tuple[int, str]:
    """Run lint if a lint script exists in package.json.

    If lint fails and a lint:fix script exists, runs it automatically and
    re-checks. Returns (exit_code, output).
    """
    pkg_path = os.path.join(workspace, "package.json")
    try:
        with open(pkg_path) as f:
            pkg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return -1, "no package.json"
    scripts = pkg.get("scripts", {})
    if "lint" not in scripts:
        return -1, "no lint script"
    result = _run(["pnpm", "lint"], cwd=workspace, timeout=300, check=False)
    if result.returncode != 0 and "lint:fix" in scripts:
        if _log:
            _log.warn("lint failed, attempting lint:fix")
        _run(["pnpm", "lint:fix"], cwd=workspace, timeout=300, check=False)
        result = _run(["pnpm", "lint"], cwd=workspace, timeout=300, check=False)
    return result.returncode, (result.stdout + "\n" + result.stderr)[-2000:]


def run_format(workspace: str) -> tuple[int, str]:
    """Run formatter if a format script exists in package.json.

    Runs the write/fix variant (e.g. 'format' or 'format:fix') to auto-fix,
    then checks with 'format:check' if available.
    """
    pkg_path = os.path.join(workspace, "package.json")
    try:
        with open(pkg_path) as f:
            pkg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return -1, "no package.json"
    scripts = pkg.get("scripts", {})
    # Run the formatter to auto-fix
    if "format" in scripts:
        _run(["pnpm", "format"], cwd=workspace, timeout=300, check=False)
    elif "format:fix" in scripts:
        _run(["pnpm", "format:fix"], cwd=workspace, timeout=300, check=False)
    else:
        return -1, "no format script"
    # Verify with format:check if available
    if "format:check" in scripts:
        result = _run(["pnpm", "format:check"], cwd=workspace, timeout=300, check=False)
        return result.returncode, (result.stdout + "\n" + result.stderr)[-2000:]
    return 0, "formatted (no check script to verify)"


def run_typecheck(workspace: str) -> tuple[int, str]:
    """Run typecheck if a typecheck/tsc script exists. Falls back to tsc --noEmit."""
    pkg_path = os.path.join(workspace, "package.json")
    try:
        with open(pkg_path) as f:
            pkg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return -1, "no package.json"
    scripts = pkg.get("scripts", {})
    if "typecheck" in scripts:
        cmd = ["pnpm", "typecheck"]
    elif "type-check" in scripts:
        cmd = ["pnpm", "type-check"]
    elif os.path.exists(os.path.join(workspace, "tsconfig.json")):
        cmd = ["pnpm", "exec", "tsc", "--noEmit"]
    else:
        return -1, "no typecheck script or tsconfig.json"
    result = _run(cmd, cwd=workspace, timeout=300, check=False)
    return result.returncode, (result.stdout + "\n" + result.stderr)[-2000:]


def default_branch(workspace: str) -> str:
    result = _run(["git", "symbolic-ref", "--short", "HEAD"], cwd=workspace)
    return result.stdout.strip() or "main"


def existing_pr(workspace: str, env: dict) -> str | None:  # type: ignore[type-arg]
    """Idempotency: don't open a second PR if one of ours is already open."""
    result = subprocess.run(
        ["gh", "pr", "list", "--state", "open", "--json", "headRefName,url"],
        cwd=workspace,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        prs = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return None
    for pr in prs:
        if pr.get("headRefName", "").startswith("deps/update-"):
            return str(pr["url"])
    return None


def create_pr(workspace: str, token: str, base: str, body: str) -> str:
    """Branch, commit, push, open PR. Returns the PR URL."""
    env = {**os.environ, "GH_TOKEN": token}
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    branch = f"deps/update-{stamp}"

    _run(["git", "checkout", "-b", branch], cwd=workspace)
    _run(["git", "add", "-A"], cwd=workspace)
    _run(
        ["git", "commit", "-m", "chore(deps): automated dependency update"],
        cwd=workspace,
    )

    # Push needs the credential; supply it for this call only.
    subprocess.run(
        ["git", "push", "origin", branch],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
        env={
            **env,
            "GIT_ASKPASS": "true",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "credential.helper",
            "GIT_CONFIG_VALUE_0": (
                f"!f() {{ echo username=x-access-token; echo password={token}; }}; f"
            ),
        },
    )

    # Write body to a temp file (--body-file avoids shell quoting issues with
    # markdown tables and long content).
    body_file = os.path.join(workspace, ".pr-body.md")
    with open(body_file, "w") as f:
        f.write(body)

    result = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--title",
            "chore(deps): automated dependency update",
            "--body-file",
            body_file,
            "--base",
            base,
            "--head",
            branch,
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    os.remove(body_file)
    return result.stdout.strip()


# ─────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────

app = BedrockAgentCoreApp()


def _run_pipeline(payload: dict, task_id: int) -> None:  # type: ignore[type-arg]
    """Execute the full dependency-update pipeline on a worker thread.

    Wrapped in try/finally to guarantee app.complete_async_task is called,
    ensuring /ping transitions back to Healthy even on failure.
    """
    global _workspace, _log  # noqa: PLW0603

    token: str | None = None
    # Track pipeline result for span attribute emission (S-010)
    _pipeline_result: str = "error"  # default to error; overwritten on success paths
    _pr_url: str | None = None
    _subject_id: str | None = None

    try:
        # Parse the control-plane payload envelope (handles prompt-unwrap, normalization,
        # params validation, and defaults).
        try:
            parsed = parse_payload(payload)
        except PayloadError as e:
            # Fail fast with a clear logged error for invalid payloads
            _log = JsonLogger(session_id="unknown", agent="dep-updater", repo="unknown")
            _log.error("payload validation failed", error=str(e))
            return

        session_id = parsed.session_id
        repo_url = parsed.clone_url
        max_attempts = int(parsed.params.get("max_fix_attempts", 3))
        allow_fixes = bool(parsed.params.get("allow_fixes", True))
        _subject_id = parsed.repo

        _workspace = tempfile.mkdtemp(prefix="dep-agent-", dir="/tmp")

        # Initialize structured logger binding context for this invocation
        _log = JsonLogger(
            session_id=session_id,
            agent="dep-updater",
            repo=parsed.repo,
        )

        _log.info(
            "invocation start",
            allow_fixes=allow_fixes,
            max_attempts=max_attempts,
        )

        _log.info("fetching GitHub token from Secrets Manager")
        token = get_github_token()
        _log.info("token retrieved successfully")

        _log.info("cloning repository")
        clone_repo(repo_url, _workspace, token)
        base = default_branch(_workspace)
        _log.info("clone complete", workspace=_workspace, base_branch=base)

        _log.info("detecting project pnpm version")
        _ensure_pnpm_version(_workspace)

        _log.info("installing dependencies (frozen)")
        install_deps(_workspace, frozen=True)
        _log.info("install complete")

        # -- Snapshot before state ---
        _log.info("snapshotting package versions (before)")
        packages_before = snapshot_lockfile_packages(_workspace)

        _log.info("running pnpm audit (before)")
        audit_before = run_audit(_workspace)
        vuln_count_before = count_vulns(audit_before)
        advisories_before = extract_advisories(audit_before)
        _log.info("audit complete", vulnerabilities=vuln_count_before)

        # -- Update ---
        _log.info("running pnpm update")
        update_packages(_workspace)
        if not has_changes(_workspace):
            _log.info("no changes after update — nothing to do")
            _pipeline_result = "no_updates"
            return

        # -- Snapshot after state ---
        _log.info("snapshotting package versions (after)")
        packages_after = snapshot_lockfile_packages(_workspace)
        upgraded = diff_packages(packages_before, packages_after)
        _log.info("packages diffed", packages_changed=len(upgraded))

        _log.info("running pnpm audit (after)")
        audit_after = run_audit(_workspace)
        vuln_count_after = count_vulns(audit_after)
        advisories_after = extract_advisories(audit_after)
        _log.info("post-update audit complete", vulnerabilities=vuln_count_after)

        # Determine which advisories were fixed
        after_ids = {a["id"] for a in advisories_after}
        fixed_advisories = [a for a in advisories_before if a["id"] not in after_ids]
        _log.info("advisories resolved", fixed_count=len(fixed_advisories))

        # -- Re-install and validate ---
        _log.info("re-installing dependencies")
        install_deps(_workspace, frozen=False)

        _log.info("running lint")
        lint_code, _lint_output = run_lint(_workspace)
        lint_status = "passed" if lint_code == 0 else ("skipped" if lint_code == -1 else "failed")
        _log.info("lint complete", status=lint_status)

        _log.info("running format")
        fmt_code, _fmt_output = run_format(_workspace)
        fmt_status = "passed" if fmt_code == 0 else ("skipped" if fmt_code == -1 else "failed")
        _log.info("format complete", status=fmt_status)

        _log.info("running typecheck")
        tc_code, _tc_output = run_typecheck(_workspace)
        tc_status = "passed" if tc_code == 0 else ("skipped" if tc_code == -1 else "failed")
        _log.info("typecheck complete", status=tc_status)

        _log.info("running tests")
        exit_code, test_output = run_tests(_workspace)
        _log.info("tests complete", exit_code=exit_code)
        attempts = 0

        if exit_code != 0 and allow_fixes:
            _log.warn("tests failed, invoking fix agent", model=MODEL_ID)
            fix_agent = Agent(
                model=MODEL_ID,
                tools=[shell, read_file, write_file, find_files, grep_code],
                system_prompt=(
                    "You are a senior engineer fixing a test suite that broke after "
                    "`pnpm update` bumped dependencies. You have tools to read, search "
                    "and edit the repo and to run commands.\n"
                    "Method: read the failure, locate the call site, work out what the "
                    "new package version changed, apply the smallest fix, then run "
                    "`pnpm test` to verify.\n"
                    "Constraints: change only what is needed to make tests pass. Never "
                    "delete, skip or weaken a test to make it green. Never edit "
                    "package.json versions to roll a dependency back — the point of "
                    "this run is to land the update."
                ),
            )
            while exit_code != 0 and attempts < max_attempts:
                attempts += 1
                _log.warn("fix attempt", attempt=attempts, max_attempts=max_attempts)
                fix_agent(
                    f"Attempt {attempts} of {max_attempts}.\n\n"
                    f"Test output (tail):\n{test_output[-4000:]}\n\n"
                    "Diagnose and fix. Then run `pnpm test`."
                )
                exit_code, test_output = run_tests(_workspace)
                _log.info("post-fix tests complete", exit_code=exit_code)

            # Re-run lint/format/typecheck after fixes in case the agent touched source
            if exit_code == 0:
                lint_code, _lint_output = run_lint(_workspace)
                lint_status = (
                    "passed" if lint_code == 0 else ("skipped" if lint_code == -1 else "failed")
                )
                fmt_code, _fmt_output = run_format(_workspace)
                fmt_status = (
                    "passed" if fmt_code == 0 else ("skipped" if fmt_code == -1 else "failed")
                )
                tc_code, _tc_output = run_typecheck(_workspace)
                tc_status = "passed" if tc_code == 0 else ("skipped" if tc_code == -1 else "failed")

        if exit_code != 0:
            _log.error(
                "tests still failing after fix attempts",
                attempts=attempts,
            )
            _pipeline_result = "tests_failing"
            return

        # -- Idempotency check ---
        env = {**os.environ, "GH_TOKEN": token}
        _log.info("checking for existing PR")
        already = existing_pr(_workspace, env)
        if already:
            _log.info("PR already open, skipping", pr_url=already)
            _pipeline_result = "pr_already_open"
            _pr_url = already
            return

        # -- Build PR body ---
        body = _build_pr_body(
            vuln_count_before=vuln_count_before,
            vuln_count_after=vuln_count_after,
            fixed_advisories=fixed_advisories,
            upgraded=upgraded,
            lint_status=lint_status,
            fmt_status=fmt_status,
            tc_status=tc_status,
            test_status="passed",
            attempts=attempts,
        )

        pr_url = create_pr(_workspace, token, base, body)
        _log.info("PR created", pr_url=pr_url)
        _pipeline_result = "success"
        _pr_url = pr_url

    except subprocess.CalledProcessError as e:
        cmd_str = " ".join(e.cmd) if isinstance(e.cmd, list) else str(e.cmd)
        # Scrub any embedded credentials from the command string.
        if token:
            cmd_str = cmd_str.replace(token, "***")
        stderr = (e.stderr or "")[-1500:]
        if token:
            stderr = stderr.replace(token, "***")
        if _log:
            _log.error("CalledProcessError", cmd=cmd_str, stderr=stderr)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        if token:
            msg = msg.replace(token, "***")
        if _log:
            _log.error("unhandled exception", error=msg)
    finally:
        # Emit llipe.* span attributes on the root span (S-010).
        # This runs on every path: success, failure, exception.
        if _subject_id:
            try:
                run_result = map_result(_pipeline_result, pr_url=_pr_url)
                emit_span_attributes(result=run_result, subject_id=_subject_id)
            except Exception:
                # Never let emission failure mask the actual pipeline result
                if _log:
                    _log.warn("failed to emit span attributes")

        # Stamp outcome into DynamoDB (S-011).
        # Uses the mapped result status from emission — "success" or "failed".
        if _subject_id:
            try:
                _outcome_result = map_result(_pipeline_result, pr_url=_pr_url)
                stamp_outcome(
                    subject_id=_subject_id,
                    agent_name="dep-updater",
                    status=_outcome_result.status,
                    outcome_url=_outcome_result.outcome_url,
                )
            except Exception:
                # Never let DynamoDB failure mask the actual pipeline result
                if _log:
                    _log.error("failed to stamp outcome to DynamoDB")

        app.complete_async_task(task_id)


@app.entrypoint
def dep_update(payload: dict, context: object) -> dict:  # type: ignore[type-arg]
    """Non-blocking entrypoint: registers an async task and starts the pipeline
    on a daemon worker thread, returning immediately so /ping stays responsive.
    """
    # Extract session_id from context for task tracking (fallback for CLI invocations
    # where session_id is not in the payload envelope).
    session_id: str = getattr(context, "session_id", None) or "unknown"

    # If the payload doesn't already have a session_id (CLI shim case),
    # inject the one from the runtime context.
    if "session_id" not in payload:
        payload["session_id"] = session_id

    # Register async task so /ping reports HealthyBusy
    task_id = app.add_async_task(f"dep-update-{session_id}")

    # Start the pipeline on a daemon thread — does not block the HTTP thread
    worker = threading.Thread(
        target=_run_pipeline,
        args=(payload, task_id),
        name=f"pipeline-{session_id}",
        daemon=True,
    )
    worker.start()

    # Return immediately — pipeline continues in background
    return {"status": "accepted", "session_id": session_id, "task_id": task_id}


def _build_pr_body(
    vuln_count_before: int,
    vuln_count_after: int,
    fixed_advisories: list[dict],  # type: ignore[type-arg]
    upgraded: list[dict[str, str]],
    lint_status: str,
    fmt_status: str,
    tc_status: str,
    test_status: str,
    attempts: int,
) -> str:
    """Assemble a detailed PR description."""
    lines = [
        "## Automated Dependency Update",
        "",
        "Generated by `dep-updater`.",
        "",
        "### Security",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Vulnerabilities before | {vuln_count_before} |",
        f"| Vulnerabilities after | {vuln_count_after} |",
        f"| Advisories fixed | {len(fixed_advisories)} |",
        "",
    ]

    if fixed_advisories:
        lines.append("#### Fixed Advisories")
        lines.append("")
        lines.append("| Severity | Package | Title | Reference |")
        lines.append("|----------|---------|-------|-----------|")
        for adv in fixed_advisories:
            if adv["cves"]:
                ref = ", ".join(adv["cves"])
            elif adv.get("url"):
                ref = f"[more info]({adv['url']})"
            else:
                ref = "—"
            title = adv["title"][:60]
            lines.append(f"| {adv['severity']} | `{adv['module']}` | {title} | {ref} |")
        lines.append("")

    lines.append("### Upgraded Packages")
    lines.append("")
    if upgraded:
        lines.append("| Package | From | To |")
        lines.append("|---------|------|-----|")
        for pkg in upgraded[:30]:  # cap at 30 to keep PR readable
            lines.append(f"| `{pkg['name']}` | {pkg['from']} | {pkg['to']} |")
        if len(upgraded) > 30:
            lines.append(f"| ... | +{len(upgraded) - 30} more | |")
        lines.append("")
    else:
        lines.append("No direct dependency changes detected (transitive only).")
        lines.append("")

    lines.append("### Validations")
    lines.append("")
    emoji = {"passed": "✅", "failed": "❌", "skipped": "⏭️"}
    lines.append("| Check | Result |")
    lines.append("|-------|--------|")
    lines.append(f"| Lint | {emoji.get(lint_status, '?')} {lint_status} |")
    lines.append(f"| Format | {emoji.get(fmt_status, '?')} {fmt_status} |")
    lines.append(f"| Typecheck | {emoji.get(tc_status, '?')} {tc_status} |")
    test_detail = f"{test_status} (after {attempts} fix attempt(s))" if attempts else test_status
    lines.append(f"| Tests | {emoji.get(test_status, '?')} {test_detail} |")
    lines.append("| Lockfile | reconciled (`pnpm install` post-update) |")
    lines.append("")

    if attempts > 0:
        lines.append(
            f"> The test suite initially failed after the update. "
            f"An AI agent (Claude) applied fixes in {attempts} attempt(s). "
            f"Review the non-lockfile changes carefully."
        )
        lines.append("")

    lines.append("---")
    lines.append(
        "*Updated via `pnpm update` (patch/minor within semver ranges, no majors). "
        "Review the diff before merging.*"
    )

    return "\n".join(lines)


if __name__ == "__main__":
    app.run()
