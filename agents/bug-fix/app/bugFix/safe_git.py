"""
safe_git — the wrapper's only git runner (spec §7, §8.7, §12 item 7;
S-189; D-62, D-63, D-83, D-110; DF-01, DF-02, DF-03).

The wrapper (root, D-110) runs git **only** against its own clone,
``/work/wrapper/repo`` inside root-owned ``/work/wrapper`` (mode 0700). It never
runs git against a ``.git`` that ``fixer`` can write: ``/work/repo`` is
``fixer``'s, and ``fixer`` may ``git init`` there, plant hooks,
``core.fsmonitor``, ``diff.external``, filter drivers, ``include.path`` or
``url.<x>.insteadOf``. None of that can reach the wrapper, because:

1. **One hardened command shape.** Every call is
   ``git <HARDENED_ARGS> --attr-source=<empty tree> --git-dir=<clone>/.git
   [--work-tree=<dir>] <subcommand>`` with an env built from scratch
   (:data:`HARDENED_ENV`: ``GIT_CONFIG_NOSYSTEM=1``,
   ``GIT_CONFIG_GLOBAL=/dev/null``, no prompt, ``HOME`` that doesn't exist, so
   no user attributes or excludes file either). ``core.hooksPath=/dev/null``
   and ``core.fsmonitor=false`` are forced. ``safe.directory`` is never set:
   with an explicit ``--git-dir`` git does no ownership discovery. ``-C``,
   ``GIT_DIR`` and a ``cwd`` under the work tree are never used.
2. **No attributes from the work tree.** ``--attr-source`` points at the empty
   tree, so a ``.gitattributes`` that ``fixer`` writes can't name a filter
   driver, a textconv or an eol conversion for ``add`` (git ≥ 2.40). No driver
   is configured anyway: the only config git reads is the clone's own.
3. **Trees leave as data, through ``fixer``.** :meth:`SafeGit.materialize`
   lists the tree (``ls-tree``), reads each blob raw (``cat-file --batch``),
   and streams a tar it builds itself into ``tar -x`` **spawned as
   ``fixer``** through the ``setpriv`` drop (D-110). It is not ``git
   archive``, which would apply the repo's own ``export-ignore`` and
   ``export-subst`` attributes. Symlinks are tar symlink entries, modes are
   ``0644``/``0755``, and nothing is ever written to ``/work/repo`` by root.
4. **Changes come back as data.** :meth:`SafeGit.capture` resets the wrapper
   index to the base tree with no stat data (``read-tree``), then runs ``git
   --git-dir=<clone>/.git --work-tree=<dir> add -A`` and ``write-tree``.
   Every file is re-hashed, so an edit that keeps size and mtime is still
   seen; untracked files are included (DF-01); symlinks are stored as links
   (mode ``120000``), never followed; an embedded repository is a gitlink
   (``160000``, D-83 rejects it later); ``info/exclude`` lists only
   :data:`EXCLUDE_LINES` (D-83).
5. **The token never rests.** :func:`clone` passes the installation token as
   an ``http.https://github.com/.extraheader`` through ``GIT_CONFIG_*`` env
   variables (never argv, which is world-readable in ``/proc``), so it applies
   to ``https://github.com/`` only, isn't written to ``.git/config``, and with
   ``http.followRedirects=false`` can't follow a redirect elsewhere. The remote
   URL is token-free.

``fixer`` spawns (``tar``, ``rm``) go through ``sandbox.fixer_prefix``:
``setpriv --reuid=10002 … -- python3 -I fixer_exec.py``. No repo code runs
here: these are fixed system binaries.
"""

from __future__ import annotations

import base64
import contextlib
import io
import os
import re
import stat
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import IO, Any

from sandbox import DEFAULT_PATHS, build_env, fixer_prefix
from scrubber import SecretSet, SecretsLike, scrub_all, tail

GIT_TIMEOUT_SECONDS = 300.0
MAX_BLOB_BYTES = 1024 * 1024  # TreeReader only: the repo gate reads small files
RM_CHUNK = 200

# The clone's info/exclude: dependency directories only (D-83). Build outputs
# are governed by the repo's own .gitignore.
EXCLUDE_LINES: tuple[str, ...] = ("node_modules/", ".venv/", ".pnpm-store/", "__pycache__/")

