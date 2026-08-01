# Spec: grade-scope

**Status: DRAFT — awaiting approval (⛳ Gate 0).**
Research provenance: [research/psa-costs-2026.md](research/psa-costs-2026.md), [research/value-sources-2026.md](research/value-sources-2026.md).

## 1. Objective

Answer one question per card, with defensible math: **is it worth paying PSA to grade this card?**

Jake inventories a modest (tens of cards) well-preserved childhood Pokemon collection; the tool models the true end-to-end cost of a PSA submission, the card's value raw vs. slabbed at PSA 7/8/9/10, and produces a per-card verdict — **submit / hold / don't bother** — backed by expected value, break-even thresholds, and sensitivity analysis. Batch-aware: shared costs are amortized, and adding/removing a card changes every other card's verdict.

Success looks like: Jake runs one command against his data files and gets a report he could defend line-by-line to another collector, with zero AI involvement in the computation.

**Non-goals (hard constraints, not revisitable):** no graders other than PSA; no per-grade value modeling below PSA 7; no network calls, API keys, or LLM dependencies in the core; no database/web app/service layer.

## 2. Name and directory

**`grade-scope`** at `~/projects/grade-scope`. (Alternates considered: `slab-math`, `psa-ev`, `gradeworthy`. Recommendation: keep `grade-scope` — descriptive, unclaimed, portfolio-friendly. Rename at this gate if preferred.)

## 3. Tech stack

- **Python 3.12+**, project managed with **uv** (fast, single-tool venv+deps; `uv run` gives copy-pasteable commands).
- Runtime dependencies: **PyYAML** (data files), **click** (CLI ergonomics for guided entry). Nothing else — no pydantic, no pandas, no requests. Validation is hand-rolled against dataclasses because per-row/per-field error reporting is a core feature we want full control over, and the schemas are small.
- Dev dependencies: **pytest**, **ruff** (lint + format).
- Justification vs. simplicity bias: this is the smallest stack that gives readable data files (YAML), a pleasant interactive CLI, and a real test harness. The engine itself is stdlib-only math.

### Commands (the green bar)

```
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

All three must pass before every commit. (Wrapped in `checks.sh` at scaffold time, per repo-adopt.)

CLI entry point: `uv run gradescope <subcommand>` — subcommands: `add` (guided entry), `import` (CSV), `analyze` (per-card + batch report), `snapshot` (record a value snapshot from prompts), `costs` (show active cost data).

## 4. Project structure

```
grade-scope/
  SPEC.md
  README.md               # includes the AI/deterministic boundary diagram
  research/               # dated research notes (provenance for cost data)
  src/gradescope/
    models.py             # dataclasses: Card, ValueSnapshot, GradeProbs, Batch, CostBook
    validate.py           # schema + CSV validation, per-row error reporting
    costs.py              # cost book loading, tier selection, batch amortization
    values.py             # snapshot loading, freshness, net-realizable conversion
    engine.py             # EV, net gain, break-even, sensitivity, verdicts (stdlib only)
    report.py             # human-readable per-card and batch output
    cli.py                # click commands (guided entry, import, analyze, snapshot)
  tests/
    golden/               # hand-computed EV cases (see Testing)
  data/
    costs/                # dated cost books (committed — public info)
    sample/               # synthetic demo collection (committed fixture)
    inventory.yaml        # Jake's real cards — GITIGNORED
    probabilities.yaml    # Jake's grade estimates — GITIGNORED
    values.jsonl          # Jake's snapshots — GITIGNORED
    batches/              # Jake's batch definitions — GITIGNORED
```

`.gitignore` covers `data/` except `data/costs/` and `data/sample/`. No personal data in the repo; the sample collection makes every command demoable.

## 5. Data schemas

### 5.1 Card record (`data/inventory.yaml` — list of cards)

```yaml
- id: base1-4-charizard-holo-unl        # stable slug, unique, required
  name: Charizard
  set_name: Base Set
  card_number: "4/102"
  variant: unlimited_holo               # enum below
  language: en
  condition:
    centering: "60/40 front, back near-centered"
    corners: "sharp, slight whitening rear-left"
    edges: "clean"
    surface: "light scratches in holo under glare"
    whitening: "minor back-edge whitening"
    notes: "stored in binder ~1999-2005, then box"
  estimated_grade_range: [7, 9]         # informational; probabilities are the record
  provenance: "pulled from booster ~1999"
  date_added: 2026-08-01
