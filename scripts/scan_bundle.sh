#!/usr/bin/env bash
# Scan a built static bundle (or any directory) before it is published.
# Usage: scripts/scan_bundle.sh <dir> [blocklist-file]
# The optional blocklist is a private list of names (one per line) that must not
# appear anywhere; it is matched case-insensitively as whole words and its
# contents are never printed. Exits non-zero on any hit.
set -euo pipefail

dir="${1:?usage: scan_bundle.sh <dir> [blocklist-file]}"
blocklist="${2:-}"
[ -d "$dir" ] || { echo "scan: no such directory: $dir" >&2; exit 2; }

fail=0
check() { # <label> <extended regex>
  local label="$1" re="$2" hits
  hits="$(grep -rIEno "$re" "$dir" 2>/dev/null || true)"
  if [ -n "$hits" ]; then
    echo "scan: FAIL $label"
    echo "$hits" | cut -c1-200 | head -20
    fail=1
  else
    echo "scan: ok   $label"
  fi
}

check "workspace host"   '[A-Za-z0-9-]+\.cloud\.databricks\.com|databricksapps\.com|azuredatabricks\.net'
check "internal npm host" 'npm-proxy|artifactory|jfrog\.io|nexus\.[a-z]'
check "access token"     'dapi[0-9a-f]{20,}'
check "system prompt"    'system_prompt'
check "uuid"             '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'

# Emails: only reserved example domains are allowed.
emails="$(grep -rIEoh '[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}' "$dir" 2>/dev/null \
  | grep -viE '@(example\.(com|org|net)|[A-Za-z0-9.-]+\.example)$' | sort -u || true)"
if [ -n "$emails" ]; then echo "scan: FAIL email"; echo "$emails" | head -20; fail=1; else echo "scan: ok   email"; fi

if [ -n "$blocklist" ]; then
  [ -f "$blocklist" ] || { echo "scan: blocklist not found: $blocklist" >&2; exit 2; }
  terms="$(mktemp)"; trap 'rm -f "$terms"' EXIT
  grep -v '^[[:space:]]*$' "$blocklist" | grep -v '^#' > "$terms" || true
  files="$(grep -rIlwiFf "$terms" "$dir" 2>/dev/null || true)"
  if [ -n "$files" ]; then
    echo "scan: FAIL blocklist (terms not shown) in:"; echo "$files" | head -20; fail=1
  else
    echo "scan: ok   blocklist ($(wc -l < "$terms" | tr -d ' ') terms)"
  fi
fi

[ "$fail" -eq 0 ] && echo "scan: PASS $dir" || echo "scan: FAILED $dir"
exit "$fail"
