#!/usr/bin/env python3
"""
STEP 02 — inter-coder agreement + deterministic item resolution (local, free).

    python3 02_agreement.py

Two independent coders (A=gemini, B=openai) extracted each paper. This step:
  1. Reports how much they AGREED, with metrics matched to each field type and
     robust to the messiness of extracted data (nulls, imbalance, formatting).
  2. Resolves scale items deterministically (verify against source text, then
     union) so item COUNT is never a spurious "disagreement".
  3. Routes only GENUINE scalar/structural disputes to the judge (step 03);
     everything else is auto-accepted for free.

Metrics (all pre-adjudication — this is reliability, not validity):
  categorical fields : Cohen's kappa + PABAK (prevalence-adjusted) + % agreement
  continuous fields  : ICC(A,1) absolute-agreement + mean abs difference + % within tol
  scale items        : Jaccard of source-verified item sets (honest recall)

Why PABAK and ICC (not just kappa and Pearson r):
  * Cohen's kappa collapses to 0 / undefined when a category is near-constant
    (the prevalence paradox — e.g. every paper is quality_flag=GOOD). PABAK is
    reported alongside so a paradoxically-low kappa can't be misread.
  * Pearson r measures correlation, not agreement (two coders can correlate
    perfectly while one systematically reads double). ICC(A,1) measures actual
    agreement; r is kept only as a secondary reference.

Reports (data/final/):
  agreement_report.csv    per-field metrics table (for your methods section)
  agreement_summary.txt   human-readable summary
  disagreements.csv       papers with a real dispute (fed to step 03)
  auto/<pid>.json         finalized records where coders agreed (union items merged)
"""
import csv
import json
import math
import statistics
from pathlib import Path

import resolve
import schema
from common import CODERS, FINAL, banner, log_event, md_text, norm, num, sub_papers, tee

AUTO = FINAL / "auto"
ADJ = FINAL / "adjudicated"

# ---- fields reported for reliability (includes formatting labels) -----------
CATEGORICAL = ["study_type", "age_format", "gender_format", "quality_flag"]
CONTINUOUS = ["total_n", "age_mean", "age_sd", "gender_pct_female"]
# absolute-difference tolerance for the "% within tolerance" report column
REPORT_TOL = {"total_n": 0.0, "age_mean": 0.05, "age_sd": 0.05, "gender_pct_female": 0.5}

# ---- fields that actually ROUTE a paper to the judge (lenient but honest) ----
# Formatting labels (age_format/gender_format) are NOT routed: they are cosmetic
# and the underlying numbers carry the real signal. Nulls abstain (see below).
ROUTE_CATEGORICAL = ["study_type", "quality_flag"]
ROUTE_TOL = {"total_n": 0.0, "age_mean": 0.5, "age_sd": 0.5, "gender_pct_female": 2.0}


def rj(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


def primary(doc):
    for s in doc.get("samples") or []:
        if s.get("is_primary"):
            return s
    return (doc.get("samples") or [{}])[0] if doc.get("samples") else {}


def flat(doc):
    p, s = doc.get("paper") or {}, primary(doc)
    q = doc.get("pdf_quality") or {}
    return {"study_type": p.get("study_type"), "age_format": s.get("age_format"),
            "gender_format": s.get("gender_format"), "quality_flag": q.get("quality_flag"),
            "total_n": s.get("total_n"), "age_mean": s.get("age_mean"),
            "age_sd": s.get("age_sd"), "gender_pct_female": s.get("gender_pct_female"),
            "n_samples": len(doc.get("samples") or [])}


# --------------------------------------------------------------- metrics
def pct_agreement(la, lb):
    n = len(la)
    return None if n == 0 else sum(1 for x, y in zip(la, lb) if x == y) / n


def cohen_kappa(a, b):
    """Standard Cohen's kappa for two raters, any number of categories."""
    cats = sorted(set(a) | set(b)); n = len(a)
    if n == 0:
        return None
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa = {c: a.count(c) / n for c in cats}; pb = {c: b.count(c) / n for c in cats}
    pe = sum(pa[c] * pb[c] for c in cats)
    return None if pe == 1 else (po - pe) / (1 - pe)


def pabak(a, b):
    """Prevalence-Adjusted Bias-Adjusted Kappa (Byrt et al.), generalised to q
    categories: (q*po - 1)/(q - 1). Stable under imbalance where Cohen's kappa
    paradoxically drops. If only one category is present, agreement is trivially
    perfect -> 1.0."""
    n = len(a)
    if n == 0:
        return None
    q = len(set(a) | set(b))
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    if q <= 1:
        return 1.0
    return (q * po - 1) / (q - 1)


def icc_a1(pairs):
    """ICC(A,1): two-way random effects, absolute agreement, single rater
    (McGraw & Wong). pairs = [(x, y), ...] with both values present. This is the
    correct agreement statistic for two continuous raters."""
    n = len(pairs)
    if n < 2:
        return None
    xs = [p[0] for p in pairs]; ys = [p[1] for p in pairs]
    k = 2
    grand = sum(xs + ys) / (k * n)
    row_means = [(x + y) / 2 for x, y in pairs]
    col_means = [sum(xs) / n, sum(ys) / n]
    ss_rows = k * sum((rm - grand) ** 2 for rm in row_means)     # between subjects
    ss_cols = n * sum((cm - grand) ** 2 for cm in col_means)     # between raters
    ss_err = 0.0
    for i, (x, y) in enumerate(pairs):
        for j, val in enumerate((x, y)):
            ss_err += (val - row_means[i] - col_means[j] + grand) ** 2
    msr = ss_rows / (n - 1)
    msc = ss_cols / (k - 1)
    mse = ss_err / ((n - 1) * (k - 1))
    denom = msr + (k - 1) * mse + k * (msc - mse) / n
    if denom == 0:
        return 1.0 if msr == mse else None      # all identical -> perfect agreement
    return (msr - mse) / denom


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs)); sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def interpret(k):
    if k is None:
        return "n/a"
    for thr, lab in [(0.81, "almost perfect"), (0.61, "substantial"),
                     (0.41, "moderate"), (0.21, "fair"), (0.0, "slight")]:
        if k >= thr:
            return lab
    return "poor (<0)"


