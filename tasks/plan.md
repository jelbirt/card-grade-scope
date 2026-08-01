# Implementation Plan: card-grade-scope

Per approved [SPEC.md](../SPEC.md). Status: **DRAFT — awaiting ⛳ Gate 1 approval.**

## Overview

Build the deterministic PSA grading decision engine first (data models → cost/value loading → EV math → batch analysis → sensitivity → report), each task landing a runnable vertical slice with golden tests; then the two input paths (CSV import, guided entry); then documentation and the AI-assisted acquisition workflow last, so the core is provably AI-free before any AI touches anything.

## Architecture decisions (from SPEC, restated for the build)

- Engine is stdlib-only math on `Decimal`; PyYAML/click confined to loaders and CLI.
- YAML/JSON numeric fields are parsed to `Decimal` via string conversion (never `float(...)` → Decimal) to keep golden tests exact.
- Verdicts depend on sensitivity (robustness), so the verdict rule is finalized in the sensitivity task; earlier tasks emit provisional verdicts clearly labeled in code.
- The AI side ships as **documentation + a file validator**, not runtime code: `gradescope validate-snapshots` lints any hand- or AI-written `values.jsonl`, keeping the handoff checkable deterministically.

## Delivery workflow

- After this plan is approved: run **repo-adopt** (scaffold `checks.sh`, commit guard, PR template, repo CLAUDE.md, wire `tasks/todo.md`). Ask Jake before creating a GitHub remote.
- Work lands as **one PR per phase** (3 PRs), built under checkpoint-batched approvals: no per-commit approvals, green bar (`uv run ruff check .` / `ruff format --check .` / `pytest`) before every commit, one code-reviewer pass per PR diff before handoff, Jake merges.
- Phase checkpoints (⛳) = PR handoffs.

## Task list

### Phase 1 — Deterministic core (PR #1)

#### Task 1: Project skeleton, models, and data loading

**Description:** `pyproject.toml` (uv, deps per spec), package layout, `.gitignore` (real data out, `data/costs/` + `data/sample/` in), dataclasses for Card/GradeProbs/ValueSnapshot/CostBook/Batch, YAML/JSONL loaders with explicit validation errors, the real 2026-08-01 cost book generated from research notes, and a ~10-card synthetic sample collection (inventory, probabilities, snapshots, one batch). CLI stub with `gradescope costs` printing the loaded cost book.

**Acceptance criteria:**
- [ ] `uv run gradescope costs` prints service levels (active + paused flagged), membership, shipping bands, supplies, CT tax from `data/costs/psa-costs-2026-08-01.yaml`
- [ ] Loaders reject bad data with messages naming file/entry/field (probability sum ≠ 1 named explicitly per SPEC §5.2)
- [ ] Sample data loads clean; all numeric fields are `Decimal`

**Verification:** `uv run pytest tests/test_loaders.py` (valid + invalid fixtures); green bar.
**Dependencies:** none. **Scope:** M (models, loaders, cli stub, data files, tests).

#### Task 2: Single-card EV engine and provisional verdicts

**Description:** Probability validation, tier selection (cheapest orderable ≥ declared value, per scenario), single-card `C_i` (fee + supplies + solo share of S), two-view EV/Net_gain (sticker + take-home), below-7 short-circuit, cost floor, upcharge warning. `analyze --card <id>` prints the per-card detail section (inputs with sources/dates, arithmetic, C_i decomposition, provisional verdict per view + overall).

**Acceptance criteria:**
- [ ] Golden tests: ≥3 hand-computed cards (worked arithmetic in comments) incl. a short-circuit card and a never-viable card, exact `Decimal` equality, pinned to a frozen fixture cost book
- [ ] Two views computed from one gross snapshot set; `C_i` identical across views
- [ ] `analyze --card` output shows every number needed to recompute by hand

**Verification:** `uv run pytest tests/golden/`; manual: run against sample card, recompute on paper once.
**Dependencies:** Task 1. **Scope:** M (engine.py, report.py start, cli, golden tests).

#### Task 3: Break-even solver

**Description:** Closed-form minimum `p_10*` with proportional redistribution over `{7,8,9,below7}` (SPEC §6), per view; edge cases "never breaks even" and "positive regardless"; wired into the per-card report as the *"worth submitting only if ≥ X% chance of a PSA 10"* line.

**Acceptance criteria:**
- [ ] Golden tests with hand-computed `p_10*`; edge cases covered
- [ ] Property test: `p_10*` monotonically increases with `C_i`
- [ ] Reported per view in `analyze --card`