# Every wrapper git call starts with these (D-62).
HARDENED_ARGS: tuple[str, ...] = (
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.symlinks=true",
    "-c",
    "core.autocrlf=false",
    "-c",
    "credential.helper=",
    "-c",
    "protocol.ext.allow=never",
    "-c",
    "gc.auto=0",
    "-c",
    "maintenance.auto=false",
)

# The whole env of every wrapper git call: nothing comes from os.environ.
HARDENED_ENV: dict[str, str] = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_LITERAL_PATHSPECS": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "HOME": "/nonexistent",
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
}

# The empty tree per object format: the attribute source that has no
# attributes. git knows it without it being stored.
EMPTY_TREE: dict[str, str] = {
    "sha1": "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
    "sha256": "6ef19b41225c5369f1c104d45d8d85efa9b057b53b14b4b9b939dd74decc5321",
}

GITHUB_EXTRAHEADER_KEY = "http.https://github.com/.extraheader"

_SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_BRANCH_COMPONENT_BAD = re.compile(r"(^\.)|(\.lock$)")
_BRANCH_BAD_CHARS = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]")
MAX_BRANCH_LEN = 255


class GitError(Exception):
    """A wrapper git call or a fixer file operation failed. Scrubbed message."""

    code = "GIT_FAILED"


@dataclass(frozen=True)
class GitTools:
    """Binaries and spawners. Production defaults are the image's paths."""

    git: str = "/usr/bin/git"
    tar: str = "/usr/bin/tar"
    rm: str = "/usr/bin/rm"
    fixer_prefix: tuple[str, ...] = tuple(fixer_prefix(DEFAULT_PATHS))
    run: Callable[..., Any] = subprocess.run
    popen: Callable[..., Any] = subprocess.Popen
    timeout: float = GIT_TIMEOUT_SECONDS


@dataclass(frozen=True)
class Change:
    """One ``diff-tree --raw`` entry between two trees (renames off)."""

    status: str  # A, M, D or T
    path: str
    old_mode: str
    new_mode: str

    @property
    def in_base(self) -> bool:
        """The path exists in the old tree (anything but an addition)."""
        return self.old_mode != "000000"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(HARDENED_ENV)
    if extra:
        env.update(extra)
    return env


def auth_env(token: str | None) -> dict[str, str]:
    """The installation token as a ``https://github.com/``-scoped header, by env."""
    if not token:
        return {}
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": GITHUB_EXTRAHEADER_KEY,
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
    }


def _as_list(secrets: SecretsLike | None) -> list[str]:
    if secrets is None:
        return []
    return secrets.values() if isinstance(secrets, SecretSet) else list(secrets)


def _token_secrets(token: str | None) -> list[str]:
    if not token:
        return []
    return [token, base64.b64encode(f"x-access-token:{token}".encode()).decode()]


def validate_branch(name: object) -> str:
    """``name`` if it is a plain branch name (git's ref rules, stricter), else
    :class:`GitError`. It never starts with ``-``, so it can't be an option."""
    if not isinstance(name, str) or not name or len(name) > MAX_BRANCH_LEN:
        raise GitError("invalid base branch name")
    if (
        name.startswith(("-", "/"))
        or name.endswith(("/", "."))
        or ".." in name
        or "//" in name
        or "@{" in name
        or name == "@"
        or _BRANCH_BAD_CHARS.search(name)
        or any(_BRANCH_COMPONENT_BAD.search(c) for c in name.split("/"))
    ):
        raise GitError("invalid base branch name")
    return name


def parse_raw_diff(raw: str) -> list[Change]:
    """Parse ``diff-tree -r -z --raw --no-renames --no-abbrev`` output."""
    out: list[Change] = []
    fields = raw.split("\0")
    i = 0
    while i < len(fields):
        head = fields[i]
        if head == "":
            i += 1
            continue
        parts = head.lstrip(":").split(" ")
        if not head.startswith(":") or len(parts) != 5 or i + 1 >= len(fields):
            raise GitError("unexpected diff-tree output")
        path = fields[i + 1]
        if not path:
            raise GitError("unexpected diff-tree output")
        old_mode, new_mode, _old, _new, status = parts
        out.append(Change(status[:1], path, old_mode, new_mode))
        i += 2
    return out


def _safe_rel(path: str) -> bool:
    if not path or path.startswith("/") or "\0" in path:
        return False
    return all(p not in ("", ".", "..") for p in path.split("/"))


def _check_dir(dest: str) -> None:
    try:
        st = os.lstat(dest)
    except OSError:
        raise GitError("destination is missing") from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise GitError("destination is not a plain directory")


