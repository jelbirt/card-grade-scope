# Assisted lookup: getting values into the tool

This is the workflow for the **left side** of the boundary diagram in the
[README](../README.md#the-ai--deterministic-boundary): using a web-enabled session (an LLM
with browsing, or you with a browser) to gather market values, and handing them to the
deterministic core as plain, cited, lintable data.

The rules that make this defensible:

1. **Browse, read, cite — never scrape.** Every source below is read the way a human
   reads it. No headless harvesting, no automated fetch loops, no API keys. (eBay's user
   agreement prohibits scraping; psacard.com blocks automated fetches; the paid/keyed
   aggregator APIs are excluded from this project by design.)
2. **Every number carries its provenance**: source name, URL, date observed, and — where
   the source shows individual sales — how many comps it rests on and their spread.
3. **Nothing is used until the linter passes it.** The session's output is appended to a
   snapshot file and checked with `gradescope validate-snapshots`; the engine only ever
   reads validated files. A human with a text editor can produce byte-identical data.

**The session needs a real browser.** The useful price sources refuse server-side/
programmatic fetching (Cloudflare 403s), so a text-only "web-enabled LLM" mostly can't
read them. What works, verified in practice: either you browsing with the session
narrating what to record, or an assistant that drives *your actual browser session*
(e.g. a browser-extension integration), reading pages at human pace. That is still
browse-read-cite — same pages a human sees, same ToS posture, one page at a time.

## Where to look, per value kind

