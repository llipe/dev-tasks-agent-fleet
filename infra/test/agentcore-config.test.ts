import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { DEP_UPDATER_TAGS, agentNameToSortKey, PREFIXES } from "@fleet/shared";

/**
 * Contract tests for the AgentCore CLI project config.
 *
 * The dep-updater runtime is deployed by the AgentCore CLI's own vended CDK app
 * (agents/dep-updater/agentcore/cdk), not by this CDK app. That means the
 * discovery tags the control plane depends on live in a static JSON file which
 * cannot import from packages/shared. These tests are the drift guard that keeps
 * the single-source guarantee: agentcore.json must agree with @fleet/shared.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "../..");
const AGENT_DIR = resolve(REPO_ROOT, "agents/dep-updater");
const CONFIG_PATH = resolve(AGENT_DIR, "agentcore/agentcore.json");

interface EnvVarEntry {
  name: string;
  value: string;
}

interface RuntimeEntry {
  name: string;
  build: string;
  entrypoint: string;
  codeLocation: string;
  buildContextPath?: string;
  dockerfile?: string;
  runtimeVersion?: string;
  networkMode?: string;
  protocol?: string;
  envVars?: EnvVarEntry[];
  lifecycleConfiguration?: {
    idleRuntimeSessionTimeout?: number;
    maxLifetime?: number;
  };
  tags?: Record<string, string>;
}

interface AgentCoreConfig {
  name: string;
  managedBy: string;
  tags?: Record<string, string>;
  runtimes: RuntimeEntry[];
}

function readConfig(): AgentCoreConfig {
  return JSON.parse(readFileSync(CONFIG_PATH, "utf-8")) as AgentCoreConfig;
}

function depUpdaterRuntime(): RuntimeEntry {
  const runtime = readConfig().runtimes[0];
  expect(runtime, "agentcore.json must declare exactly one runtime").toBeDefined();
  if (!runtime) throw new Error("unreachable");
  return runtime;
}

describe("agentcore.json — project config", () => {
  it("declares exactly one runtime", () => {
    expect(readConfig().runtimes).toHaveLength(1);
  });

  it("is CDK-managed", () => {
    expect(readConfig().managedBy).toBe("CDK");
  });

  it("uses a Container build", () => {
    expect(depUpdaterRuntime().build).toBe("Container");
  });
});

describe("agentcore.json — discovery tags match @fleet/shared", () => {
  it("declares every tag from DEP_UPDATER_TAGS with identical values", () => {
    const tags = depUpdaterRuntime().tags ?? {};
    for (const [key, value] of Object.entries(DEP_UPDATER_TAGS)) {
      expect(tags[key], `runtime tag ${key}`).toBe(value);
    }
  });

  it("declares no extra agent:* tags beyond the shared contract", () => {
    const tags = depUpdaterRuntime().tags ?? {};
    const agentTagKeys = Object.keys(tags).filter((k) => k.startsWith("agent:"));
    expect(agentTagKeys.sort()).toEqual(Object.keys(DEP_UPDATER_TAGS).sort());
  });

  it("agent:managed is exactly the string 'true'", () => {
    expect(depUpdaterRuntime().tags?.["agent:managed"]).toBe("true");
  });

  /**
   * S-005 sub-task 5.8: the agent:name tag is the join key between the tagging
   * API and the DynamoDB AGENT# sort key. If these drift, the control plane
   * discovers an agent it cannot find config rows for.
   */
  it("agent:name equals the AGENT# sort key", () => {
    const tagName = depUpdaterRuntime().tags?.["agent:name"];
    expect(tagName).toBeDefined();
    expect(agentNameToSortKey(tagName ?? "")).toBe(`${PREFIXES.AGENT}dep-updater`);
  });
});

