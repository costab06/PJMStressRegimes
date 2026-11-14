# GridRegime: operational-flexibility investigation (2026-11-14)

## Question
When PJM actual demand exceeds forecast by thousands of MW, what differentiates an S2 capacity alert that does not escalate from an S3 emergency action?

## Priority cases
- ELL_2022 (S3): December 2022
- HEAT_2026 (S3): July 2026
- HEAT_2024 (S2): June 2024
- HEAT_2025_JUL (S2): July 2025

Do not interpret these as a balanced statistical sample: two S3 episodes, overlapping event windows, and episode-level dependence.

## Candidate PJM data feeds and validation requirements

1. **gen_outages_by_type** — generation outage forecasts, by forecast execution date and forecast date, PJM region, forced/planned/maintenance/total MW. PJM documentation says indefinite retention, first available May 26, 2015, daily publication around 06:00 Eastern. Confirm historic records and select the most recent *published-before-anchor* execution for each operating day. Do not select hindsight revisions. Source: https://dataminer2.pjm.com/feed/gen_outages_by_type/definition
2. **day_gen_capacity** — daily generation capacity; inspect field definitions, geographical coverage, units, and timestamp semantics before use. Source: https://dataminer2.pjm.com/feed/day_gen_capacity/definition
3. **ops_sum_prev_period** — actual operational statistics; inspect whether reserves, capacity or interchange are reported and the time resolution. Source: https://dataminer2.pjm.com/feed/ops_sum_prev_period/definition
4. **ops_sum_frcst_peak_rto** — projected RTO statistics at peak, with forecast vintage; evaluate whether projected resource margin can be reconstructed from verified fields. Source: https://dataminer2.pjm.com/feed/ops_sum_frcst_peak_rto/definition
5. **operational_reserves** — 15-second operational reserve quantities; gridstatus documentation indicates only ~15 days available. Treat historical availability as unconfirmed and do not silently substitute reserve-market prices for reserve MW. Source: https://dataminer2.pjm.com/feed/operational_reserves/definition
6. **PJM historical load forecasts** — evaluate vintages and operational relevance; EIA-930 forecasts are not automatically PJM day-ahead commitment forecasts. Source: https://www.pjm.com/markets-and-operations/data-dictionary.aspx/

## Acquisition gate
- Check PJM Data Miner terms and membership requirements before exporting, storing, sharing or publishing data-derived tables. PJM's public Data Miner page restricts redistribution without active membership.
- API access requires a PJM account; never put API keys in GitHub. Read credentials from environment only.
- Request metadata and schema first, then a small sample of each priority case; record HTTP status, rows, time span, timezone, region, publication/forecast vintage, units and gaps.
- Do not interpolate missing reserve or outage records. Flag unavailable feeds explicitly.
- Confirm whether reported outages are contemporaneous known outages, retrospective revised outages, or future forecasts.
- Confirm geographic scope: the July 2026 emergency metadata labels MIDATL+SOUTHERN while EIA demand is PJM RTO; an RTO aggregate may mask local reserve constraints.

## Proposed derived indicators (only after validating inputs)
- Underforecast MW = actual demand MW - forecast demand MW (positive = underforecast).
- Reported forced outage MW and total outage MW, with appropriate publication vintage.
- Available-capacity proxy = verified comparable capacity MW - verified outage MW, *only if the underlying definitions permit subtraction*.
- Proxy headroom = available-capacity proxy - actual load MW, with caveats for interchange, deliverability, reserves, generation commitment, and scope.
- Actual reserve margin or shortage only from a documented reserve quantity and requirement, not inferred from nameplate capacity.

## Design
1. Reconstruct each episode's first alert and S3 escalation action times from verified PJM notices. S3 event catalog currently lacks first-alert timestamps: resolve these before trajectory comparison.
2. Build time-aligned, point-in-time records for each episode, ideally beginning at the first comparable alert. Separate data known then from retrospective data.
3. Compare within-event underforecast and capacity/outage/headroom changes over 48h and 24h pre-action; include same-season S2 controls.
4. Check whether large underforecast occurs without escalation when capacity/headroom proxies are favorable, and whether similar forecast error escalates when margins are constrained.
5. Publish descriptive episode case studies and counterexamples, not a classifier or causal estimate with only two S3 episodes.

## Source documentation
- https://www.pjm.com/markets-and-operations/etools/data-miner-2/
- https://www.pjm.com/markets-and-operations/etools/data-miner-2/data-availability
- https://www.pjm.com/-/media/DotCom/etools/data-miner-2/data-miner-2-api-guide.ashx?la=en

## Current status
**Source discovery completed; historical reserve/capacity/outage data not yet downloaded or validated.** No conclusions about reserve exhaustion, generator outage causality, or resource adequacy are justified yet.
