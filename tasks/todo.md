# card-grade-scope — task checklist

Source of truth for task detail: [tasks/plan.md](plan.md). Status: awaiting ⛳ Gate 1 approval.

## Scaffold (after plan approval)
- [ ] Run repo-adopt (checks.sh, commit guard, PR template, repo CLAUDE.md); ask Jake before any GitHub remote

## Phase 1 — Deterministic core (PR #1)
- [ ] Task 1: Project skeleton, models, data loading, real cost book, sample collection, `gradescope costs`
- [ ] Task 2: Single-card EV engine, two views, provisional verdicts, golden tests, `analyze --card`
- [ ] Task 3: Break-even solver (+ monotonicity property test)
- [ ] ⛳ Checkpoint A (internal): paper-recompute matches golden output
- [ ] Task 4: Batch analysis — amortization, marginal classification, tier-minimum flags, `analyze --batch`
- [ ] Task 5: Sensitivity + flip points, final verdict rules, staleness, summary-first report, `--compare-scenarios`
- [ ] Task 6: No-network guarantee, config.yaml knobs, fuzz-case hardening
- [ ] ⛳ Checkpoint B — PR #1: review pass, hand to Jake (STOP)

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
