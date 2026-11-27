"""Check the tasks themselves, by exhaustive enumeration. No model is called.

For every task, over every string of its alphabet up to its length limit:
  * the reference never crashes, and every listed example is valid
  * `value` (what the harness computes for a valid input) equals the reference on every valid input
  * each rule-deletion variant differs from the reference on at least one input
  * every rule has "single-rule" inputs: invalid for that rule alone (used for gold items and the test audit)
  * the second, independently written reference (refb.py) agrees with the first on every input

Writes verified.json. Exit code 1 if anything fails.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import tasks as T

HERE = Path(__file__).resolve().parent


def facts(task: T.Task, refb=None) -> dict:
    ref = T.load(T.source(task), task.fn)
    variants = {r: T.load(T.source(task, skip=r), task.fn) for r in T.variant_rules(task)}
    problems, labels = [], Counter()
    differs = {r: 0 for r in variants}
    single = {r: 0 for r in variants}
    disagreements = []
    n = 0
    for x in T.domain(task):
        n += 1
        out = T.outcome(ref, x)
        if out.startswith("CRASH"):
            problems.append(f"reference crashes on {x!r}: {out}")
            continue
        lab = T.label_of(task, out)
        labels[lab] += 1
        if task.kind == "validity" and lab == "VALID" and T.outcome(task.value, x) != out:
            problems.append(f"value() disagrees with the reference on valid input {x!r}")
        changed = [r for r, f in variants.items() if T.outcome(f, x) != out]
        for r in changed:
            differs[r] += 1
        if len(changed) == 1 and lab == "INVALID":
            single[changed[0]] += 1
        if refb is not None:
            ob = T.outcome(refb, x)
            if ob != out and len(disagreements) < 12:
                disagreements.append({"input": x, "reference": out, "second": ob})
            if ob != out:
                differs.setdefault("__refb__", 0)
                differs["__refb__"] += 1
    for e in task.examples:
        if T.label_of(task, T.outcome(ref, e)) in ("INVALID", "CRASH"):
            problems.append(f"example {e!r} is not valid")
    for r, k in differs.items():
        if r != "__refb__" and k == 0:
            problems.append(f"deleting {r} changes nothing: the rule is redundant")
    for r, k in single.items():
        if k == 0 and labels["INVALID"] and any(l.rstrip().endswith("raise ValueError") or "raise ValueError" in l for l in task.marked.split("\n") if l.rstrip().endswith(f"#{r}")):
            problems.append(f"no input is invalid for {r} alone")
    nb = differs.pop("__refb__", 0)
    if refb is not None and nb:
        problems.append(f"the second reference disagrees on {nb} inputs")
    return {"inputs": n, "labels": dict(labels), "variant_differs_on": differs, "single_rule_invalid": single,
            "second_reference": None if refb is None else {"disagreements": nb, "examples": disagreements},
            "problems": problems}


def main() -> int:
    refb = None
    if (HERE / "refb.py").exists():
        import refb as B  # noqa: PLC0415
        refb = B
    out, bad = {}, 0
    for task in T.ALL:
        fb = getattr(refb, task.fn, None) if refb else None
        f = facts(task, fb)
        out[task.name] = f
        bad += len(f["problems"])
        second = "no second reference yet" if f["second_reference"] is None else f"second reference: {f['second_reference']['disagreements']} disagreements"
        print(f"{task.name:13} {f['inputs']:7} inputs  labels {f['labels']}  variants {f['variant_differs_on']}  {second}")
        for p in f["problems"]:
            print(f"    PROBLEM: {p}")
        for d in (f["second_reference"] or {}).get("examples", [])[:6]:
            print(f"    disagree on {d['input']!r}: reference {d['reference']}  second {d['second']}")
    (HERE / "verified.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print("\nall checks passed" if not bad else f"\n{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
