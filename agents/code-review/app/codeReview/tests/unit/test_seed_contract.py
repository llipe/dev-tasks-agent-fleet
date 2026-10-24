"""
S-204 AC5 — the ``agents`` seed row contract (TC-204-14, TC-204-16, CT-02).

Reads ``supabase/seed.sql`` and ``supabase/migrations/*_seed_code_review_agent.sql``
as text (no database) and checks that each inserts the ``code-review`` row with
the spec §5.1 ``params_schema`` and ``default_params``, the operational columns
the reaper and the panel rely on (test plan DF-09), and the siblings'
``on conflict (slug) do update`` shape. The live-database half is TC-204-15
(panel Layer 2.5) and the manual ``supabase db reset``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import config
from main import apply_defaults

PKG = Path(__file__).resolve().parents[2]
REPO = PKG.parents[3]
SEED = REPO / "supabase" / "seed.sql"
MIGRATIONS = REPO / "supabase" / "migrations"
AGENTCORE_JSON = PKG.parents[1] / "agentcore" / "agentcore.json"

# Spec §5.1, verbatim.
SPEC_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["pr_number"],
    "properties": {
        "pr_number": {"type": "integer", "minimum": 1, "title": "Pull request number"},
        "max_diff_lines": {"type": "integer", "minimum": 100, "maximum": 10000, "default": 2000},
        "max_context_tokens": {
            "type": "integer",
            "minimum": 20000,
            "maximum": 400000,
            "default": 150000,
        },
        "max_suggestions": {"type": "integer", "minimum": 0, "maximum": 20, "default": 5},
        "run_timeout_seconds": {"type": "integer", "minimum": 120, "maximum": 900, "default": 900},
        "reasoning_effort": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "default": "high",
        },
    },
}

# ---------------------------------------------------------------------------
# Minimal SQL reader for `insert into agents (...) values (...) on conflict ...;`
# ---------------------------------------------------------------------------


def _strip_comments(sql: str) -> str:
    """Drop `--` comments outside quotes and dollar quotes."""
    out: list[str] = []
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            j = i + 1
            while j < len(sql):
                if sql[j] == "'" and sql[j + 1 : j + 2] == "'":
                    j += 2
                    continue
                if sql[j] == "'":
                    break
                j += 1
            out.append(sql[i : j + 1])
            i = j + 1
            continue
        m = re.match(r"\$([A-Za-z_]*)\$", sql[i:])
        if m:
            tag = m.group(0)
            end = sql.index(tag, i + len(tag))
            out.append(sql[i : end + len(tag)])
            i = end + len(tag)
            continue
        if sql.startswith("--", i):
            nl = sql.find("\n", i)
            i = len(sql) if nl == -1 else nl
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _split_top_level(body: str) -> list[str]:
    """Split a comma-separated list at depth 0, respecting quotes."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "'":
            j = i + 1
            while j < len(body):
                if body[j] == "'" and body[j + 1 : j + 2] == "'":
                    j += 2
                    continue
                if body[j] == "'":
                    break
                j += 1
            buf.append(body[i : j + 1])
            i = j + 1
            continue
        m = re.match(r"\$([A-Za-z_]*)\$", body[i:])
        if m:
            tag = m.group(0)
            end = body.index(tag, i + len(tag))
            buf.append(body[i : end + len(tag)])
            i = end + len(tag)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    if "".join(buf).strip():
        parts.append("".join(buf).strip())
    return parts


def _balanced(text: str, start: int) -> tuple[str, int]:
    """Return the contents of the parenthesis group opening at ``start``."""
    assert text[start] == "("
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "'":
            i = text.index("'", i + 1)
            while text[i + 1 : i + 2] == "'":
                i = text.index("'", i + 2)
        elif m := re.match(r"\$([A-Za-z_]*)\$", text[i:]):
            i = text.index(m.group(0), i + len(m.group(0))) + len(m.group(0)) - 1
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i
        i += 1
    raise AssertionError("unbalanced parentheses")


def _literal(token: str) -> object:
    token = re.sub(r"::\s*jsonb\s*$", "", token.strip()).strip()
    if token.startswith("'") and token.endswith("'"):
        return token[1:-1].replace("''", "'")
    m = re.fullmatch(r"\$([A-Za-z_]*)\$(.*)\$\1\$", token, re.S)
    if m:
        return m.group(2)
    if token.lower() in {"true", "false"}:
        return token.lower() == "true"
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    return token  # expression; returned raw


def agent_rows(path: Path) -> dict[str, dict]:
    """Map slug -> {"columns": {...}, "conflict": "<on conflict clause>"}."""
    sql = _strip_comments(path.read_text())
    rows: dict[str, dict] = {}
    for m in re.finditer(r"insert\s+into\s+agents\s*\(", sql, re.I):
        cols_text, end = _balanced(sql, m.end() - 1)
        cols = [c.strip() for c in cols_text.split(",")]
        vm = re.compile(r"\s*values\s*\(", re.I).match(sql, end + 1)
        assert vm, f"{path.name}: `insert into agents` without a values list"
        vals_text, vend = _balanced(sql, vm.end() - 1)
        vals = _split_top_level(vals_text)
        assert len(cols) == len(vals), f"{path.name}: {len(cols)} columns, {len(vals)} values"
        stmt_end = sql.index(";", vend)
        columns = {c: _literal(v) for c, v in zip(cols, vals, strict=True)}
        rows[str(columns["slug"])] = {
            "columns": columns,
            "conflict": " ".join(sql[vend + 1 : stmt_end].split()).lower(),
        }
    return rows


def _migration() -> Path:
    found = sorted(MIGRATIONS.glob("*_seed_code_review_agent.sql"))
    assert len(found) == 1, f"expected one *_seed_code_review_agent.sql, found {found}"
    return found[0]


