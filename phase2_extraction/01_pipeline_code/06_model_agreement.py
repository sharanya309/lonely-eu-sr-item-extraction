#!/usr/bin/env python3
"""
STEP 06 — per-model agreement vs the FINAL record (local, free, no model calls).

    python3 06_model_agreement.py

For every finalized paper (data/final/records/), compares each source against the
final answer:
    Gemini  (coder A)  — independent
    OpenAI  (coder B)  — independent
    Claude  (judge)    — the ARBITER: it authored the final for disputed papers, so
                         its agreement is high by construction (shown for completeness,
                         not as an independent validity measure). It only ran on the
                         papers that were routed to it.

Fields:
    population : total_n (exact), age_mean (±0.5), gender_%female (±2.0) on the primary sample
    scales     : overlap of scale keys with the final set (recall of final)
    items      : overlap of source-verified item set with the final set (recall of final)

Writes data/final/model_agreement.csv and prints a summary.
"""
import csv
import glob
import json
import os

import resolve
from common import FINAL, CODERS, banner, md_text, norm, num

RECORDS = FINAL / "records"
ADJ = FINAL / "adjudicated"


def rj(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def primary(doc):
    s = doc.get("samples") or []
    return next((x for x in s if x.get("is_primary")), s[0] if s else {})


def pop_match(field, fin, src, tol):
    a, b = num(fin.get(field)), num(src.get(field))
    if a is None:
        return None                      # final has no value -> not counted
    if b is None:
        return False                     # final has it, source missing -> disagree
    return abs(a - b) <= tol


def main():
    banner("06_model_agreement — each model vs the FINAL record")
    recs = sorted(glob.glob(str(RECORDS / "*.json")))
    if not recs:
        raise SystemExit("No final records — run 04_export.py first.")

    SOURCES = {"gemini": lambda pid: rj(CODERS / "gemini" / "results" / f"{pid}.json"),
               "openai": lambda pid: rj(CODERS / "openai" / "results" / f"{pid}.json"),
               "claude(judge)": lambda pid: rj(ADJ / f"{pid}.json")}
    POP = {"total_n": 0.0, "age_mean": 0.5, "gender_pct_female": 2.0}

    # accumulators: per source -> per field -> [hits, comparable]
    acc = {s: {f: [0, 0] for f in list(POP) + ["scales", "items"]} for s in SOURCES}
    n_papers = {s: 0 for s in SOURCES}

    for rp in recs:
        pid = os.path.basename(rp)[:-5]
        fin = rj(rp)
        if not fin:
            continue
        fp = primary(fin)
        ns = norm(md_text(pid))
        fin_items = {k for k in (resolve.item_key(it)
                     for sc in (fin.get("scales") or []) for it in (sc.get("items") or [])) if k}
        fin_scales = {resolve.scale_key(sc) for sc in (fin.get("scales") or []) if resolve.scale_key(sc)}
        for sname, load in SOURCES.items():
            sd = load(pid)
            if not sd:
                continue                 # source didn't run on this paper (e.g. claude on auto)
            n_papers[sname] += 1
            sp = primary(sd)
            for f, tol in POP.items():
                m = pop_match(f, fp, sp, tol)
                if m is not None:
                    acc[sname][f][1] += 1
                    acc[sname][f][0] += int(m)
            # scales
            if fin_scales:
                ss = {resolve.scale_key(sc) for sc in (sd.get("scales") or []) if resolve.scale_key(sc)}
                acc[sname]["scales"][1] += 1
                acc[sname]["scales"][0] += len(fin_scales & ss) / len(fin_scales)
            # items (verify the source's items against the paper, then overlap w/ final)
            if fin_items:
                si = resolve.verified_item_set(sd, ns)
                acc[sname]["items"][1] += 1
                acc[sname]["items"][0] += len(fin_items & si) / len(fin_items)

    fields = list(POP) + ["scales", "items"]
    rows = []
    print(f"\n  {'source':16}{'papers':>7}  " + "".join(f"{f:>16}" for f in fields))
    for s in SOURCES:
        cells = []
        for f in fields:
            hit, comp = acc[s][f]
            cells.append(round(100 * hit / comp, 1) if comp else None)
        rows.append({"source": s, "papers_compared": n_papers[s],
                     **{f + "_agree_pct": c for f, c in zip(fields, cells)}})
        print(f"  {s:16}{n_papers[s]:>7}  " + "".join(f"{(str(c)+'%'):>16}" for c in cells))

    with open(FINAL / "model_agreement.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["source", "papers_compared"]
                           + [x + "_agree_pct" for x in fields])
        w.writeheader(); w.writerows(rows)
    print(f"\n  population = % of papers whose value matches the final; "
          "scales/items = mean overlap (recall) with the final set.")
    print("  NOTE: Claude is the arbiter (authored the final for disputed papers), so its")
    print("        agreement is high by construction; Gemini/OpenAI are the independent ones.")
    print(f"\n  written: {FINAL / 'model_agreement.csv'}\n")


if __name__ == "__main__":
    main()
