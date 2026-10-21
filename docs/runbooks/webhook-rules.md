---
name: runbook-webhook-rules
trigger: Writing or debugging a webhook rule in /webhooks (events, conditions, repository source, payload parameters)
owner: operator (repository owner)
last_verified: 2026-10-21 — behavior checked against panel/lib/domain/webhook-routing.ts, webhook-resolve.ts and webhook-rule-save.ts on main (08a2ded)
related: ["panel/lib/domain/webhook-routing.ts", "panel/lib/domain/webhook-resolve.ts", "panel/lib/domain/webhook-rule-save.ts", "docs/runbooks/webhook-deployment.md"]
---

# Webhook rules: conditions and configuration

How a rule on `/webhooks/<endpoint>` decides whether a delivery starts a run, and what each
field accepts. For creating endpoints, secrets and the GitHub registration, see
[`webhook-deployment.md`](webhook-deployment.md).

## How a delivery is matched

A delivery that passes the signature check is evaluated in this order. The first step that
decides wins, and the outcome is shown in the endpoint's delivery log.

1. **Event allowlist** (endpoint setting). The `X-GitHub-Event` header must be one of the
   endpoint's events, or the delivery is `ignored` ("Event is not in this endpoint's events").
2. **Bot guard** (endpoint setting "Ignore events from the fleet's bot", on by default). If
   `sender.login` is the fleet's bot (`devtasks-agent-fleet[bot]`) **and** `sender.type` is
   `Bot`, the delivery is `ignored` ("Sent by the fleet's own bot"). This runs before any rule.
3. **Rules, top to bottom.** Disabled rules and the default rule are skipped. A rule matches
   when the event is one of its events **and every** condition holds. The first match fires;
   later rules are not evaluated.
4. **Default rule.** If nothing matched and the endpoint has an enabled default rule, it
   fires. It ignores events and conditions.
5. Otherwise the delivery is `no_match`.

After a rule is chosen, its repository and parameters are resolved (see below). If that
fails, the delivery is `rejected`. Otherwise the guardrails decide between `fired` (a run
starts) and `skipped` (a run is already active for the agent and repository, the last run's
PR is still open, or the fleet-wide concurrency cap is reached).

Order matters: put specific rules above general ones, because a broad rule higher up will
take every delivery it matches.

## Events

A rule lists one or more events, chosen from the endpoint's allowlist. A non-default rule
needs at least one. Common GitHub events:

| Event | Fires for | Useful `action` values |
| --- | --- | --- |
| `issue_comment` | comments on issues **and** on pull requests (the conversation tab) | `created`, `edited`, `deleted` |
| `pull_request_review_comment` | inline review comments on a PR diff | `created`, `edited`, `deleted` |
| `pull_request_review` | a submitted review | `submitted`, `edited`, `dismissed` |
| `pull_request` | PR lifecycle | `opened`, `reopened`, `synchronize`, `closed`, `labeled`, `ready_for_review` |
| `push` | pushes to a branch | (no `action`; use `ref`) |
| `issues` | issue lifecycle | `opened`, `labeled`, `closed` |

Most events send several actions. Without an `action` condition, a rule on `issue_comment`
also fires on edits and deletions, so add `action equals created` when you only want new
comments.

## Conditions

Each condition is **field · operator · value**. All conditions on a rule must hold (AND).
There is no OR inside a rule: use two rules, or `in`. A rule with no conditions matches every
delivery of its events.

### Operators

| Operator | Holds when | Value |
| --- | --- | --- |
| `equals` | the field is a string identical to the value | one string |
| `not_equals` | the field is a string different from the value | one string |
| `contains` | the field is a string containing the value | one string |
| `prefix` | the field is a string starting with the value | one string |
| `suffix` | the field is a string ending with the value | one string |
| `in` | the field is a string equal to one of the values | a list. In the editor, separate values with commas: `opened, reopened` |
| `exists` | the field is present and not `null` (any type, including `false`, `0` and objects) | none |
| `matches_event` | the delivery's event equals the value (no field) | one event name. Not offered in the editor; the event checkboxes do the same |

Rules for every operator:

- **Case-sensitive, exact text.** `contains /audit` does not match `/AUDIT` or `/Audit`.
  There is no regex, wildcard or case-insensitive option. Add a second rule if you need
  another spelling.
- **Strings only, no conversion.** Except for `exists`, the field must be a string. A number
  or boolean never matches: `issue.number equals 7` is always false, and so is
  `pull_request.draft equals false`. Use `exists`, or a string field instead.
- **A missing field is never a match**, not even for `not_equals`. `comment.body not_equals
  /skip` is false when there is no `comment.body`. To mean "absent or different", combine it
  with a rule order that handles the absent case first.
- **Long strings don't match.** A field or value over 1,024 characters makes the condition
  false (the comparison is skipped, not truncated).
- `exists` is the way to test booleans, numbers and objects. For example
  `issue.pull_request exists` separates comments on a PR from comments on a plain issue.
  `pull_request.draft exists` is true for both drafts and non-drafts, so it does not tell
  them apart.

### Field paths

A path names a value in the JSON payload, as GitHub sends it:

- dot-separated keys: `comment.body`, `pull_request.head.ref`;
- `[n]` for an array element, counted from 0: `pull_request.labels[0].name`;
- keys may use letters, digits and `_ - : @ $`. No spaces, empty segments (`a..b`),
  wildcards (`[*]`), negative indexes or quotes;
- at most 16 segments (each index counts) and 200 characters;
- `__proto__`, `constructor` and `prototype` are always rejected.