**Verification:** `uv run pytest tests/test_breakeven.py`; green bar.
**Dependencies:** Task 2. **Scope:** S (engine.py, report.py, tests).

⛳ **Checkpoint A (internal, no stop):** single-card path solid — golden tests pass, paper recompute matches.

#### Task 4: Batch analysis

**Description:** Batch loading, shared-cost pool S (membership per scenario/`membership_already_held`, inbound + return shipping from chart bands incl. 20+ interpretation, per-submission supplies, tax), flat `S/N` shares, batch totals, marginal analysis (recompute-with-removal; standalone-positive / ride-along / drag), tier-minimum flags (below-minimum cost-to-fill vs next tier). `analyze --batch <name>`.

**Acceptance criteria:**
- [ ] Amortization invariant test: `Σ share_i = S` exactly
- [ ] Marginal consistency test: removing a "drag" card raises total Net_gain
- [ ] Golden batch test: hand-computed 3-card batch; tier-minimum flag fires on a sub-20 Value Bulk batch in `value_restored`
- [ ] Return-shipping band selection tested at boundaries (4/5, 9/10, 19/20 items)

**Verification:** `uv run pytest tests/test_batch.py`; green bar.
**Dependencies:** Task 2. **Scope:** M (costs.py, engine.py, report.py, tests).

#### Task 5: Sensitivity, final verdicts, and summary report

