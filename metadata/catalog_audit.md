# Event Catalog Audit Notes

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