# --------------------------------------------------------------- routing
def scalar_disputes(fa, fb):
    """Which fields send a paper to the judge. Lenient: formatting labels are not
    routed, and a one-sided null ABSTAINS (missing != conflicting) rather than
    counting as a disagreement. Sample-structure mismatch is routed directly."""
    bad = []
    if fa.get("n_samples") != fb.get("n_samples"):
        bad.append("n_samples")
    for f in ROUTE_CATEGORICAL:
        if str(fa[f]) != str(fb[f]):
            bad.append(f)
    for f, tol in ROUTE_TOL.items():
        x, y = num(fa[f]), num(fb[f])
        if x is None or y is None:        # one (or both) abstained -> not a conflict
            continue
        if abs(x - y) > tol:              # both gave a value AND they differ
            bad.append(f)
    return bad


def auto_record(a, b, merged_scales):
    """Scalars agree -> final record = richer base + union-verified items."""
    base = json.loads(json.dumps(a if len(a.get("scales") or []) >= len(b.get("scales") or []) else b))
    base["scales"] = merged_scales
    m = base.get("extraction_meta") or {}
    m.setdefault("extraction_confidence", "high")
    m.setdefault("confidence_reason", ""); m.setdefault("extraction_notes", "")
    m["needs_human_review"] = False; m["overruled_summary"] = ""
    base["extraction_meta"] = m; base["provenance"] = "auto_agreement"
    return schema.add_counts(base)


