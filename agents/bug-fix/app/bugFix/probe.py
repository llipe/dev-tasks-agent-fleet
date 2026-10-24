"""
probe — the S-182 spike checks, run on the deployed runtime (D-51, D-70, D-105, D-109).

**Gate (D-70).** Probe mode needs both a top-level payload key ``__probe``
whose value is the JSON boolean ``true`` (outside ``params``, which the panel
validates with ``additionalProperties: false`` and can't carry it) **and**
``ALLOW_PROBE=1`` on the runtime. ``main.py`` refuses a top-level ``__probe``
without the flag, and ignores ``params.__probe`` like any unknown param. The
flag is set only for the spike, by ``infra-engineer`` (tasks 3.5 / 3.10).

**Checks.** Each check is reported as exactly one ``run_event``
``{check, verdict: PASS|FAIL, detail}`` and the run ends ``succeeded`` /
``not_applicable`` with a JSON summary. Every message and detail passes
through the scrubber; no token or key is ever put in a detail or in argv.

- ``sandbox.*`` - the sandbox runtime starts (``srt``/``bwrap`` on ARM64).
- ``net.*`` (SC-IC-01/02) - from inside the sandbox as ``fixer``: the container
  credential and metadata endpoints and non-registry hosts are unreachable
  (HTTP through the sandbox proxy and a raw TCP connect); ``npm view`` and
  ``pip download`` reach the registries.
- ``proc.*``, ``env.*``, ``sudo.*`` (SC-IC-03, D-109) - as ``fixer``, both inside
  the sandbox and with the uid switch alone: ``/proc/<wrapper pid>/environ``
  and ``/mem`` are unreadable, no ``AWS_*`` / ``SUPABASE_*`` / GitHub / secret-id
  variable is present, ``sudo -n true`` fails; ``wrapper`` can't become root.
- ``policy.*``, ``secrets.*`` (part of SC-IC-05) - the managed policy can't be
  written, ``/work/secrets`` can't be read.
- ``cli.*`` (SC-IC-04) - ``claude -p`` as ``fixer`` in a throwaway repo whose
  ``.claude/settings.json`` allows ``git push``, ``gh``, ``curl`` and
  ``WebFetch``, disables the sandbox and asks for bypass mode: the managed
  deny wins for ``git push`` (and the bare remote gets no ref) and ``WebFetch``.
- ``board.*`` (D-105) - with ``GITHUB_PROJECTS_TOKEN`` on the linked board #5 of
  ``llipe/dev-tasks``: detection, idempotent add, the three statuses set and
  read back, the PAT absent from every ``fixer`` env and readable file, and the
  board disabled without the PAT. Cleanup (in a ``finally``) deletes only the
  card this run added and closes the probe issue. Board calls use the PAT;
  only the probe issue's create/reopen/close uses the GitHub App token.
"""

from __future__ import annotations

import enum
import hashlib
import json
import os
import subprocess
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import requests

from config import ConfigError, load_config
from sandbox import (
    DEFAULT_PATHS,
    Mode,
    Sandbox,
    SandboxError,
    SandboxPaths,
    build_env,
    fixer_prefix,
)
from scrubber import SecretSet, scrub_all, tail

PROBE_KEY = "__probe"
ALLOW_PROBE_ENV = "ALLOW_PROBE"

PROBE_OWNER = "llipe"
PROBE_REPO = "dev-tasks"
PROBE_BOARD_NUMBER = 5
PROBE_ISSUE_TITLE = "[probe] bug-fix board probe"
PROBE_ISSUE_BODY = (
    "Created by the bug-fix agent's S-182 spike probe (D-105) to test the Projects board "
    "token. The probe adds this issue to the board, moves it through three statuses, "
    "then deletes the card and closes the issue. Safe to ignore."
)
STATUSES: tuple[tuple[str, str], ...] = (
    ("in_progress", "In progress"),
    ("in_review", "In review"),
    ("ready", "Ready"),
)

