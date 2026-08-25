#!/usr/bin/env python3
"""Shared paths + the ONE normalization used for all exact-match de-duplication.
Keep normalization identical everywhere so scale/item matching is consistent and
fully reversible."""
import os, re, unicodedata

BASE = "/Users/sharanyamosalakanti/Documents/SysReview"
PREP = os.path.join(BASE, "CLAUDE_WORKSPACE/PHASE2_ITEM_CODING_PREP")
OUT  = os.path.join(PREP, "output")

# Phase-2 raw extraction (the new corpus to prepare for coding)
MASTER_FLAT = os.path.join(BASE, "pipeline_final_v3 final/data/final/master_flat.csv")
# The already-CODED Phase-1 set (32,444 items, each with an RSF domain = 'final_coding')
CODED_32444 = os.path.join(BASE, "social connection results/Step 3/confirmatory_Step3_finished.xlsx")
#   columns: Item | gemini | openai | mistralai | deepseek | anthropic | final_coding | country | questionnaire
# The Phase-1 final 32,444 WITH both item_text_original and item_text_english (to match
# non-English Phase-2 items on their ORIGINAL text as well as English).
STEP4_FINAL = os.path.join(BASE, "CLAUDE_WORKSPACE/04_reference_copies/step4_final.xlsx")

def norm(s):
    """Exact-match key: lowercase, trim, collapse internal whitespace. NFC unicode.
    (Same spirit as the Phase-1 R cleaning: tolower(trimws()) + whitespace collapse.)"""
    s = unicodedata.normalize("NFC", str(s) if s is not None else "")
    return re.sub(r"\s+", " ", s.strip().lower())

def item_key(english, original=""):
    """Item identity for de-dup: prefer English text (coding was done on English);
    fall back to original if English is blank."""
    e = norm(english)
    return e if e else norm(original)
