#!/usr/bin/env bash
# Create a worktree for a workstream branch: scripts/new-worktree.sh {branch} [dir]
#
# Wiring notes for THIS repo:
# - No secrets files and no shared caches to wire; each worktree recreates its
#   own .venv on first `uv run` / `uv sync`.
# - PEN RULE (shared mutable state): Jake's real collection data
#   (data/inventory.yaml, data/probabilities.yaml, data/values.jsonl —
#   append-only — and data/batches/) is gitignored and lives ONLY in the main
#   checkout. The main checkout holds the pen; worktrees develop against the
#   committed data/sample/ fixtures and MUST NOT create their own real-data
#   files. Analysis runs against real data happen in the main checkout.
set -euo pipefail
cd "$(dirname "$0")/.."

branch="${1:?usage: scripts/new-worktree.sh BRANCH [DIR]}"
dir="${2:-../card-grade-scope-${branch}}"

if git show-ref --verify --quiet "refs/heads/${branch}"; then
  git worktree add "${dir}" "${branch}"
else
  git worktree add -b "${branch}" "${dir}" main
fi

echo
echo "Worktree ready: ${dir} (branch: ${branch})"
echo "Reminder: real data stays in the main checkout (pen rule in script header)."
echo "Next: cd ${dir} && scripts/checks.sh"
