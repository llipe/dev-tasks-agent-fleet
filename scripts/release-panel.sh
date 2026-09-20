#!/usr/bin/env bash
#
# release-panel.sh — suggest the next panel-vX.Y.Z tag from Conventional
# Commits, confirm with a human, then cut the annotated tag + GitHub Release
# that fires .github/workflows/deploy-panel.yml.
#
# Numbering was previously ad hoc (an operator picking panel-vX.Y.Z by hand
# after reading `git tag -l` and the commit log). This script replaces the
# guesswork with a suggestion; a human still makes the final call.
#
# Scope: only commits touching panel-relevant paths count toward the bump —
# this is a monorepo, and an unrelated agents/ change must not force a panel
# release number to jump.
#
# Bump rules (Conventional Commits, https://www.conventionalcommits.org):
#   any commit subject/body with `BREAKING CHANGE` or a `!` before the `:`
#     (e.g. `feat!:`, `fix(panel)!:`)                       -> MAJOR
#   any `feat:` / `feat(scope):` commit                     -> MINOR
#   anything else conventional (`fix`, `perf`, `refactor`,
#     `docs`, `chore`, `test`, `ci`, ...)                    -> PATCH
#   no commits touching panel paths since the last tag       -> refuse (exit 2)
#
# Tag policy (human-only, unchanged by this script): annotated, cut on `main`
# only, immutable, no prerelease. This script NEVER moves or deletes a tag.
#
# Usage:
#   scripts/release-panel.sh [--dry-run] [--yes]
#
#   --dry-run   Print the suggested version and changelog; make no changes.
#   --yes       Skip the interactive confirmation prompt (still refused in CI
#               without INFRA_HUMAN_APPROVED=1 — see the human-only guard below).
#
# Exit codes: 0 ok · 1 error · 2 blocked
set -euo pipefail

DRY_RUN=false
ASSUME_YES=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --yes) ASSUME_YES=true ;;
    --help|-h)
      sed -n '2,33p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

TAG_PREFIX="panel-v"
# Paths whose commits count toward the panel version.
PANEL_PATHS=(
  panel
  Dockerfile.panel
  .dockerignore
  scripts/deploy-panel.sh
  scripts/verify-panel-auth.sh
  scripts/release-panel.sh
  docs/runbooks/panel-deployment.md
  .github/workflows/deploy-panel.yml
)

echo "== release-panel: preflight =="

# --- Human-only guard --------------------------------------------------
# This script creates a tag and a GitHub Release — a human decision, even
# when it runs inside a protected-environment CI job. It must never fire
# unattended from an ordinary CI trigger.
if ! $DRY_RUN; then
  if [[ -n "${CI:-}" && "${INFRA_HUMAN_APPROVED:-}" != "1" ]]; then
    echo "BLOCKED: running under CI without INFRA_HUMAN_APPROVED=1. Tag/release creation is human-only." >&2
    exit 2
  fi
  if ! $ASSUME_YES && [[ ! -t 0 ]]; then
    echo "BLOCKED: no interactive TTY and --yes not passed. Refusing to guess at confirmation." >&2
    exit 2
  fi
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "BLOCKED: gh CLI not found on PATH." >&2
  exit 2
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "BLOCKED: gh is not authenticated (gh auth login)." >&2
  exit 2
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  echo "BLOCKED: on branch '$CURRENT_BRANCH' — release tags are cut on main only." >&2
  exit 2
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "BLOCKED: working tree is not clean." >&2
  exit 2
fi
git fetch origin main --tags -q
if [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]]; then
  echo "BLOCKED: local main is not up to date with origin/main." >&2
  exit 2
fi

# --- Find the last panel tag and the commits since it -------------------
LAST_TAG="$(git tag -l "${TAG_PREFIX}*" --sort=-v:refname | head -1)"
if [[ -z "$LAST_TAG" ]]; then
  echo "== release-panel: no prior ${TAG_PREFIX}* tag found — this will be the first release =="
  RANGE="HEAD"
  LAST_VERSION="0.0.0"
else
  echo "== release-panel: last release is $LAST_TAG =="
  RANGE="${LAST_TAG}..HEAD"
  LAST_VERSION="${LAST_TAG#"$TAG_PREFIX"}"
fi

COMMITS="$(git log "$RANGE" --pretty=format:'%H%x09%s%x09%b%x03' -- "${PANEL_PATHS[@]}")"
if [[ -z "$COMMITS" ]]; then
  echo "BLOCKED: no commits touching panel paths since $LAST_TAG. Nothing to release." >&2
  exit 2
fi

# --- Classify the bump ----------------------------------------------------
BUMP="patch"
declare -a LOG_LINES=()
while IFS=$'\t' read -r -d $'\x03' HASH SUBJECT BODY; do
  [[ -z "$HASH" ]] && continue
  SHORT="${HASH:0:7}"
  LOG_LINES+=("- ${SUBJECT} (${SHORT})")
  if [[ "$SUBJECT" == *"!:"* ]] || [[ "$SUBJECT $BODY" == *"BREAKING CHANGE"* ]]; then
    BUMP="major"
  elif [[ "$BUMP" != "major" && "$SUBJECT" =~ ^feat(\(.+\))?: ]]; then
    BUMP="minor"
  fi
done <<< "$COMMITS"

IFS='.' read -r MAJOR MINOR PATCH <<< "$LAST_VERSION"
case "$BUMP" in
  major) NEXT_VERSION="$((MAJOR + 1)).0.0" ;;
  minor) NEXT_VERSION="${MAJOR}.$((MINOR + 1)).0" ;;
  patch) NEXT_VERSION="${MAJOR}.${MINOR}.$((PATCH + 1))" ;;
esac
NEXT_TAG="${TAG_PREFIX}${NEXT_VERSION}"

echo ""
echo "== release-panel: suggested release =="
echo "  previous : ${LAST_TAG:-<none>}"
echo "  next     : $NEXT_TAG   (bump: $BUMP)"
echo ""
echo "  commits since ${LAST_TAG:-the beginning}:"
printf '%s\n' "${LOG_LINES[@]}"
echo ""

if $DRY_RUN; then
  echo "-- DRY RUN: no tag or release created --"
  exit 0
fi

if git rev-parse "$NEXT_TAG" >/dev/null 2>&1; then
  echo "BLOCKED: $NEXT_TAG already exists. Tags are immutable — re-run after resolving the collision (e.g. a manual version override is not supported by this script; edit LAST_TAG detection or delete an erroneous unpublished tag by hand)." >&2
  exit 2
fi

if ! $ASSUME_YES; then
  read -r -p "Create annotated tag and GitHub Release '$NEXT_TAG' on main HEAD ($(git rev-parse --short HEAD))? [y/N] " REPLY
  if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
    echo "Aborted — no changes made."
    exit 0
  fi
fi

NOTES_FILE="$(mktemp)"
trap 'rm -f "$NOTES_FILE"' EXIT
{
  echo "Automated bump: $BUMP (Conventional Commits, panel-scoped paths)."
  echo ""
  printf '%s\n' "${LOG_LINES[@]}"
} > "$NOTES_FILE"

echo "== release-panel: creating annotated tag $NEXT_TAG =="
git tag -a "$NEXT_TAG" -m "Release $NEXT_TAG"
git push origin "$NEXT_TAG"

echo "== release-panel: creating GitHub Release =="
gh release create "$NEXT_TAG" \
  --target main \
  --title "Panel $NEXT_TAG" \
  --notes-file "$NOTES_FILE"

echo "== release-panel: OK — $NEXT_TAG published; deploy-panel.yml should now be waiting on the production reviewer =="