# --------------------------------------------------------------- main
def main():
    banner("02_agreement")
    log_event("02_agreement", "START")
    AUTO.mkdir(parents=True, exist_ok=True)
    FINAL.mkdir(parents=True, exist_ok=True)
    # A paper the judge has already ruled on (data/final/adjudicated/) is FINAL —
    # never rewritten here. Without this, a plain re-run could reclassify an
    # already-adjudicated paper as "auto" (its coder outputs can look like they
    # agree even after the judge corrected them), overwriting the judge's answer
    # with a lesser one and creating a paper that exists in both auto/ and
    # adjudicated/ (04_export silently prefers adjudicated/, but the duplicate is
    # confusing and the auto/ copy is stale). Wipe-and-rebuild is still safe for
    # AUTO because we never write an already-adjudicated pid back into it.
    already_adjudicated = {p.stem for p in ADJ.glob("*.json")} if ADJ.exists() else set()
    for old in AUTO.glob("*.json"):
        try:
            old.unlink()
        except OSError:
            pass

    # The two coders are PINNED (not alphabetical) so downstream A/B is stable.
    A, B = "gemini", "openai"
    have = {d.name for d in CODERS.iterdir() if (d / "results").exists()} if CODERS.exists() else set()
    if not ({A, B} <= have):
        log_event("02_agreement", "ABORT: need gemini AND openai results/")
        raise SystemExit("Need both coders (gemini, openai) under data/coders/*/results/")
    tee("02_agreement", f"  coders: {A} (A), {B} (B)")

    both, data, single = [], {}, []
    for pid in sorted(sub_papers()):
        da, db = rj(CODERS / A / "results" / f"{pid}.json"), rj(CODERS / B / "results" / f"{pid}.json")
        if da is not None and db is not None:
            both.append(pid); data[pid] = (da, db)
        elif da is not None or db is not None:
            single.append(pid)
    tee("02_agreement", f"  papers: {len(both)} with both coders, {len(single)} single-coder"
                        f" ({len(already_adjudicated)} already adjudicated -> locked, not re-routed)")

    # ---- per-paper: resolve items, collect recall stats, route disputes ----
    disagree, n_auto = {}, 0
    jac, fab_per_paper = [], []
    # corpus-level overlap accumulators (pooled across all papers), for items & scales:
    # inter = found by BOTH, union = found by EITHER, a/b = found by each coder.
    it_inter = it_union = it_a = it_b = 0
    sc_inter = sc_union = sc_a = sc_b = 0
    for pid in both:
        da, db = data[pid]
        ns = norm(md_text(pid))
        merged = resolve.resolve_items([da, db], ns)
        ka, kb = resolve.verified_item_set(da, ns), resolve.verified_item_set(db, ns)
        if ka or kb:
            jac.append(len(ka & kb) / len(ka | kb))
        it_inter += len(ka & kb); it_union += len(ka | kb); it_a += len(ka); it_b += len(kb)
        raw = sum(len(s.get("items") or []) for s in (da.get("scales") or [])) + \
            sum(len(s.get("items") or []) for s in (db.get("scales") or []))
        fab_per_paper.append(raw - len(ka) - len(kb))
        bad = scalar_disputes(flat(da), flat(db))
        # Also send CONTENT disagreements to the judge, not just scalar ones: the
        # coders' source-verified item sets or their scale sets differing. Item
        # agreement is inherently low, so this routes most papers — intended, since
        # the judge now resolves scale/subscale/item disputes too. To adjudicate
        # fewer papers, relax these two checks (e.g. only route when Jaccard < 0.8).
        if ka != kb:
            bad = bad + ["items"]
        ska = {resolve.scale_key(s) for s in (da.get("scales") or []) if resolve.scale_key(s)}
        skb = {resolve.scale_key(s) for s in (db.get("scales") or []) if resolve.scale_key(s)}
        sc_inter += len(ska & skb); sc_union += len(ska | skb); sc_a += len(ska); sc_b += len(skb)
        if ska != skb:
            bad = bad + ["scales"]
        # Reliability stats above (jac/it_*/sc_*) still cover EVERY both-coder
        # paper, adjudicated or not — that's pre-adjudication reliability for the
        # methods section and must reflect the whole corpus. Routing/writing below
        # is what must stop touching an already-adjudicated paper.
        if pid in already_adjudicated:
            continue
        if bad:
            disagree[pid] = bad
        else:
            (AUTO / f"{pid}.json").write_text(
                json.dumps(auto_record(da, db, merged), ensure_ascii=False, indent=2),
                encoding="utf-8")
            n_auto += 1
    for pid in single:
        if pid in already_adjudicated:
            continue
        disagree[pid] = ["single_coder"]

    # ---- reliability report ----
    report = []
    for f in CATEGORICAL:
        la = [str(flat(data[p][0])[f]) for p in both]
        lb = [str(flat(data[p][1])[f]) for p in both]
        k = cohen_kappa(la, lb); pk = pabak(la, lb); pa = pct_agreement(la, lb)
        report.append({"field": f, "type": "categorical", "n": len(both),
                       "pct_agreement": round(pa * 100, 1) if pa is not None else None,
                       "cohen_kappa": None if k is None else round(k, 3),
                       "pabak": None if pk is None else round(pk, 3),
                       "icc": "", "pearson_r": "", "mean_abs_diff": "",
                       "interpretation": interpret(k if k is not None else pk)})
    for f in CONTINUOUS:
        pairs, diffs, within, tot = [], [], 0, 0
        tol = REPORT_TOL[f]
        for p in both:
            x, y = num(flat(data[p][0])[f]), num(flat(data[p][1])[f])
            if x is None and y is None:
                continue
            tot += 1
            if x is not None and y is not None:
                pairs.append((x, y)); diffs.append(abs(x - y))
                if abs(x - y) <= tol:
                    within += 1
        icc = icc_a1(pairs); r = pearson([p[0] for p in pairs], [p[1] for p in pairs])
        report.append({"field": f, "type": "continuous", "n": tot,
                       "pct_agreement": round(within / tot * 100, 1) if tot else None,
                       "cohen_kappa": "", "pabak": "",
                       "icc": None if icc is None else round(icc, 3),
                       "pearson_r": None if r is None else round(r, 3),
                       "mean_abs_diff": round(sum(diffs) / len(diffs), 3) if diffs else None,
                       "interpretation": interpret(icc)})
    report.append({"field": "scale_items", "type": "item-set", "n": len(jac),
                   "pct_agreement": round(100 * sum(1 for j in jac if j >= 0.9) / len(jac), 1) if jac else None,
                   "cohen_kappa": "", "pabak": "", "icc": "", "pearson_r": "",
                   "mean_abs_diff": round(statistics.mean(jac), 3) if jac else None,
                   "interpretation": "jaccard(verified) in mean_abs_diff col"})

    # pooled corpus-level overlap (items & scales) -> methods table + summary.
    # Kept separate from `report` so the per-field table above stays clean.
    def pct(n, d):
        return round(100 * n / d, 1) if d else None
    pooled_rows = [{"field": fld, "type": "corpus-pooled", "n": d,
                    "pct_agreement": pct(n, d), "cohen_kappa": "", "pabak": "",
                    "icc": "", "pearson_r": "", "mean_abs_diff": "",
                    "interpretation": "pooled % of union found"}
                   for fld, n, d in [("item_overlap_both_pct", it_inter, it_union),
                                     (f"item_recall_{A}_pct", it_a, it_union),
                                     (f"item_recall_{B}_pct", it_b, it_union),
                                     ("scale_overlap_both_pct", sc_inter, sc_union),
                                     (f"scale_recall_{A}_pct", sc_a, sc_union),
                                     (f"scale_recall_{B}_pct", sc_b, sc_union)]]

    cols = ["field", "type", "n", "pct_agreement", "cohen_kappa", "pabak",
            "icc", "pearson_r", "mean_abs_diff", "interpretation"]
    with open(FINAL / "agreement_report.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader()
        for row in report + pooled_rows:
            w.writerow({k: ("" if row.get(k) is None else row.get(k, "")) for k in cols})
    with open(FINAL / "disagreements.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["paper_id", "n_fields", "fields"])
        for p in sorted(disagree):
            w.writerow([p, len(disagree[p]), ";".join(disagree[p])])

    # ---- summary ----
    fab_total = sum(fab_per_paper)
    lines = ["INTER-CODER AGREEMENT (pre-adjudication reliability)", "=" * 52,
             f"coders: {A}, {B}   papers (both): {len(both)}",
             f"{'field':<20}{'stat':<26}{'value':<8}{'interpretation'}"]
    for row in report:
        if row["type"] == "categorical":
            s = f"kappa={row['cohen_kappa']} pabak={row['pabak']}"
            v = f"agr={row['pct_agreement']}%"
        elif row["type"] == "continuous":
            s = f"ICC={row['icc']} r={row['pearson_r']}"
            v = f"MAD={row['mean_abs_diff']}"
        else:
            s = "jaccard(verified)"
            v = f"{row['mean_abs_diff']}"
        lines.append(f"{row['field']:<20}{s:<28}{str(v):<13}{row['interpretation'][:26]}")
    lines += ["",
              "EXTRACTION SIMILARITY (source-verified, pooled over all papers)",
              f"  items  : both coders captured {pct(it_inter, it_union)}% of all items found "
              f"({it_inter}/{it_union}); "
              f"{A} {pct(it_a, it_union)}%, {B} {pct(it_b, it_union)}% of the total each; "
              f"mean per-paper Jaccard {round(statistics.mean(jac), 3) if jac else None}",
              f"  scales : both coders captured {pct(sc_inter, sc_union)}% of all scales found "
              f"({sc_inter}/{sc_union}); "
              f"{A} {pct(sc_a, sc_union)}%, {B} {pct(sc_b, sc_union)}% of the total each",
              "  (read: each coder independently finds most of the same items/scales; the",
              "   gap is what verification cleans and the 3rd coder adjudicates.)",
              "",
              f"fabricated items removed by verification: {fab_total}",
              f"auto-accepted (coders agreed): {n_auto}",
              f"routed to judge (real dispute / single coder): {len(disagree)}",
              "NOTE: this is reliability (coder-vs-coder), NOT validity. For validity,",
              "score the adjudicated output against a human gold-standard subset."]
    (FINAL / "agreement_summary.txt").write_text("\n".join(lines))
    print("\n" + "\n".join(lines))
    log_event("02_agreement",
              f"DONE both={len(both)} auto={n_auto} disputes={len(disagree)} "
              f"fabricated_removed={fab_total}")
    print("\n  Next: python3 03_adjudicate.py submit\n")


if __name__ == "__main__":
    main()
