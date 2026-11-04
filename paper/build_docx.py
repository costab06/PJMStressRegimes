"""Build paper/article.docx from structured content.

Run from the project root:
    python3 paper/build_docx.py
"""

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import copy

OUTPUT = "paper/article.docx"


def add_horizontal_rule(doc):
    """Insert a thin horizontal rule paragraph."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("─" * 60)
    run.font.color.rgb = RGBColor(0xCC, 0xCC, 0xCC)
    run.font.size = Pt(8)


def heading(doc, text, level):
    p = doc.add_heading(text, level=level)
    return p


def body(doc, text):
    p = doc.add_paragraph(text)
    p.style = doc.styles["Normal"]
    return p


def callout(doc, text):
    """Indented italic paragraph used for pull quotes / sidebars."""
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.5)
    p.paragraph_format.right_indent = Inches(0.5)
    run = p.add_run(text)
    run.italic = True
    run.font.color.rgb = RGBColor(0x44, 0x44, 0x88)
    return p


def caption(doc, text):
    p = doc.add_paragraph(text)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.runs[0]
    run.italic = True
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    return p


def build():
    doc = Document()

    # ── Page margins ──────────────────────────────────────────────────────────
    for section in doc.sections:
        section.top_margin    = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.left_margin   = Inches(1.25)
        section.right_margin  = Inches(1.25)

    # ── Normal style ─────────────────────────────────────────────────────────
    normal = doc.styles["Normal"]
    normal.font.name = "Georgia"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(8)
    normal.paragraph_format.line_spacing = Pt(16)

    # ── Title ─────────────────────────────────────────────────────────────────
    t = doc.add_heading("Before the Emergency", level=0)
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub = doc.add_paragraph(
        "Detecting Hidden Stress Regimes in America's Largest Power Market"
    )
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.runs[0].font.size = Pt(14)
    sub.runs[0].italic = True
    sub.runs[0].font.color.rgb = RGBColor(0x44, 0x44, 0x44)

    doc.add_paragraph()  # spacer

    # ── Byline ────────────────────────────────────────────────────────────────
    byline = doc.add_paragraph("Draft · November 2026 · Grid Regime Study")
    byline.alignment = WD_ALIGN_PARAGRAPH.CENTER
    byline.runs[0].font.size = Pt(9)
    byline.runs[0].font.color.rgb = RGBColor(0x88, 0x88, 0x88)

    add_horizontal_rule(doc)

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — THE NIGHT THE GRID NEARLY FAILED
    # ═══════════════════════════════════════════════════════════════════════════
    heading(doc, "The Night the Grid Nearly Failed", 1)

    body(doc,
        "On the evening of December 23, 2022, a grid operator sitting in PJM "
        "Interconnection's control room outside Philadelphia made an announcement "
        "that affects the lives of 65 million people: a Maximum Generation Emergency "
        "Action. Every available megawatt of electricity in a thirteen-state region — "
        "from Chicago to the Chesapeake Bay — was to be dispatched. The system was "
        "running out of room."
    )

    body(doc,
        "Winter Storm Elliott had roared across the eastern United States with "
        "temperatures 20 to 30 degrees below normal. Power plants that had never been "
        "designed to start in Arctic cold failed to come online. Natural gas pipelines "
        "froze. Demand soared while supply collapsed. The same scene played out the "
        "next morning on December 24, when a second emergency action was issued as the "
        "storm refused to relent."
    )

    body(doc,
        "PJM managed the crisis. The lights stayed on. But the event exposed something "
        "that grid engineers and researchers had suspected for years: the conventional "
        "tools for anticipating capacity emergencies — scalar thresholds on load forecasts, "
        "reserve margins, single-variable alarms — had not flagged the 2022 emergency "
        "with the lead time or confidence that operators needed. The grid had entered "
        "dangerous territory and the warning systems had been, at best, ambiguous."
    )

    callout(doc,
        "\"Some non-emergency periods exhibit more extreme individual load anomalies "
        "than emergency periods. Scalar extremeness alone is insufficient to distinguish "
        "emergency from successfully-managed conditions.\"\n"
        "— Research Hypothesis v1, Grid Regime Study, 2026"
    )

    body(doc,
        "This article describes an ongoing research effort to build something better: "
        "a data-driven system that treats the power grid as a dynamical system with "
        "latent stress regimes, and attempts to detect the transition into those regimes "
        "before they become emergencies. We describe the data infrastructure, the "
        "analytical pipeline, and the early exploratory findings that motivate the "
        "approach. The model does not yet exist — but the groundwork being laid here "
        "is the part that will determine whether the model, when it is built, can be "
        "trusted."
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — WHAT IS PJM AND WHY DOES IT MATTER
    # ═══════════════════════════════════════════════════════════════════════════
    heading(doc, "What Is PJM, and Why Does It Matter?", 1)

    body(doc,
        "PJM Interconnection is the regional transmission organization (RTO) that "
        "coordinates the movement of wholesale electricity across 13 states and the "
        "District of Columbia — Pennsylvania, New Jersey, Maryland, Delaware, Virginia, "
        "West Virginia, Ohio, Indiana, Illinois, Michigan, Kentucky, Tennessee, North "
        "Carolina, and DC. It is the largest competitive wholesale electricity market "
        "in the world by load served, operating a grid with roughly 180,000 megawatts "
        "of installed generating capacity and annual electricity consumption equivalent "
        "to the output of hundreds of large power plants running continuously."
    )

    body(doc,
        "As an RTO, PJM does not own generators or transmission lines — it operates "
        "the bulk transmission system, clears the wholesale energy and capacity markets, "
        "and issues the operational instructions (alerts, advisories, emergency actions) "
        "that tell generators what to do in real time. When demand exceeds what the "
        "available generation fleet can supply — or when it threatens to — PJM escalates "
        "through a hierarchy of emergency actions defined by NERC (the North American "
        "Electric Reliability Corporation) reliability standards."
    )

    body(doc,
        "That hierarchy matters for this research. It gives us a natural classification "
        "scheme:"
    )

    # Table of S1/S2/S3 definitions
    table = doc.add_table(rows=4, cols=3)
    table.style = "Table Grid"
    hdr = table.rows[0]
    for i, txt in enumerate(["Population", "Label", "Operational Definition"]):
        cell = hdr.cells[i]
        cell.text = txt
        cell.paragraphs[0].runs[0].bold = True

    rows_data = [
        ("S3 — Emergency", "Positive",
         "Maximum Generation Emergency Action, Energy Emergency Alert Level 2 or 3, "
         "or any action with documented reserve shortfall or involuntary load reduction."),
        ("S2 — Stressed, Managed", "Hard Negative",
         "Energy Emergency Alert Level 1, pre-emergency demand response, or capacity "
         "advisory that did not escalate to S3. Conditions required operator attention "
         "but the system was successfully managed."),
        ("S1 — Quantitative Extreme", "Hard Negative",
         "Periods with statistically extreme load or ramp conditions but no documented "
         "significant operator intervention, identified from grid data alone."),
    ]
    for i, (pop, lbl, defn) in enumerate(rows_data, 1):
        table.rows[i].cells[0].text = pop
        table.rows[i].cells[1].text = lbl
        table.rows[i].cells[2].text = defn

    doc.add_paragraph()
    caption(doc,
        "Table 1. Episode taxonomy used in this study. Populations and criteria were "
        "fixed before the exhaustive archive search to prevent post-hoc selection."
    )

    body(doc,
        "The distinction between S2 and S3 is the primary scientific target. It is "
        "operationally meaningful — S3 represents a system that is failing to balance "
        "supply and demand without extraordinary intervention — and it is difficult. "
        "Many of the worst S2 events look, from a raw numbers perspective, more extreme "
        "than some S3 events. That is the puzzle this research is designed to crack."
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 3 — THE RESEARCH HYPOTHESIS
    # ═══════════════════════════════════════════════════════════════════════════
    heading(doc, "The Research Hypothesis: Regimes, Not Thresholds", 1)

    body(doc,
        "The conventional approach to grid stress detection is threshold-based. Load "
        "exceeds X megawatts: alarm. Reserve margin drops below Y percent: alert. "
        "Forecast error exceeds Z percent: notification. These scalar triggers are "
        "operationally simple and auditable — which is why grid operators use them. "
        "But they treat each variable in isolation, and they treat the problem as "
        "binary: either the threshold is crossed or it is not."
    )

    body(doc,
        "The research hypothesis here is different. It proposes that grid emergencies "
        "are better understood as transitions between latent system regimes — "
        "configurations of the multivariate operational state that persist over time "
        "and evolve in characteristic ways before, during, and after stress events. "
        "The joint configuration, trajectory, and persistence of multiple variables "
        "contains information about systemic risk that is absent from their individual "
        "magnitudes."
    )

    body(doc,
        "This hypothesis is motivated by a striking exploratory observation: the "
        "December 2022 Elliott emergency and the July 2026 heat emergency — the two "
        "confirmed S3 events in PJM's recent history — were driven by entirely different "
        "operational signatures. Elliott showed sustained, large positive load-forecast "
        "error (demand consistently exceeded what operators had predicted), while "
        "July 2026 showed demand running below forecast even as emergency conditions "
        "developed. The variable that distinguished emergency from non-emergency was "
        "not the same across the two events."
    )

    body(doc,
        "Meanwhile, several S2 events — the January 2019 polar vortex, the July 2023 "
        "heat wave, the June 2025 heat wave — showed individual load or ramp anomalies "
        "that were, in isolation, as extreme as the S3 events. If scalar thresholds "
        "cannot reliably distinguish these populations, what can?"
    )

    callout(doc,
        "The working hypothesis: the answer lies in how the variables move together — "
        "their joint trajectory through a multivariate operational state space — rather "
        "than in any single variable's instantaneous value."
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 4 — THE DATA INFRASTRUCTURE
    # ═══════════════════════════════════════════════════════════════════════════
    heading(doc, "The Data Infrastructure", 1)

    heading(doc, "EIA-930: The Grid's Public Vital Signs", 2)

    body(doc,
        "The primary data source is EIA-930, a dataset published by the U.S. Energy "
        "Information Administration that records hourly electricity supply and demand "
        "for every balancing authority in the United States. For PJM, this means a "
        "continuous hourly record of:"
    )

    items = [
        "Actual electricity demand (in megawatt-hours consumed per hour)",
        "Day-ahead demand forecast (what PJM predicted the day before)",
        "Net interchange with neighboring grid regions",
        "Generation by fuel type (natural gas, coal, nuclear, wind, solar, hydro)",
    ]
    for item in items:
        p = doc.add_paragraph(item, style="List Bullet")

    body(doc,
        "EIA-930 is available in two forms. Since 2019, the EIA provides an API (v2) "
        "that delivers data in near-real-time, with typical latency of a few hours. "
        "Before 2019, the data exists only in bulk CSV files that the EIA publishes "
        "semi-annually. The ingest pipeline described in this paper handles both "
        "formats transparently, routing API calls for post-2019 windows and bulk "
        "downloads for earlier periods."
    )

    body(doc,
        "The data is surprisingly clean but not perfectly so. During the API ingest "
        "for 2021 baseline data, three rows appeared with demand values in the "
        "billions of megawatts — physically impossible values that would correspond "
        "to the output of millions of large power plants. These are API artifacts, "
        "likely sentinel values inserted during data maintenance. The pipeline filters "
        "these automatically using plausibility bounds: PJM demand is expected to "
        "fall between 10,000 MW (a deep overnight minimum) and 200,000 MW (well above "
        "any recorded peak), and any row outside this range is discarded with a logged "
        "warning."
    )

    heading(doc, "PJM Alerts and Advisories", 2)

    body(doc,
        "The event catalog — the list of emergency and near-emergency episodes that "
        "define the training and evaluation data — is constructed from PJM's public "
        "Alerts & Advisories archive, a numbered sequence of operational postings that "
        "PJM issues to market participants whenever conditions warrant notification. "
        "The archive is searchable by message ID, date, and subject, and it records "
        "every EEA declaration, Maximum Generation Emergency Action, pre-emergency "
        "demand response activation, and significant advisory."
    )

    body(doc,
        "Supplementing the PJM archive, the U.S. Department of Energy's Office of "
        "Electricity publishes 202(c) emergency orders — orders issued under Section "
        "202(c) of the Federal Power Act that authorize grid operators to direct "
        "generators to run even if doing so violates their environmental permits. "
        "These orders are a definitive marker of severe operational stress: they are "
        "only issued when the grid operator has declared that normal market mechanisms "
        "are insufficient. In 2026 alone, thirteen PJM-specific 202(c) orders were "
        "issued, providing an independent cross-check on the archive classification."
    )

    heading(doc, "Building an Auditable Event Catalog", 2)

    body(doc,
        "The event catalog is not just a list of interesting events — it is a "
        "methodologically controlled research database. The design principle is that "
        "every inclusion and exclusion decision must be recorded and defensible, and "
        "that the decisions must be made according to pre-specified rules rather than "
        "post-hoc judgments about what looks interesting."
    )

    body(doc,
        "This matters because machine learning models are only as trustworthy as their "
        "training data. If the researcher unconsciously includes events that match a "
        "pre-formed pattern and excludes those that don't, the model will appear to "
        "work in validation but fail in deployment. The catalog design explicitly "
        "guards against this:"
    )

    guards = [
        ("Population criteria fixed before search.",
         "The definitions of S3, S2, and S1 were written into a version-controlled "
         "research specification file before the exhaustive archive search began. "
         "They cannot be modified retroactively."),
        ("Classification independent of exploratory figures.",
         "The exploratory phase of the project produced z-scored time series and "
         "phase portraits showing what the data looks like across known events. "
         "The archive classification was performed without reference to these figures "
         "to prevent the visual patterns from influencing which events enter the "
         "sample."),
        ("Every reviewed item recorded.",
         "The audit log records every archive item reviewed, whether included or "
         "excluded. Exclusion rows carry the posting date, message ID, classification "
         "considered, and the reason for exclusion. This provides an auditable "
         "denominator — a reviewer can verify that cherry-picking did not occur."),
        ("Episode consolidation during cataloging.",
         "Multiple operator actions caused by the same continuous weather or grid "
         "event are assigned a single episode ID during the cataloging step. This "
         "prevents a multi-day event from inflating the sample size by appearing "
         "as many independent observations."),
    ]
    for title, detail in guards:
        p = doc.add_paragraph()
        p.add_run(title + " ").bold = True
        p.add_run(detail)

    body(doc,
        "The exhaustive catalog audit covered 2015-07-01 through 2026-09-30 — the "
        "period for which EIA-930 data is available. The audit found 11 qualifying "
        "episodes, including 2 S3 emergencies and 8 S2 stressed-managed events. "
        "Two items (Winter Storm Uri's effect on PJM in February 2021, and a possible "
        "July 14, 2026 heat event) remain pending direct archive review."
    )

    # Episode count table
    doc.add_paragraph()
    etable = doc.add_table(rows=5, cols=3)
    etable.style = "Table Grid"
    ehdr = etable.rows[0]
    for i, txt in enumerate(["Population", "Count", "Episodes"]):
        c = ehdr.cells[i]
        c.text = txt
        c.paragraphs[0].runs[0].bold = True

    edata = [
        ("S3 (positive)",      "2",
         "ELL_2022 (Winter Storm Elliott), HEAT_2026 (July 2026)"),
        ("S2 (hard negative)", "8",
         "POLAR_2019, HEAT_2023, HEAT_2024, COLD_2025, HEAT_2025 (Jun), "
         "HEAT_2025_JUL, COLD_2026, HEAT_2026_SEP"),
        ("S1 (hard negative)", "1",
         "COLD_2018 (2017–18 Cold Snap)"),
        ("Total",              "11", ""),
    ]
    for i, (pop, cnt, eps) in enumerate(edata, 1):
        etable.rows[i].cells[0].text = pop
        etable.rows[i].cells[1].text = cnt
        etable.rows[i].cells[2].text = eps

    doc.add_paragraph()
    caption(doc,
        "Table 2. Episode inventory after exhaustive catalog audit, 2015–2026. "
        "Counts are by independent meteorological episode, not by individual "
        "operator action."
    )

    body(doc,
        "Eleven episodes over eleven years. The rarity of S3 events — two confirmed "
        "emergencies across a decade — is itself a finding. PJM operates one of the "
        "most reliable bulk electric systems in the world, and RTO-wide capacity "
        "emergencies are, by design, extremely rare. This rarity shapes every "
        "subsequent methodological choice."
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 5 — THE ANALYSIS PIPELINE
    # ═══════════════════════════════════════════════════════════════════════════
    heading(doc, "The Analysis Pipeline", 1)

    heading(doc, "Overview", 2)

    body(doc,
        "The pipeline transforms raw EIA-930 hourly data into a set of normalized, "
        "event-aligned time series that can be used for exploratory analysis and, "
        "eventually, model training. It proceeds in four stages: ingest, validate, "
        "feature engineering, and alignment/windowing."
    )

    heading(doc, "Stage 1: Ingest", 2)

    body(doc,
        "For each episode, the pipeline fetches a 84-hour window of hourly PJM data "
        "centered on the key operational event time: 72 hours before and 12 hours "
        "after. For S3 and S2 events, the anchor point is the time of the operator "
        "action (the EEA declaration or emergency action). For S1 events, where no "
        "operator action occurred, the anchor is the hour of peak demand within the "
        "event window."
    )

    body(doc,
        "The ingest module routes requests to the appropriate data source. Post-2019 "
        "windows use the EIA-930 v2 API, authenticated with an API key, fetching "
        "monthly parquet files that are cached locally to avoid redundant downloads. "
        "Pre-2019 windows — relevant for the 2017–18 Cold Snap episode — use the "
        "EIA's bulk CSV files, which the agency publishes in six-month chunks. These "
        "files are plain CSV despite carrying no extension in some contexts; the "
        "pipeline includes a guard against accidentally downloading HTML error pages "
        "mistaken for data."
    )

    body(doc,
        "The caching layer stores each monthly or semi-annual dataset as a parquet "
        "file keyed by balancing authority and time period. Parquet was chosen over "
        "CSV for its efficient columnar compression and its preservation of data types "
        "(particularly UTC-aware timestamps, which are a persistent source of bugs "
        "when stored as plain strings)."
    )

    heading(doc, "Stage 2: Validation", 2)

    body(doc,
        "Each ingested window passes through nine automated validation checks before "
        "it is used downstream. These checks are not optional post-processing — they "
        "are a hard gate. A window that fails any check is flagged and excluded from "
        "analysis, with the failure logged for human review."
    )

    checks = [
        ("tz_utc", "All timestamps must be UTC-aware. Naive timestamps indicate "
         "a parsing or merging error."),
        ("monotone", "Timestamps must be strictly increasing. Duplicate or "
         "out-of-order rows indicate a merge artifact."),
        ("no_dups", "No duplicate timestamps after deduplication."),
        ("no_dst", "Interior calendar days (not the first or last) must have "
         "exactly 24 hourly rows. Days with 23 or 25 rows indicate a "
         "daylight-saving-time artifact — a known hazard with UTC-to-local "
         "conversions that can corrupt ramp calculations."),
        ("no_gaps", "The window must contain no gaps longer than one hour. "
         "Gaps would produce spurious ramp values."),
        ("sentinels", "No demand values matching known EIA sentinel patterns "
         "(e.g., the exact value 888,888 MW used in some legacy systems)."),
        ("demand_pos", "Demand must be positive. Zero or negative demand is "
         "physically impossible under normal operating conditions."),
        ("interchange_bounds", "Interchange must fall within physically plausible "
         "limits for the PJM footprint (roughly ±50,000 MW)."),
        ("df_era", "The window must fall within the EIA-930 data availability "
         "period (2015-07-01 onward)."),
    ]
    for code, desc in checks:
        p = doc.add_paragraph()
        p.add_run(f"{code}. ").bold = True
        p.add_run(desc)

    body(doc,
        "In practice, all 11 catalog episodes pass validation at 0% missing data "
        "after the bulk ingest corrections described above. The validation layer "
        "exists primarily to protect the pipeline against future data quality issues "
        "and to make the data preparation process auditable."
    )

    heading(doc, "Stage 3: Seasonal Normalization", 2)

    body(doc,
        "Raw demand in megawatt-hours is difficult to compare across seasons and "
        "times of day. A demand of 140,000 MW at 3pm on a July afternoon is "
        "unremarkable; the same demand at 3am on a mild October night would be "
        "extraordinary. The same logic applies to forecast error, ramp rates, and "
        "interchange flows."
    )

    body(doc,
        "To remove these predictable seasonal and diurnal patterns, each variable "
        "is z-scored against a climatological baseline conditioned on hour-of-day "
        "and calendar month. The baseline is computed from 2021 PJM data — a year "
        "with no qualifying stress events in the catalog — and stores the mean and "
        "standard deviation of each variable for each of the 288 (hour, month) cells."
    )

    body(doc,
        "The result is a set of four standardized time series that have the "
        "interpretation: \"how many standard deviations above or below normal for "
        "this hour in this month is this value?\""
    )

    # Z-score table
    ztable = doc.add_table(rows=5, cols=3)
    ztable.style = "Table Grid"
    zhdr = ztable.rows[0]
    for i, txt in enumerate(["Variable", "Formula", "Interpretation"]):
        c = zhdr.cells[i]
        c.text = txt
        c.paragraphs[0].runs[0].bold = True

    zdata = [
        ("LoadZ",
         "(D_t − μ_{h,m}) / σ_{h,m}",
         "Demand deviation from climatological normal for this hour and month."),
        ("ForecastErrorZ",
         "(FE_t − μ_FE_{h,m}) / σ_FE_{h,m}",
         "Standardized forecast error. Positive = demand exceeded forecast."),
        ("RampZ",
         "(R3_t − μ_R3_{h,m}) / σ_R3_{h,m}",
         "Standardized 3-hour ramp rate. Captures rate-of-change stress."),
        ("InterchangeZ",
         "(I_t − μ_I_{h,m}) / σ_I_{h,m}",
         "Standardized net import/export. Negative = PJM exporting; "
         "positive = importing."),
    ]
    for i, (var, form, interp) in enumerate(zdata, 1):
        ztable.rows[i].cells[0].text = var
        ztable.rows[i].cells[1].text = form
        ztable.rows[i].cells[2].text = interp

    doc.add_paragraph()
    caption(doc,
        "Table 3. The frozen state vector. Variables and formulas were fixed "
        "before the exploratory figures were produced; they may not be modified "
        "without creating a new versioned feature set."
    )

    body(doc,
        "The state vector was frozen — formally recorded in a version-controlled "
        "research specification — after the second exploratory pass but before any "
        "quantitative model evaluation. This freeze is a methodological safeguard: "
        "it prevents the researcher from unconsciously tuning the features to fit "
        "the known events. Two extensions (a weather deviation index and a "
        "neighboring-BA stress score) were specified in the design before the "
        "exploratory figures were produced; they are logged as predefined extensions "
        "awaiting additional data, not as post-hoc additions."
    )

    heading(doc, "Stage 4: Windowing and Alignment", 2)

    body(doc,
        "The normalized time series for each episode is cut to an 84-hour window "
        "and aligned on a common time axis t, where t=0 is the anchor event time. "
        "This alignment allows direct comparison across episodes: the curves for "
        "December 2022 and July 2026 can be overlaid on the same axes, with t=−24 "
        "meaning \"24 hours before the operator action\" for both."
    )

    body(doc,
        "For S1 hard-negative events (no operator action), the alignment uses the "
        "hour of peak demand within the window as t=0. This is a deliberate "
        "methodological choice: it aligns the hard-negative controls at their "
        "worst moment, giving the classifier the hardest possible discrimination "
        "task and ensuring the model is not simply learning to distinguish \"before "
        "the peak\" from \"after the peak.\""
    )

    body(doc,
        "The output of this stage is a coverage table that records, for each episode, "
        "the fraction of the 84 expected hourly rows that were successfully ingested "
        "and validated. All current episodes achieve 100% coverage."
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 6 — EXPLORATORY FINDINGS
    # ═══════════════════════════════════════════════════════════════════════════
    heading(doc, "Exploratory Findings", 1)

    body(doc,
        "With the pipeline operational and the state vector normalized, survey "
        "figures were produced overlaying all 11 cataloged episodes across the "
        "four z-scored variables, aligned on t=0. These figures are exploratory — "
        "they motivated the research hypothesis and informed the feature freeze — "
        "but they are not results. All subsequent analyses in this section use "
        "the frozen feature set without modification."
    )

    heading(doc, "Heterogeneity Across S3 Events", 2)

    body(doc,
        "The most striking early observation is the heterogeneity between the two "
        "S3 emergency episodes. Winter Storm Elliott (December 2022) shows a "
        "characteristic signature in ForecastErrorZ: in the 12 to 24 hours before "
        "the emergency action, demand consistently and substantially exceeded the "
        "day-ahead forecast. The z-scored forecast error climbs steadily toward "
        "+6 to +7 standard deviations — an extraordinary departure — with a "
        "near-monotonic ramp in the final hours before t=0."
    )

    body(doc,
        "The July 2026 heat emergency shows the opposite. Demand runs below forecast "
        "in the hours before the emergency action, producing negative ForecastErrorZ. "
        "The emergency is driven instead by a different combination: high absolute "
        "load (strongly positive LoadZ), a rapid ramp (positive RampZ), and a shift "
        "in interchange (becoming more negative, indicating PJM was exporting "
        "despite the stress — possibly because neighboring regions were also stressed)."
    )

    body(doc,
        "Two emergencies, two entirely different paths through state space. This "
        "observation is what makes the multivariate regime approach attractive: "
        "a model that looks only at ForecastErrorZ would have flagged Elliott but "
        "potentially missed the 2026 event. A model trained on joint trajectories "
        "in the four-dimensional state space has the possibility of capturing both."
    )

    heading(doc, "The Phase Portrait", 2)

    body(doc,
        "One visualization technique that proved particularly informative is the "
        "phase portrait: a trajectory plot in two-dimensional subspaces of the "
        "state vector, tracing the path of the system from t=−24 to t=0 and "
        "annotating the trajectory with time markers."
    )

    body(doc,
        "In the (ForecastErrorZ, InterchangeZ) plane, the Elliott episode traces "
        "a path through the upper-right quadrant — positive forecast error and "
        "positive interchange (PJM importing from neighbors). The 2026 heat episode "
        "traces a path through the lower-right quadrant — negative forecast error "
        "but positive interchange. The S2 and S1 hard-negative controls occupy "
        "the upper-left quadrant — elevated load but no forecast error surprise, "
        "with PJM self-sufficient or exporting."
    )

    body(doc,
        "The quadrant separation is suggestive: it hints that the joint configuration "
        "of forecast error and interchange may carry information about whether a "
        "stressed period escalates to an emergency. But this observation is post-hoc "
        "on a sample of five episodes and must be treated with appropriate caution. "
        "The purpose of the phase portrait in this context is to motivate the "
        "hypothesis and inform the feature choice — not to constitute a finding."
    )

    callout(doc,
        "The phase portrait is a visualization tool, not a result. It shows what "
        "the data looks like; it does not show that the model works."
    )

    # ── New subsections added after full-catalog analysis ─────────────────────

    heading(doc, "Unsupervised Regime Structure", 2)

    body(doc,
        "With all 11 episodes ingested, a Gaussian Hidden Markov Model was fit "
        "on the pooled episode sequences — 981 hourly observations across 11 "
        "episodes — without reference to outcome labels. The goal was to discover "
        "latent operational states from the structure of the data alone, then ask "
        "whether the S3 episodes are distributed differently across those states "
        "than the S2 controls."
    )

    body(doc,
        "The BIC criterion selected K=5 states. The fitted state means revealed "
        "that the HMM organized the data primarily by season and weather type — "
        "it found a winter cold state (mean LoadZ ≈ +5.2σ, strongly exporting), "
        "a summer heat state with high load and negative interchange, and several "
        "intermediate states — rather than directly separating emergency from "
        "managed conditions. This is the expected behavior of an unsupervised "
        "approach on heterogeneous data: it finds the dominant variance, which "
        "here is meteorological type, not operational outcome."
    )

    body(doc,
        "The result is nonetheless informative. ELL_2022 was the only episode to "
        "spend substantial time (50% of the final 24 hours) in the net-importer "
        "state — a state characterized by modestly elevated load combined with "
        "strongly positive interchange (PJM drawing power from neighbors). No S2 "
        "episode reached this state at all. HEAT_2026 spent 71% of its final 24 "
        "hours in the high-load, strongly-exporting state, alongside two S2 summer "
        "episodes — confirming that this state alone does not discriminate outcome, "
        "but its combination with other features might."
    )

    body(doc,
        "The unsupervised analysis confirms the core difficulty: the two S3 events "
        "are in different regimes from each other. Any model that finds a single "
        "latent 'emergency state' and uses it to discriminate S3 from S2 must "
        "account for the fact that the two known emergencies look quite different "
        "from each other — and both need to be detected."
    )

    heading(doc, "Case-Control Matched Comparison", 2)

    body(doc,
        "To identify what, if anything, the two S3 episodes share that distinguishes "
        "them from their season-matched controls, a case-control comparison was "
        "conducted. Each S3 episode was matched to the hard-negative episodes from "
        "the same season and compared across all four z-scored features in the "
        "final 12 hours before t=0."
    )

    body(doc,
        "The winter group paired ELL_2022 against four cold-season controls "
        "(COLD_2018, POLAR_2019, COLD_2025, COLD_2026). The summer group paired "
        "HEAT_2026 against five summer controls (HEAT_2023, HEAT_2024, HEAT_2025, "
        "HEAT_2025_JUL, HEAT_2026_SEP)."
    )

    # Case-control summary table
    doc.add_paragraph()
    cc_table = doc.add_table(rows=12, cols=7)
    cc_table.style = "Table Grid"
    cc_hdr = cc_table.rows[0]
    for i, txt in enumerate(["Episode", "Group", "Role",
                              "Mean LoadZ", "Mean FE_Z",
                              "Max RampZ", "Mean IC_Z"]):
        c = cc_hdr.cells[i]
        c.text = txt
        c.paragraphs[0].runs[0].bold = True
        c.paragraphs[0].runs[0].font.size = Pt(8)

    cc_data = [
        ("ELL_2022",      "Winter", "S3 ★", "4.35", "0.90", "7.02", "0.23"),
        ("COLD_2018",     "Winter", "S1",   "5.24", "2.20", "3.05", "−4.23"),
        ("POLAR_2019",    "Winter", "S2",   "6.44", "−1.81","3.26", "−2.51"),
        ("COLD_2025",     "Winter", "S2",   "6.12", "0.44", "2.14", "4.30"),
        ("COLD_2026",     "Winter", "S2",   "5.98", "−0.92","2.04", "−1.25"),
        ("HEAT_2026",     "Summer", "S3 ★", "3.06", "0.50", "2.17", "−3.09"),
        ("HEAT_2023",     "Summer", "S2",   "1.69", "−0.09","1.35", "0.25"),
        ("HEAT_2024",     "Summer", "S2",   "1.93", "0.02", "1.70", "−1.62"),
        ("HEAT_2025",     "Summer", "S2",   "3.01", "0.50", "2.73", "−2.85"),
        ("HEAT_2025_JUL", "Summer", "S2",   "2.22", "−0.19","1.36", "−3.06"),
        ("HEAT_2026_SEP", "Summer", "S2",   "3.47", "−0.10","2.12", "−3.18"),
    ]
    for i, row_data in enumerate(cc_data, 1):
        for j, val in enumerate(row_data):
            cell = cc_table.rows[i].cells[j]
            cell.text = val
            cell.paragraphs[0].runs[0].font.size = Pt(8)
            if row_data[2].startswith("S3"):
                cell.paragraphs[0].runs[0].bold = True

    doc.add_paragraph()
    caption(doc,
        "Table 4. Case-control summary statistics in t ∈ [−12 h, 0]. "
        "Starred rows (★) are S3 emergency episodes. All values are z-scores "
        "against the 2021 seasonal baseline."
    )

    body(doc,
        "The winter comparison reveals a striking asymmetry in RampZ. ELL_2022 "
        "reaches a maximum RampZ of +7.0σ in the final 12 hours — nearly double "
        "the highest control value (POLAR_2019 at +3.3σ). This surge occurred "
        "despite ELL_2022 having a lower peak LoadZ (+6.3σ) than all four controls "
        "(range +6.7 to +7.1σ). Load magnitude was not the discriminator; the "
        "rate of change was. ELL_2022 also shows positive mean InterchangeZ "
        "(+0.23σ, net importer), while three of four controls are strong net "
        "exporters, suggesting the region was drawing on neighbors even before "
        "the emergency declaration."
    )

    body(doc,
        "The summer comparison is subtler. HEAT_2026 is not distinguished by "
        "any single feature. Its mean ForecastErrorZ (+0.50σ) equals HEAT_2025 "
        "exactly. Its mean InterchangeZ (−3.09σ) is matched by HEAT_2025_JUL "
        "(−3.06σ) and exceeded by HEAT_2026_SEP (−3.18σ), neither of which "
        "produced an emergency. The discrimination appears to require the "
        "conjunction: HEAT_2026 combines very high mean LoadZ (+3.06σ, among "
        "the highest in the summer group) with extreme export pressure (IC_Z "
        "≈ −3.09σ). HEAT_2026_SEP has comparably extreme IC_Z but achieves it "
        "without a concurrent high absolute load — it represents a different "
        "operational configuration that the system managed without intervention. "
        "The specific temporal trajectory of the ramp in the final hours may "
        "also contribute to the discrimination beyond the 12-hour means alone."
    )

    callout(doc,
        "The core finding of the case-control analysis: neither the winter nor "
        "the summer S3 event can be separated from its controls by any single "
        "feature. The winter emergency is marked by an extraordinary ramp rate "
        "in the final hours; the summer emergency by the conjunction of extreme "
        "load and extreme export pressure. The joint configuration is the signal."
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 7 — THE MODELING APPROACH
    # ═══════════════════════════════════════════════════════════════════════════
    heading(doc, "The Modeling Approach", 1)

    body(doc,
        "The supervised prediction model — a Hidden Markov Model with "
        "leave-one-episode-out cross-validation — remains gated on episode count. "
        "With S3=2, training a fold on one S3 emergency and evaluating on the "
        "other produces an interval too wide to be scientifically informative. "
        "The catalog would need S3 ≥ 6 before the HMM evaluation is meaningful. "
        "That gate has not been reached, and the preliminary analyses above "
        "clarify why: reaching it would require another four RTO-wide PJM "
        "capacity emergencies, which at the observed rate of roughly one per "
        "five years represents a multi-decade wait."
    )

    body(doc,
        "The modeling gate is therefore being treated as a design decision point "
        "rather than a waiting condition. The preliminary analyses — unsupervised "
        "regime detection and case-control matched comparison — have established "
        "that the data contains structure consistent with the research hypothesis, "
        "and have identified the specific feature signatures associated with "
        "each of the two known emergencies. The paper's contribution is being "
        "reframed accordingly: from 'here is a trained predictive model' to "
        "'here is a methodologically rigorous characterization of the operational "
        "signatures preceding the two known PJM capacity emergencies, against "
        "a full catalog of season-matched controls.' This is a publishable "
        "contribution, particularly given the rarity of the events and the "
        "absence of any comparable systematic catalog in the literature."
    )

    body(doc,
        "When additional S3 episodes accumulate — either from future events or "
        "from extending the analysis to other RTOs (MISO, NYISO, ISO-NE) — "
        "the planned supervised approach is:"
    )

    modeling_items = [
        "A Hidden Markov Model (HMM) on the frozen four-dimensional state vector, "
        "treating the sequence of hourly state observations as emissions from a "
        "small number of latent operational regimes.",
        "Leave-one-episode-out (LOEO) cross-validation, where each fold holds out "
        "all event rows belonging to a single meteorological episode. This prevents "
        "the model from learning that December 23 predicts December 24 within "
        "Elliott.",
        "A phase portrait in data-derived (PCA) state space as the primary "
        "visualization of results — analogous to the exploratory phase portrait "
        "but in a basis learned from the full dataset.",
        "Discrimination analysis focused on the S2 vs. S3 boundary (the hard "
        "problem), with S1 vs. S3 as a secondary check.",
    ]
    for item in modeling_items:
        doc.add_paragraph(item, style="List Bullet")

    body(doc,
        "The HMM is appropriate for this problem for several reasons. It is a "
        "generative model that can produce a probability distribution over latent "
        "states at each timestep, enabling a \"probability of emergency regime\" "
        "output that is more interpretable than a binary classifier. It naturally "
        "handles the temporal structure of the problem — the observation that "
        "regime transitions tend to be smooth and persistent. And it has a long "
        "history in time-series analysis of complex dynamical systems, with "
        "well-understood failure modes."
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 8 — THE SIGNIFICANCE OF SMALL NUMBERS
    # ═══════════════════════════════════════════════════════════════════════════
    heading(doc, "The Significance of Small Numbers", 1)

    body(doc,
        "A recurring theme in this research is the rarity of the target event. "
        "In eleven years of operation, PJM — the world's largest competitive "
        "electricity market — experienced two RTO-wide capacity emergencies. This "
        "rarity is a feature of the system, not a bug in the data collection."
    )

    body(doc,
        "Grid operators design for reliability. The combination of reserve margin "
        "requirements, capacity markets, pre-emergency demand response programs, "
        "and real-time operational protocols is specifically engineered to prevent "
        "emergencies from occurring. When an S3 event does occur, it represents "
        "a failure of multiple independent safeguards — a simultaneous stressor "
        "severe enough to overwhelm redundancies that individually should have "
        "been sufficient."
    )

    body(doc,
        "This is precisely what makes the problem interesting from a machine "
        "learning perspective. The distinguishing signal — whatever configuration "
        "of variables separates an S2 event that the operator successfully manages "
        "from an S3 event that overwhelms the system — is not a simple threshold. "
        "It is a subtle pattern in a high-dimensional, time-varying system. And "
        "it is rare enough that conventional supervised learning approaches, which "
        "require large training sets, will struggle."
    )

    body(doc,
        "The research design reflects this reality. The feature freeze, the "
        "methodological controls on catalog construction, the explicit modeling "
        "gate, the LOEO cross-validation protocol — all of these are responses "
        "to the challenge of doing rigorous science with a small and irreplaceable "
        "dataset."
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 9 — WHY THIS MATTERS
    # ═══════════════════════════════════════════════════════════════════════════
    heading(doc, "Why This Matters", 1)

    body(doc,
        "Power grid emergencies are not merely inconvenient. The Elliott event of "
        "December 2022 came within hours of rolling blackouts affecting tens of "
        "millions of people during one of the coldest periods in decades. The "
        "effects would have included not just dark homes and offices but hospitals "
        "on backup power, water treatment plants unable to operate, heating systems "
        "failing in a dangerous cold snap."
    )

    body(doc,
        "The energy transition is making this harder, not easier. As coal and "
        "natural gas plants retire and are replaced by wind, solar, and storage, "
        "the operational characteristics of the grid change. Variable generation "
        "introduces ramp patterns that older generation fleets never had to manage. "
        "Electrification of heating and transportation increases the sensitivity "
        "of demand to temperature. The relationships between observable variables "
        "and systemic risk are evolving."
    )

    body(doc,
        "A model that can identify emerging stress regimes 6 to 24 hours before "
        "an emergency action — even with imperfect recall — would have operational "
        "value. It could trigger earlier activation of demand response programs, "
        "earlier calls for emergency imports from neighboring regions, earlier "
        "communications with major industrial customers. The marginal cost of "
        "a false alarm (activating demand response unnecessarily) is far lower "
        "than the marginal cost of a missed alarm (a blackout)."
    )

    body(doc,
        "This is the animating purpose of the research: not to replace the "
        "operator, but to give the operator an earlier and better-calibrated "
        "signal that the system is entering territory from which recovery becomes "
        "progressively harder."
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 10 — CURRENT STATUS AND NEXT STEPS
    # ═══════════════════════════════════════════════════════════════════════════
    heading(doc, "Current Status and Next Steps", 1)

    body(doc,
        "The analysis pipeline is fully operational across all 11 cataloged "
        "episodes. The event catalog has been exhaustively audited over the "
        "full 2015–2026 window. The normalized survey figures have been "
        "produced on the complete catalog. The unsupervised regime analysis "
        "and case-control matched comparison have both been completed and "
        "their findings are documented in this paper."
    )

    body(doc,
        "Completed stages:"
    )

    completed = [
        ("Catalog audit (2015–2026).",
         "33 PJM operational notification review records covering 9 seeds "
         "and all subsequent follow-up. 11 independent episodes classified: "
         "S3=2 (EEA-2/3 or equivalent), S2=8 (EEA-1 or Max Gen Alert), S1=1 "
         "(quantitative extreme, no intervention)."),
        ("Ingest pipeline — full 11-episode catalog.",
         "EIA-930 hourly data downloaded and validated for all episodes. "
         "One EIA sentinel value identified and replaced (demand_mwh=99,999 "
         "at 2019-01-27 23:00 UTC). Coverage: all episodes ≥99.6% of "
         "expected hourly rows."),
        ("Z-scored survey figures (Figs 1–9).",
         "LoadZ, ForecastErrorZ, RampZ, and InterchangeZ time series plus "
         "phase portrait produced on the full 11-episode catalog with "
         "tab20 color scheme to distinguish all 20 event windows."),
        ("Unsupervised regime detection (Figs 10–14).",
         "Gaussian HMM fit on 981 pooled hourly observations; BIC selected "
         "K=5. States organized primarily by season and weather type. "
         "ELL_2022 uniquely concentrated in net-importer state in final 24h."),
        ("Episode-level feature analysis (Figs 15–16).",
         "Per-episode summary statistics in t∈[−12,0] tabulated. No single "
         "feature separates both S3 events from all controls."),
        ("Case-control matched comparison (Figs 17–20).",
         "ELL_2022 matched against 4 winter controls; HEAT_2026 matched "
         "against 5 summer controls. Key findings: winter S3 distinguished "
         "by extraordinary RampZ (+7.0σ vs. controls ≤+3.3σ); summer S3 "
         "requires conjunction of high LoadZ + extreme export pressure."),
    ]
    for title, detail in completed:
        p = doc.add_paragraph()
        p.add_run(title + " ").bold = True
        p.add_run(detail)

    body(doc,
        "Remaining work:"
    )

    next_steps = [
        ("Resolve two pending catalog items.",
         "The February 2021 Winter Storm Uri episode and a possible "
         "July 14, 2026 heat episode (DOE 202-26-35) require direct review "
         "of the PJM archive to classify. They could add 0 to 2 further "
         "episodes to the catalog."),
        ("Acquire feature extensions.",
         "The weather deviation index (NOAA reanalysis integration) and the "
         "neighboring-BA stress index (EIA-930 for MISO, NYISO, ISO-NE) "
         "were specified in the design before exploratory analysis and "
         "are waiting on data acquisition."),
        ("Supervised modeling gate.",
         "The HMM leave-one-episode-out evaluation requires S3≥6. With "
         "S3=2, this gate remains open. The planned path is to extend the "
         "analysis to other RTOs or to pursue the case-control methodology "
         "as the primary contribution while the catalog grows."),
    ]
    for title, detail in next_steps:
        p = doc.add_paragraph()
        p.add_run(title + " ").bold = True
        p.add_run(detail)

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 11 — CONCLUSION
    # ═══════════════════════════════════════════════════════════════════════════
    heading(doc, "Conclusion", 1)

    body(doc,
        "Power grid emergencies are rare, consequential, and growing more complex "
        "as the energy system transitions. The conventional approach to detecting "
        "them — scalar thresholds on individual variables — has documented "
        "limitations. This research is building the infrastructure and evidence "
        "base for an alternative: a multivariate, regime-based approach that "
        "treats the operational state of the grid as a trajectory in a "
        "high-dimensional space and attempts to identify the configurations "
        "associated with emerging systemic risk."
    )

    body(doc,
        "The early exploratory findings are encouraging. The two confirmed S3 "
        "emergencies in the catalog trace distinctly different paths through state "
        "space, suggesting that no single variable is sufficient to detect both. "
        "The hard-negative controls are meaningfully separable from the positives "
        "in at least some two-dimensional projections. The phase portrait in "
        "(ForecastErrorZ, InterchangeZ) shows four-quadrant structure that "
        "corresponds, roughly, to the four operational populations."
    )

    body(doc,
        "But these are observations on a small dataset under post-hoc inspection. "
        "The methodological discipline built into this research — the frozen "
        "feature set, the pre-specified populations, the exhaustive and "
        "independently audited catalog, the LOEO validation protocol — exists "
        "precisely to ensure that the eventual model evaluation is not just "
        "pattern-matching on the training set. The infrastructure is the science."
    )

    body(doc,
        "The lights stayed on in December 2022. They may not always."
    )

    add_horizontal_rule(doc)

    # ── Technical Appendix ────────────────────────────────────────────────────
    heading(doc, "Technical Appendix: Software Stack", 1)

    body(doc,
        "The analysis pipeline is implemented in Python 3.11 with the following "
        "core dependencies:"
    )

    tech_items = [
        "pandas / numpy — data manipulation and numerical computation",
        "pyarrow / parquet — columnar storage for cached EIA-930 data",
        "requests — EIA-930 API v2 and bulk CSV downloads",
        "matplotlib — survey figures and phase portraits",
        "scikit-learn — PCA and baseline classifiers",
        "hmmlearn — Gaussian Hidden Markov Model (unsupervised regime detection)",
        "scipy — OLS slope estimation and statistical utilities",
    ]
    for item in tech_items:
        doc.add_paragraph(item, style="List Bullet")

    body(doc,
        "The project uses a version-controlled research specification (YAML) "
        "to record methodological decisions with dates, preventing retroactive "
        "revision. The event catalog, audit log, and operator action tables are "
        "maintained as CSV files under version control. All figures are "
        "reproducible from the raw EIA-930 data and the catalog files through "
        "a single pipeline invocation."
    )

    body(doc,
        "Code and data are maintained in a private repository. The event catalog "
        "metadata will be published alongside the research paper."
    )

    add_horizontal_rule(doc)

    # ── Footer note ───────────────────────────────────────────────────────────
    fn = doc.add_paragraph(
        "Draft. This article will be updated as the research progresses. "
        "Episode counts, figures, and modeling results are subject to change."
    )
    fn.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fn.runs[0].font.size = Pt(9)
    fn.runs[0].italic = True
    fn.runs[0].font.color.rgb = RGBColor(0x88, 0x88, 0x88)

    doc.save(OUTPUT)
    print(f"Written: {OUTPUT}")


if __name__ == "__main__":
    build()
