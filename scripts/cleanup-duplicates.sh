#!/usr/bin/env bash
# cleanup-duplicates.sh — Find and optionally delete macOS " 2" duplicate files.
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

echo "=== Scanning for ' 2' duplicate files under: $ROOT ==="
echo

# Find all files matching the " 2" pattern (macOS Finder copy convention)
FILES=()
while IFS= read -r -d '' f; do
  FILES+=("$f")
done < <(find "$ROOT" \( -name "* 2.*" -o -name "* 2" \) -print0 2>/dev/null | sort -z)

if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "No duplicate files found."
  exit 0
fi

echo "Found ${#FILES[@]} duplicate file(s):"
echo
for f in "${FILES[@]}"; do
  echo "  $f"
done
echo

if [[ "$DELETE" == true ]]; then
  echo "=== Deleting ${#FILES[@]} file(s)... ==="
  for f in "${FILES[@]}"; do
    rm -v "$f"
  done
  echo
  echo "Done. ${#FILES[@]} file(s) deleted."
else
  echo "=== Dry run — no files deleted. ==="
  echo "Run with --delete to remove them:"
  echo "  ./scripts/cleanup-duplicates.sh --delete"
fi
