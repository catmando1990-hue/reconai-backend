#!/usr/bin/env bash
set -euo pipefail

fail=0

check_path() {
  local p="$1"
  if [ -e "$p" ]; then
    echo "HYGIENE_FAIL: Found disallowed path: $p" >&2
    fail=1
  fi
}

# Secrets / local config
check_path ".env"
check_path ".env.local"

# Node artifacts should not live in backend repo packages
check_path "node_modules"

# Python bytecode caches should not be shipped in repo zips
check_path "__pycache__"
check_path "app/__pycache__"

if [ "$fail" -ne 0 ]; then
  echo "Repo hygiene check FAILED. Remove the listed paths before committing/deploying." >&2
  exit 2
fi

echo "Repo hygiene check PASS."
