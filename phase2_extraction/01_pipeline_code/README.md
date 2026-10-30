# Extraction pipeline — clean, run in order

Run the steps one at a time in the terminal; each tells you the next. Model calls
go through provider Batch APIs, and every step is **resumable**, so an interruption
or a re-run never bills you twice.

```bash
cd this-folder
source .venv/bin/activate        # see SETUP.md (google-genai, openai, anthropic)
```

## The steps

Everything that calls a model is **BATCH ONLY** (50% cheaper). Batch is async:
`submit` → `status` (poll until done) → `retrieve`. All resumable.

| # | command | what it does |
|---|---------|--------------|
| 00a | `python3 00_ocr_v2.py submit --src <pdf-folder> --n 200` → `status` → `retrieve` | PDFs → markdown via Gemini (`gemini-2.5-flash-lite`) batch OCR, **tables inlined** |
| 0 | `python3 00_subsample.py --n 100` | pick a reproducible pilot (skip for the full corpus) |
| 1 | `python3 01_extract_v2.py submit` → `status` → `retrieve` | two coders (Gemini + OpenAI) extract, batch |
| 2 | `python3 02_agreement.py` | inter-rater κ; verify+union items; auto-accept agreers; route disputes — scalar AND scale/item — to the judge (local, instant) |
| 3 | `python3 03_adjudicate.py submit` → `status` → `retrieve` | Claude judges the disagreeing papers: resolves scalars **and** scales/subscales/items (items it returns are re-verified against the source) |
| 4 | `python3 04_export.py` | master/samples/scales/items CSVs (local) |
| 5 | `python3 05_costs.py` | cost ledger for reporting (local) |
| 6 | `python3 06_model_agreement.py` | each model scored against the final record (local) |
| 7 | `python3 07_verify.py` | independent audit: every paper has exactly one record, master_flat matches the records exactly, no auto/adjudicated overlap, no duplicate items (local, free) — run after every 04_export |

Typical loop per model stage:
```bash
python3 01_extract_v2.py submit      # send
python3 01_extract_v2.py status      # check every few min until "done"
python3 01_extract_v2.py retrieve    # pull results
```

## Always smoke-test first (a few cents)

Because batch is all-or-nothing per submit, smoke-test by sampling a tiny set first:

```bash
python3 00_ocr_v2.py submit --src <pdf-folder> --n 2   # then status -> retrieve; eyeball one .md
python3 00_subsample.py --n 3                        # 3-paper pilot
python3 01_extract_v2.py submit                         # then status -> retrieve
python3 02_agreement.py
python3 03_adjudicate.py submit                      # then status -> retrieve
python3 04_export.py
```

If that looks right, re-sample `--n 100` and run the full thing.

## What each step writes

- `data/coders/{gemini,openai}/results/<pid>.json` — raw per-coder extractions
- `data/final/agreement_report.csv` — **your IRR table for the methods section**
- `data/final/disagreements.csv` — which papers/fields disagreed
- `data/final/auto/<pid>.json` — finalized records where coders agreed (free)
- `data/final/adjudicated/<pid>.json` — judge's final records for disagreements
- `data/final/records/`, `master_flat.csv`, `samples.csv`, `scales.csv`,
  `items.csv` — the export

## How items are handled (the disagreement fix)

Item extraction was the biggest source of coder disagreement, and we traced it
to fabrication — a model reconstructing a famous scale's items from memory when
they weren't printed. `resolve.py` fixes this deterministically (no model call):

1. **Verify** every extracted item against the paper text; drop the ones that
   aren't there (this removed ~545 fabricated items in the pilot).
2. **Union** the two coders' verified items — each is proven real, so the merged
   set maximises recall. Subscale names are unioned the same way, and items are
   matched across coders on their **original-language** text, so a
   translated-vs-untranslated copy of the same item no longer double-counts.

When the coders AGREE (scalars and scale/item sets), that verified union is the
final record — free, no model call. When they DISAGREE on anything — scalars OR
scale/subscale/item content — the paper goes to the judge (step 03). The judge
reads the paper and both coders and returns the corrected record, **including
scales/subscales/items**. Crucially, every item the judge returns is re-checked
against the source afterwards (`resolve.prune_record`), so it can restructure and
re-attribute items but can never reintroduce a fabricated one; if it truncates on
a huge paper, items fall back to the verified union so nothing is lost.

`agreement_report.csv` reports item overlap (Jaccard) for the two coders, and
`master_flat.csv`'s `item_both_coders` column flags the consensus subset for
robustness analyses.

## Reading the local markdowns efficiently

`01_extract_v2.py` calls `trim_md()` (in `common.py`), which drops the
references/bibliography before sending — saving ~10–20% input tokens per paper
while keeping appendices (where items live). Nothing else re-reads the files.

## Money

- Everything is **resumable**: `01` and `03` skip papers already done, so re-runs
  are free. Interrupt with Ctrl-C anytime.
- Rates in `common.py:RATE` are **batch prices**. Run `05_costs.py` after the pilot
  for a real projection.

## Tuning (one place each)

- **Which models** → `common.py:MODEL_ID`
- **How strict "agreement" is** (how many papers reach the judge) →
  `02_agreement.py:ROUTE_TOL`. Loosen `total_items_extracted` if you don't want
  every item-count difference adjudicated.
- **Judge instructions** → `../02_prompts/adjudicate.md`
- **Schema / field rules** → `schema.py`

## Appending new papers (how the later runs were done)

`run_append_v2.py` runs steps 00–03 unattended, then appends only the new papers to
`master_flat.csv` without rewriting existing rows (`04_export.py` does a full rebuild).

## The two rules (why the scripts are called `_v2`)

Repeated failures while processing the remaining papers led us to add two rules, used
for the final 253 papers:

1. **Page limit** (`00_ocr_v2.py`): PDFs over 120 pages are excluded from OCR and logged.
2. **Retry cap** (`01_extract_v2.py`): a paper is skipped and logged after 2 failed attempts.

These are the only additions; the rest of the pipeline is unchanged. The first 3,639
papers ran without these rules and were not re-filtered afterwards (see
`TECHNICAL_REPORT.md`, §2.4).

## To force a clean rebuild

Delete `data/final/` (keeps coder outputs) and re-run from step 2, or delete
`data/coders/` too and re-run from step 1.
