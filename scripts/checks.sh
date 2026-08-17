#!/usr/bin/env bash
# The green bar, defined once. CI and the commit guard both run this script,
# so the local bar and the CI bar cannot drift.
# Changing the commands here means updating CLAUDE.md's Commands section in
# the same commit.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "checks.sh: uv not found on PATH — install uv (https://docs.astral.sh/uv/) and retry" >&2
  exit 1
fi

# `bash -n a.sh b.sh` parses only a.sh — the rest become its positional
# parameters, so a syntax error in every script but the first went unseen. One
# file per invocation, and globbed so a script added later is still checked.
# This lives here rather than in CI so that local green still means CI green.
for f in scripts/*.sh .claude/hooks/*.sh; do
  bash -n "$f"
done

uv run ruff check .
uv run ruff format --check .
uv run pytest -q
echo "checks.sh: green"