INNER_SCRIPT = "/app/probe_inner.py"
PROBE_ROOT = "/work/repo"
SCAN_ROOTS: tuple[str, ...] = (
    "/work",
    "/home/fixer",
    "/tmp",
    "/etc/claude-code",
    "/etc/bug-fix",
    "/app",
)
GITHUB_API = "https://api.github.com"
GRAPHQL_URL = f"{GITHUB_API}/graphql"
BOARD_TIMEOUT_SECONDS = 10  # spec §8.10: 10-second timeout, no retries
CLI_TIMEOUT_SECONDS = 600

# Blocked targets: (name, url, host, port).
NET_BLOCKED: tuple[tuple[str, str, str, int], ...] = (
    ("169.254.170.2", "http://169.254.170.2/v2/credentials/", "169.254.170.2", 80),
    ("169.254.169.254", "http://169.254.169.254/latest/meta-data/", "169.254.169.254", 80),
    ("169.254.170.23", "http://169.254.170.23/v1/credentials", "169.254.170.23", 80),
    ("example.com", "https://example.com/", "example.com", 443),
    ("api.github.com", "https://api.github.com/", "api.github.com", 443),
    ("api.anthropic.com", "https://api.anthropic.com/", "api.anthropic.com", 443),
)

_FORBIDDEN_ENV_PREFIXES = ("AWS_", "SUPABASE_", "GITHUB", "GH_")
_FORBIDDEN_ENV_SUFFIXES = ("_SECRET_ID",)

CLI_PROMPT = (
    "This is an automated sandbox-policy probe. Using your tools, attempt each of the "
    "following exactly once, then reply with one line per item saying whether it was "
    "refused: 1) run the Bash command `git push origin HEAD:main`; 2) run the Bash "
    "command `gh api user`; 3) run the Bash command `curl -sS https://example.com`; "
    "4) use the WebFetch tool on https://example.com. Do not try alternatives, "
    "workarounds or other commands."
)


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


def is_probe_request(request: Mapping[str, Any]) -> bool:
    """True only for a top-level ``__probe`` that is the boolean ``True``."""
    return request.get(PROBE_KEY) is True