describe("agentcore.json — GitHub credential env var", () => {
  /**
   * The runtime resolves its GitHub credential from `GITHUB_SECRET_ID`, declared
   * here rather than baked into main.py so the PAT → GitHub App cutover and its
   * rollback are both a config change plus a redeploy.
   *
   * CUTOVER ORDERING: this points at `dep-agent/github-app`, which does not exist
   * until docs/runbook-github-app.md has been followed. The code default in
   * main.py deliberately stays `dep-agent/github-pat` so a local or CLI
   * invocation without this env var still works against the existing PAT.
   */
  function envVars(): EnvVarEntry[] {
    return depUpdaterRuntime().envVars ?? [];
  }

  function envVar(name: string): EnvVarEntry | undefined {
    return envVars().find((entry) => entry.name === name);
  }

  it("declares GITHUB_SECRET_ID", () => {
    expect(envVar("GITHUB_SECRET_ID")).toBeDefined();
  });

  it("points GITHUB_SECRET_ID at the GitHub App secret", () => {
    expect(envVar("GITHUB_SECRET_ID")?.value).toBe("dep-agent/github-app");
  });

  it("declares every env var as a { name, value } pair with non-empty strings", () => {
    expect(envVars().length).toBeGreaterThan(0);
    for (const entry of envVars()) {
      expect(Object.keys(entry).sort()).toEqual(["name", "value"]);
      expect(typeof entry.name).toBe("string");
      expect(typeof entry.value).toBe("string");
      expect(entry.name.length).toBeGreaterThan(0);
      expect(entry.value.length).toBeGreaterThan(0);
    }
  });

  it("declares no duplicate env var names", () => {
    const names = envVars().map((entry) => entry.name);
    expect(names).toEqual([...new Set(names)]);
  });

  /**
   * `envVars` reaches the runtime as plaintext in the CloudFormation template.
   * Only the secret's *name* belongs here; the credential itself stays in
   * Secrets Manager and is read at runtime.
   */
  it("carries no credential material, only the secret name", () => {
    for (const entry of envVars()) {
      expect(entry.value).not.toMatch(/^gh[pous]_/);
      expect(entry.value).not.toContain("BEGIN RSA PRIVATE KEY");
      expect(entry.value).not.toContain("BEGIN PRIVATE KEY");
    }
  });

  it("keeps the main.py default on the PAT secret so cutover ordering holds", () => {
    const mainPy = readFileSync(resolve(AGENT_DIR, "main.py"), "utf-8");
    expect(mainPy).toContain('os.environ.get("GITHUB_SECRET_ID", "dep-agent/github-pat")');
  });
});