```

`variant` enum: `first_edition_holo | first_edition | shadowless_holo | shadowless | unlimited_holo | unlimited | reverse_holo | promo | other`. `language`: ISO 639-1. `condition.*` free text (human judgment, feeds guided estimation); `estimated_grade_range` two ints 1–10.

### 5.2 Grade probabilities (`data/probabilities.yaml` — keyed by card id)

```yaml
base1-4-charizard-holo-unl:
  p7: 0.25
  p8: 0.40
  p9: 0.25
  p10: 0.02
  p_below7: 0.08
  method: guided          # guided | manual
  date: 2026-08-01
```

Must sum to 1 within tolerance 1e-6; otherwise the engine **rejects with an explicit error** naming the card and the sum — never silently normalizes.

**Capture mechanism (decision):** the stored record is always **explicit numbers Jake confirms**. The guided-entry flow asks condition questions (centering bands, corner sharpness, edge/surface/whitening severity), maps answers to a suggested prior from a small, documented lookup table shipped as data, shows the suggestion, and Jake accepts or edits it. Justification: keeps the engine deterministic and honest — the tool never pretends to be a calibrated grading model; the questionnaire is an anchoring aid, and `method: guided` records that provenance. Direct `manual` entry is always available.

### 5.3 Cost book (`data/costs/psa-costs-YYYY-MM-DD.yaml`)

One dated file per refresh; the CLI loads the newest by default (`--cost-book` overrides). Structure:

```yaml
meta: {date_accessed: 2026-08-01, currency: USD}
service_levels:
  - name: regular
    status: active                 # active | paused
    fee_per_card: 79.99
    max_declared_value: 1500
    min_cards: null
    membership_required: false
    turnaround_business_days: [40, 50]
    source: {url: "https://www.psacard.com/services/tradingcardgrading", date_accessed: 2026-08-01}
  - name: value_bulk
    status: paused
    fee_per_card: 24.99
    max_declared_value: 500
    min_cards: 20
    membership_required: true
    ...
membership:
  - {name: standard, annual_fee: 149.00, source: {...}}
return_shipping:                    # PSA chart: bands by item count x insured value
  - {items_min: 1, items_max: 4, value_max: 2000, fee: 19.99, source: {...}}
  - {items_min: 20, items_max: null, value_max: 2000, base_fee: 29.99, per_item_over: 0.39, source: {...}}
inbound_shipping: {default: 25.00, estimate: true, source: {...}}
supplies: {per_card: 0.30, per_submission: 8.00, estimate: true, source: {...}}
```

Every entry carries `source.url` + `source.date_accessed`. Entries PSA doesn't publish exactly carry `estimate: true` and surface as assumptions in reports.

**Refresh procedure (documented in README):** copy newest file to a new date-stamped name, re-verify each figure against its source URL (assisted lookup allowed), update dates, commit. Old files are never edited or deleted.

### 5.4 Value snapshots (`data/values.jsonl` — append-only, one JSON object per line)

```json
{"card_id": "base1-4-charizard-holo-unl", "kind": "psa9", "value": 1400.00, "currency": "USD",
 "source_name": "PSA APR", "source_url": "https://www.psacard.com/auctionprices/...",
 "date_observed": "2026-08-01", "n_comps": 6, "spread": {"low": 1150, "high": 1650},
 "recorded_by": "assisted-lookup"}
