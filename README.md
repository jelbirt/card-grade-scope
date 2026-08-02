# card-grade-scope

**Is this card worth paying PSA to grade?** A small, offline, deterministic CLI that answers
that question for a Pokémon card collection — with math you can defend line-by-line, and
zero AI anywhere in the computation.

```
  card                                   raw   PSA 7.5     PSA 8   PSA 8.5     PSA 9    PSA 10  tier         all-in/card
  ----------------------------------------------------------------------------------------------------------------------
  nd-54-mewtwo-ex-full-art            $90.00   $120.00   $160.00   $200.00   $260.00   $750.00  regular $79.99      $85.37
    profit/loss if graded                      -$55.37   -$15.37   +$24.63   +$84.63  +$574.63
  nd-1-deerling-common                 $0.25     $4.00     $8.00    $11.00    $15.00    $35.00  regular $79.99      $85.37
    profit/loss if graded                      -$81.62   -$77.62   -$74.62   -$70.62   -$50.62
```

That table is the tool's default face: what each card is worth raw, what it's worth slabbed
at each grade, what grading costs all-in, and the profit or loss *if* it comes back at each
grade. No prediction involved — you look at the row and judge for yourself. An optional
layer on top adds expected value, break-even thresholds, and sensitivity-tested verdicts,
but only if you choose to write down grade probabilities.

> All sample data in this repo (`data/sample/`) is **synthetic**: real card names from
> public set checklists, invented values and condition notes. Not price advice.

