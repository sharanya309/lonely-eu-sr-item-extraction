# Phase-2 → Item Coding prep

Prepares the Phase-2 `master_flat` items for Item Coding: removes items already coded
(so we don't re-code them) and internal exact duplicates, produces the coding list, and
(after coding) re-maps RSF domains back onto **every** item.

**De-dup method: item-level EXACT match only** (case/whitespace-insensitive). We deliberately
do NOT collapse scales by name — that would drop distinct same-named-scale variants
(different languages/versions) and leave them with no RSF domain.

## Pipeline
| step | script | in → out |
|---|---|---|
| 1 | `code/01_dedup_items.py` | master_flat + coded-32,444 → `01_new_items.csv`, `item_disposition.csv` |
| 2 | `code/02_make_coding_list.py` | `01_new_items.csv` → **`items_for_coding.csv/.xlsx`** (6 cols) |
| 3 | `code/03_remap_rsf_after_coding.py` | *(run AFTER coding)* coding output + `item_disposition.csv` → `master_flat_with_rsf.csv` |

`code/common_paths.py` holds paths + the single `norm()` used everywhere.

## Inputs
- Phase-2: `pipeline_final_v3 final/data/final/master_flat.csv`
- Already-coded Phase-1 set (RSF domains): `social connection results/Step 3/confirmatory_Step3_finished.xlsx`
  (`Item` = item text, `final_coding` = RSF domain).

## Coding-list columns
`title, country_study, scale_name, subscale, item_text_original, item_text_english`

## Re-map guarantee
`item_disposition.csv` records every item row as `new` / `already_coded` / `internal_dup`,
so after coding, step 3 assigns an RSF domain to 100% of items:
new → from the coding output; already_coded → inherited from the 32,444; internal_dup →
inherited from its kept twin.

## Run
```bash
python3 code/01_dedup_items.py
python3 code/02_make_coding_list.py
# ...after Item Coding returns domains for the new items:
python3 code/03_remap_rsf_after_coding.py --coded <coding_output.csv>
```