```

`kind` enum: `raw | psa7 | psa8 | psa9 | psa10 | pop` (for `pop`, `value` is the population count at that grade, `pop_grade` field required). Values are **gross** sale prices as sources report them (see §7). Append-only: newer snapshots supersede for analysis, history is retained, and the engine warns when the freshest snapshot for any used `kind` is older than `staleness_days` (default **90**, configurable).

### 5.5 Batch definition (`data/batches/<name>.yaml`)

```yaml
name: first-submission
pricing_scenario: current            # current | value_restored
membership_already_held: false
card_ids: [base1-4-charizard-holo-unl, ...]
```

`pricing_scenario` selects which service-level `status` values are considered orderable: `current` uses only `active` tiers; `value_restored` treats `paused` tiers as available (clearly labeled hypothetical in output). Both scenarios can be reported side-by-side (`analyze --compare-scenarios`) because the Value pause (see research) changes the cheapest per-card fee by 3.2× and is expected to lift ~Oct 2026.

### 5.6 CSV import format (`gradescope import cards.csv`)

Columns (exact header names):

| Column | Required | Rule |
|---|---|---|
| `id` | yes | unique in file **and** vs. existing inventory; slug `[a-z0-9-]+` |
| `name` | yes | non-empty |
| `set_name` | yes | non-empty |
| `card_number` | yes | non-empty |
| `variant` | yes | must be in variant enum |
| `language` | no (default `en`) | ISO 639-1 |
| `centering`,`corners`,`edges`,`surface`,`whitening`,`condition_notes` | no | free text |
| `grade_low`,`grade_high` | no | ints 1–10, low ≤ high |
| `provenance` | no | free text |

Validation behavior: the whole file is parsed; **every** invalid row is reported (`row N, column C: message`) — no abort on first error, nothing silent. Valid rows import; invalid rows are skipped and summarized (`imported 12, rejected 3`). `--strict` aborts the entire import if any row fails. Duplicate-id collisions (in-file or vs. inventory) are row errors.

## 6. The analysis engine (deterministic core)

Implements exactly the math in the kickoff, restated here as the normative reference.

For card *i*: outcomes `G = {7,8,9,10}` plus lumped `below7`; probabilities validated to sum to 1 (tolerance 1e-6, explicit rejection otherwise).

- `V_g` = **net realizable** value at grade g = `gross_g × (1 − sale_friction)`
- `V_raw` = net realizable ungraded, same friction
- `V_below7 = α · V_raw`, **α default 1.0** (a low-grade slab of a well-preserved vintage card resells for roughly its raw value; the slab neither destroys nor meaningfully adds value below 7). Configurable.
- `C_i = f_i + share_i(S, N)` (see amortization)

```
EV_submit(i) = Σ_{g∈G} p_g·V_g + p_below7·V_below7 − C_i
Net_gain(i)  = EV_submit(i) − V_raw
```

**Baseline (decision):** `V_raw` means **"sell raw today"** at the freshest raw snapshot. Hold-and-do-nothing is not modeled as a separate EV branch — it has no cash flow and identical card-value exposure; the **hold** verdict covers "positive but thin/fragile, revisit later." Documented in README.

**Net vs. gross (decision):** snapshots store **gross** values as sources report them; the engine applies a configurable `sale_friction` (default **0.13**, from eBay trading-card final value fee ≈13.25%, exact figure flagged for confirmation) uniformly to every `V_g`, `V_raw`, and hence `V_below7`. One knob, applied consistently, raw source data stays faithful.

**Short-circuit:** if `p_below7 ≥ 0.5` (configurable `below7_short_circuit`), verdict is **don't bother** ("expected grade below 7") with no further modeling; the distribution is still shown.

**Tier selection:** cheapest orderable tier (per scenario) whose `max_declared_value ≥ declared_value_i`, where `declared_value_i = Σ p_g·gross_g + p_below7·gross_below7` (probability-weighted post-grading value, gross — what you'd honestly declare). **Upcharge-risk warning** when `gross_10 > tier.max_declared_value`.

**Batch amortization (decision):** per-card `f_i` = tier fee + per-card supplies. Shared `S` = membership (if the scenario's chosen tiers require it and `membership_already_held: false`) + inbound shipping + return shipping (from the chart, using N and total declared value) + per-submission supplies. **Flat split `share_i = S/N`** for everything, including insurance — with tens of cards and shared costs of ~$50–200, proportional allocation changes per-card cost by a few dollars while making marginal analysis harder to read. Documented; proportional allocation noted as a possible future knob.

Batch outputs: total cost / total EV_submit / total Net_gain; per-card marginal analysis by recomputing the batch with each card removed (N ≤ ~100, O(N²) trivial) — classifying cards as *standalone-positive*, *ride-along* (positive only sharing S), and *drag* (removal raises total Net_gain); tier minimum-count flags (e.g., batch of 14 under a 20-card Value Bulk minimum → shows the cost of adding 6 filler cards vs. staying on the next tier).

**Break-even (decision, parameterization stated in README):** holding the relative proportions of all non-top outcomes fixed, solve for minimum `p_10*` such that `Net_gain = 0`, redistributing `1 − p_10*` over `{7,8,9,below7}` proportionally to their current ratios. Closed form: Net_gain is linear in `p_10` under this reparameterization. Reported as *"worth submitting only if you believe there's ≥ X% chance of a PSA 10."* If even `p_10 = 1` is negative, report "never breaks even at current values/costs"; if break-even at `p_10 = 0`, report "positive regardless of top grade."

**Sensitivity:** shocks (defaults, configurable): value ±10% / ±25% (all `V_g` scaled); probability shifts of 5-point mass between adjacent grades (10→9, 9→8, 8→7, 7→below7 and reverse); cost +10% / +25%; batch size N±1 (recomputed shares). Output reports **verdict flip points** — the smallest tested perturbation that changes the verdict — labeling each verdict `robust` (survives ±25% value shock) or `fragile` (flips at ≤10%).

**Verdicts (decision, thresholds configurable in `config.yaml`):**

- **submit** — `Net_gain ≥ min_gain` (default **$20**) **and** robust (survives the ±25% value shock without going ≤ 0) **and** no staleness warnings on used values.
- **hold** — `Net_gain > 0` but thin (< min_gain), or fragile, or any used snapshot stale.
- **don't bother** — `Net_gain ≤ 0`, or `p_below7 ≥ 0.5`, or `gross_10 < C_i` (cost floor: even a 10 doesn't pay).

Every verdict is explainable: the report prints inputs (with snapshot dates/sources), the EV arithmetic, `C_i` decomposition, break-even, and the triggering rule.

## 7. AI / deterministic boundary (architecture)

```
┌────────────────────────────┐          ┌─────────────────────────────────┐
│  AI-ASSISTED (optional)    │  writes  │  PLAIN DATA FILES (reviewable)  │
│                            │ ───────► │                                 │
│ 1. Assisted lookups:       │          │  data/values.jsonl  (snapshots) │
│    browse eBay sold, APR,  │          │  data/costs/*.yaml  (cost book) │
│    PriceCharting, pop      │          │  data/inventory.yaml (via chat) │
│    reports; record value + │          └────────────────┬────────────────┘
│    source URL + date +     │                           │ reads (only input)
│    n_comps                 │                           ▼
│ 2. Card identification     │          ┌─────────────────────────────────┐
│    during guided entry     │          │  DETERMINISTIC CORE (no AI)     │
└────────────────────────────┘          │  gradescope CLI: validation,    │
                                        │  cost model, EV, break-even,    │
   never touches the engine,            │  sensitivity, verdicts, report  │
   never computes a verdict             │  offline · no keys · stdlib math│
                                        └─────────────────────────────────┘
```

- The **only** handoff is files: an assisted session appends snapshot lines / writes a refreshed cost book; a human can produce identical files by hand in a text editor, and every entry cites source URL + date.
- Nothing in the core or the on-disk schemas references any AI vendor. `recorded_by` is a free-text provenance string (`"assisted-lookup"`, `"jake-manual"`).
- No scraping, no headless harvesting, no API keys — the acquisition workflow is "browse, read, cite" (see research/value-sources-2026.md).
- README reproduces this diagram and walks one card end-to-end across the boundary. **Stated goal, not a nicety.**

## 8. Code style

```python
def net_gain(card: CardAnalysis, costs: CostShare) -> Money:
    """EV of submitting minus selling raw today (kickoff §5)."""
    ev_graded = sum(card.p[g] * card.net_value[g] for g in GRADES)
    ev_submit = ev_graded + card.p_below7 * card.net_below7 - costs.total
    return ev_submit - card.net_raw
```

Money as `Decimal` end-to-end (currency math; float EV drift would poison golden tests). Type hints everywhere; dataclasses over dicts at module boundaries; small pure functions in `engine.py`; ruff defaults for naming/format.

## 9. Testing strategy

- **pytest**, tests in `tests/`, run via `uv run pytest`; coverage expectation: every `engine.py` branch, every validation rule.
- **Golden cases** (`tests/golden/`): hand-computed EV/Net_gain/break-even for ≥3 cards (worked arithmetic in comments), incl. a short-circuit card and a never-breaks-even card, pinned to a frozen cost book fixture and the synthetic sample collection.
- Property-style checks: probability-sum rejection; break-even monotonicity (higher `C_i` → higher `p_10*`); amortization invariant (`Σ share_i = S`); marginal-analysis consistency (removing a "drag" card raises total Net_gain).
- CSV import: fixture files exercising every error class; assert per-row messages and non-abort behavior.
- **No-network guarantee**: no HTTP library is a dependency; a test asserts the engine modules import no networking modules.

## 10. Boundaries

- **Always:** run the green bar before every commit; every cost/value datum carries source URL + date; explicit errors over silent normalization; gitignore real inventory.
- **Ask first:** adding any dependency; changing on-disk schemas after first real data exists; creating a GitHub remote; anything touching Jake's real data files.
- **Never:** AI/vendor coupling in core or schemas; network calls in the core; scraping or ToS-violating harvesting; committing Jake's real inventory; other graders; per-grade modeling below PSA 7; merge a PR; attribution trailers in commits.

## 11. Success criteria

1. `uv run gradescope analyze --batch first-submission` runs offline from local files and produces per-card verdicts with visible arithmetic, break-even, and sensitivity flip points, plus the batch view (totals, marginal classification, tier-minimum flags).
2. Golden tests pin the math to hand-computed values; green bar passes.
3. A stranger with Python and the data files reproduces identical numbers with no AI anywhere.
4. Both input paths work: guided entry (with condition-question prior suggestion) and CSV import (per-row errors, non-silent).
5. README explains the AI/deterministic boundary with the diagram, the break-even parameterization, net-vs-gross treatment, and the cost-book refresh procedure.
6. Repo is portfolio-publishable: synthetic sample data, no personal data, sensible history.

## 12. Resolved decisions (summary)

| Decision | Choice |
|---|---|
| Name | `grade-scope` (confirm at gate) |
| Stack | Python 3.12 + uv; PyYAML + click; pytest + ruff; Decimal money |
| Net vs. gross | Snapshots gross; engine applies `sale_friction` (default 0.13) uniformly |
| α (below-7 fallback) | 1.0, configurable |
| `V_raw` baseline | Sell raw today; no separate hold branch |
| Below-7 short-circuit | `p_below7 ≥ 0.5` → don't bother |
| Declared value | Probability-weighted post-grading gross value; upcharge warning vs. tier max |
| Amortization | Flat `S/N` for all shared costs incl. insurance |
| Break-even | Min `p_10` with proportional redistribution over remaining outcomes |
| Verdict thresholds | submit: ≥$20 and robust at ±25% and fresh; hold: positive-but-thin/fragile/stale; don't bother: ≤0, short-circuit, or cost floor |
| Staleness | 90 days default |
| Pricing scenarios | `current` vs. `value_restored` (Value tiers paused since 2026-06-02) |
| Probability capture | Explicit numbers of record; guided questionnaire proposes, Jake confirms |
| Snapshot store | Append-only `values.jsonl`; costs as dated YAML books |

## 13. Open questions / UNVERIFIED (for Jake at this gate)

1. **eBay final value fee for trading cards** — sources conflict (13.25% vs 13.6%); default 0.13. Confirm or set your number. (research/psa-costs-2026.md §8)
2. **Sales tax on grading fees/membership** — state-dependent; which state should the cost book assume, or ignore tax?
3. **Membership required to submit at Regular+?** — strong indication no (join page frames membership as bulk access only), but **UNVERIFIED** until the actual submission flow is exercised.
4. **20+ item return-shipping interpretation** — chart reads as base + $0.39/item over 19; UNVERIFIED against a real submission.
5. **Inbound shipping+insurance default $25** — estimate; adjust to your carrier preference.
6. **Signup voucher** — some secondary sources claim a $50 voucher for new Collectors Club members; not on PSA's current page; treated as absent.
7. **Upcharge trigger thresholds** — PSA doesn't publish exact rules; tool warns on risk only.
8. **Value-tier reinstatement** — tied to PSA backlog milestone (~Oct 2026 projection). Affects whether "hold until Value Bulk returns" is your dominant strategy for sub-$500 cards; the scenario comparison exists precisely for this.
9. **Pop-report integration depth** — v1 records pop counts as snapshots and displays them; it does **not** algorithmically adjust the PSA-10 premium. OK?
10. **Sample collection contents** — I'll invent ~10 synthetic WOTC-era cards with plausible-but-fake values for fixtures/demo. Any preference?
