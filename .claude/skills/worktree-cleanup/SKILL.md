---
name: worktree-cleanup
description: Tear down finished git worktrees for card-grade-scope — verify merged + clean, then remove worktree, delete branch, prune. Use when the user wants to clean up, tear down, or sweep worktrees/branches.
---

# worktree-cleanup (card-grade-scope)

Thin wrapper over `scripts/rm-worktree.sh`, which gates on: branch merged into
main (`--force` for squash-merges), clean tree, not the main checkout, not the
current directory.

## With a branch argument

```bash
scripts/rm-worktree.sh <branch>
```

Add `--force` if the PR was squash-merged; add `--delete-remote` to also
delete the remote branch.

## With no argument — sweep

1. `git worktree list` from the main checkout.
2. For each non-main worktree: check `git -C <dir> status --porcelain` is
   empty and the branch is merged — `git merge-base --is-ancestor
   refs/heads/<branch> refs/heads/main`, or the same against
   `refs/remotes/origin/main` (fetch first), or squash-merged per the PR
   history. Use fully-qualified refs: a bare name lets a same-named tag win
   the lookup and make an unmerged branch look merged. Check origin too —
   branches here merge by PR, so local `main` is routinely behind and a
   local-only test would drop merged branches off this list.
3. List the candidates, confirm once with the user, then run
   `scripts/rm-worktree.sh` for each (with `--force` only where squash-merged).

## Repo-specific notes

- Real collection data (gitignored `data/` files) lives only in the main
  checkout — removing a worktree never touches it. If a worktree somehow has
  its own real-data files, stop and flag it: that violates the pen rule in
  `scripts/new-worktree.sh`.
- Worktree `.venv/` directories are disposable (recreated by `uv run`).