# ---------------------------------------------------------------------------
# The wrapper clone
# ---------------------------------------------------------------------------


@dataclass
class SafeGit:
    """Hardened git on the wrapper clone at ``clone_dir`` (git dir
    ``clone_dir/.git``)."""

    clone_dir: str
    tools: GitTools = field(default_factory=GitTools)
    secrets: SecretsLike = field(default_factory=list)
    base_sha: str = ""

    @property
    def git_dir(self) -> str:
        return os.path.join(self.clone_dir, ".git")

    def _object_format(self) -> str:
        """The clone's object format, from its own config (trusted data)."""
        try:
            with open(os.path.join(self.git_dir, "config"), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return "sha1"
        return "sha256" if re.search(r"objectformat\s*=\s*sha256", text, re.I) else "sha1"

    def command(self, *args: str, work_tree: str | None = None) -> list[str]:
        cmd = [
            self.tools.git,
            *HARDENED_ARGS,
            f"--attr-source={EMPTY_TREE[self._object_format()]}",
            f"--git-dir={self.git_dir}",
        ]
        if work_tree is not None:
            cmd.append(f"--work-tree={work_tree}")
        cmd.extend(args)
        return cmd

    def _fail(self, what: str, detail: str | bytes = "") -> GitError:
        text = detail.decode("utf-8", "replace") if isinstance(detail, bytes) else detail
        message = f"{what} failed"
        if text.strip():
            message += f": {tail(text.strip(), self.secrets, 500)}"
        return GitError(scrub_all(message, self.secrets))

    def run_bytes(
        self, *args: str, work_tree: str | None = None, input: bytes | None = None
    ) -> bytes:
        cmd = self.command(*args, work_tree=work_tree)
        try:
            proc = self.tools.run(
                cmd,
                env=git_env(),
                cwd=self.clone_dir,
                input=input,
                stdin=None if input is not None else subprocess.DEVNULL,
                capture_output=True,
                timeout=self.tools.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise self._fail(f"git {args[0]}", "timeout") from None
        except OSError as exc:
            raise self._fail(f"git {args[0]}", exc.strerror or type(exc).__name__) from None
        if proc.returncode != 0:
            raise self._fail(f"git {args[0]} (exit {proc.returncode})", proc.stderr or b"")
        out: bytes = proc.stdout or b""
        return out

    def run(self, *args: str, work_tree: str | None = None) -> str:
        return self.run_bytes(*args, work_tree=work_tree).decode("utf-8", "surrogateescape")

    # -------------------------------------------------------------- reads

    def rev_parse(self, rev: str) -> str:
        sha = self.run("rev-parse", "--verify", "--end-of-options", rev).strip()
        if not _SHA.fullmatch(sha):
            raise GitError("rev-parse returned no object id")
        return sha

    def tree_of(self, rev: str) -> str:
        return self.rev_parse(f"{rev}^{{tree}}")

    def ls_tree(self, rev: str, paths: Sequence[str] = ()) -> dict[str, tuple[str, str]]:
        """``{path: (mode, object id)}`` of every entry under ``rev``, recursive.
        Gitlinks are listed with mode ``160000``."""
        out = self.run("ls-tree", "-r", "-z", "--full-tree", rev, "--", *paths)
        entries: dict[str, tuple[str, str]] = {}
        for record in out.split("\0"):
            if not record:
                continue
            meta, _, path = record.partition("\t")
            parts = meta.split(" ")
            if len(parts) != 3 or not path:
                raise GitError("unexpected ls-tree output")
            entries[path] = (parts[0], parts[2])
        return entries

    def blob(self, sha: str) -> bytes:
        if not _SHA.fullmatch(sha):
            raise GitError("invalid object id")
        return self.run_bytes("cat-file", "blob", sha)

    def blob_size(self, sha: str) -> int:
        if not _SHA.fullmatch(sha):
            raise GitError("invalid object id")
        return int(self.run("cat-file", "-s", sha).strip())

    def reader(self, rev: str) -> TreeReader:
        return TreeReader(self, rev)

    # -------------------------------------------------------------- setup

    def write_exclude(self) -> None:
        info = os.path.join(self.git_dir, "info")
        os.makedirs(info, mode=0o700, exist_ok=True)
        with open(os.path.join(info, "exclude"), "w", encoding="utf-8") as f:
            f.write("".join(f"{line}\n" for line in EXCLUDE_LINES))

    # -------------------------------------------------------------- capture

    def capture(self, work_tree: str, base: str | None = None) -> str:
        """The tree of ``work_tree`` as the wrapper's git sees it (D-62):
        tracked and untracked files, symlinks as links, excludes skipped.

        The index is first reset to ``base`` with no stat data, so every file
        is hashed again rather than trusted by size and mtime.
        """
        _check_dir(work_tree)
        self.run("read-tree", base or self.base_sha)
        self.run("add", "-A", "--", ".", work_tree=work_tree)
        tree = self.run("write-tree").strip()
        if not _SHA.fullmatch(tree):
            raise GitError("write-tree returned no object id")
        return tree

    def changes(self, old: str, new: str) -> list[Change]:
        raw = self.run(
            "diff-tree",
            "-r",
            "-z",
            "--raw",
            "--no-renames",
            "--no-abbrev",
            "--no-ext-diff",
            "--no-textconv",
            old,
            new,
        )
        return parse_raw_diff(raw)

    # -------------------------------------------------------------- fixer writes

    def _spawn_fixer(self, argv: Sequence[str], **kwargs: Any) -> Any:
        return self.tools.popen(
            [*self.tools.fixer_prefix, *argv],
            env=build_env(None),
            close_fds=True,
            **kwargs,
        )

    def materialize(
        self, tree: str, dest: str, *, paths: Iterable[str] | None = None, fresh: bool = True
    ) -> int:
        """Write ``tree`` (or only ``paths`` of it) into ``dest`` as ``fixer``.

        ``fresh`` requires ``dest`` to be an empty plain directory (the base
        checkout); otherwise files are written over what is there (the base
        restore). Returns the number of entries written.
        """
        _check_dir(dest)
        if fresh and os.listdir(dest):
            raise GitError("destination is not empty")
        entries = self.ls_tree(tree)
        if paths is not None:
            wanted = set(paths)
            entries = {p: e for p, e in entries.items() if p in wanted}
        if not entries:
            return 0
        with tempfile.TemporaryFile() as err:
            tar = self._spawn_fixer(
                [self.tools.tar, "-x", "-f", "-", "-C", dest],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=err,
                cwd="/",
            )
            try:
                self._stream_tar(entries, tar.stdin)
            except BrokenPipeError:
                pass
            except BaseException:
                with contextlib.suppress(OSError):
                    tar.kill()
                tar.wait()
                raise
            finally:
                with contextlib.suppress(OSError):
                    tar.stdin.close()
            try:
                code = tar.wait(timeout=self.tools.timeout)
            except subprocess.TimeoutExpired:
                tar.kill()
                tar.wait()
                raise self._fail("tar -x as fixer", "timeout") from None
            if code != 0:
                err.seek(0)
                raise self._fail(f"tar -x as fixer (exit {code})", err.read())
        return len(entries)

    def _stream_tar(self, entries: dict[str, tuple[str, str]], sink: IO[bytes]) -> None:
        """A tar of ``entries`` built here, blob by blob, raw (no attributes)."""
        now = int(time.time())
        with (
            tarfile.open(fileobj=sink, mode="w|", format=tarfile.PAX_FORMAT) as out,
            self._batch() as batch,
        ):
            for path, (mode, sha) in sorted(entries.items()):
                if not _safe_rel(path):
                    raise GitError("unsafe path in tree")
                info = tarfile.TarInfo(path)
                info.mtime = now
                if mode == "160000":  # gitlink: an empty directory, as git archive does
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    out.addfile(info)
                    continue
                data = batch(sha)
                if mode == "120000":
                    info.type = tarfile.SYMTYPE
                    info.linkname = os.fsdecode(data)
                    info.mode = 0o777
                    out.addfile(info)
                elif mode in ("100644", "100755"):
                    info.size = len(data)
                    info.mode = 0o755 if mode == "100755" else 0o644
                    out.addfile(info, io.BytesIO(data))
                else:
                    raise GitError(f"unexpected tree entry mode {mode}")

    @contextlib.contextmanager
    def _batch(self) -> Any:
        """``cat-file --batch``: one long-lived reader for every blob."""
        proc = self.tools.popen(
            self.command("cat-file", "--batch"),
            env=git_env(),
            cwd=self.clone_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

        def read(sha: str) -> bytes:
            if not _SHA.fullmatch(sha):
                raise GitError("invalid object id")
            proc.stdin.write(sha.encode() + b"\n")
            proc.stdin.flush()
            header = proc.stdout.readline().decode("ascii", "replace").split()
            if len(header) != 3 or header[1] != "blob":
                raise GitError("cat-file returned no blob")
            size = int(header[2])
            data = proc.stdout.read(size)
            proc.stdout.read(1)  # the trailing newline
            if len(data) != size:
                raise GitError("cat-file returned a short blob")
            return bytes(data)

        try:
            yield read
        finally:
            with contextlib.suppress(OSError):
                proc.stdin.close()
            try:
                proc.wait(timeout=self.tools.timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    def remove(self, paths: Sequence[str], dest: str) -> None:
        """``rm -rf -- <paths>`` in ``dest`` as ``fixer``. Paths are
        repo-relative (from ``diff-tree``); anything else is refused."""
        _check_dir(dest)
        for p in paths:
            if not _safe_rel(p):
                raise GitError("unsafe path to remove")
        for i in range(0, len(paths), RM_CHUNK):
            chunk = list(paths[i : i + RM_CHUNK])
            with tempfile.TemporaryFile() as err:
                proc = self._spawn_fixer(
                    [self.tools.rm, "-rf", "--", *chunk],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=err,
                    cwd=dest,
                )
                try:
                    proc.wait(timeout=self.tools.timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    raise self._fail("rm as fixer", "timeout") from None
                # A non-zero rm (ENOTDIR on a replaced parent) is not fatal:
                # the caller re-captures and checks the tree is back at base.


class TreeReader:
    """``toolchain.RepoReader`` over a commit of the wrapper clone.

    Reads regular blobs only (``100644``/``100755``) at an exact path; a
    symlink, a directory, a gitlink, a path under a symlinked directory, or a
    blob over :data:`MAX_BLOB_BYTES` reads as ``None``.
    """

    def __init__(self, git: SafeGit, rev: str) -> None:
        self.git = git
        self.rev = rev

    def read_text(self, path: str) -> str | None:
        if not _safe_rel(path):
            return None
        entries = self.git.ls_tree(self.rev, [path])
        entry = entries.get(path)
        if entry is None or entry[0] not in ("100644", "100755"):
            return None
        if self.git.blob_size(entry[1]) > MAX_BLOB_BYTES:
            return None
        return self.git.blob(entry[1]).decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# Clone
# ---------------------------------------------------------------------------


def clone(
    url: str,
    branch: str,
    clone_dir: str,
    *,
    tools: GitTools | None = None,
    token: str | None = None,
    secrets: SecretsLike | None = None,
) -> SafeGit:
    """Shallow-clone ``branch`` of ``url`` into ``clone_dir`` (which must not
    exist), mode 0700, with no work-tree files, and record the base SHA."""
    tools = tools or GitTools()
    scrub_list = _as_list(secrets)
    scrub_list += _token_secrets(token)
    branch = validate_branch(branch)
    if not isinstance(url, str) or not url or url.startswith("-") or any(c.isspace() for c in url):
        raise GitError("invalid remote URL")
    if os.path.lexists(clone_dir):
        raise GitError("the wrapper clone directory already exists")
    parent = os.path.dirname(clone_dir) or "."
    _check_dir(parent)

    cmd = [
        tools.git,
        *HARDENED_ARGS,
        "-c",
        "http.followRedirects=false",
        "clone",
        "--quiet",
        "--no-checkout",
        "--depth=1",
        "--single-branch",
        "--no-tags",
        "--template=",
        f"--branch={branch}",
        "--",
        url,
        clone_dir,
    ]
    try:
        proc = tools.run(
            cmd,
            env=git_env(auth_env(token)),
            cwd=parent,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=tools.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise GitError("git clone failed: timeout") from None
    except OSError as exc:
        raise GitError(scrub_all(f"git clone failed: {exc.strerror}", scrub_list)) from None
    if proc.returncode != 0:
        stderr = (proc.stderr or b"").decode("utf-8", "replace").strip()
        detail = tail(stderr, scrub_list, 500) if stderr else ""
        raise GitError(
            scrub_all(
                f"git clone failed (exit {proc.returncode}): {detail}".rstrip(": "), scrub_list
            )
        )
    os.chmod(clone_dir, 0o700)
    git = SafeGit(clone_dir, tools=tools, secrets=scrub_list)
    git.write_exclude()
    git.base_sha = git.rev_parse("HEAD")
    return git
