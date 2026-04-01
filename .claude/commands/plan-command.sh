#!/bin/bash
set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
if [[ "$#" -gt 0 ]]; then
  REQUEST="$*"
else
  REQUEST="$(cat)"
fi

unset CLAUDECODE
unset CLAUDE_PROJECT_DIR

if [[ -z "${REQUEST//[[:space:]]/}" ]]; then
  exit 0
fi

if [[ -n "${PLAN_CLI_BIN:-}" ]]; then
  PLAN_CMD=("$PLAN_CLI_BIN")
else
  echo "PLAN_CLI_BIN is not set" >&2
  exit 1
fi

cd "$PROJECT_DIR"
printf '%s' "$REQUEST" | "${PLAN_CMD[@]}" plan --raw --stdin