SOURCES = {"seed.sql": lambda: SEED, "migration": _migration}


@pytest.fixture(params=list(SOURCES), ids=list(SOURCES))
def row(request) -> dict:
    rows = agent_rows(SOURCES[request.param]())
    assert "code-review" in rows, f"{request.param}: no code-review row"
    return rows["code-review"]


# ---------------------------------------------------------------------------
# TC-204-14 — schema and defaults
# ---------------------------------------------------------------------------


def test_migration_file_name_sorts_after_existing_migrations():
    names = sorted(p.name for p in MIGRATIONS.glob("*.sql"))
    assert names[-1] == _migration().name


def test_params_schema_equals_spec_5_1(row):
    assert json.loads(row["columns"]["params_schema"]) == SPEC_SCHEMA


def test_runtime_schema_constant_equals_spec_5_1():
    assert config.PARAMS_SCHEMA == SPEC_SCHEMA


def test_default_params_equal_schema_defaults_without_pr_number(row):
    defaults = json.loads(row["columns"]["default_params"])
    schema_defaults = {
        k: v["default"] for k, v in SPEC_SCHEMA["properties"].items() if "default" in v
    }
    assert defaults == schema_defaults
    assert "pr_number" not in defaults


def test_on_conflict_slug_do_update(row):
    conflict = row["conflict"]
    assert conflict.startswith("on conflict (slug) do update"), conflict
    for col in ("params_schema", "default_params", "max_runtime_seconds", "grace_seconds"):
        assert f"{col} = excluded.{col}" in conflict, f"{col} not refreshed on conflict"


def test_on_conflict_never_overwrites_the_deployed_runtime_arn(row):
    # runtime_arn is a placeholder until Wave B (S-214) deploys the runtime and
    # sets it; re-applying the seed or the migration must not clobber it.
    assert "runtime_arn" not in row["conflict"]


def test_row_is_seeded_disabled_until_deploy(row):
    # D-39: runtime_arn is a placeholder until S-214 deploys the runtime, so the
    # row starts disabled; S-214 sets runtime_arn and is_enabled = true together.
    assert row["columns"].get("is_enabled") is False, "is_enabled must be inserted as false"
    assert row["columns"]["runtime_arn"] == "pending-deploy:code-review"


def test_on_conflict_never_touches_is_enabled(row):
    # D-39: an operator's later enable (or disable) survives re-applies.
    assert "is_enabled" not in row["conflict"]


def test_seed_and_migration_insert_the_same_row():
    seed = agent_rows(SEED)["code-review"]["columns"]
    mig = agent_rows(_migration())["code-review"]["columns"]
    assert {k: v for k, v in seed.items() if k not in {"params_schema", "default_params"}} == {
        k: v for k, v in mig.items() if k not in {"params_schema", "default_params"}
    }
    assert json.loads(seed["params_schema"]) == json.loads(mig["params_schema"])
    assert json.loads(seed["default_params"]) == json.loads(mig["default_params"])


def test_sibling_rows_still_parse():
    rows = agent_rows(SEED)
    assert {"dependency-update", "security-analyst", "code-review"} <= set(rows)


# ---------------------------------------------------------------------------
# TC-204-16 — operational columns (DF-09)
# ---------------------------------------------------------------------------


def test_operational_columns(row):
    cols = row["columns"]
    assert cols["name"] == "Code Review"
    assert cols["version"] == "0.1.0"
    assert isinstance(cols["description"], str) and cols["description"]
    assert cols["requires_repository"] is True
    assert cols["max_runtime_seconds"] == config.MAX_LIFETIME == 1800
    assert cols["grace_seconds"] == config.GRACE_SECONDS
    assert cols["start_timeout_seconds"] == 300
    assert cols["runtime_qualifier"] == "DEFAULT"
    assert isinstance(cols["runtime_arn"], str) and cols["runtime_arn"]


def test_reaper_threshold_matches_seed(row):
    cols = row["columns"]
    assert (cols["max_runtime_seconds"] + cols["grace_seconds"]) == config.REAPER_THRESHOLD_SECONDS


def test_max_runtime_matches_agentcore_max_lifetime_when_present(row):
    if not AGENTCORE_JSON.exists():
        pytest.skip("agents/code-review/agentcore/agentcore.json lands with S-214 (Wave B)")
    spec = json.loads(AGENTCORE_JSON.read_text())
    lifetimes = {
        rt["lifecycleConfiguration"]["maxLifetime"]
        for rt in spec.get("runtimes", [])
        if "lifecycleConfiguration" in rt
    }
    assert lifetimes == {row["columns"]["max_runtime_seconds"]}


# ---------------------------------------------------------------------------
# CT-02 — defaults parity: seed default_params = schema defaults = apply_defaults
# ---------------------------------------------------------------------------


def test_every_non_required_property_has_a_default():
    for key, prop in SPEC_SCHEMA["properties"].items():
        if key in SPEC_SCHEMA["required"]:
            continue
        assert "default" in prop, f"{key} has no default"


def test_defaults_parity_across_three_sources(row):
    seed_defaults = json.loads(row["columns"]["default_params"])
    runtime = apply_defaults({"pr_number": 1})
    runtime.pop("pr_number")
    assert seed_defaults == runtime == config.DEFAULT_PARAMS


def test_default_types_match_schema_types(row):
    seed_defaults = json.loads(row["columns"]["default_params"])
    py_types = {"integer": int, "string": str}
    for key, value in seed_defaults.items():
        assert key in SPEC_SCHEMA["properties"], f"default for unknown key {key}"
        expected = py_types[SPEC_SCHEMA["properties"][key]["type"]]
        assert type(value) is expected, f"{key}={value!r} is not {expected.__name__}"
