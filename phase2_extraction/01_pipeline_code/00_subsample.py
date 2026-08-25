#!/usr/bin/env python3
"""
STEP 00 — reproducible pilot from EXISTING markdowns. Touches nothing in
data/markdown; only writes data/subsample.csv.

    python3 00_subsample.py            # 100 papers (default)
    python3 00_subsample.py --n 80     # a different size

Sampling 100 of your ~200 markdowns. To run the WHOLE corpus instead, skip
this step — 01_extract.py falls back to all "ok" papers when no subsample
exists.

Triage on the markdown itself:
    < 2,000 chars                      -> thin      (likely cover page / failed OCR)
    no digits and no '%' anywhere      -> odd       (no stats reported?)
    otherwise                          -> eligible

Sampling is stratified by length tercile so the pilot sees short, medium and
long papers — cost projections then transfer honestly to the full corpus.
"""
import csv
import random
import statistics
import sys

from common import SUBSAMPLE, banner, ok_papers, read_log

SEED = 42
N = 100


def main():
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else N
    log = read_log()
    rows = []
    for pid, p in sorted(ok_papers().items()):
        if not p.exists():
            continue
        t = p.read_text(encoding="utf-8")
        st = "eligible"
        if len(t) < 2000:
            st = "thin"
        elif not any(c.isdigit() for c in t):
            st = "odd"
        rows.append({"paper_id": pid, "filename": log[pid]["filename"],
                     "chars": len(t), "token_est": len(t) // 4, "triage": st})

    elig = [r for r in rows if r["triage"] == "eligible"]
    if len(elig) < n:
        sys.exit(f"FATAL: only {len(elig)} eligible markdowns, wanted {n}.")

    elig.sort(key=lambda r: r["chars"])
    k = len(elig) // 3
    terciles = [elig[:k], elig[k:2 * k], elig[2 * k:]]
    rng = random.Random(SEED)
    per = [n // 3, n // 3, n - 2 * (n // 3)]
    pick = []
    for t, m in zip(terciles, per):
        pick += rng.sample(t, min(m, len(t)))
    pick.sort(key=lambda r: r["paper_id"])

    with open(SUBSAMPLE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["paper_id", "filename", "chars",
                                          "token_est", "triage"])
        w.writeheader()
        w.writerows(pick)

    tok = sum(r["token_est"] for r in pick)
    banner("00_subsample")
    print(f"  markdowns scanned : {len(rows)}  (eligible {len(elig)}, "
          f"thin {sum(r['triage']=='thin' for r in rows)}, "
          f"odd {sum(r['triage']=='odd' for r in rows)})")
    print(f"  pilot             : {len(pick)} papers, seed {SEED}, "
          f"stratified by length")
    print(f"  tokens (est)      : {tok:,}  median/paper "
          f"{statistics.median(r['token_est'] for r in pick):,.0f}")
    print(f"  written           : {SUBSAMPLE}")
    print(f"\n  Next: python3 01_extract.py\n")


if __name__ == "__main__":
    main()
