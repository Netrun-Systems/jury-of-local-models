"""Scripted jurors for smoke.py. No model is called.

Each one answers from the reference with a KNOWN fault, so the scorer can be checked against
numbers we can predict:

  oracle, oracle2   always right
  blindA, blindB    both ignore the task's first rule (a shared blind spot)
  blindC            ignores the task's second rule
  noisy             right, except a seeded 15% of answers
  lister            right, but answers as a numbered list instead of JSON (parser fallback)
  mute              never gives a usable answer
"""
from __future__ import annotations

import json

import lib as L
import tasks as T

_MATERIAL: dict = {}


def material(task: T.Task) -> dict:
    if task.name not in _MATERIAL:
        r = L.rng("fake-material", task.name)
        pool = list(T.domain(task))
        r.shuffle(pool)
        valid = [x for x in pool if L.truth(task, x) != "INVALID"][:12]
        single: dict = {}
        want = len(T.variant_rules(task))
        for x in pool:
            if L.truth(task, x) == "INVALID":
                rules = L.deciding_rules(task, x)
                if len(rules) == 1 and len(single.setdefault(rules[0], [])) < 3:
                    single[rules[0]].append(x)
            if len(single) == want and all(len(v) >= 3 for v in single.values()):
                break
        _MATERIAL[task.name] = {"valid": valid, "single": single}
    return _MATERIAL[task.name]


def _label(kind: str, task: T.Task, x: str, r) -> str:
    rules = T.variant_rules(task)
    labels = T.vote_labels(task)
    if kind in ("blindA", "blindB", "blindC"):
        rule = rules[1 if kind == "blindC" else 0]
        lab = T.label_of(task, T.outcome(L.variants(task)[rule], x))
        return lab if lab in labels else "INVALID"
    lab = L.truth(task, x)
    if kind == "noisy" and r.random() < 0.15:
        return r.choice([v for v in labels if v != lab])
    return lab


def answer(kind: str, meta: dict) -> str:
    if kind == "mute":
        return "I am not able to help with that request."
    task = T.BY_NAME[meta["task"]]
    stage = meta["stage"]
    r = L.rng("fake", kind, task.name, stage, meta.get("rep"), meta.get("build"))
    if stage == "vote":
        got = {str(i): _label(kind, task, x, r) for i, x in enumerate(meta["inputs"], 1)}
        if kind == "lister":
            return "Here are my answers:\n" + "\n".join(f"{i}. {v}" for i, v in got.items())
        return "```json\n" + json.dumps(got) + "\n```"
    if stage == "propose":
        m = material(task)
        return json.dumps({**{rule: {"breaks": xs[:3], "keeps": m["valid"][:2]} for rule, xs in m["single"].items()}, "VALID": m["valid"][2:8]})
    if stage == "audit":
        out = {}
        for t in meta["tests"]:
            if kind in ("blindA", "blindB", "blindC"):
                verdict = "REQUIRED"                      # says yes to everything, as the first experiment's jurors did
            elif kind == "noisy" and r.random() < 0.15:
                verdict = r.choice(["REQUIRED", "NOT_REQUIRED", "CONTRADICTS"])
            else:
                verdict = {"contradicts": "CONTRADICTS", "not_required": "NOT_REQUIRED"}.get(t["kind"], "REQUIRED")
            out[t["id"]] = {"verdict": verdict, "rule": t["rule"] or "-"}
        return json.dumps(out)
    if stage == "review":
        if kind in ("blindA", "blindB", "blindC"):
            return json.dumps({"verdict": "CORRECT", "failing_input": None, "reason": "looks right"})
        if meta["correct"]:
            return json.dumps({"verdict": "CORRECT", "failing_input": None, "reason": "matches every rule"})
        xs = material(task)["single"].get(meta["rule"]) or []
        return json.dumps({"verdict": "INCORRECT", "failing_input": xs[0] if xs else None, "reason": f"{meta['rule']} is not enforced"})
    raise ValueError(f"unknown stage {stage!r}")
