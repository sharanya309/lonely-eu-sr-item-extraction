# LONELY-EU — Systematic Review Item Extraction

*Systematic review of social connection and loneliness instruments — technical report and the extraction/cleaning pipeline (code).*

This repository documents the **item-extraction** work carried out under the systematic review of social connection inventories project of LONELY-EU, a Horizon Europe project. Following a pre-registered search protocol, we screened roughly 80,000 records in ten languages and extracted measurement instruments from the included full-text articles using a reproducible, dual-model AI pipeline with source verification and human validation. For every instrument we captured item wording, response formats, subscales, use of validated instruments, and study/population metadata, then cleaned, de-duplicated, and organised the results into a single searchable item database — supporting data discovery, systematic assessment of measurement heterogeneity and cross-dataset comparability, and identification of substantive and geographic gaps in loneliness measurement.

**Read [`TECHNICAL_REPORT.md`](TECHNICAL_REPORT.md)**

## Links
- **Technical report / methodology (OSF):** https://osf.io/preprints/psyarxiv/6ueyd_v1
- **Systematic review pre-registration:** https://osf.io/preprints/psyarxiv/6ueyd_v1
- **Interactive explorer** (browse & filter instruments and items): https://lonelinessineurope.eu/lonely-eu-item-explorer

Part of the systematic review of social connection inventories (Paris et al., registered report), which will inform the EU Social Isolation & Loneliness (SIL) Index.

## Data availability
This repository ships the **code and documentation only** — the extracted questionnaire items and intermediate/output data files are **not** included. The full, searchable item database is publicly available through the [interactive explorer](https://lonelinessineurope.eu/lonely-eu-item-explorer), and the methodology and headline numbers are reported in [`TECHNICAL_REPORT.md`](TECHNICAL_REPORT.md) and on OSF. Running the pipelines below regenerates the outputs from source PDFs (not distributed here).

## What's here
| folder | contents |
|---|---|
| **[phase1_extraction/](phase1_extraction/)** | Single-model (Gemini 2.0 Flash) extraction, then the R cleaning/dedup funnel and RSF remapping. |
| ├ `01_extraction_code/` | `extract_items_final_improved.py` — extractor + embedded prompt |
| └ `02_cleaning_and_dedup_code/` | `00_merge_batches.R` → `01_item_cleaning_step1-4_and_dedup.R` → `02_remap_RSF_domains_onto_duplicates.R` |
| **[phase2_extraction/](phase2_extraction/)** | Dual-coder + adjudicator pipeline (pipeline of record). |
| ├ `01_pipeline_code/` | `00_ocr_v2`→`04_export`, `common`/`schema`/`resolve`, `run_append_v2`, checks (`06`, `07`) |
| └ `02_prompts/` | `extract.md`, `adjudicate.md` |
| **[PHASE2_ITEM_CODING_PREP/](PHASE2_ITEM_CODING_PREP/)** | `code/` that prepares Phase-2 items for RSF coding and remaps domains back afterwards. |
| [`DATABASE_SUMMARY.md`](DATABASE_SUMMARY.md), `database_summary_tables.csv`, `database_totals.py` | Combined totals, their definitions, and the script that computes them. |

## Replicating the pipeline
**Required to re-run Phase 2:** `00_ocr_v2`, `01_extract_v2`, `02_agreement`, `03_adjudicate`,
`04_export`, `common`, `schema`, `resolve` and both prompts. Setup is in
[`SETUP.md`](phase2_extraction/01_pipeline_code/SETUP.md).

**Checks and reporting (not needed to produce the data):** `06_model_agreement`, `07_verify`,
`05_costs`, `00_subsample` (pilot samples), `run_append_v2` (for adding papers to an existing
`master_flat.csv`) and `database_totals.py`.

**You will also need** your own source PDFs (not distributed here) and API keys. Model outputs
are not deterministic and hosted models change, so a re-run will be close to these results but
not identical. Phase-1 RSF coding was a separate pipeline and is not in this repository.

## Headline numbers
- **Phase 1:** 4,046 articles → 78,509 raw items → cleaned/deduped/filtered to
  **32,444 items · 2,734 scales · 2,260 articles**. Scale-deduplicated (all items kept):
  2,583 articles · 3,373 scales · 50,072 items.
- **Phase 2 (pipeline of record):** `master_flat.csv` = **3,892 articles · 53,600 item rows**
  (raw, not yet cleaned) — 2,288 new + 1,604 re-runs of Phase-1 articles.
- **Combined database:** **6,011 articles · 17,457 scales · 103,672 items**
  (see [`DATABASE_SUMMARY.md`](DATABASE_SUMMARY.md)).

## Notes
- Phase 2 added two rules for its final 253 papers: a 120-page OCR limit and a retry cap.
  The rest of the pipeline is unchanged (see `TECHNICAL_REPORT.md`, §2.4).
- Models — Phase 1: `gemini-2.0-flash`. Phase 2: `gemini-2.5-flash` + `gpt-5.4-mini`
  (coders) + `claude-haiku-4.5` (adjudicator); OCR `gemini-2.5-flash-lite`.
- API keys live in a local `.env` (not committed).
- Extracted-item data and pipeline outputs are not included — see **Data availability** above.