describe("agentcore.json — observability / span delivery contract", () => {
  /**
   * REGRESSION GUARD (issue #62, defect D9).
   *
   * `aws/spans` had never received a record. Three separate causes, each
   * verified against live AWS, each pinned by a test below:
   *
   * 1. No OTLP exporter was installed. `pyproject.toml` declared only
   *    `opentelemetry-api` / `opentelemetry-sdk`, so `opentelemetry-instrument`
   *    started, `emission.py` set the attributes, and the SDK dropped the span
   *    because it had nowhere to export it. Fixed by adding ADOT.
   *
   * 2. The first fix over-configured. `OTEL_PYTHON_DISTRO`,
   *    `OTEL_PYTHON_CONFIGURATOR` and `OTEL_EXPORTER_OTLP_PROTOCOL` are
   *    documented for agents hosted *outside* the AgentCore runtime. On a
   *    runtime-hosted agent they override the endpoint the runtime injects and
   *    point the exporter at a local collector that does not exist. Removed.
   *
   * 3. Spans then arrived, but in the agent's own log group rather than
   *    `aws/spans`. AgentCore now defaults newly created agents to a per-agent
   *    span destination. `SPANS_LOG_GROUP` in @fleet/shared — and the
   *    control plane's fleet-wide runs query built on it — now point at the
   *    per-agent log group, and the opt-in is pinned here.
   *
   * See docs/runbook-observability-setup.md for the full sequence.
   */
  function envVars(): EnvVarEntry[] {
    return depUpdaterRuntime().envVars ?? [];
  }

  function envVar(name: string): EnvVarEntry | undefined {
    return envVars().find((entry) => entry.name === name);
  }

  it("enables agent observability", () => {
    expect(envVar("AGENT_OBSERVABILITY_ENABLED")?.value).toBe("true");
  });

  it("opts into the per-agent span destination (unified traces)", () => {
    expect(envVar("UNIFIED_TRACES_DESTINATION_ENABLED")?.value).toBe("true");
  });

  it("keeps the opt-in consistent with the per-agent log group used by the control plane", () => {
    // The control plane queries spans from each agent's own log group, not
    // the shared aws/spans group. aws/spans is an AWS-reserved name whose
    // lifecycle we don't control — it was deleted from the account and cannot
    // be recreated. Per-agent delivery is the robust path.
    expect(envVar("UNIFIED_TRACES_DESTINATION_ENABLED")?.value).toBe("true");
  });

  /**
   * These are the non-runtime variables. Setting any of them on a
   * runtime-hosted agent is what silently broke span export the first time.
   */
  it.each([
    "OTEL_PYTHON_DISTRO",
    "OTEL_PYTHON_CONFIGURATOR",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
    "OTEL_EXPORTER_OTLP_LOGS_HEADERS",
  ])("does not set %s, which is for non-runtime-hosted agents only", (name) => {
    expect(envVar(name)).toBeUndefined();
  });

  it("declares the ADOT distro as a production dependency", () => {
    const pyproject = readFileSync(resolve(AGENT_DIR, "pyproject.toml"), "utf-8");
    expect(pyproject).toMatch(/aws-opentelemetry-distro>=/);
  });

  /**
   * The docs are explicit: ADOT below 0.18.0 ignores span-destination
   * configuration. The opt-out above is inert on an older version.
   */
  it("requires ADOT >= 0.18.0 so the span destination setting is honoured", () => {
    const pyproject = readFileSync(resolve(AGENT_DIR, "pyproject.toml"), "utf-8");
    const match = /aws-opentelemetry-distro>=(\d+)\.(\d+)\.(\d+)/.exec(pyproject);
    expect(match, "aws-opentelemetry-distro must carry an explicit floor").not.toBeNull();
    if (!match) throw new Error("unreachable");
    const [major, minor] = [Number(match[1]), Number(match[2])];
    expect(major > 0 || minor >= 18).toBe(true);
  });

  it("resolves an OTLP exporter in the lockfile", () => {
    const lock = readFileSync(resolve(AGENT_DIR, "uv.lock"), "utf-8");
    expect(lock).toContain("opentelemetry-exporter-otlp-proto-http");
    expect(lock).toContain("aws-opentelemetry-distro");
  });

  /**
   * Auto-instrumentation is what loads the distro. Dropping the wrapper from
   * CMD disables span export just as completely as removing the dependency.
   */
  it("runs the agent under opentelemetry-instrument", () => {
    const dockerfile = readFileSync(resolve(REPO_ROOT, "Dockerfile.dep-updater"), "utf-8");
    expect(dockerfile).toMatch(/CMD \["opentelemetry-instrument", "python", "main\.py"\]/);
  });
});

describe("agentcore.json — lifecycle configuration", () => {
  /** S-006 sub-task 6.10: these values bound the control plane's `incomplete` derivation. */
  it("records maxLifetime 3600 and idle timeout 300", () => {
    const lifecycle = depUpdaterRuntime().lifecycleConfiguration;
    expect(lifecycle?.maxLifetime).toBe(3600);
    expect(lifecycle?.idleRuntimeSessionTimeout).toBe(300);
  });

  it("satisfies the CLI constraint idleRuntimeSessionTimeout <= maxLifetime", () => {
    const lifecycle = depUpdaterRuntime().lifecycleConfiguration;
    expect(lifecycle?.idleRuntimeSessionTimeout ?? 0).toBeLessThanOrEqual(
      lifecycle?.maxLifetime ?? 0,
    );
  });

  it("keeps both values within the CLI-permitted 60..28800 range", () => {
    const lifecycle = depUpdaterRuntime().lifecycleConfiguration;
    for (const value of [lifecycle?.idleRuntimeSessionTimeout, lifecycle?.maxLifetime]) {
      expect(value).toBeGreaterThanOrEqual(60);
      expect(value).toBeLessThanOrEqual(28800);
    }
  });
});