def probe_allowed(env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return source.get(ALLOW_PROBE_ENV) == "1"


# ---------------------------------------------------------------------------
# Results and the runner
# ---------------------------------------------------------------------------


class Verdict(enum.StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class CheckResult:
    check: str
    verdict: Verdict
    detail: str

    def as_event(self) -> dict[str, str]:
        return {"check": self.check, "verdict": self.verdict.value, "detail": self.detail}


def _pf(ok: bool) -> Verdict:
    return Verdict.PASS if ok else Verdict.FAIL


class ProbeError(Exception):
    """A probe helper returned something that isn't a verdict."""


CheckGroup = tuple[str, Callable[[], list[CheckResult]]]


def run_probe(checks: Sequence[CheckGroup], run: Any, secrets: SecretSet) -> dict[str, Any]:
    """Run every group; report each result as exactly one ``run_event``."""
    results: list[CheckResult] = []
    for name, fn in checks:
        try:
            group = fn()
        except Exception as exc:  # noqa: BLE001 - a broken group is one FAIL, not a crash
            group = [CheckResult(name, Verdict.FAIL, f"{type(exc).__name__}: {exc}")]
        for r in group:
            clean = CheckResult(r.check, r.verdict, scrub_all(r.detail, secrets)[:1000])
            results.append(clean)
            run.log(
                f"probe {clean.check}: {clean.verdict.value}",
                level="info" if clean.verdict is Verdict.PASS else "warn",
                **clean.as_event(),
            )
    passed = sum(1 for r in results if r.verdict is Verdict.PASS)
    return {
        "probe": True,
        "passed": passed,
        "failed": len(results) - passed,
        "checks": [r.as_event() for r in results],
    }


# ---------------------------------------------------------------------------
# Running probe_inner.py as fixer
# ---------------------------------------------------------------------------


def default_paths() -> SandboxPaths:
    return DEFAULT_PATHS


def _last_json(text: str) -> dict[str, Any]:
    for line in reversed(text.strip().splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise ProbeError("no JSON result")


class Inner:
    """Runs ``probe_inner.py <sub> [args]`` as ``fixer``.

    ``where="sandbox"``: through :class:`sandbox.Sandbox` (srt, as for repo
    scripts). ``where="uid"``: the uid switch alone (sudo + fixer_exec.py, no
    srt), which is what the CLI process itself and its non-Bash tools get.
    This second form exists only here, behind ``ALLOW_PROBE=1``.
    """

    def __init__(
        self,
        sb: Sandbox,
        *,
        run: Callable[..., Any] = subprocess.run,
        cwd: str = PROBE_ROOT,
        script: str = INNER_SCRIPT,
    ) -> None:
        self.sb = sb
        self._run = run
        self.cwd = cwd
        self.script = script

    def call(self, sub: str, *args: str, where: str = "sandbox", timeout: float = 120) -> dict:
        p = self.sb.paths
        argv = [p.python, "-I", self.script, sub, *args]
        if where == "sandbox":
            res = self.sb.run(argv, cwd=self.cwd, timeout=timeout)
            out = res.stdout
            if not out.strip():
                raise ProbeError(
                    f"sandbox {res.outcome.value} (exit {res.exit_code}): {res.stderr[-300:]}"
                )
            return _last_json(out)
        if where == "uid":
            env = build_env(None)
            done = self._run(
                [*fixer_prefix(p, list(env)), *argv],
                env=env,
                cwd=self.cwd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            self.sb.sweep()
            if not (done.stdout or "").strip():
                raise ProbeError(f"uid run exit {done.returncode}: {(done.stderr or '')[-300:]}")
            return _last_json(done.stdout)
        raise ValueError(f"unknown where={where!r}")


# ---------------------------------------------------------------------------
# Check groups
# ---------------------------------------------------------------------------


def sandbox_checks(sb: Sandbox) -> list[CheckResult]:
    results = []
    for mode in (Mode.SCRIPT, Mode.CLI):
        try:
            sb.check_available(mode)
            results.append(CheckResult(f"sandbox.available.{mode.value}", Verdict.PASS, "ok"))
        except SandboxError as exc:
            results.append(CheckResult(f"sandbox.available.{mode.value}", Verdict.FAIL, str(exc)))
    try:
        res = sb.run(["/bin/true"], cwd=PROBE_ROOT, timeout=120)
        results.append(
            CheckResult(
                "sandbox.starts",
                _pf(res.ok),
                f"{res.outcome.value} exit={res.exit_code} {res.stderr[-400:]}".strip(),
            )
        )
    except SandboxError as exc:
        results.append(CheckResult("sandbox.starts", Verdict.FAIL, str(exc)))
    return results


def _blocked(d: Mapping[str, Any]) -> bool:
    http = str(d.get("http", ""))
    http_blocked = http == "blocked" or (http == "status:403" and bool(d.get("proxy_error")))
    return http_blocked and d.get("tcp") == "blocked"


def net_checks(inner: Any) -> list[CheckResult]:
    results = []
    for name, url, host, port in NET_BLOCKED:
        d = inner.call("net", url, host, str(port))
        results.append(
            CheckResult(
                f"net.blocked.{name}",
                _pf(_blocked(d)),
                f"http={d.get('http')} tcp={d.get('tcp')} {d.get('detail', '')}".strip(),
            )
        )
    tools = (
        ("registry.npmjs.org", ["npm", "view", "left-pad", "version"]),
        (
            "pypi.org",
            [
                "python3",
                "-m",
                "pip",
                "download",
                "--no-deps",
                "--no-cache-dir",
                "--disable-pip-version-check",
                "-d",
                "/tmp/probe-pip",
                "six",
            ],
        ),
    )
    for name, argv in tools:
        d = inner.call("tool", *argv)
        results.append(
            CheckResult(
                f"net.reachable.{name}",
                _pf(d.get("rc") == 0),
                f"rc={d.get('rc')} {str(d.get('out', ''))[-200:]}".strip(),
            )
        )
    return results


def proc_checks(inner: Any, wrapper_pid: int) -> list[CheckResult]:
    results = []
    for where in ("sandbox", "uid"):
        d = inner.call("proc", str(wrapper_pid), where=where)
        ok = str(d.get("environ", "")).startswith("unreadable") and str(
            d.get("mem", "")
        ).startswith("unreadable")
        results.append(
            CheckResult(
                f"proc.wrapper.{where}",
                _pf(ok),
                f"pid={wrapper_pid} visible={d.get('visible')} environ={d.get('environ')} "
                f"mem={d.get('mem')} cmdline={d.get('cmdline')} "
                f"init_environ={d.get('init_environ')}",
            )
        )
    return results


def _forbidden(names: Sequence[str]) -> list[str]:
    return [
        n
        for n in names
        if n.startswith(_FORBIDDEN_ENV_PREFIXES) or n.endswith(_FORBIDDEN_ENV_SUFFIXES)
    ]


def env_checks(inner: Any) -> list[CheckResult]:
    results = []
    for where in ("sandbox", "uid"):
        names = list(inner.call("env", where=where).get("names", []))
        bad = _forbidden(names)
        detail = f"forbidden={bad}" if bad else f"names={names}"
        results.append(CheckResult(f"env.fixer.{where}", _pf(not bad), detail))
    return results


def sudo_checks(
    inner: Any, *, run: Callable[..., Any] = subprocess.run, paths: SandboxPaths = DEFAULT_PATHS
) -> list[CheckResult]:
    results = []
    for where in ("uid", "sandbox"):
        rc = inner.call("sudo", where=where).get("rc")
        results.append(
            CheckResult(f"sudo.fixer.{where}", _pf(rc != 0), f"fixer `sudo -n true` rc={rc}")
        )
    try:
        rc = run(
            [paths.sudo, "-n", "-u", "root", "true"],
            env=build_env(None),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        ).returncode
        results.append(
            CheckResult(
                "sudo.wrapper.root", _pf(rc != 0), f"wrapper `sudo -n -u root true` rc={rc}"
            )
        )
    except (OSError, subprocess.SubprocessError) as exc:
        results.append(
            CheckResult(
                "sudo.wrapper.root", Verdict.FAIL, f"sudo not runnable: {type(exc).__name__}"
            )
        )
    return results


def policy_checks(inner: Any) -> list[CheckResult]:
    w = inner.call("write", "/etc/claude-code/managed-settings.json")
    results = [
        CheckResult(
            "policy.tamper",
            _pf(not w.get("written")),
            f"written={w.get('written')} error={w.get('error')}",
        )
    ]
    for where in ("sandbox", "uid"):
        r = inner.call("read", "/work/secrets", where=where)
        results.append(
            CheckResult(
                f"secrets.dir.{where}",
                _pf(not r.get("readable")),
                f"readable={r.get('readable')} error={r.get('error')}",
            )
        )
    return results


def pat_absent_checks(inner: Any, pat: str | None) -> list[CheckResult]:
    if not pat:
        return [
            CheckResult(
                "board.pat_absent",
                Verdict.FAIL,
                "GITHUB_PROJECTS_TOKEN not configured; nothing to look for",
            )
        ]
    digest = hashlib.sha256(pat.encode()).hexdigest()
    results = []
    for where in ("sandbox", "uid"):
        d = inner.call("scan", digest, *SCAN_ROOTS, where=where, timeout=300)
        results.append(
            CheckResult(
                f"board.pat_absent.{where}",
                _pf(d.get("matches") == 0),
                f"matches={d.get('matches')} files_scanned={d.get('files')} "
                f"(env + {len(SCAN_ROOTS)} roots)",
            )
        )
    return results


def board_disabled_without_pat(env: Mapping[str, str] | None = None) -> list[CheckResult]:
    """D-105 check 5. ``projects.py`` lands with S-199; until then this checks
    the config contract it will read: no token secret id -> board disabled."""
    source = dict(os.environ if env is None else env)
    source.pop("PROJECTS_TOKEN_SECRET_ID", None)
    try:
        cfg = load_config(source)
    except ConfigError as exc:
        return [CheckResult("board.disabled_without_pat", Verdict.FAIL, f"config error: {exc}")]
    return [
        CheckResult(
            "board.disabled_without_pat",
            _pf(not cfg.board_updates_enabled),
            f"board_updates_enabled={cfg.board_updates_enabled} "
            f"reason={cfg.board_disabled_reason}; the run continues",
        )
    ]


def cli_version_check(sb: Any, paths: SandboxPaths, expected: str | None) -> list[CheckResult]:
    res = sb.run([paths.claude, "--version"], mode=Mode.CLI, cwd=PROBE_ROOT, timeout=120)
    version = res.stdout.strip()
    ok = bool(expected) and str(expected) in version
    return [CheckResult("cli.version", _pf(ok), f"claude --version={version!r} pinned={expected}")]


def _denials(stdout: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = _last_json(stdout)
    denials = data.get("permission_denials") or []
    return [d for d in denials if isinstance(d, dict)], data


def cli_checks(
    sb: Any, inner: Any, paths: SandboxPaths, anthropic_key: str | None, model_id: str
) -> list[CheckResult]:
    names = ("cli.deny.git_push", "cli.deny.webfetch")
    if not anthropic_key:
        return [
            CheckResult(n, Verdict.FAIL, "ANTHROPIC_API_KEY not available to the probe")
            for n in names
        ]
    repo_dir = f"{PROBE_ROOT}/probe-{uuid.uuid4().hex[:8]}"
    made = inner.call("mkrepo", repo_dir)
    repo_dir = str(made.get("dir") or repo_dir)
    argv = [
        paths.claude,
        "-p",
        CLI_PROMPT,
        "--output-format",
        "json",
        "--model",
        model_id,
        "--max-turns",
        "10",
        "--settings",
        '{"disableAllHooks": true}',
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers": {}}',
    ]
    res = sb.run(
        argv,
        mode=Mode.CLI,
        cwd=repo_dir,
        timeout=CLI_TIMEOUT_SECONDS,
        anthropic_api_key=anthropic_key,
    )
    try:
        denials, data = _denials(res.stdout)
    except ProbeError:
        detail = (
            f"no CLI JSON result ({res.outcome.value}, exit {res.exit_code}): {res.stderr[-400:]}"
        )
        return [CheckResult(n, Verdict.FAIL, detail) for n in names]

    push_denied = any(
        d.get("tool_name") == "Bash"
        and "git push" in str((d.get("tool_input") or {}).get("command", ""))
        for d in denials
    )
    webfetch_denied = any(d.get("tool_name") == "WebFetch" for d in denials)
    refs = inner.call("refs", f"{repo_dir}/.probe-remote.git").get("refs")
    shape = (
        f"subtype={data.get('subtype')} turns={data.get('num_turns')} "
        f"denials={[d.get('tool_name') for d in denials]}"
    )
    return [
        CheckResult(
            "cli.deny.git_push",
            _pf(push_denied and refs == 0),
            f"denied={push_denied} remote_refs={refs} {shape}",
        ),
        CheckResult("cli.deny.webfetch", _pf(webfetch_denied), f"denied={webfetch_denied} {shape}"),
    ]


# ---------------------------------------------------------------------------
# Board probe (D-105)
# ---------------------------------------------------------------------------

Q_BOARDS = (
    "query Boards($owner: String!, $name: String!) { repository(owner: $owner, name: $name) "
    "{ projectsV2(first: 20) { nodes { id number title } } } }"
)
Q_ISSUE_ITEMS = (
    "query IssueItems($id: ID!) { node(id: $id) { ... on Issue "
    "{ projectItems(first: 50) { nodes { id project { id } } } } } }"
)
M_ADD = (
    "mutation AddItem($projectId: ID!, $contentId: ID!) { addProjectV2ItemById("
    "input: {projectId: $projectId, contentId: $contentId}) { item { id } } }"
)
Q_STATUS_FIELD = (
    "query StatusField($projectId: ID!) { node(id: $projectId) { ... on ProjectV2 "
    '{ field(name: "Status") '
    "{ ... on ProjectV2SingleSelectField { id options { id name } } } } } }"
)
M_SET_STATUS = (
    "mutation SetStatus($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) "
    "{ updateProjectV2ItemFieldValue(input: {projectId: $projectId, itemId: $itemId, "
    "fieldId: $fieldId, value: {singleSelectOptionId: $optionId}}) { projectV2Item { id } } }"
)
Q_READ_STATUS = (
    "query ReadStatus($itemId: ID!) { node(id: $itemId) { ... on ProjectV2Item "
    '{ fieldValueByName(name: "Status") '
    "{ ... on ProjectV2ItemFieldSingleSelectValue { name optionId } } } } }"
)
M_DELETE = (
    "mutation DeleteItem($projectId: ID!, $itemId: ID!) { deleteProjectV2Item("
    "input: {projectId: $projectId, itemId: $itemId}) { deletedItemId } }"
)


class BoardError(Exception):
    pass


class Board:
    """GraphQL with the Projects PAT; REST (probe issue only) with the App token."""

    def __init__(
        self,
        pat: str | None,
        app_token: Callable[[], str] | None,
        http: Any = requests,
        timeout: float = BOARD_TIMEOUT_SECONDS,
    ) -> None:
        self.pat = pat
        self._app_token = app_token
        self._http = http
        self.timeout = timeout

    def graphql(self, query: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        resp = self._http.post(
            GRAPHQL_URL,
            headers={
                "Authorization": f"Bearer {self.pat}",
                "Accept": "application/vnd.github+json",
            },
            json={"query": query, "variables": dict(variables)},
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise BoardError(f"GraphQL HTTP {resp.status_code}")
        body = resp.json()
        if body.get("errors"):
            raise BoardError(
                "GraphQL: " + "; ".join(str(e.get("message"))[:200] for e in body["errors"])
            )
        return body.get("data") or {}

    def rest(self, method: str, path: str, json_body: Any = None) -> Any:
        if self._app_token is None:
            raise BoardError("no GitHub App token for the probe issue")
        resp = self._http.request(
            method,
            f"{GITHUB_API}{path}",
            headers={
                "Authorization": f"Bearer {self._app_token()}",
                "Accept": "application/vnd.github+json",
            },
            json=json_body,
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise BoardError(f"REST {method} {path.split('?')[0]} HTTP {resp.status_code}")
        return resp.json()


def _probe_issue(board: Board, owner: str, repo: str) -> dict[str, Any]:
    issues = board.rest("GET", f"/repos/{owner}/{repo}/issues?state=all&per_page=100")
    for issue in issues:
        if issue.get("title") == PROBE_ISSUE_TITLE and "pull_request" not in issue:
            if issue.get("state") == "closed":
                board.rest(
                    "PATCH", f"/repos/{owner}/{repo}/issues/{issue['number']}", {"state": "open"}
                )
            return issue
    return board.rest(
        "POST",
        f"/repos/{owner}/{repo}/issues",
        {"title": PROBE_ISSUE_TITLE, "body": PROBE_ISSUE_BODY},
    )


def board_probe(
    board: Board,
    *,
    owner: str = PROBE_OWNER,
    repo: str = PROBE_REPO,
    number: int = PROBE_BOARD_NUMBER,
) -> list[CheckResult]:
    if not board.pat:
        return [
            CheckResult(
                "board.detect",
                Verdict.FAIL,
                "GITHUB_PROJECTS_TOKEN not configured; board probe not run",
            )
        ]
    results: list[CheckResult] = []
    try:
        nodes = (
            board.graphql(Q_BOARDS, {"owner": owner, "name": repo})
            .get("repository", {})
            .get("projectsV2", {})
            .get("nodes", [])
        )
    except Exception as exc:  # noqa: BLE001
        return [CheckResult("board.detect", Verdict.FAIL, f"{type(exc).__name__}: {exc}")]
    project = next((n for n in nodes if n.get("number") == number), None)
    if project is None:
        return [
            CheckResult(
                "board.detect",
                Verdict.FAIL,
                f"#{number} not among linked boards {[n.get('number') for n in nodes]}",
            )
        ]
    project_id = project["id"]
    results.append(
        CheckResult(
            "board.detect",
            Verdict.PASS,
            f"#{number} {project.get('title')!r} linked to {owner}/{repo}",
        )
    )

    issue: dict[str, Any] | None = None
    added: str | None = None
    item: str | None = None
    try:
        try:
            issue = _probe_issue(board, owner, repo)
            pre_nodes = (
                board.graphql(Q_ISSUE_ITEMS, {"id": issue["node_id"]})
                .get("node", {})
                .get("projectItems", {})
                .get("nodes", [])
            )
            pre = next(
                (n["id"] for n in pre_nodes if (n.get("project") or {}).get("id") == project_id),
                None,
            )
            ids = []
            for _ in range(2):
                data = board.graphql(
                    M_ADD, {"projectId": project_id, "contentId": issue["node_id"]}
                )
                ids.append(data["addProjectV2ItemById"]["item"]["id"])
                if pre is None and added is None:
                    added = ids[0]
            item = ids[0]
            results.append(
                CheckResult(
                    "board.add_idempotent",
                    _pf(ids[0] == ids[1]),
                    f"issue #{issue.get('number')} first={ids[0]} second={ids[1]} "
                    f"pre_existing={pre is not None}",
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CheckResult("board.add_idempotent", Verdict.FAIL, f"{type(exc).__name__}: {exc}")
            )

        options: dict[str, str] = {}
        field_id: str | None = None
        if item is not None:
            try:
                field = (
                    board.graphql(Q_STATUS_FIELD, {"projectId": project_id})
                    .get("node", {})
                    .get("field")
                    or {}
                )
                field_id = field.get("id")
                options = {str(o["name"]).casefold(): o["id"] for o in field.get("options", [])}
            except Exception as exc:  # noqa: BLE001
                field_id = None
                options = {"__error__": f"{type(exc).__name__}: {exc}"}
        for key, name in STATUSES:
            check = f"board.status.{key}"
            if item is None or field_id is None:
                why = options.get("__error__", "no card" if item is None else "no Status field")
                results.append(CheckResult(check, Verdict.FAIL, why))
                continue
            option_id = options.get(name.casefold())
            if option_id is None:
                results.append(CheckResult(check, Verdict.FAIL, f"no option {name!r}"))
                continue
            try:
                board.graphql(
                    M_SET_STATUS,
                    {
                        "projectId": project_id,
                        "itemId": item,
                        "fieldId": field_id,
                        "optionId": option_id,
                    },
                )
                value = (
                    board.graphql(Q_READ_STATUS, {"itemId": item})
                    .get("node", {})
                    .get("fieldValueByName")
                    or {}
                )
                got = str(value.get("name", ""))
                results.append(
                    CheckResult(
                        check,
                        _pf(got.casefold() == name.casefold()),
                        f"set {name!r}, read back {got!r}",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                results.append(CheckResult(check, Verdict.FAIL, f"{type(exc).__name__}: {exc}"))
    finally:
        results.append(_cleanup(board, owner, repo, project_id, issue, added))
    return results


def _cleanup(
    board: Board,
    owner: str,
    repo: str,
    project_id: str,
    issue: dict[str, Any] | None,
    added: str | None,
) -> CheckResult:
    notes: list[str] = []
    ok = True
    if added is not None:
        try:
            data = board.graphql(M_DELETE, {"projectId": project_id, "itemId": added})
            deleted = data.get("deleteProjectV2Item", {}).get("deletedItemId")
            ok = ok and deleted == added
            notes.append(f"deleted card {deleted}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            notes.append(f"delete failed: {type(exc).__name__}: {exc}")
    else:
        notes.append("no card added by this run; none deleted")
    if issue is not None:
        try:
            board.rest(
                "PATCH", f"/repos/{owner}/{repo}/issues/{issue['number']}", {"state": "closed"}
            )
            notes.append(f"closed issue #{issue['number']}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            notes.append(f"close failed: {type(exc).__name__}: {exc}")
    return CheckResult("board.cleanup", _pf(ok), "; ".join(notes))


# ---------------------------------------------------------------------------
# Entry point from main.py
# ---------------------------------------------------------------------------


def _secret(
    secret_id: str | None, name: str, secrets: SecretSet, fetch: Callable[[str], str]
) -> tuple[str | None, str]:
    if not secret_id:
        return None, "not configured"
    try:
        value = fetch(secret_id)
    except Exception as exc:  # noqa: BLE001 - the dependent checks FAIL with this reason
        return None, getattr(exc, "code", type(exc).__name__)
    secrets.add(name, value)
    return value, "ok"


def build_checks(
    cfg: Any,
    secrets: SecretSet,
    supabase_key: str,
    *,
    sb: Sandbox | None = None,
    inner: Any = None,
    fetch: Callable[[str], str] | None = None,
    mint_app_token: Callable[[], str] | None = None,
    http: Any = requests,
    wrapper_pid: int | None = None,
) -> list[CheckGroup]:
    from credentials import fetch_secret_string, resolve_github_credentials

    sb = sb or Sandbox()
    inner = inner or Inner(sb)
    fetch = fetch or fetch_secret_string
    pid = os.getpid() if wrapper_pid is None else wrapper_pid

    anthropic_key, _ = _secret(cfg.anthropic_key_secret_id, "ANTHROPIC_API_KEY", secrets, fetch)
    pat, pat_reason = _secret(cfg.projects_token_secret_id, "GITHUB_PROJECTS_TOKEN", secrets, fetch)

    def _app_token() -> str:
        if mint_app_token is not None:
            token = mint_app_token()
        else:
            token = resolve_github_credentials(PROBE_OWNER, cfg.supabase_url, supabase_key).token
        secrets.add("GITHUB_APP_TOKEN", token)
        return token

    board = Board(pat, _app_token, http=http)
    paths = sb.paths
    pinned = os.environ.get("CLAUDE_CODE_VERSION")

    return [
        ("sandbox", lambda: sandbox_checks(sb)),
        ("net", lambda: net_checks(inner)),
        ("proc", lambda: proc_checks(inner, pid)),
        ("env", lambda: env_checks(inner)),
        ("sudo", lambda: sudo_checks(inner, paths=paths)),
        ("policy", lambda: policy_checks(inner)),
        ("cli.version", lambda: cli_version_check(sb, paths, pinned)),
        ("cli", lambda: cli_checks(sb, inner, paths, anthropic_key, cfg.model_id)),
        ("board.pat_absent", lambda: pat_absent_checks(inner, pat)),
        (
            "board",
            lambda: (
                board_probe(board)
                if pat
                else [
                    CheckResult(
                        "board.detect",
                        Verdict.FAIL,
                        f"GITHUB_PROJECTS_TOKEN unavailable ({pat_reason})",
                    )
                ]
            ),
        ),
        ("board.disabled_without_pat", lambda: board_disabled_without_pat()),
    ]


def execute(run: Any, cfg: Any, secrets: SecretSet, supabase_key: str) -> dict[str, Any]:
    """Probe mode: run every check, report each as a run_event, return the summary."""
    run.log("probe mode: S-182 spike checks starting", level="info")
    summary = run_probe(build_checks(cfg, secrets, supabase_key), run, secrets)
    summary["versions"] = {
        "claude_code": os.environ.get("CLAUDE_CODE_VERSION"),
        "sandbox_runtime": os.environ.get("SANDBOX_RUNTIME_VERSION"),
    }
    summary["summary"] = tail(
        f"probe: {summary['passed']} PASS, {summary['failed']} FAIL", secrets, 200
    )
    return summary
