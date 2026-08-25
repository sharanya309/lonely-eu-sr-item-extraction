#!/usr/bin/env python3
"""
STEP 05 — cost ledger + full-corpus projection (optional, run anytime).

    python3 05_costs.py

Reads the token ledgers written by steps 01 and 03:
    data/coders/<coder>/usage.csv     extraction (per coder)
    data/final/adjudicate_usage.csv   judge
    data/final/disagreements.csv      how many papers needed the judge

Token counts are the providers' own numbers; RATE values in common.py are
list-price estimates — reconcile against your provider dashboards.
"""
import csv

from common import CODERS, DATA, FINAL, MODEL_ID, N_FULL, RATE, banner, log_event


def read(path):
    return list(csv.DictReader(open(path, encoding="utf-8"))) if path.exists() else []


def i(r, k):
    try:
        return int(float(r.get(k) or 0))
    except Exception:
        return 0


def main():
    rows, n_pilot = [], 0
    # 00 OCR (token-billed via RATE["ocr"])
    ocr = read(DATA / "ocr_usage.csv")
    if ocr:
        it, ot = sum(i(r, "in_tok") for r in ocr), sum(i(r, "out_tok") for r in ocr)
        c = it / 1e6 * RATE["ocr"]["in"] + ot / 1e6 * RATE["ocr"]["out"]
        rows.append(("00 ocr", MODEL_ID["ocr"], len(ocr), it, ot, c, 1.0))
    for coder in ("gemini", "openai"):
        u = [r for r in read(CODERS / coder / "usage.csv") if r.get("status") == "ok"]
        if not u:
            continue
        n_pilot = max(n_pilot, len(u))
        it, ot = sum(i(r, "in_tok") for r in u), sum(i(r, "out_tok") for r in u)
        c = it / 1e6 * RATE[coder]["in"] + ot / 1e6 * RATE[coder]["out"]
        rows.append((f"01 extract ({coder})", MODEL_ID[coder], len(u), it, ot, c, 1.0))

    # judge only fires on the disagreeing fraction
    dis = read(FINAL / "disagreements.csv")
    both_n = n_pilot
    judge_frac = (len(dis) / both_n) if both_n else 0.0
    ju = [r for r in read(FINAL / "adjudicate_usage.csv") if r.get("status") == "ok"]
    if ju:
        it, ot = sum(i(r, "in_tok") for r in ju), sum(i(r, "out_tok") for r in ju)
        c = it / 1e6 * RATE["judge"]["in"] + ot / 1e6 * RATE["judge"]["out"]
        rows.append(("03 adjudicate", MODEL_ID["judge"], len(ju), it, ot, c, judge_frac))

    if not rows:
        raise SystemExit("No usage yet — run 01 (and 03) first.")

    banner("05_costs")
    print(f"  {'stage':22s}{'model':26s}{'n':>5s}{'in_tok':>12s}{'out_tok':>11s}{'$':>9s}")
    print("  " + "-" * 86)
    tot = proj = 0.0
    for stage, model, n, it, ot, c, frac in rows:
        tot += c
        per = c / max(n, 1)
        proj += per * N_FULL * frac          # judge scales by disagreement fraction
        print(f"  {stage:22s}{model[:26]:26s}{n:>5d}{it:>12,d}{ot:>11,d}{c:>9.3f}")
    print("  " + "-" * 86)
    print(f"  pilot total: ${tot:.3f}   ({n_pilot} papers)")
    if ju:
        print(f"  judge fired on {len(dis)}/{both_n} papers ({judge_frac*100:.0f}%)")
    print(f"  projection to {N_FULL} papers: ~${proj:.2f}")
    print(f"  (batch prices, 50% off list; reconcile with provider dashboards.)\n")

    # final cost table for reporting
    FINAL.mkdir(parents=True, exist_ok=True)
    with open(FINAL / "cost_ledger.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["stage", "model", "n_papers", "in_tok", "out_tok", "cost_usd"])
        for stage, model, n, it, ot, c, frac in rows:
            w.writerow([stage, model, n, it, ot, round(c, 4)])
        w.writerow(["TOTAL", "", "", "", "", round(tot, 4)])
    print(f"  cost ledger written: {FINAL / 'cost_ledger.csv'}\n")
    log_event("05_costs", f"total=${tot:.3f} n_pilot={n_pilot} "
                          f"projection_{N_FULL}=${proj:.2f}")


if __name__ == "__main__":
    main()
