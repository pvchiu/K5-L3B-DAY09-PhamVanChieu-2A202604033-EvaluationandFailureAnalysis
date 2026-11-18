"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []

    # 1. Any metric value in pr["metrics"] that is NaN or inf
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, (int, float)) and (math.isnan(v) or math.isinf(v)):
            problems.append(f"metric {k} is NaN or inf")

    # 2. Row count check: len(pr["rows"]) != manifest items x len(manifest seeds)
    manifest = pr.get("manifest") or {}
    items_count = manifest.get("items")
    seeds = manifest.get("seeds") or []
    if items_count is not None and seeds:
        expected_rows = items_count * len(seeds)
        if len(pr.get("rows", [])) != expected_rows:
            problems.append(f"row count {len(pr.get('rows', []))} != expected {expected_rows}")

    # 3. The (item_id, seed) set of PR differs from baseline's
    pr_pairs = {(r.get("item_id"), r.get("seed")) for r in pr.get("rows", [])}
    base_pairs = {(r.get("item_id"), r.get("seed")) for r in base.get("rows", [])}
    if pr_pairs != base_pairs:
        problems.append("PR (item_id, seed) set differs from baseline")

    # 4. Evaluator failures or missing metric value
    if pr.get("evaluator_failures"):
        problems.append(f"evaluator failures non-empty: {pr['evaluator_failures']}")
    spec_metrics = [m["id"] for m in spec.get("metrics", [])]
    for r in pr.get("rows", []):
        for mid in spec_metrics:
            if mid in r and r[mid] is None:
                problems.append(f"row {r.get('item_id')}@{r.get('seed')} has None for metric {mid}")
                break

    # 5. Ratchet against base_spec
    if base_spec and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        base_metric_map = {m["id"]: m for m in base_spec.get("metrics", [])}
        spec_metric_map = {m["id"]: m for m in spec.get("metrics", [])}
        for mid, bm in base_metric_map.items():
            if mid not in spec_metric_map:
                problems.append(f"metric {mid} dropped from spec")
                continue
            sm = spec_metric_map[mid]
            if bm.get("blocking") and not sm.get("blocking"):
                problems.append(f"metric {mid} changed from blocking to non-blocking")
            b_th = bm.get("threshold", {})
            s_th = sm.get("threshold", {})
            if "min" in b_th:
                if "min" not in s_th or s_th["min"] < b_th["min"] - 1e-9:
                    problems.append(f"metric {mid} min threshold loosened")
            if "max" in b_th:
                if "max" not in s_th or s_th["max"] > b_th["max"] + 1e-9:
                    problems.append(f"metric {mid} max threshold loosened")
            if b_th.get("no_significant_drop") and not s_th.get("no_significant_drop"):
                problems.append(f"metric {mid} dropped no_significant_drop")

        base_slices = {s["name"]: s for s in base_spec.get("slices", [])}
        spec_slices = {s["name"]: s for s in spec.get("slices", [])}
        for sname, bs in base_slices.items():
            if sname not in spec_slices:
                problems.append(f"slice {sname} dropped from spec")
                continue
            ss = spec_slices[sname]
            if bs.get("blocking") and not ss.get("blocking"):
                problems.append(f"slice {sname} changed to non-blocking")
            if "min" in bs and ("min" not in ss or ss["min"] < bs["min"] - 1e-9):
                problems.append(f"slice {sname} min threshold loosened")
            if bs.get("no_significant_drop") and not ss.get("no_significant_drop"):
                problems.append(f"slice {sname} dropped no_significant_drop")

    # 6. Slice tags match baseline
    if len(pr.get("rows", [])) == len(base.get("rows", [])):
        pr_slices = {f"{r.get('item_id')}@{r.get('seed')}": sorted(r.get("slices") or []) for r in pr.get("rows", [])}
        base_slices = {f"{r.get('item_id')}@{r.get('seed')}": sorted(r.get("slices") or []) for r in base.get("rows", [])}
        if pr_slices != base_slices:
            problems.append("PR row slice tags differ from baseline")

    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices", []):
        sname = sl["name"]
        mid = sl.get("metric", "pass_rate")
        smin = sl.get("min")
        blocking = sl.get("blocking", False)
        slice_id = f"slice:{sname}/{mid}"

        a_map = per_item(pr, mid, slice_name=sname)
        b_map = per_item(base, mid, slice_name=sname)
        if not a_map:
            val = None
        else:
            val = sum(a_map.values()) / len(a_map)

        verdict = "ok"
        note = ""
        if val is None:
            verdict = "missing"
        elif smin is not None and val < smin:
            verdict = "fail"

        if sl.get("no_significant_drop") and a_map and b_map:
            keys = sorted(set(a_map) & set(b_map))
            if keys:
                d, lo, hi = stats.paired_bootstrap(
                    [a_map[k] for k in keys],
                    [b_map[k] for k in keys],
                    n_resamples=bs.get("n_resamples", 1000),
                    rng=bs.get("rng", 2027),
                )
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"

        if verdict != "ok" and blocking:
            blocked.append(slice_id)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if blocking else "warn")
        val_str = f"{val:.4f}" if val is not None else "None"
        th_info = {"name": sname, "min": smin}
        lines.append(f"  {slice_id:<22} {val_str:<8} {json.dumps(th_info):<40} {note:<28} {label}")

    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    spec = load_spec(Path(args.spec))
    blocked, lines = check(pr, base, spec, base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    for line in lines:
        print(line)
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