| Value | Primary source | Corroboration | Record |
|---|---|---|---|
| `raw` | eBay sold listings | TCGplayer market price, PriceCharting | median-ish sold price, `n_comps`, `spread` |
| `psa7.5` … `psa10` | [PSA Auction Prices Realized](https://www.psacard.com/auctionprices) | eBay sold (search "`<card>` PSA `<grade>`"), PriceCharting | recent realized prices, `n_comps`, `spread` |
| `pop` | [PSA Population Report](https://www.psacard.com/pop) | — | population count, `pop_grade` |

Source-by-source procedure:

- **eBay sold listings** — search the card name + set + number, filter to *Sold items*.
  Read the recent sales for the right variant/condition; ignore damaged/altered outliers.
  Record the search URL, the count of comps you actually looked at, and low/high as
  `spread`. ([130point.com/sales](https://130point.com/sales/) is a free assist that
  surfaces the true price of best-offer sales — same read-and-cite posture.)
- **PSA APR** — navigate to the card's page under `psacard.com/auctionprices`, pick the
  grade column, read the individual realized sales (venue + date shown per sale). Best
  source for graded comps; record the card-page URL.
- **PSA Population Report** — the card's row under `psacard.com/pop`; record the count for
  the grade you care about as `value`, with `kind: "pop"` and `pop_grade` set. Pop counts
  contextualize the PSA-10 premium (low pop → outsized premium); the tool displays them
  and never algorithmically adjusts values with them.
- **PriceCharting** — the card's page under `pricecharting.com` shows a full per-grade
  price guide (Ungraded / 7 / 8 / 9 / 9.5 / PSA 10) computed from **completed sales
  only** (unsold listings excluded), plus the dated sold listings behind each grade and
  per-grade sale volume. In practice this makes it the workhorse for per-grade values;
  use APR/eBay to corroborate the numbers that matter most. Two caveats: the whole-grade
  columns pool grading companies (a "Grade 9" mixes PSA 9 and CGC 9 sales — CGC often
  sells lower; only the PSA 10 column is company-specific), and a grade with zero sold
  listings still shows a price — that's their algorithm's estimate, not an observation.
- **TCGplayer** — market price for **raw** near-mint singles; the de-facto raw reference.

Thin comps happen on vintage cards at specific grades. Record what's actually there
(`n_comps: 2` is honest data) rather than widening the search until a number looks solid.

**`n_comps` conventions** (keep them consistent so a low number reads as low confidence):
record the source's sold-listing count for that grade; record `n_comps: 0` when the
source shows a price with **no** recorded sales behind it (an estimate); omit the field
entirely when the source doesn't expose counts at all.

## Screening a whole set

To find every grading candidate in a set without opening a hundred card pages, work in
two stages:

1. **Set index page** — `pricecharting.com/console/pokemon-<set-slug>?sort=highest-price`
   lists every card with Ungraded / Grade 9 / PSA 10 columns in one load. Shortlist any
   card whose Grade 9 or PSA 10 could plausibly clear the all-in grading cost; everything
   else in the long tail is dead on arrival (commons show near-identical estimated PSA 10
   values with no sales behind them — ignore those). Ranking by raw price alone is a trap:
   graded ceilings don't track raw prices.
2. **Detail pages for the shortlist only** — full per-grade guide, sold counts (the
   `n_comps` source), and dated sale history.

## The prompt template

Paste this into a web-enabled LLM session, filling the bracketed parts. It is written so
the output drops straight into a snapshot file.

```text
Look up current market values for this Pokémon card:

  Card: [NAME], [SET] [NUMBER] ([VARIANT — e.g. full art, secret rare])
  My inventory id for it: [CARD_ID]

I need, as of today:
  - raw (ungraded, near-mint) value: eBay sold listings primary, TCGplayer to corroborate
  - PSA-graded values for each grade in my configured grade set: [GRADES — copy the
    `grades` list from config.yaml; note most price guides track whole grades only, so a
    config of [7, 8, 9, 10] matches the available data; half-grade comps are thin —
    report what exists]
  - PSA population count at grade 10 from the PSA Population Report

Rules:
  - Browse and read pages like a human; do not scrape, automate fetches, or use paid APIs.
  - For each value: record the price you'd honestly report, how many recent comps you saw
    (n_comps), and the low/high of those comps (spread). Skip n_comps/spread only where
    the source shows a single aggregate number.
  - Every line must cite the exact source URL you read and today's date.

Output: one JSON object per line, no prose, exactly this shape —
{"card_id": "[CARD_ID]", "kind": "raw", "value": 90.00, "currency": "USD",
 "source_name": "eBay sold", "source_url": "https://...", "date_observed": "YYYY-MM-DD",
 "n_comps": 12, "spread": {"low": 75, "high": 110}, "recorded_by": "assisted-lookup"}

kind must be one of: raw, psa7.5, psa8, psa8.5, psa9, psa10, pop.
For kind "pop", value is the population count and add "pop_grade": "10".
If you cannot find a value for some kind, say so in a comment line starting with # —
do not invent a number.
```

## After the session: validate, then use

Append the returned lines to the target file and lint it:

```bash
uv run gradescope validate-snapshots data/values.jsonl
```

Every problem is reported with its line number (bad JSON, unknown kind, lowercase
currency, missing `pop_grade`, malformed date, …); fix or delete the offending lines and
re-run until it exits 0. `#`-comment lines from the template are **not** valid JSONL —
read them (they're the session telling you a value is missing), act on them, delete them.

Two sanity checks the linter cannot do for you:

- Open one cited URL per session and confirm the number is what the session says it is.
- Compare against the previous snapshot for the same card/kind; a large move should be
  explainable (a real sale, not a misread).

`values.jsonl` is append-only history — add new lines rather than editing old ones; the
engine uses the newest snapshot per (card, kind) and warns when it's older than 90 days.

## Cost-book refresh, same treatment

Refreshing `data/costs/` follows the identical pattern (see
[README — Cost book refresh](../README.md#cost-book-refresh)): a session may *look up*
PSA's current fees, shipping chart, and membership pricing on psacard.com and draft the
new dated YAML — but every figure cites `source: {url, date_accessed}`, estimates stay
flagged `estimate: true`, and the file must load cleanly (`uv run gradescope costs
--cost-book data/costs/psa-costs-<date>.yaml`) before it's committed. Old books are never
edited or deleted.

## Template dry run

Verified two ways on 2026-08-02:

- **Format dry run:** a full set of lines in exactly the template's output shape (raw +
  graded kinds + a pop line, with `n_comps`, `spread`, real source-URL patterns) passed
  `validate-snapshots` unmodified — 0 problems, exit 0.
- **End to end:** a full recording pass ran through this workflow for real — an assisted
  session reading the sources through the owner's browser (server-side fetches get 403'd;
  PriceCharting and psacard.com both verified blocking them the same day), set-index
  screening, detail pages for the shortlist, snapshot lines appended and linted clean on
  the first try. The linter, not the acquisition path, is the trust boundary — and it
  held.

After any template edit, repeat the format dry run: produce lines for one card, validate
them in a scratch file, and only then commit the new template text.