**Description:** Shock grid (value ±10/±25%, adjacent-grade probability shifts of 0.05, cost +10/+25%, N±1), verdict flip-point search, robust/fragile labeling; finalize verdict rules (submit/hold/don't bother incl. robustness + staleness inputs and the views-disagree → hold rule); staleness warnings (>90d); the summary-table-first report layering (SPEC §6) and `--compare-scenarios`.

**Acceptance criteria:**
- [ ] Flip-point tests: a fixture card engineered to flip at +10% value shock is labeled fragile; a robust card survives ±25%
- [ ] Views-disagree fixture yields overall **hold** with disagreement stated
- [ ] Stale-snapshot fixture downgrades submit → hold with warning naming the stale kind/date
- [ ] `analyze --batch` prints summary table (verdict, both Net_gains, break-even p₁₀, batch totals) before detail; `--compare-scenarios` shows current vs value_restored side by side

**Verification:** `uv run pytest`; manual: full sample-collection run reads correctly top-down.
**Dependencies:** Tasks 3, 4. **Scope:** M (engine.py, report.py, cli, tests).

#### Task 6: No-network guarantee and core hardening

**Description:** Test asserting engine/costs/values/validate import no networking modules; `config.yaml` for all thresholds (min_gain, α, sale_friction, staleness_days, shocks, short-circuit) with defaults per spec; input fuzz cases (empty inventory, missing snapshot kinds, zero probabilities on a grade, unknown card id in batch) all failing loud and named.

**Acceptance criteria:**
- [ ] No-network test passes; `requests`/`urllib`-free dependency tree asserted
- [ ] Every config knob overridable from `config.yaml`; defaults match SPEC §12
- [ ] Fuzz cases produce actionable errors, never silent results

**Verification:** `uv run pytest`; green bar.
**Dependencies:** Task 5. **Scope:** S.

⛳ **Checkpoint B — PR #1 handoff (STOP):** deterministic core complete; code-reviewer pass done; Jake reviews math + report shape before input paths are built.

### Phase 2 — Input paths (PR #2)

#### Task 7: CSV bulk import

**Description:** `gradescope import cards.csv` per SPEC §5.6: full-file parse, per-row errors (`row N, column C: message`), enum + slug + duplicate-id checks (in-file and vs inventory), valid rows import with summary, `--strict` aborts all.

**Acceptance criteria:**
- [ ] Fixture CSVs exercise every error class; messages match spec format
- [ ] Mixed valid/invalid file: valid rows land, summary reads `imported X, rejected Y`, exit code nonzero when any rejected
- [ ] `--strict` writes nothing on any failure

**Verification:** `uv run pytest tests/test_import.py`; manual import of a sample CSV.
**Dependencies:** Task 1 (spec-frozen by Phase 1 close). **Scope:** M (validate.py, cli, fixtures).

#### Task 8: Guided interactive entry

**Description:** `gradescope add`: click-prompted walk through card fields (enum choices inline), condition questionnaire (centering bands, corner/edge/surface/whitening severities) mapped via a data-shipped lookup table to a suggested grade-probability prior, shown for Jake to accept or edit (`method: guided` vs `manual`); writes inventory + probabilities; never overwrites an existing id without explicit confirm.

**Acceptance criteria:**
- [ ] `CliRunner`-scripted session produces exactly the expected YAML records
- [ ] Suggested prior always sums to 1; edited prior re-validated before write
- [ ] Prior lookup table lives in `data/` as documented, editable data (not code)

**Verification:** `uv run pytest tests/test_guided.py`; manual: add one synthetic card end-to-end.
**Dependencies:** Task 7 (shares validators). **Scope:** M (cli, prior table data, tests).

#### Task 9: Snapshot entry and snapshot-file validation

**Description:** `gradescope snapshot` (prompted manual entry appending validated lines to `values.jsonl`) and `gradescope validate-snapshots <file>` (lints any snapshot file — schema, enums, dates, currency, append-only-safe) so AI-written files are deterministically checkable before use.

**Acceptance criteria:**
- [ ] Appends never rewrite existing lines; malformed existing lines reported with line numbers
- [ ] `validate-snapshots` catches every schema violation class in fixtures; clean file exits 0
- [ ] `pop` kind requires `pop_grade`; enforced

**Verification:** `uv run pytest tests/test_snapshots.py`.
**Dependencies:** Task 7. **Scope:** S.

⛳ **Checkpoint C — PR #2 handoff (STOP):** both input paths work; Jake can begin entering real cards while Phase 3 proceeds.

### Phase 3 — Docs and AI-assisted workflow (PR #3)

#### Task 10: README with the AI/deterministic boundary

**Description:** Portfolio-grade README: what/why, quickstart on sample data, the boundary diagram (SPEC §7) with a one-card walkthrough crossing it, the math (EV, two views, break-even parameterization, amortization, verdicts) in plain language, cost-book refresh procedure, config reference, green-bar commands.

**Acceptance criteria:**
- [ ] Boundary section explicitly labels what AI touches / hands off / what is pure computation (kickoff hard constraint)
- [ ] Every documented command copy-paste-runs against sample data
- [ ] Break-even and two-view semantics stated so the report is interpretable without reading code

**Verification:** manual doc pass; run every fenced command.
**Dependencies:** Tasks 5, 9. **Scope:** S (README.md).

#### Task 11: Assisted-lookup workflow

**Description:** `docs/assisted-lookup.md`: the exact browse-read-cite procedure per source (eBay sold, PSA APR, pop report, PriceCharting, TCGplayer), a copy-paste prompt template for a web-enabled LLM session that outputs `values.jsonl` lines, the rule that output must pass `validate-snapshots` before use, and the ToS posture (no scraping, human-reproducible). Cost-book refresh gets the same treatment.

**Acceptance criteria:**
- [ ] A session following the doc yields lines that pass `validate-snapshots` (dry-run the template once and validate the output)
- [ ] Every source lists its URL pattern and what to record (value, n_comps, spread, pop)
- [ ] No step requires an API key or violates a stated ToS

**Verification:** dry-run + `uv run gradescope validate-snapshots` on the produced file.
**Dependencies:** Tasks 9, 10. **Scope:** S.

#### Task 12: End-to-end polish and final review

**Description:** Full demo run scripted in README (import sample CSV → analyze batch → compare scenarios), CLI `--help` text pass, error-message consistency sweep, final code-reviewer pass over the whole repo, prune anything dead.

**Acceptance criteria:**
- [ ] Fresh-clone demo: `uv sync` → documented commands run clean on sample data only
- [ ] All SPEC §11 success criteria checked off one by one
- [ ] Review findings fixed or explicitly noted as not-worth-fixing

**Verification:** fresh-clone dry run in a temp dir; green bar.
**Dependencies:** all. **Scope:** S.

⛳ **Checkpoint D — PR #3 handoff (STOP):** project complete pending Jake's merge.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Decimal/YAML float corruption breaks golden exactness | Med | String→Decimal parse rule (Task 1), exact-equality golden tests catch drift immediately |
| Verdict rules entangled with sensitivity cause churn | Med | Provisional verdicts explicitly labeled until Task 5 finalizes; golden tests updated once, deliberately |
| Return-shipping 20+ interpretation wrong | Low | Isolated in one chart function; UNVERIFIED flag surfaces in report assumptions |
| Guided-entry prior table implies false precision | Med | Table is editable data + always human-confirmed; `method` provenance recorded |
| click prompt flows hard to test | Low | `CliRunner` scripted sessions from the start |

## Open questions

None blocking — SPEC §13 residual UNVERIFIED items are flagged in data/report output, not decision points for this plan.
