# card-grade-scope — repo conventions

PSA grading decision-support tool. Source of truth: [SPEC.md](SPEC.md) (approved Gate 0),
[tasks/plan.md](tasks/plan.md) (approved Gate 1), [tasks/todo.md](tasks/todo.md) (current state).

## Commands (the green bar)

`scripts/checks.sh` defines the bar once — CI runs it, the commit guard enforces it. It runs:

```
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Green before **every** commit. Changing `checks.sh` means updating this section in the same commit.

## Workflow

- **PR-based flow.** One branch per workstream via `scripts/new-worktree.sh {branch}`; main is
  the review inbox. PRs are opened for Jake's review and **never merged by the agent**.
- **Gates:** spec → plan → build are gated (⛳ in tasks/plan.md). Within an approved phase, build
  autonomously (checkpoint-batched approvals; no per-commit asks). Stop at PR handoffs.
- One code-reviewer pass per PR diff, findings addressed, before handing the PR to Jake.
- Teardown finished worktrees with `scripts/rm-worktree.sh` or the repo `worktree-cleanup` skill.

## Commit guard escapes (deliberate, visible overrides only)

- `SKIP_CHECKS=1 git commit ...` — skip the checks.sh run (e.g. docs-only emergency; rare).
- `ALLOW_MAIN_COMMIT=1 git commit ...` — permit a commit on main (bootstrap/scaffold class only).

## Pen registry (shared mutable state)

- **Real collection data** (`data/inventory.yaml`, `data/probabilities.yaml`, append-only
  `data/values.jsonl`, `data/batches/`): gitignored, exists **only in the main checkout**, which
  holds the pen. Worktrees develop against committed `data/sample/` fixtures and must not create
  real-data files. Analysis runs on real data happen in the main checkout.

## Hard rules (from SPEC — not relaxable here)

- Deterministic core: no network, no API keys, no AI/vendor coupling in `src/` or on-disk schemas.
- Money is `Decimal`; YAML/JSON numbers parse via string → `Decimal`, never through `float`.
- Explicit errors over silent normalization (probability sums, CSV rows, schema violations).
- Never commit real inventory/values; sample data is synthetic + public checklists only.
- No AI attribution trailers in commits or PRs.
