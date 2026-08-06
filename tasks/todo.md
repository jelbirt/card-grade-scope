# card-grade-scope — task checklist

Source of truth for task detail: [tasks/plan.md](plan.md). Status: **all phases merged (2026-08-02)** — project complete pending the pre-publication sweep (SPEC §13.7 resolved 2026-08-04, PR #7).

Pen registry: real `data/` files live only in the main checkout (see CLAUDE.md).
Remote: https://github.com/jelbirt/card-grade-scope — **private now, intended public later** (Jake, 2026-08-01).

## Pre-publication sweep (before flipping the repo public)
- [x] `git log --all --diff-filter=A --name-only` shows nothing under `data/` beyond `data/costs/` and `data/sample/` — one additional file, `data/guided-priors.yaml`, is the SPEC §5.2 guided-entry lookup table (shipped config, no personal data); allowed (swept 2026-08-06)
- [x] Grep history and docs for real-inventory specifics (condition/provenance of Jake's actual copies), none present (swept 2026-08-06; all hits are pricing-source prose or synthetic fixtures)
- [x] PR bodies / issues / CI logs contain no real-data output (PRs 1-7 scanned 2026-08-06; all cited values trace to the synthetic demo set)
- [x] README states the sample data is synthetic (README line 22)

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
- [x] Task 7: CSV import with per-row errors, `--strict`; Next Destinies + Dark Explorers checklist fixtures import 214/214 (verified, zero rejects)
- [x] Task 8: Guided entry with condition-questionnaire prior (accept/edit); lookup table shipped as `data/guided-priors.yaml`
- [x] Task 9: `snapshot` entry + `validate-snapshots` linter
- [x] ⛳ Checkpoint C — PR #2: review pass done (3 findings fixed), merged by Jake 2026-08-02

## Post-gate additions (SPEC updated in-line)
- [x] Values view per-grade profit/loss line (`V_g − V_raw − all-in/card`, net of raw confirmed by Jake) — merged by Jake 2026-08-02 (PR #3)
- [x] Test-hermeticity fix: suite no longer inherits a checkout-local `config.yaml` (single `paths.default_config()` seam + autouse conftest isolation) — PR #5
- [x] Test-hermeticity fix, part 2: suite no longer inherits a checkout's real `data/` or its `data/costs/` state (autouse fixtures pin `paths.default_data_dir` to `data/sample/` and `paths.newest_cost_book` to the frozen golden book) — PR #6
- [x] Batch-size N±1 shock (SPEC §13.7 resolved by Jake 2026-08-04: additive): informational `N±1` summary column + marginal-analysis detail; shares recomputed as S/(N±1), pool and tiers fixed; never feeds robustness/verdicts, so existing outputs unchanged — PR #7

## Phase 3 — Docs + AI workflow (PR #4)
- [x] Task 10: README incl. AI/deterministic boundary diagram + walkthrough (every fenced command verified against sample data)
- [x] Task 11: docs/assisted-lookup.md + prompt template (dry run: template-shaped output passes `validate-snapshots`, exit 0)
- [x] Task 12: End-to-end polish, fresh-clone demo (temp-dir clone, all commands green), final review sweep
- [x] ⛳ Checkpoint D — PR #4: review pass done (4 findings fixed), field-test learnings folded back, merged by Jake 2026-08-02

## Known gaps (need Jake's call)
- [x] Batch-size N±1 sensitivity shock — resolved (Jake, 2026-08-04): implemented additively, see Post-gate additions (PR #7).
