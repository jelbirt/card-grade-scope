#!/usr/bin/env bash
# Tear down a finished workstream worktree: scripts/rm-worktree.sh {branch} [--force] [--delete-remote]
#   --force          also covers squash-merged branches (the merged-check can't
#                    see them)
#   --delete-remote  delete the remote branch too (if a remote exists)
#
# ORDER MATTERS, AND SO DOES WHO DECIDES. The worktree has to go before the
# branch, because git will not delete a branch that is still checked out — so by
# the time the branch delete runs the removal is already irreversible, and
# nothing after it may veto. The merged gate below is the sole authority and the
# branch delete is `-D`, not `-d`: `-d` asks a DIFFERENT question (reachable
# from HEAD or upstream, not "merged into main"), and when the two disagree it
# refuses with the worktree already gone, leaving a half-torn-down repo and a
# suggestion to use --force — which skips the merged gate entirely.
set -euo pipefail

# Snapshot the caller's cwd BEFORE the cd below, or the "you are standing inside
# it" gate below compares the repo root against itself.
invoked_from="$(pwd -P 2>/dev/null || printf '%s' "${PWD:-}")"
cd "$(dirname "$0")/.."
repo_root="$PWD"

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
# A registered worktree whose directory is gone makes every gate below fail
# open. Refuse rather than delete a branch whose checkout may have only moved.
[ -d "$dir" ] || {
  echo "refusing: worktree for ${branch} is registered at ${dir}, but that directory does not exist" >&2
  echo "  if it was moved: git worktree repair — if it is gone: git worktree prune" >&2
  exit 1
}
[ "$dir" != "$main_checkout" ] || { echo "refusing to remove the main checkout" >&2; exit 1; }
for d in "$invoked_from" "$repo_root"; do
  case "$d" in
    "$dir"|"$dir"/*) echo "refusing: you are inside ${dir} — cd out first" >&2; exit 1 ;;
  esac
done

# Capture the status and its exit code separately: a command substitution inside
# `[ -n ... ]` throws the exit code away, so a FAILING git status reads as clean.
if ! status="$(git -C "$dir" status --porcelain 2>&1)"; then
  echo "refusing: cannot read git status in ${dir}" >&2
  printf '%s\n' "$status" >&2
  exit 1
fi
if [ -n "$status" ]; then
  echo "refusing: worktree ${dir} has uncommitted changes" >&2
  exit 1
fi

# Fully-qualified refs: a bare name lets a same-named TAG win the lookup and
# make an unmerged branch look merged. Check origin/main as well — in a PR flow
# the branch is merged on origin while local main is still behind, and a
# local-only test would report "not merged" and train the --force habit.
git fetch --quiet origin main 2>/dev/null || true
merged=0
for base in refs/heads/main refs/remotes/origin/main; do
  git show-ref --verify --quiet "$base" || continue
  if git merge-base --is-ancestor "refs/heads/${branch}" "$base"; then
    merged=1
    break
  fi
done
if [ "$merged" -eq 0 ]; then
  if [ "$force" -eq 1 ]; then
    echo "warning: ${branch} is not merged into main (squash-merge?) — proceeding due to --force"
  else
    echo "refusing: ${branch} is not merged into main (use --force if squash-merged)" >&2
    exit 1
  fi
fi

git worktree remove "$dir"
# -D, not -d: see the header. The merged gate above is the authority, and
# nothing may veto once the removal above has made teardown irreversible.
git branch -D "${branch}"
git worktree prune
if [ "$delete_remote" -eq 1 ] && git remote get-url origin >/dev/null 2>&1; then
  git push origin --delete "${branch}"
fi
echo "removed worktree ${dir} and branch ${branch}"
