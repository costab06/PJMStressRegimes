# Event Catalog Audit Notes

## Population Definitions (fixed 2026-10-01, before exhaustive search)

Three target populations are defined in `research_spec.yaml` and reproduced
here for reference. These criteria were established before reviewing the PJM
archive to prevent post-hoc population selection.

| Population | Label | Criterion |
|------------|-------|-----------|
| S3 | positive | RTO-wide capacity emergency: Maximum Generation Emergency Action, EEA-2/EEA-3, or documented reserve shortfall |
| S2 | hard_negative | EEA-1, pre-emergency DR, capacity advisory — anomalous conditions requiring attention, not escalating to S3 |
| S1 | hard_negative | Quantitatively extreme conditions (LoadZ/RampZ threshold exceedance) with no significant operator intervention |

**Primary discrimination target: S2 → S3** (stressed-managed vs. emergency).
Do not modify these criteria after the archive search begins.

---

## Current Status

The catalog in `events.csv` is a **strong first catalog, not yet a verified
exhaustive enumeration** of every qualifying PJM emergency from July 2015
(EIA-930 availability) through the present.

The records currently present were identified through a combination of
direct recall and targeted search. They cover the highest-profile events
but have not been systematically verified against the PJM Alerts & Advisories
archive.

---

## Required Exhaustive Pass

Before the catalog is used for any quantitative false-positive or recall
analysis, a structured audit against the PJM Alerts & Advisories posting
archive is needed. The audit must:

### 1. Scope

- Date range: **2015-07-01 through present** (EIA-930 start date)
- Archive location: PJM Alerts & Advisories (numeric message IDs)
- Candidate action classes to include:

  | action_class         | Include? | Notes |
  |----------------------|----------|-------|
  | max_generation       | Yes      | RTO-wide capacity emergency — primary target class |
  | eea2 / eea3          | Yes      | Energy Emergency Alert levels 2 and 3 |
  | pre_emergency_dr     | Yes      | Recorded in operator_actions.csv; not a standalone event |
  | eea1                 | Conditional | Hard-negative if no escalation; positive if escalates |
  | deploy_all_resources | No (standalone) | Subregional transmission action; record in operator_actions.csv only |
  | reliability_coordinator_action | Case-by-case | |

### 2. Filters — Exclusions

The PJM archive contains many postings that must be **excluded** from the
positive event class:

- **Drills**: Explicitly labeled "DRILL" or "TEST" in the subject line.
  PJM conducts annual emergency operation drills; these must not be treated
  as real emergencies.

- **Local / transmission-only actions**: Actions scoped to a single zone
  (e.g. BGE, PEPCO, DOM) without a corresponding RTO-wide capacity emergency
  are **not** RTO-wide capacity stress events. Record them in
  `operator_actions.csv` as subregional context for a parent event only.

- **Informational advisories with no escalation**: Issuance of a Weather
  Alert or EEA1 that is subsequently canceled without progressing to
  EEA2/EEA3 or Maximum Generation Emergency Action → `model_role=hard_negative`,
  not positive.

### 3. Audit Output

For each candidate posting:

1. Record `pjm_message_id`, `timestamp`, `action_name`, and `region`.
2. Apply the inclusion/exclusion rules above.
3. Assign `model_role` (positive / hard_negative).
4. Check whether an existing `event_id` already covers this action (same
   event, multiple actions) or whether a new event_id is needed.
5. Add new rows to `events.csv` and/or `operator_actions.csv`.

### 4. What "Exhaustive" Means Here

The goal is not to enumerate every EEA1 advisory (there are many per year)
but to ensure that **every RTO-wide capacity emergency and every hard-negative
control period of comparable meteorological severity** is represented. Missed
positives inflate apparent model recall; missed hard-negatives deflate
apparent false-positive rates.

---

## Known Gaps in Current Catalog

- **February 2021 (Winter Storm Uri)**: Primarily ERCOT/SPP but PJM also
  issued emergency actions. Needs verification.
- **Summer 2022**: Multiple heat events; only 2022 Elliott (winter) is
  currently in catalog.
- **2016–2019 winters**: Not yet reviewed.
- **Non-PJM regions**: The current catalog is PJM-only. MISO, NYISO, ISO-NE
  emergency actions are not included and are out of scope for Milestone 1A
  but should be considered for generalization.

---

## Exhaustive Search Plan

**Objective**: enumerate every qualifying episode in **2015-07-01 through
2026-09-30** under the S3/S2/S1 criteria above, then stop. No further
episode-class selection after this pass.

### Sources to search

1. **PJM Alerts & Advisories archive** (primary for S3 and S2)
   - Search for: Maximum Generation Emergency Action, Energy Emergency Alert
     (EEA 1/2/3), Emergency Load Management, Reserve Shortage Warning
   - Filter OUT: drills/tests, subregional-only transmission actions,
     informational advisories with no follow-on action
   - Record: `pjm_message_id`, UTC timestamp, action class, region scope

2. **EIA-930 data (threshold exceedance)** (primary for S1)
   - LoadZ > 3.0 sustained ≥ 6h with no S2/S3 action documented
   - RampZ > 3.0 sustained ≥ 3h
   - Identify candidate dates from 2019–2026 (API) and 2015–2018 (bulk CSV)

3. **Cross-check**: NERC event analysis reports and PJM state of the market
   reports for corroboration of S3 events

### Output schema additions

For each new episode found:
- Add row(s) to `events.csv` with correct `episode_id`, `model_role`,
  `severity`, `event_type`
- Add action rows to `operator_actions.csv` if applicable
- Note PJM message IDs in `source_id` field

### Episode count target

The HMM is deferred until at least:
- **S3 episodes ≥ 6** (currently: 2 — ELL_2022, HEAT_2026)
- **S2 episodes ≥ 10** (currently: 3 — COLD_2018, HEAT_2023, HEAT_2025)
- Total independent episodes ≥ 20 preferred before model evaluation