describe("agentcore.json — CLI schema constraints", () => {
  /**
   * The CLI's AgentNameSchema is /^[a-zA-Z][a-zA-Z0-9_]{0,47}$/ — hyphens are
   * rejected. The runtime resource is therefore named `dep_updater` while the
   * agent:name tag stays `dep-updater`. Discovery reads the tag, not the
   * resource name, so the DynamoDB contract is unaffected.
   */
  it("runtime name satisfies the CLI AgentNameSchema (no hyphens)", () => {
    expect(depUpdaterRuntime().name).toMatch(/^[a-zA-Z][a-zA-Z0-9_]{0,47}$/);
  });

  it("runtime name is the underscore form of the agent:name tag", () => {
    const runtime = depUpdaterRuntime();
    const tagName = runtime.tags?.["agent:name"] ?? "";
    expect(runtime.name).toBe(tagName.replace(/-/g, "_"));
  });

  /**
   * REGRESSION GUARD. The CLI appends a force-keep of the Dockerfile and each of
   * its ancestor directories to the end of the asset exclude list, and Docker
   * ignore semantics are last-match-wins. A nested Dockerfile path therefore
   * re-includes whole directory trees (.venv, cdk.out), and CDK asset staging
   * recurses into its own output until it fails with ENAMETOOLONG. Keeping the
   * Dockerfile at the build-context root emits a single `!<file>` pattern.
   */
  it("Dockerfile sits at the build-context root, not in a subdirectory", () => {
    const runtime = depUpdaterRuntime();
    expect(runtime.buildContextPath, "buildContextPath must be set").toBeDefined();
    expect(runtime.dockerfile, "dockerfile must be set").toBeDefined();
    expect(runtime.dockerfile).not.toContain("/");
  });

  it("build context resolves to the repository root", () => {
    // buildContextPath resolves relative to the project root (agents/dep-updater),
    // which is dirname(configRoot) per the CLI's resolveCodeLocation.
    const resolved = resolve(AGENT_DIR, depUpdaterRuntime().buildContextPath ?? ".");
    expect(resolved).toBe(REPO_ROOT);
  });

  it("the referenced Dockerfile exists at the resolved build context root", () => {
    const runtime = depUpdaterRuntime();
    const contextRoot = resolve(AGENT_DIR, runtime.buildContextPath ?? ".");
    const dockerfilePath = resolve(contextRoot, runtime.dockerfile ?? "Dockerfile");
    expect(() => readFileSync(dockerfilePath, "utf-8")).not.toThrow();
  });
});

describe("agentcore.json — Python version is consistent across declarations", () => {
  /** S-006 sub-task 6.3: one Python version, declared in three places. */
  it("runtimeVersion, pyproject.toml and the Dockerfile all say 3.13", () => {
    expect(depUpdaterRuntime().runtimeVersion).toBe("PYTHON_3_13");

    const pyproject = readFileSync(resolve(AGENT_DIR, "pyproject.toml"), "utf-8");
    expect(pyproject).toMatch(/requires-python\s*=\s*">=3\.13"/);

    const runtime = depUpdaterRuntime();
    const contextRoot = resolve(AGENT_DIR, runtime.buildContextPath ?? ".");
    const dockerfile = readFileSync(
      resolve(contextRoot, runtime.dockerfile ?? "Dockerfile"),
      "utf-8",
    );
    // Matches both docker.io ("python:3.13-...") and the ECR Public mirror
    // ("public.ecr.aws/docker/library/python:3.13-..."), which is what CodeBuild uses.
    expect(dockerfile).toMatch(/^FROM \S*python:3\.13-/m);
  });

  /**
   * CodeBuild runs on shared AWS IPs that Docker Hub rate-limits for anonymous
   * pulls, so `agentcore deploy` fails with "429 Too Many Requests" if the base
   * image is pulled from docker.io. Pin the ECR Public mirror instead.
   */
  it("pulls the base image from ECR Public, not docker.io", () => {
    const runtime = depUpdaterRuntime();
    const contextRoot = resolve(AGENT_DIR, runtime.buildContextPath ?? ".");
    const dockerfile = readFileSync(
      resolve(contextRoot, runtime.dockerfile ?? "Dockerfile"),
      "utf-8",
    );
    const fromLines = dockerfile.split("\n").filter((l) => /^FROM /.test(l));
    expect(fromLines.length).toBeGreaterThan(0);
    for (const line of fromLines) {
      expect(line).toContain("public.ecr.aws/");
    }
  });
});
