"""Check a run's saved answers against its raw model outputs. No model is called.

Every vote, audit verdict and review in the JSON files must be exactly what parsing the raw
answer files gives, and nothing may be missing. Written after the first real run, whose replay
pass died on a file write: this proves the scored data is what the models actually said.

  python verify_run.py --run main
"""
from __future__ import annotations

import argparse
import sys

import lib as L
import stage1 as S
import tasks as T


def raw(run: str, step: str, model: str):
    p = L.run_dir(run) / "raw" / f"{L._safe(step)}__{L._safe(model)}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="main")
    ap.add_argument("--chunk", type=int, default=S.CHUNK)
    a = ap.parse_args(argv)
    d = L.run_dir(a.run)
    cases, votes = L.load_json(d / "cases.json", {}), L.load_json(d / "votes.json", {})
    audit, tests, reviews = L.load_json(d / "audit.json", {}), L.load_json(d / "audit_tests.json", {}), L.load_json(d / "reviews.json", {})
    problems, checked, missing_raw = [], 0, 0

    for model, by_task in votes.items():
        for tname, by_rep in by_task.items():
            task = T.BY_NAME[tname]
            base = S.items_of(cases, task)
            for rep, saved in by_rep.items():
                order = list(base)
                L.rng("order", tname, int(rep)).shuffle(order)
                got = {}
                for c in range(0, len(order), a.chunk):
                    part = order[c:c + a.chunk]
                    text = raw(a.run, f"vote-{tname}-r{rep}-c{c // a.chunk}", model)
                    missing_raw += text is None
                    got.update(S.parse_votes(text or "", part, T.vote_labels(task)))
                checked += len(got)
                if got != saved:
                    diff = [x for x in got if got[x] != saved.get(x)]
                    problems.append(f"votes differ from raw: {model} {tname} repeat {rep}: {len(diff)} items")
    for model, by_task in audit.items():
        for tname, saved in by_task.items():
            text = raw(a.run, f"audit-{tname}", model)
            missing_raw += text is None
            got = S.parse_audit(text or "", tests[tname])
            checked += len(got)
            if got != saved:
                problems.append(f"audit differs from raw: {model} {tname}")
    for model, by_task in reviews.items():
        for tname, by_build in by_task.items():
            for build, saved in by_build.items():
                text = raw(a.run, f"review-{tname}-{build}", model)
                missing_raw += text is None
                checked += 1
                if S.parse_review(text or "") != saved:
                    problems.append(f"review differs from raw: {model} {tname} {build}")

    # completeness: what a full run of this configuration must contain
    cfg = L.load_json(d / "config.json", {})
    if not cfg:
        # config.json is written when a run completes; a run that died in its replay pass has none.
        cfg = {"tasks": [t.name for t in T.TASKS if t.name in cases], "jurors": S.JURORS, "reviewers": S.REVIEWERS, "repeats": 3, "arbiter": "paid" in votes}
        print("  note: no config.json, so completeness is checked against the default configuration")
    names = cfg.get("tasks") or list(cases)
    for model in cfg.get("jurors", []):
        for tname in names:
            have = votes.get(model, {}).get(tname, {})
            if sorted(have) != [str(r) for r in range(cfg.get("repeats", 3))]:
                problems.append(f"votes incomplete: {model} {tname} has repeats {sorted(have)}")
            if tname not in audit.get(model, {}):
                problems.append(f"audit missing: {model} {tname}")
    for model in cfg.get("reviewers", []):
        for tname in names:
            want = set(L.builds(T.BY_NAME[tname]))
            have = set(reviews.get(model, {}).get(tname, {}))
            if want != have:
                problems.append(f"reviews incomplete: {model} {tname} lacks {sorted(want - have)}")
    if cfg.get("arbiter") and any("0" not in votes.get("paid", {}).get(t, {}) for t in names):
        problems.append("arbiter votes incomplete")

    none = sum(1 for m in votes.values() for t in m.values() for r in t.values() for v in r.values() if v is None)
    print(f"  checked {checked} saved answers against the raw outputs; raw files missing: {missing_raw}; votes with no usable answer: {none}")
    for p in problems:
        print(f"  PROBLEM: {p}")
    print("  the saved data matches the raw outputs and is complete" if not problems else f"  {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