There is no "any element of an array" path: `labels[0]` is only the first label. To react to
a label being added, use the `pull_request` or `issues` event with `action equals labeled`
and `label.name equals <name>`, which carries the label that was just added.

Paths you will use most often with GitHub:

| Path | Example value | Notes |
| --- | --- | --- |
| `action` | `created`, `opened` | what happened |
| `comment.body` | `/audit please` | `issue_comment`, `pull_request_review_comment` |
| `comment.user.login` / `sender.login` | `llipe` | who triggered it |
| `sender.type` | `User`, `Bot` | |
| `issue.pull_request` | (object) | present only when the comment is on a PR; use `exists` |
| `pull_request.base.ref` / `pull_request.head.ref` | `main`, `feature/x` | target and source branch |
| `ref` | `refs/heads/main` | `push` only |
| `label.name` | `security` | `labeled` / `unlabeled` actions |
| `repository.full_name` | `llipe/memo-cli` | the default repository source |

The full payload for each event is in GitHub's "Webhook events and payloads" documentation,
and under Settings → Webhooks → Recent Deliveries on the repository.

### Limits

Up to 50 conditions per rule and 50 values per `in`.

## Repository

A rule's agent runs against one repository, chosen in one of two ways:

- **From the payload** (default `repository.full_name`): the value must be an `owner/name`
  string naming a repository that is registered **and enabled** on `/repositories` (case does
  not matter). Anything else rejects the delivery: "The payload's repository is not a
  registered, enabled repository." A webhook can never start a run on a repository the
  panel doesn't already know.
- **Fixed repository**: always the same one, chosen from the enabled repositories.

For an agent that doesn't take a repository, this setting is ignored.

## Parameters

The parameter grid is the agent's own form, as in Invoke and Schedules. Values set there are
stored on the rule and sent with every run.

**Fill from the payload** adds per-run values on top. Each row maps one of the agent's
parameters to a payload path. For example `pr_number` ← `issue.number`.

- Only parameters the agent declares, and only single-value types (string, number, integer,
  boolean). Lists and objects can't be filled from the payload.
- If the path is missing in a delivery, the fixed value (or the agent default) is used.
- If the path holds an object or a list, the delivery is rejected ("The rule's parameters
  failed the agent's schema").
- After merging, the parameters are validated against the agent's schema for every
  delivery. A payload value of the wrong type or outside an allowed list rejects the
  delivery rather than starting a broken run.
- A required parameter may be left empty in the grid if a payload row fills it, but then a
  delivery without that path is rejected.

List-typed parameters such as the security-analyst's `scanners` show as "unsupported" in
the grid and keep the agent's default.

## Guardrails

- **Disable after consecutive failed starts** (default 3, range 1–100): the rule turns itself
  off after that many runs in a row fail **to start**, and sends one notification. A run that
  starts and later fails doesn't count. Turning the rule back on resets the counter.
- **Notify me when a run succeeds**: off by default. Failures and PRs always notify.
- **Enabled**: a disabled rule is skipped as if it didn't exist.
- Always on: no run starts while one is active for the same agent and repository, or while
  the last run's PR is open (a later manual run clears that), and the fleet-wide concurrency
  cap applies. These show as `skipped` with the reason.

## Checked before saving

**Save rule** refuses a rule, and highlights the field, when:

- a non-default rule has no events, or an event the endpoint doesn't accept;
- a condition has an unknown operator, a missing value, a value on `exists`, an extra key, or
  a path that doesn't parse;
- the agent is missing or disabled;
- the repository path is empty or invalid, or the fixed repository is disabled or archived;
- a parameter fails the agent's schema, isn't declared by the agent, or a payload row has no
  parameter chosen or an invalid path;
- the threshold is outside 1–100;
- the endpoint already has a different default rule (one per endpoint).

Passing these checks means the rule is well formed. Whether it matches a given delivery
still depends on the payload, so test it.

## Testing a rule

1. Trigger the event on a test repository: for an `issue_comment` rule, comment on an issue.
2. Open the endpoint page. The newest row in **Deliveries** shows the outcome and, in plain
   language, why: `fired` (with **Open run ▸**), `no match`, `skipped`, `rejected` or
   `ignored`.
3. For `no match`, compare the rule's conditions with the payload under the repository's
   Settings → Webhooks → Recent Deliveries. Case and non-string fields are the usual causes.
4. GitHub's **Redeliver** button sends the same delivery id, so it is recorded as `duplicate`
   and starts nothing. Send a new event to test again.

## Examples

**`/audit` comment → security-analyst, audit only, on the commented repository**

- Events: `issue_comment`
- Conditions: `action equals created`; `comment.body prefix /audit`
- Agent: Security Analyst · Repository: from the payload (`repository.full_name`) · `mode`: `audit_only`

**Security review requested in a PR review comment**

- Events: `pull_request_review_comment`
- Conditions: `action equals created`; `comment.body contains security review`
- Agent and repository as above. Note that `Security review` would not match.

**`/audit` only on pull requests, only from the owner**

- Events: `issue_comment`
- Conditions: `issue.pull_request exists`; `comment.user.login equals llipe`; `comment.body prefix /audit`

**A PR opened or reopened against `main`**

- Events: `pull_request`
- Conditions: `action in opened, reopened`; `pull_request.base.ref equals main`

**A push to `main` on one fixed repository**

- Events: `push`
- Conditions: `ref equals refs/heads/main`
- Repository: fixed

**Catch-all**

- Turn on **Default rule** (events and conditions are hidden). It fires only when no other
  rule matched. Keep it narrow in effect, for example `audit_only`, because it runs for
  every allowlisted event that nothing else claimed.
