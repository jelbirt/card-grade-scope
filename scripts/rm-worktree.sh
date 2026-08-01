#!/usr/bin/env bash
# Tear down a finished workstream worktree: scripts/rm-worktree.sh {branch} [--force] [--delete-remote]
#   --force          also covers squash-merged branches (merged-check can't see
#                    them); upgrades branch delete to -D
#   --delete-remote  delete the remote branch too (if a remote exists)
set -euo pipefail
cd "$(dirname "$0")/.."

branch="${1:?usage: scripts/rm-worktree.sh BRANCH [--force] [--delete-remote]}"
force=0
delete_remote=0
for arg in "${@:2}"; do
  case "$arg" in
    --force) force=1 ;;
    --delete-remote) delete_remote=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 1 ;;
  esac
done

main_checkout="$(git rev-parse --path-format=absolute --git-common-dir)"
main_checkout="$(dirname "$main_checkout")"

dir="$(git worktree list --porcelain | awk -v b="refs/heads/${branch}" '
  $1 == "worktree" { wt = $2 }
  $1 == "branch" && $2 == b { print wt }')"
[ -n "$dir" ] || { echo "no worktree found for branch ${branch}" >&2; exit 1; }
[ "$dir" != "$main_checkout" ] || { echo "refusing to remove the main checkout" >&2; exit 1; }
case "$PWD/" in "$dir"/*) echo "refusing: you are inside ${dir} — cd out first" >&2; exit 1 ;; esac

if [ -n "$(git -C "$dir" status --porcelain)" ]; then
  echo "refusing: worktree ${dir} has uncommitted changes" >&2
  exit 1
fi

if ! git merge-base --is-ancestor "${branch}" main; then
  if [ "$force" -eq 1 ]; then
    echo "warning: ${branch} not an ancestor of main (squash-merge?) — proceeding due to --force"
  else
    echo "refusing: ${branch} is not merged into main (use --force if squash-merged)" >&2
    exit 1
  fi
fi

git worktree remove "$dir"
if [ "$force" -eq 1 ]; then git branch -D "${branch}"; else git branch -d "${branch}"; fi
git worktree prune
if [ "$delete_remote" -eq 1 ] && git remote get-url origin >/dev/null 2>&1; then
  git push origin --delete "${branch}"
fi
echo "removed worktree ${dir} and branch ${branch}"
