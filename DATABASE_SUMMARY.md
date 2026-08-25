# Database summary — LOCKED totals

*The full LONELY-EU item database across both phases. Reproduces from
`CLAUDE_WORKSPACE/FINAL_COUNT/database_totals.py`.*

## LOCKED TOTALS
| | total |
|---|---:|
| **Articles** | **6,011** |
| **Scales** | **17,457** |
| **Items** | **103,672** |

All 6,011 articles run from the 8.8k masterlist map to these scales and items.
Articles with no scales, and scales with no items, are included in the counts; the **item
count is exact** (item-bearing rows). Of the 17,457 scales, 10,147 have ≥1 item.

## By phase
| phase | scales | items |
|---|---:|---:|
| **Phase 1** — 32,444 coded → remapped to unique scales + all items | 4,189 | 50,072 |
| **Phase 2** — `master_flat`; 45,598 items sent for coding → remap back | 13,295 | 53,600 |
| **Combined** | **17,457** | **103,672** |

## Masterlist coverage
| | articles |
|---|---:|
| Master (8.8k, unique) | 8,852 |
| — **done (run)** | **6,011** |
| — pending | 2,841 |

`6,011 + 2,841 = 8,852` — every master article is either done or pending.

## Flow (in order)
1. **Phase 1** ran 4,046 articles → 78,509 raw items → cleaned/deduped/filtered to the
   **32,444** social-connection items (2,734 scales, 2,260 articles) → RSF-coded → remapped
   onto all original scales + exact-match items → **4,189 scales / 50,072 items**.
2. **Phase 2** (`master_flat`) added the re-run + new articles → **13,295 scales / 53,600
   items**; **45,598** de-duplicated new items sent for Item Coding, then remapped back so
   every Phase-2 item carries an RSF domain.
3. **Combined database: 6,011 articles · 17,457 scales · 103,672 items.**

*Source files:* `26 May_rerun/merged_all_batches.csv`, `step2a_deduplicated_scales.xlsx`,
`pipeline_final_v3 final/data/final/master_flat.csv`.