## Quickstart

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/jelbirt/card-grade-scope && cd card-grade-scope
uv sync
```

```bash
uv run gradescope
```

With no real data present the CLI runs against the committed sample collection. The other
commands, all runnable as-is:

```bash
uv run gradescope costs
```

```bash
uv run gradescope analyze --card nd-54-mewtwo-ex-full-art --as-of 2026-08-02
```

```bash
uv run gradescope analyze --batch demo --as-of 2026-08-02
```

```bash
uv run gradescope validate-snapshots data/sample/values.jsonl
```

Bulk-import the two complete set checklists (214 cards) into a scratch copy of the sample
data, then view them:

```bash
demo=$(mktemp -d) && cp -r data/sample/. "$demo"
uv run gradescope import data/sample/checklists/next-destinies.csv --data-dir "$demo"
uv run gradescope import data/sample/checklists/dark-explorers.csv --data-dir "$demo"
uv run gradescope values --data-dir "$demo"
```

(Cards without value snapshots show `-` cells — the values view shows what exists rather
than demanding completeness.)

## Commands

| Command | What it does |
|---|---|
| `gradescope` / `gradescope values` | The default: per-card raw + per-grade values, all-in grading cost, per-grade profit/loss. Needs no probabilities. |
| `gradescope costs` | The active PSA cost book: tiers (active + paused), membership, shipping bands, supplies, tax. |
| `gradescope add` | Guided entry for one card: fields, condition questionnaire, suggested grade-probability prior you accept or edit. |
| `gradescope import <file.csv>` | Bulk import; whole file parsed, every bad row reported (`row N, column C: message`), `--strict` imports nothing on any failure. |
| `gradescope snapshot` | Record one value observation (price seen, source URL, date) appended to `values.jsonl`. |
| `gradescope validate-snapshots <file>` | Lint any snapshot file; every problem reported with its line number; clean file exits 0. |
| `gradescope analyze --card <id>` / `--batch <name>` | The opt-in verdict layer: EV, break-even, sensitivity, submit/hold/don't-bother. Requires probabilities. |

Every command takes `--help` for its options (`--data-dir`, `--cost-book`, `--scenario`,
`--config`, ...).

## The AI / deterministic boundary

The design constraint this project exists to demonstrate: **AI may help gather data, but
the computation is deterministic, offline, and AI-free.** The only handoff between the two
worlds is plain data files a human can read, audit, or write by hand.

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

Concretely:

- The runtime dependency tree is **click + pyyaml, nothing else** — no HTTP client can
  even be present. A test asserts both that and that no module in the core imports a
  networking module.
- Every value and cost datum carries a **source URL and access date**. Entries PSA doesn't
  publish exactly are marked `estimate: true` and surface as assumptions in reports.
- `gradescope validate-snapshots` is the gate: an AI-written snapshot file is not used
  until the deterministic linter passes it. A human with a text editor can produce
  byte-identical files; nothing about the schema knows AI exists.
  See [docs/assisted-lookup.md](docs/assisted-lookup.md) for the exact workflow.

### One card across the boundary

1. **Left side (assisted, optional).** In a web-enabled chat session, you ask for recent
   sold prices of Mewtwo EX full art (Next Destinies 98/99), raw and at each PSA grade.
   The session browses eBay solds and PSA's Auction Prices Realized, then emits JSONL
   lines like:

   ```json
   {"card_id": "nd-54-mewtwo-ex-full-art", "kind": "psa10", "value": 750.00,
    "currency": "USD", "source_name": "PSA APR",
    "source_url": "https://www.psacard.com/auctionprices/...",
    "date_observed": "2026-07-20", "n_comps": 5, "recorded_by": "assisted-lookup"}
   ```

2. **The handoff.** You append those lines to `data/values.jsonl` and run
   `gradescope validate-snapshots data/values.jsonl`. Schema, kinds, dates, currency —
   every problem reported with a line number. Until it exits 0, the data doesn't exist as
   far as the engine is concerned.

3. **Right side (deterministic).** `gradescope analyze --card nd-54-mewtwo-ex-full-art`
   loads the freshest snapshot per kind and prints the entire calculation — every number
   needed to recompute it by hand:

   ```
   probabilities: p7.5=0.10 p8=0.25 p8.5=0.15 p9=0.25 p10=0.20 below=0.05 (manual)
   declared value $301.50 -> tier regular ($79.99/card)
   cost: fee $79.99 + tax $5.08 + supplies $0.30 + shared share $52.99 = $138.36
   EV(submit) = $301.50 - cost $138.36 = $163.14
   Net gain   = $163.14 - raw $90.00 = $73.14
   Verdict    = HOLD — positive ($73.14) but not robust: net gain falls to $-1.11
                within the +/-25.00% value shocks
   ```

   Run it twice, get the same answer. Run it on a plane, get the same answer.

## The math, in plain language

**Values and profit (no probabilities).** For each card the values view shows gross market
value raw and at each configured grade, the per-card all-in cost (tier fee + sales tax +
per-card supplies, insuring for the top-grade outcome), and per-grade profit/loss:
`value at grade − raw value − all-in cost` — what grading *adds* if the card comes back at
that grade, since you already own it raw. Shared per-submission costs (shipping both ways,
packing) are listed once below the table.

**Expected value (opt-in).** Write down what you believe: a probability for each configured
grade (default 7.5 / 8 / 8.5 / 9 / 10) plus `below`, the lumped chance of anything under
the lowest grade. They must sum to 1 — the tool rejects anything else and **never silently
normalizes**. Then:

```
EV(submit) = Σ p(g) · V(g)  +  p(below) · α·V(raw)  −  cost
Net gain   = EV(submit) − V(raw)
```

`V(raw)` is "sell raw today" at the freshest raw snapshot; holding is not a separate
branch (it has no cash flow — the *hold* verdict covers "positive but thin, revisit").
`α` (default 1.0) says a low-grade slab of a well-kept card resells for about its raw value.

**Two views, one price.** Snapshots store gross prices exactly as sources report them. With
the default `sale_friction = 0` that's the only view — if you're holding, marketplace fees
are not a cost of grading. Set `sale_friction: 0.1325` (eBay's trading-card final-value fee)
in `config.yaml` to add a take-home view where every value scales by `1 − friction`; when
the two views disagree on a verdict, the overall verdict is **hold**, because a decision
that flips on marketplace fees is assumption-dependent by definition.

**Batch amortization.** Per-card costs (tier fee, tax, supplies) stay per-card. Shared
costs `S` — inbound shipping, return shipping from PSA's chart, per-submission packing,
membership if a chosen tier requires one you don't hold — split **flat, S/N**, across the
batch. The batch report also recomputes the whole batch with each card removed, classifying
every card as *standalone-positive* (pays even alone), *ride-along* (positive only because
the batch absorbs shared costs), *drag* (removing it raises the batch's total net gain), or
— rarely — *negative* (loses money in-batch, but removing it wouldn't help the total).

**Break-even.** Instead of asking "is my p(10) right?", the report answers *"worth
submitting only if you believe there's at least an X% chance of a PSA 10."* It solves for
the minimum `p(10)` at which net gain crosses zero, redistributing the remaining mass over
the other outcomes in proportion to your current mix — under that parameterization net gain
is linear in `p(10)`, so the threshold is exact, not searched. Edge cases are reported
honestly: "never breaks even at current values and costs" and "positive regardless."

**Sensitivity and verdicts.** Every verdict is stress-tested: graded values ±10%/±25%,
costs +10%/+25%, and 5-point probability mass shifted between adjacent grades. The
smallest perturbation that flips the verdict is reported, and a `robust` / `sensitive` /
`fragile` label summarizes whether *any* tested shock flips it. The verdict rule itself
uses the strictest single criterion — the ±25% **value** shock, since the slab premium is
the estimate most likely to be wrong:

- **submit** — net gain ≥ $20, still positive under the ±25% value shock, and no stale
  inputs;
- **hold** — positive but thin, or knocked non-positive by the value shock, or built on a
  snapshot older than 90 days;
- **don't bother** — net gain ≤ 0, or p(below) ≥ 0.5, or even a PSA 10 wouldn't cover the
  cost.

(The label and the rule can therefore disagree: a card can read `SUBMIT` yet be labeled
`fragile` because a probability-mass shift — a change in *your beliefs*, not the market —
would flip it. The detail view names the exact flip so you can judge it.) Every threshold
in this section is a `config.yaml` knob.

## Your own collection

Real data lives in gitignored files that the tool prefers automatically when present:

```
data/inventory.yaml       # your cards        (gradescope add / import)
data/probabilities.yaml   # your estimates    (gradescope add, or a text editor)
data/values.jsonl         # price snapshots   (gradescope snapshot / assisted lookup)
data/batches/<name>.yaml  # submission lists  (a text editor)
```

Start with `gradescope add` (guided, suggests a prior from an editable lookup table in
[data/guided-priors.yaml](data/guided-priors.yaml) — the stored record is always numbers
*you* confirm, tagged `method: guided` or `manual`), or bulk-import a CSV
(see [SPEC.md §5.6](SPEC.md) for the column format). Record prices with
`gradescope snapshot` as you see them; `values.jsonl` is append-only history and the
newest snapshot per (card, kind) wins. Batches are plain YAML:

```yaml
name: first-submission
pricing_scenario: current        # current | value_restored
membership_already_held: false
card_ids: [nd-54-mewtwo-ex-full-art, de-63-darkrai-ex-full-art]
```

`value_restored` prices the batch as if PSA's paused Value tiers were orderable (clearly
labeled hypothetical — the pause is why the cheapest per-card fee is currently 3.2× its
early-2026 level). `analyze --batch <name> --compare-scenarios` shows both side by side.

## Cost book refresh

PSA prices are data, not code: dated YAML books in `data/costs/`, newest loaded by default
(`--cost-book` overrides). To refresh:

1. Copy the newest `psa-costs-YYYY-MM-DD.yaml` to a new file named for today.
2. Re-verify **every** figure against its `source.url` (assisted lookup is fine — it's
   browse-read-cite, per [docs/assisted-lookup.md](docs/assisted-lookup.md)).
3. Update each `date_accessed`; keep `estimate: true` on anything PSA doesn't publish
   exactly (inbound shipping, supplies, whether PSA collects CT sales tax on grading).
4. Commit. Old books are never edited or deleted — they're the price history.

Known open items, flagged in the data and settled by the first real invoice: the 20+ item
return-shipping interpretation, the $25 inbound-shipping default, and CT sales tax
collection (assumed yes, conservatively).

## Configuration

Optional `config.yaml` at the repo root; every knob has a default, unknown keys are
rejected loudly (a typo must not silently keep a default).

| Key | Default | Meaning |
|---|---|---|
| `grades` | `[7.5, 8, 8.5, 9, 10]` | Modeled grade outcomes (ascending; below the lowest is lumped as `below`). |
| `sale_friction` | `0` | Marketplace fee fraction; `> 0` enables the take-home view. |
| `alpha` | `1.0` | Value of a below-lowest-grade slab as a fraction of raw. |
| `min_gain` | `20` | Minimum net gain ($) for a *submit* verdict. |
| `below_short_circuit` | `0.5` | p(below) at or above this → *don't bother* immediately. |
| `staleness_days` | `90` | Snapshots older than this trigger warnings and cap verdicts at *hold*. |
| `value_shocks` | `[0.10, 0.25]` | Sensitivity shocks applied to graded values. |
| `cost_shocks` | `[0.10, 0.25]` | Sensitivity shocks applied to costs. |
| `prob_shift` | `0.05` | Probability mass moved between adjacent grades in sensitivity. |

## Development

The green bar, defined once in [scripts/checks.sh](scripts/checks.sh) and enforced before
every commit (CI runs the same script, so local green means CI green):

```bash
scripts/checks.sh
```

which runs `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest -q`.
The test suite pins hand-computed golden cases (worked arithmetic in comments), property
checks (amortization sums exactly, break-even is monotone in cost), every validation error
class, scripted interactive sessions, and the no-network guarantee. Money is `Decimal`
end-to-end — YAML/JSON numbers are parsed from their literal text and never pass through
`float`, which is what keeps the golden tests exact.

Design decisions and schemas live in [SPEC.md](SPEC.md); the build history in
[tasks/plan.md](tasks/plan.md) and [tasks/todo.md](tasks/todo.md).
