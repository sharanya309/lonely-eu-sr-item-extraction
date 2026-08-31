# LONELY-EU — Systematic Review Item Extraction

*Systematic review of social connection and loneliness instruments — technical report and the extraction/cleaning pipeline (code).*

This repository documents the **item-extraction** work carried out under the systematic review of social connection inventories project of LONELY-EU, a Horizon Europe project. Following a pre-registered search protocol, we screened roughly 80,000 records in ten languages and extracted measurement instruments from the included full-text articles using a reproducible, dual-model AI pipeline with source verification and human validation. For every instrument we captured item wording, response formats, subscales, use of validated instruments, and study/population metadata, then cleaned, de-duplicated, and organised the results into a single searchable item database — supporting data discovery, systematic assessment of measurement heterogeneity and cross-dataset comparability, and identification of substantive and geographic gaps in loneliness measurement.

**Read [`TECHNICAL_REPORT.md`](TECHNICAL_REPORT.md)**

## Links
- **Technical report / methodology (OSF):** https://osf.io/preprints/psyarxiv/6ueyd_v1
- **Systematic review pre-registration:** https://osf.io/preprints/psyarxiv/6ueyd_v1
- **Interactive explorer** (browse & filter instruments and items): [https://absl.shinyapps.io/lonely-eu-explorer/](https://lonelinessineurope.eu/lonely-eu-item-explorer)

Part of the systematic review of social connection inventories (Paris et al., registered report), which will inform the EU Social Isolation & Loneliness (SIL) Index.

## Data availability
This repository ships the **code and documentation only** — the extracted questionnaire items and intermediate/output data files are **not** included. The full, searchable item database is publicly available through the interactive explorer ([https://absl.shinyapps.io/lonely-eu-explorer/](https://lonelinessineurope.eu/lonely-eu-item-explorer)), and the methodology and headline numbers are reported in [`TECHNICAL_REPORT.md`](TECHNICAL_REPORT.md) and on OSF. Running the pipelines below regenerates the outputs from source PDFs (not distributed here).

## What's here
| folder | contents |
|---|---|
| **[phase1_extraction/](phase1_extraction/)** | Single-model (Gemini 2.0 Flash) extraction, then the R cleaning/dedup funnel and RSF remapping. |
| ├ `01_extraction_code/` | `extract_items_final_improved.py` — extractor + embedded prompt |
| └ `02_cleaning_and_dedup_code/` | `00_merge_batches.R` → `01_item_cleaning_step1-4_and_dedup.R` → `02_remap_RSF_domains_onto_duplicates.R` |
| **[phase2_extraction/](phase2_extraction/)** | Dual-coder + adjudicator pipeline (pipeline of record). |
| ├ `01_pipeline_code/` | `00_ocr`→`04_export`, `common`/`schema`/`resolve`, `run_append` (+ `*_v2`) |
| └ `02_prompts/` | `extract.md`, `adjudicate.md` |
| **[PHASE2_ITEM_CODING_PREP/](PHASE2_ITEM_CODING_PREP/)** | `code/` that prepares Phase-2 items for RSF coding and remaps domains back afterwards. |

## Headline numbers
- **Phase 1:** 4,046 articles → 78,509 raw items → cleaned/deduped/filtered to
  **32,444 items · 2,734 scales · 2,260 articles**. Scale-deduplicated (all items kept):
  2,583 articles · 3,373 scales · 50,072 items.
- **Phase 2 (pipeline of record):** `master_flat.csv` = **3,892 articles · 53,600 item rows**
  (raw, not yet cleaned) — 2,288 new + 1,604 re-runs of Phase-1 articles.

## Notes
- Models — Phase 1: `gemini-2.0-flash`. Phase 2: `gemini-2.5-flash` + `gpt-5.4-mini`
  (coders) + `claude-haiku-4.5` (adjudicator); OCR `gemini-2.5-flash-lite`.
- API keys live in a local `.env` (not committed).
- Extracted-item data and pipeline outputs are not included — see **Data availability** above.
