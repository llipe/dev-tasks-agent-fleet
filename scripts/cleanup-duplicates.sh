#!/usr/bin/env bash
# cleanup-duplicates.sh — Find and optionally delete macOS " 2" duplicate files and folders.
#
# Usage:
#   ./scripts/cleanup-duplicates.sh          # scan only (dry run)
#   ./scripts/cleanup-duplicates.sh --delete # actually delete

set -euo pipefail

DELETE=false
ROOT="."

# Parse args
for arg in "$@"; do
  case "$arg" in
    --delete) DELETE=true ;;
    *) ROOT="$arg" ;;
  esac
done

echo "=== Scanning for ' 2' duplicate files and folders under: $ROOT ==="
echo

# Find all files and directories matching the " 2" pattern (macOS Finder copy convention).
# Results are sorted in reverse so that nested entries are deleted before their
# parent " 2" directories, avoiding stale paths when a parent is removed first.
ENTRIES=()
while IFS= read -r -d '' f; do
  ENTRIES+=("$f")
done < <(find "$ROOT" \( -name "* 2.*" -o -name "* 2" \) -print0 2>/dev/null | sort -zr)

if [[ ${#ENTRIES[@]} -eq 0 ]]; then
  echo "No duplicate files or folders found."
  exit 0
fi

echo "Found ${#ENTRIES[@]} duplicate entr(y/ies):"
echo
for f in "${ENTRIES[@]}"; do
  if [[ -d "$f" ]]; then
    echo "  [dir]  $f"
  else
    echo "  [file] $f"
  fi
done
echo

if [[ "$DELETE" == true ]]; then
  echo "=== Deleting ${#ENTRIES[@]} entr(y/ies)... ==="
  for f in "${ENTRIES[@]}"; do
    # Skip entries whose path no longer exists (e.g. a parent " 2" dir was
    # already removed, taking nested " 2" entries with it).
    [[ -e "$f" || -L "$f" ]] || continue
    if [[ -d "$f" && ! -L "$f" ]]; then
      rm -rfv "$f"
    else
      rm -v "$f"
    fi
  done
  echo
  echo "Done. ${#ENTRIES[@]} entr(y/ies) processed."
else
  echo "=== Dry run — nothing deleted. ==="
  echo "Run with --delete to remove them:"
  echo "  ./scripts/cleanup-duplicates.sh --delete"
fi
