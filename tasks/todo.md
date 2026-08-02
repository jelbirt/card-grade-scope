# card-grade-scope — task checklist

Source of truth for task detail: [tasks/plan.md](plan.md). Status: Gate 1 approved; building Phase 1.

Pen registry: real `data/` files live only in the main checkout (see CLAUDE.md).
Remote: https://github.com/jelbirt/card-grade-scope — **private now, intended public later** (Jake, 2026-08-01).

## Pre-publication sweep (before flipping the repo public)
- [ ] `git log --all --diff-filter=A --name-only` shows nothing under `data/` beyond `data/costs/` and `data/sample/`
- [ ] Grep history and docs for real-inventory specifics (condition/provenance of Jake's actual copies), none present
- [ ] PR bodies / issues / CI logs contain no real-data output (analysis runs on real data happen locally only)
- [ ] README states the sample data is synthetic

## Scaffold
- [x] Run repo-adopt (checks.sh, commit guard, worktree scripts, CI, PR template, repo CLAUDE.md)

## Phase 1 — Deterministic core (PR #1)
- [x] Task 1: Project skeleton, models, data loading, real cost book, sample collection, `gradescope costs`
- [x] Task 2: Single-card EV engine, two views, provisional verdicts, golden tests, `analyze --card`
- [x] Task 3: Break-even solver (+ monotonicity property test)
- [x] ⛳ Checkpoint A (internal): paper-recompute matches golden output (4 golden cases, exact Decimal)
- [x] Task 4: Batch analysis — amortization, marginal classification, tier-minimum flags, `analyze --batch`
- [x] Task 5: Sensitivity + flip points, final verdict rules, staleness, summary-first report, `--compare-scenarios`
- [x] Task 6: No-network guarantee, config.yaml knobs, fuzz-case hardening
- [x] ⛳ Checkpoint B — PR #1: review pass done (4 findings fixed), reshaped per Jake's utility-first direction, merged by Jake 2026-08-02

## Phase 2 — Input paths (PR #2)
- [ ] Task 7: CSV import with per-row errors, `--strict`; Next Destinies + Dark Explorers checklist fixtures import 214/214
- [ ] Task 8: Guided entry with condition-questionnaire prior (accept/edit)
- [ ] Task 9: `snapshot` entry + `validate-snapshots` linter
- [ ] ⛳ Checkpoint C — PR #2: review pass, hand to Jake (STOP)

## Phase 3 — Docs + AI workflow (PR #3)
- [ ] Task 10: README incl. AI/deterministic boundary diagram + walkthrough
- [ ] Task 11: docs/assisted-lookup.md + prompt template (validated dry run)
- [ ] Task 12: End-to-end polish, fresh-clone demo, final review sweep
- [ ] ⛳ Checkpoint D — PR #3: hand to Jake (STOP)
