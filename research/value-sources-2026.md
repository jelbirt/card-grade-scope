# Value-data source research — 2026

Date accessed for all sources: **2026-08-01**.
Question: where can raw and PSA-graded Pokemon card values (and PSA population counts) be obtained **without paid APIs**, and what are the access/ToS constraints that shape the assisted-lookup workflow?

## Sources evaluated

### PSA Auction Prices Realized (APR)
- URL pattern: <https://www.psacard.com/auctionprices> — free to browse per card/grade; shows individual realized sales with dates and venues.
- Best source for **graded** (PSA 7/8/9/10) comps on vintage Pokemon.
- Access: free, no login for browsing. psacard.com blocks automated fetches (Cloudflare 403 observed 2026-08-01) — consistent with manual/assisted browsing only, **no scraping**.

### PSA Population Report
- URL pattern: <https://www.psacard.com/pop> — free to browse; per-card counts by grade.
- Materially affects the PSA-10 premium (low pop 10 → outsized premium). Captured as a snapshot field, not a computed input, in v1.
- Same access posture as APR: manual/assisted browsing, no scraping.

### eBay sold/completed listings
- Sold-listings filter on ebay.com search is free to view in a browser.
- eBay's User Agreement prohibits scraping/automated data collection; the official Marketplace Insights API is restricted-access. Therefore: **manual or AI-assisted browsing with human-readable citation only** — record what was seen, the search URL, date, and number of comps.
- <https://130point.com/sales/> — free sold-listing search (surfaces eBay sales incl. best-offer prices) — useful assist, same "read and cite, don't scrape" posture.

### PriceCharting
- <https://www.pricecharting.com/category/pokemon-cards> — free price guide pages showing **ungraded and graded** (incl. PSA) values per card, derived from eBay sales; per-card history charts.
- Free to browse; full-database downloads/API are paid. Good secondary cross-check for both raw and graded values; single-number estimates hide spread, so record sample-size/spread from eBay/APR when possible and use PriceCharting as corroboration.

### TCGplayer
- <https://www.tcgplayer.com> — market price for **raw** cards (near-mint and lower conditions); the de-facto raw-value reference for Pokemon singles.
- Free to browse. API access is partner-gated. Same manual/assisted posture.

### Aggregator APIs (PokemonPriceTracker, PokeTrace, pokemontcg.io, etc.)
- Free tiers exist (e.g., <https://www.pokemonpricetracker.com/pokemon-card-price-api> — 100 credits/day; <https://poketrace.com/docs> — 250 calls/day) but require API keys.
- **Excluded from the core by design** (deterministic, offline, no keys). Could inform a *human's* research session, but the tool never calls them.

## Conclusions for the assisted-lookup workflow design

1. All viable no-cost sources are **browse-only**: the workflow is "a session (human or LLM with web access) looks up comps, records value / currency / source name / URL / date / sample size / spread into the snapshot file, and a human can redo every lookup by hand."
2. Recommended source hierarchy per value:
   - **Raw value:** eBay sold (primary) + TCGplayer market (corroboration).
   - **PSA 7–10 values:** PSA APR (primary) + eBay sold and PriceCharting (corroboration).
   - **Pop counts:** PSA Population Report only.
3. No scraping, no headless browsing, no API keys anywhere. The snapshot file is the sole handoff between acquisition and the deterministic core.
4. Vintage WOTC-era cards can have thin comps at specific grades (especially PSA 7/8). The snapshot schema therefore requires `n_comps` and a `spread` field, and the engine treats low-comp values as low-confidence in sensitivity output.
