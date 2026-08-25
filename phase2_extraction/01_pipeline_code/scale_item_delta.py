#!/usr/bin/env python3
"""
scale_item_delta.py  —  split the corpus into "old" vs "new" papers and report
scales + items for each slice, plus the total.

Split method: papers are ordered by their append order in data/ocr_usage.csv
(the order they were OCR'd). The first --old papers are treated as the previous
snapshot; everything after is "new this week".

Usage:
    python3 scale_item_delta.py                # default --old 1131
    python3 scale_item_delta.py --old 1131

Definitions:
    scale rows (reported) = rows in scales.csv with items_coverage != 'none'
    items                 = rows in items.csv (verified items)
    full-coverage scales  = scales.csv rows with items_coverage == 'full'
    full-coverage items   = total_items_in_scale summed over full-coverage scales

NOTE: scale COUNTS are post-dedup (cleaning done 2026-07-28). A pre-dedup number
reported earlier will not match exactly; item counts are stable.
"""
import csv, sys, os

BASE = os.path.dirname(os.path.abspath(__file__))
def rows(p):
    with open(os.path.join(BASE, p), newline='') as f:
        return list(csv.DictReader(f))
def num(r, c):
    try: return int(float(r[c] or 0))
    except: return 0

old_n = 1131
if '--old' in sys.argv:
    old_n = int(sys.argv[sys.argv.index('--old') + 1])

order = [r['paper_id'] for r in rows('data/ocr_usage.csv')]
old, new = set(order[:old_n]), set(order[old_n:])
sc, it = rows('data/final/scales.csv'), rows('data/final/items.csv')

def summarize(name, pset):
    S = [r for r in sc if r['paper_id'] in pset]
    reported = [r for r in S if (r['items_coverage'] or '').lower() != 'none']
    full = [r for r in S if (r['items_coverage'] or '').lower() == 'full']
    items = sum(1 for r in it if r['paper_id'] in pset)
    full_items = sum(num(r, 'total_items_in_scale') for r in full)
    print(f"\n[{name}]  papers={len(pset)}  papers_with_scales={len({r['paper_id'] for r in S})}")
    print(f"  reported scales (excl 'none') = {len(reported)}")
    print(f"  items (verified)              = {items}")
    print(f"  full-coverage scales          = {len(full)}")
    print(f"  full-coverage items           = {full_items}")

summarize(f"OLD (first {old_n})", old)
summarize(f"NEW (+{len(new)})", new)
summarize(f"TOTAL ({len(old | new)})", old | new)
