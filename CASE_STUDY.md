# Why did mobile conversion fall in late December?

**Google Merchandise Store GA4 sample** · December 21–27, 2020 compared with December 14–20, 2020

## Executive summary

Across the official 92-day public dataset, the dbt pipeline reconstructed **360,129 sessions** from **4,295,584 events**, including 4,848 sessions with a purchase (1.35% conversion). Comparing consecutive complete Monday–Sunday weeks, December 21–27 had the largest absolute mobile purchase-conversion decline.

Mobile purchase conversion fell from **1.75% to 1.19%** (−0.56 percentage points, or 32.0% relative). Traffic also fell 33.1%. The largest decrease in ordered step conversion occurred between product view and add to cart, while checkout-to-purchase improved slightly.

## Funnel evidence

| Mobile metric | Dec 14–20 | Dec 21–27 | Change |
|---|---:|---:|---:|
| Sessions | 13,312 | 8,904 | −33.1% |
| Product view | 2,823 | 1,650 | −2.68 pp vs sessions |
| Add to cart | 819 | 388 | **−5.50 pp vs views** |
| Begin checkout | 288 | 121 | −3.98 pp vs carts |
| Ordered purchase | 170 | 73 | +1.30 pp vs checkouts |
| Sessions with any purchase event | 233 | 106 | −0.56 pp vs sessions |

The headline purchase metric counts any eligible session with a purchase event. The strict ordered funnel requires each stage to occur after the previous one, so the final counts differ.

## Where the decline was concentrated

A decomposition by first-acquisition channel attributes −0.528 pp to changes within channels and −0.032 pp to traffic-mix changes. Organic Search contributed the largest arithmetic change (−0.245 pp), followed by Direct (−0.125 pp) and Other (−0.113 pp).

The strongest measurable loss was in the product-to-cart transition. Product availability, merchandising, product-page experience, pricing, or event instrumentation are hypotheses for follow-up. The export contains behavioral signals, so investigating those hypotheses would require product availability and pricing histories, interaction error logs, and instrumentation checks for the two periods. The holiday timing is relevant context but does not establish a cause.

## Reproduce the investigation

1. Run the full BigQuery build or export its reporting snapshot.
2. In the Streamlit sidebar, choose the Google Merchandise Store data source and **Load December mobile case**.
3. Open Analytics Copilot and ask “Why did mobile conversion decline last week?”
4. Inspect the date windows, step counts, contribution analysis, evidence IDs, and SQL.

The independent seven-day reconciliation matched 275,031 source events, 29,035 sessions, 162 purchasing sessions, and 161 deduplicated orders exactly. All nine dbt data checks passed across the full 92-day build.

## Source and limitations

Source: [Google's public GA4 ecommerce sample](https://developers.google.com/analytics/bigquery/web-ecommerce-demo-dataset), November 1, 2020 through January 31, 2021. It is obfuscated historical data. First-acquisition channels are user acquisition fields. Product reporting uses usable item IDs, present in 62.7% of recorded product views. Of 5,692 purchase events, 906 lacked a usable transaction ID; 4,451 canonical orders were counted. The case study uses session conversion independently of transaction ID completeness.
