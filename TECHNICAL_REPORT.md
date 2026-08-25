# LONELY-EU Systematic Review of Social Connection Inventories: Item Extraction Technical Report

*Part of the pre-registered LONELY-EU Systematic Review of Social Connection Inventories
(Paris et al., registered report; see OSF — https://osf.io/preprints/psyarxiv/6ueyd_v1).
This report documents the **item-extraction** work only, aided by AI extraction pipelines,
the cleaning/deduplication, and the resulting database. The code for this work is provided
in this repository; the resulting item database is available through the interactive
explorer and OSF (see #4, Data availability).*

Last updated: 2026-08-25.

---

## 0. Corpus & screening (context)
A multilingual search across three databases in ten languages yielded ~80,000 records.
Two-phase screening (manual in Rayyan; active-learning in ASReview) screened 46,059
records and **included 9,032 articles** (37,027 excluded). Seven of the ten languages
yielded relevant articles. Full-text PDFs were then retrieved for the included set and
passed to item extraction. *(Screening details are in the project process log; this
report begins at item extraction.)*

Two extraction phases were run:
- **Phase 1** — a single-model (Gemini) pass on the PDFs available at the time.
- **Phase 2** — a redesigned, dual-model + adjudicator pipeline built for peer-review-grade
  reliability, now the pipeline of record.

---

## 1. PHASE 1 — single-model extraction (Gemini 2.0 Flash)

### 1.1 Method
- **Extractor:** `extract_items_final_improved.py` (Gemini 2.0 Flash via `google.generativeai`;
  PDF text via PyPDF2; structured-JSON prompt embedded in the script).
- **Output fields per item:** verbatim item text (original language + English translation),
  scale name, response format, subscale, a structural/functional/qualitative (RSF)
  classification, a social-connection relevance flag, per-item confidence, and
  article-level population information.
- PDFs with insufficient extractable text were flagged `not_readable`; API/JSON failures
  and low-confidence extractions were flagged for review.

### 1.2 Raw extraction
The initial run processed **4,046 articles**, yielding:

| | count |
|---|---:|
| articles | **4,046** |
| scales | **9,726** |
| raw items | **78,509** |

### 1.3 Cleaning & deduplication funnel
Performed by **`item cleaning.R`** (one canonical R script covering step-1→4 and both
deduplications; normalization is inline — `tolower(trimws())` + whitespace collapse to
build `scale_clean` / `item_clean` keys). Input = `merged_all_batches.csv` (produced by
`parallel_merge_updated.R`, which merges the 9 extraction batches).

| stage | what it does | articles | scales | items |
|---|---|---:|---:|---:|
| raw | — | 4,046 | 9,726 | 78,509 |
| **step-1** | drop `needs_review`, non-success extractions, missing English text (keeps high-confidence) | **2,665** | 3,423 | **53,864** |
| **step-2a** | global **scale** dedup (keep occurrence with most items; excludes generic "demographic/contextual" scales) | **2,583** | 3,373 | **50,072** |
| **step-2b** | cross-scale exact **item** dedup (keep first from largest scale) | 2,539 | — | **44,928** |
| **step-3** | filter to `measures_social_connection == "YES"` | 2,260 | 2,734 | **32,444** |
| **step-4** | final column selection | **2,260** | **2,734** | **32,444** |

**Phase-1 final dataset: 32,444 items across 2,734 scales, drawn from 2,260 articles.**
(Item and article counts reproduce exactly from the Phase-1 stage files; see §4, Data availability.)

### 1.4 Item coding (RSF domains) and remapping onto duplicates
The 32,444 final items were categorised into RSF domains via a separate multi-agent coding
pipeline (documented in the project process log; not part of this repository). The coded
output (`step4_final_with_categories.xlsx`, with an `assigned_category` column) was then
**remapped back onto the deduplicated items and scales** by
**`remapping duplicates.R`**: using the step-2a/step-2b mapping files, every exact-match
**item duplicate** and **scale duplicate** inherits the RSF domain of its retained
"queen" item. This recovers all original scales/items with a domain attached wherever an
exact match exists.

Recovering all scales/items and **de-duplicating only the scales** (items retained) gives
the same figures as step-2a:

| after scale-dedup (all items kept, RSF-tagged) | articles | scales | items |
|---|---:|---:|---:|
| | **2,583** | **3,373** | **50,072** |

> Note: **2,583** is the article count *after* scale-deduplication. 2,665 is the count
> *before* it (step-1). Reproduced by the `scales_deduped_all_items` stage output (see §4).

### 1.5 Articles set aside for re-running
Articles **removed at step-1 where nothing survived** (fully dropped, not carried forward)
= **1,596** — the re-run target for Phase 2. Articles that partially survived step-1 are
already represented in the Phase-1 dataset and are **not** counted here.

### 1.6 Phase-1 code (in `phase1_extraction/`)
| file | role |
|---|---|
| `01_extraction_code/extract_items_final_improved.py` | Gemini 2.0 Flash extractor + prompt |
| `02_cleaning_and_dedup_code/00_merge_batches.R` | merge extraction batches → `merged_all_batches.csv` |
| `02_cleaning_and_dedup_code/01_item_cleaning_step1-4_and_dedup.R` | **canonical** step-1→4 cleaning + scale/item dedup + normalization |
| `02_cleaning_and_dedup_code/02_remap_RSF_domains_onto_duplicates.R` | remap RSF domains onto all duplicate items/scales |

---

## 2. PHASE 2 — dual-model + adjudicator pipeline (pipeline of record)

### 2.1 Rationale & models
A single-model pass was judged insufficient for peer-review/public deposit. Phase 2 uses
**independent model redundancy**: candidate pairings were reliability-tested on 50- then
100-article batches, then the design was locked to:
- **Coder A:** `gemini-2.5-flash`  ·  **Coder B:** `gpt-5.4-mini`  (two independent extractions)
- **Adjudicator:** `claude-haiku-4.5`
- **OCR:** `gemini-2.5-flash-lite` (native-PDF vision → markdown).

### 2.2 Procedure
`OCR (00) → extract with both coders (01) → agreement/IRR (02) → adjudicate disagreements
(03) → export (04)`, all batch-based and resumable.
- **Source verification:** every extracted item is checked against the source text and
  retained only if genuinely present — hallucinated/misattributed items are discarded
  regardless of which model produced them (`resolve.py`).
- Records where both coders **agree** are accepted directly; **disagreements** on sample
  characteristics, study classification, or the scales/items are routed to the adjudicator,
  whose output passes the same source-verification check.
- `run_append.py` appends only new papers to `master_flat.csv` without rewriting existing rows.

### 2.3 Interim audit & correction
After ~1,300 articles, a Claude-Code audit of the intermediate outputs and export surfaced
two defects: (i) a handful of already-adjudicated articles could also appear in the
auto-agreement pool; (ii) the adjudicator could occasionally repeat an item within a scale
uncaught. Both were fixed **at the code level and applied retroactively to the existing
model outputs — no article was resubmitted, no new extraction performed.** After correction,
all **1,336** articles to that point were reconciled by exact match → **20,177 item rows
(17,631 with item text)**, with κ = .68–.76 / ICC ≥ .97 on scalar fields and 71.8% item /
62.0% scale overlap between coders before adjudication.

### 2.4 Operational variants (v2)
Two robustness tweaks were added and used for the later runs (documented in code; originals
kept intact for reporting):
- `00_ocr_v2.py` — auto-excludes PDFs **> 120 pages** from OCR (logged, never retried).
- `01_extract_v2.py` — **retry cap** (a paper failing a coder twice is skipped and logged),
  so unattended runs never hang.
- `run_append_v2.py` — same append logic, driving the v2 stage scripts.

### 2.5 Current Phase-2 output (`master_flat.csv`)
As of this report, the Phase-2 `master_flat.csv` (raw, pre-cleaning — the Phase-1 cleaning
funnel has **not** yet been applied to it):

| | count |
|---|---:|
| articles | **3,892** |
| item rows | **53,600** |
| scale instances (paper × scale) | 13,296 |
| — brand-new this phase (not in Phase-1) | 2,288 |
| — Phase-1 articles re-run | 1,604 |

Of the **1,596** re-run target (§1.5), **1,529** have been re-processed into Phase-2
`master_flat` (the remaining 67 are the >120-page / errored files the pipeline excludes).
The 1,604 Phase-1 articles in `master_flat` = those **1,529** plus **75** further Phase-1
articles that were also present in the re-run PDF pool.

*(The `master_flat.csv` data file is not deposited in this repository; the full item
database is available through the interactive explorer and OSF — see §4, Data availability.)*

### 2.6 Phase-2 code (in `phase2_extraction/01_pipeline_code/`)
`00_ocr.py`, `01_extract.py`, `02_agreement.py`, `03_adjudicate.py`, `04_export.py`,
`05_costs.py`, `06_model_agreement.py`, `07_verify.py`, plus shared modules `common.py`,
`schema.py`, `resolve.py`, and the driver `run_append.py`; v2 variants
`00_ocr_v2.py` / `01_extract_v2.py` / `run_append_v2.py`; helpers `00_subsample.py`,
`refresh_tables.py`, `scale_item_delta.py`; `README.md`, `SETUP.md`.
Prompts in `02_prompts/`: `extract.md` (coder prompt), `adjudicate.md` (adjudicator prompt).

---

## 3. Combined database totals (LOCKED)

The full item database across both phases (see `DATABASE_SUMMARY.md` for the derivation):

| | total |
|---|---:|
| **Articles** | **6,011** |
| **Scales** | **17,457** |
| **Items** | **103,672** |

By phase — Phase 1 (the 32,444 remapped to unique scales + all items): **4,189 scales /
50,072 items**; Phase 2 (`master_flat`): **13,295 scales / 53,600 items**. Item counts are
exact (item-bearing rows); scales include scale records with no items (10,147 of the 17,457
currently have ≥1 item). All 6,011 run articles map to these totals — Phase-1's remapped
32,444 set plus Phase-2's 45,598 items sent for coding (which remap back after coding).

**Masterlist coverage:** of the 8,852 unique master articles, **6,011 are done (run)** and
**2,841 pending** (6,011 + 2,841 = 8,852).

---

## 4. Reproducibility notes
- **Data availability:** this repository contains the **code and documentation only**. The
  extracted-item stage files and pipeline outputs (`03_key_outputs/`, `03_output/`, and the
  coding-prep `output/`) are **not** deposited here. The full, searchable item database is
  public through the interactive explorer (https://absl.shinyapps.io/lonely-eu-explorer/),
  and the headline totals are in `DATABASE_SUMMARY.md` and on OSF.
- **Phase-1 funnel** row counts (step1_cleaned / step2a / step2b / step3 / step4 =
  53,864 / 50,072 / 44,928 / 32,444 / 32,444) reproduce by re-running the cleaning code on the
  extraction output.
- **Scale counts** (3,423 / 3,373 / 2,734) follow the funnel's scale-occurrence definition
  in `item cleaning.R`; a stricter dedup-group definition yields slightly lower numbers —
  use the funnel definition for consistency.
- **Phase-2** master_flat regenerates from the pipeline code + PDFs (not deposited here).
- API keys are read from a local `.env` (not included). 

## 5. Repository map
```
lonely-eu-sr-item-extraction/         (code + documentation only — no extracted-data outputs)
├── TECHNICAL_REPORT.md              ← this file
├── DATABASE_SUMMARY.md              ← locked totals (6,011 / 17,457 / 103,672) + derivation
├── database_summary_tables.csv      ← the totals as a table
├── README.md                        ← navigation
├── phase1_extraction/
│   ├── 01_extraction_code/          Gemini extractor + prompt
│   └── 02_cleaning_and_dedup_code/  merge → step1-4 clean/dedup → RSF remap (R)
├── phase2_extraction/
│   ├── 01_pipeline_code/            dual-coder + adjudicator pipeline (+ v2)
│   └── 02_prompts/                  extract.md, adjudicate.md
└── PHASE2_ITEM_CODING_PREP/
    └── code/                        Phase-2 → item-coding prep + RSF remap
```
