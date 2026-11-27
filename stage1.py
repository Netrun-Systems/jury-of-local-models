"""Stage 1 runner. Collects answers; analyze.py scores them. See PROTOCOL.md before running.

  python stage1.py plan                       # what a run would call, no models
  python stage1.py run   --run main           # every stage, resumable (finished calls are reused)
  python stage1.py vote  --run main --jurors gemma4:12b --tasks span
  python stage1.py run   --run practice --tasks practice_pin --jurors gemma4:12b --repeats 1

Stages, in order:
  propose  two jurors propose test inputs for each rule (no reference is used)
  cases    the harness builds each task's item list: gold items, proposals, near-miss edits, random
  vote     every juror votes blind on every item, `--repeats` times, in shuffled order
  audit    every juror audits a small test suite that has known bad tests planted in it
  review   a single model reviewer reads each build and says correct or incorrect
  arbiter  (optional, `--arbiter`) the paid model votes once on every item

`run` goes model by model so each model is loaded as few times as possible, and takes the
primary pair first: proposals, cases, then each juror's votes and audit together, the paid arbiter
straight after the primary pair, and the reviewer last. `--deadline HH:MM` stops starting new
calls at that local time; a rerun picks up where it stopped.
"""
from __future__ import annotations

import argparse
import json
import re
import string
import sys

import lib as L
import tasks as T

JURORS = ["gpt-oss:20b", "gemma4:12b", "phi4:latest", "deepseek-r1:14b", "qwen3.5:9b"]   # the primary pair first
PROPOSERS = ["gemma4:12b", "gpt-oss:20b"]      # gpt-oss last, so it is already loaded when the votes start
REVIEWERS = ["qwen3.5:9b"]                     # the default local model; also the last juror, so already loaded
N_GOLD_VALID, N_GOLD, N_CASES, CHUNK = 4, 12, 48, 30
QUOTA = {"proposal": 20, "edit": 10, "random": 4, "valid-sample": 14}
BLIND = ("proposal", "edit", "random")      # chosen without the reference; "valid-sample" is not
PRINTABLE = set(string.printable) - set("\n\r\t\x0b\x0c")


def q(x: str) -> str:
    return json.dumps(x)


# ------------------------------------------------------------------------------------------ propose
def prompt_propose(task: T.Task) -> str:
    return f"""You are designing test inputs for a function described by a written request. Do not write code.

REQUEST
{T.spec(task)}

For each numbered rule in the request, give:
  "breaks": three inputs that break that rule and no other rule
  "keeps":  two valid inputs that come as close as possible to breaking that rule
Also give, under the key "VALID", six valid inputs that differ from each other as much as possible.

Reply with one JSON object and nothing else, in this shape:
{{"R1": {{"breaks": ["...", "...", "..."], "keeps": ["...", "..."]}}, "R2": {{"breaks": [...], "keeps": [...]}}, "VALID": ["...", "..."]}}
Each input is a JSON string, exactly as it would be passed to the function."""


def parse_proposals(text: str) -> dict:
    obj = L.last_json_object(text) or {}
    out = {}
    for rule, v in obj.items():
        if isinstance(v, list) and str(rule).upper() == "VALID":
            out["VALID"] = {"breaks": [], "keeps": [x for x in v if isinstance(x, str) and len(x) <= 12 and set(x) <= PRINTABLE][:8]}
            continue
        if not isinstance(v, dict):
            continue
        clean = {}
        for kind in ("breaks", "keeps"):
            clean[kind] = [x for x in (v.get(kind) or []) if isinstance(x, str) and len(x) <= 12 and set(x) <= PRINTABLE][:4]
        out[str(rule).upper()] = clean
    return out


def stage_propose(a) -> None:
    d = L.run_dir(a.run)
    props = L.load_json(d / "proposals.json", {})
    for model in a.proposers:
        for task in a.task_list:
            text = L.dispatch(a.run, model, f"propose-{task.name}", prompt_propose(task), {"stage": "propose", "task": task.name})
            props.setdefault(task.name, {})[model] = parse_proposals(text)
            L.save_json(d / "proposals.json", props)


# -------------------------------------------------------------------------------------------- cases
def edits_of(x: str, symbols: list) -> list:
    """Every string one small edit away from x: a character deleted, doubled, swapped or replaced."""
    out = []
    for i in range(len(x)):
        out.append(x[:i] + x[i + 1:])
        out.append(x[:i] + x[i] + x[i:])
        if i + 1 < len(x):
            out.append(x[:i] + x[i + 1] + x[i] + x[i + 2:])
        out.extend(x[:i] + c + x[i + 1:] for c in symbols if c != x[i])
    out.extend(x + c for c in symbols)
    return out


def build_cases(task: T.Task, proposals: dict) -> dict:
    """The item list for one task: gold items plus up to N_CASES cases in four strata.

    Three strata are chosen WITHOUT the reference, as the method would work in real use: the
    jurors' proposals, near-miss edits of inputs somebody called valid, and random strings. The
    fourth, "valid-sample", is drawn WITH the reference, because blind generation yields almost
    only invalid inputs and a wrongly rejected valid input must be measurable too. Analysis keeps
    the two apart: a missing rule only counts as caught on the blind strata."""
    r = L.rng("cases", task.name)
    ref = L.ref(task)
    try:
        import refb  # noqa: PLC0415
        second = getattr(refb, task.fn)
    except Exception:  # noqa: BLE001
        second = None
    pool = list(T.domain(task))
    r.shuffle(pool)
    valid = [x for x in pool if L.truth(task, x) != "INVALID"]
    single: dict = {rule: [] for rule in T.variant_rules(task)}
    plain_invalid = []
    for x in pool:
        if L.truth(task, x) != "INVALID" or not x:
            continue
        rules = L.deciding_rules(task, x)
        if len(rules) == 1 and len(single[rules[0]]) < 8:
            single[rules[0]].append(x)
        elif not rules and len(plain_invalid) < 12:
            plain_invalid.append(x)
        if all(len(v) >= 8 for v in single.values()) and len(plain_invalid) >= 12:
            break
    # gold: known answers mixed into every vote; they decide whether a juror is seated for this task
    by_label: dict = {}
    for x in valid:
        by_label.setdefault(L.truth(task, x), []).append(x)
    n_valid = min(N_GOLD_VALID, len(valid) // 2)
    gold_valid = []
    while len(gold_valid) < n_valid:
        for lab in sorted(by_label):
            if by_label[lab] and len(gold_valid) < n_valid:
                gold_valid.append(by_label[lab].pop())
    # A rule with few single-rule inputs keeps them all for the cases: gold never takes a rule's
    # only way of being caught.
    roomy = {rule: list(xs) for rule, xs in single.items() if len(xs) >= 6}
    gold_invalid = []
    for _ in range(2):
        for rule in sorted(roomy):
            if roomy[rule] and len(gold_invalid) < N_GOLD - len(gold_valid) - 2:
                gold_invalid.append(roomy[rule].pop())
    gold_invalid += plain_invalid[:N_GOLD - len(gold_valid) - len(gold_invalid)]
    gold = gold_valid + gold_invalid
    taken = set(gold)

    items, disputes = [], []

    def count(stratum) -> int:
        return sum(1 for it in items if it["stratum"] == stratum)

    def add(x, stratum, limit) -> bool:
        if count(stratum) >= limit or not isinstance(x, str) or x in taken or len(x) > 12 or not set(x) <= PRINTABLE:
            return False
        if second is not None and T.outcome(ref, x) != T.outcome(second, x):
            disputes.append(x)
            return False
        taken.add(x)
        items.append({"input": x, "stratum": stratum})
        return True

    # 1. the jurors' own proposals, taken list by list so no rule crowds out another
    lists, keeps = [], []
    for model in sorted(proposals):
        for rule in sorted(proposals[model]):
            for kind in ("breaks", "keeps"):
                lists.append(list(proposals[model][rule].get(kind) or []))
            keeps += proposals[model][rule].get("keeps") or []
    while any(lists):
        for lst in lists:
            if lst:
                add(lst.pop(0), "proposal", QUOTA["proposal"])
    # 2. near misses: one small edit away from an input somebody called valid
    seeds = list(dict.fromkeys([*task.examples, *keeps]))
    symbols = sorted(set("".join([*task.examples, *[it["input"] for it in items]])))
    near = [e for sd in seeds for e in edits_of(sd, symbols)]
    r.shuffle(near)
    for x in near:
        add(x, "edit", QUOTA["edit"])
    # 3. uniform random strings from the task's alphabet
    alphabet = list(task.alphabet)
    for _ in range(400):
        add("".join(r.choice(alphabet) for _ in range(r.randint(0, task.maxlen))), "random", QUOTA["random"])
    # 4. valid inputs, drawn with the reference and spread over the labels
    rest = {lab: [x for x in xs if x not in taken] for lab, xs in by_label.items()}
    while any(rest.values()) and count("valid-sample") < QUOTA["valid-sample"]:
        for lab in sorted(rest):
            if rest[lab]:
                add(rest[lab].pop(), "valid-sample", QUOTA["valid-sample"])
    # top up with more near misses when a stratum came up short (few proposals, or few valid inputs)
    for x in near:
        if len(items) >= N_CASES:
            break
        add(x, "edit", N_CASES)
    return {"gold": gold, "cases": items[:N_CASES], "reference_disputes": disputes}


def stage_cases(a) -> None:
    d = L.run_dir(a.run)
    props = L.load_json(d / "proposals.json", {})
    cases = L.load_json(d / "cases.json", {})
    for task in a.task_list:
        if task.name in cases:
            continue                       # never rebuild: the votes already cast refer to these items
        cases[task.name] = build_cases(task, props.get(task.name, {}))
        c = cases[task.name]
        strata = {s: sum(1 for it in c["cases"] if it["stratum"] == s) for s in QUOTA}
        print(f"  cases {task.name:13} gold {len(c['gold'])}  cases {len(c['cases'])} {strata}  reference disputes {len(c['reference_disputes'])}")
    L.save_json(d / "cases.json", cases)


def items_of(cases: dict, task: T.Task) -> list:
    c = cases[task.name]
    return [*c["gold"], *[it["input"] for it in c["cases"]]]


# --------------------------------------------------------------------------------------------- vote
def prompt_vote(task: T.Task, inputs: list) -> str:
    labels = T.vote_labels(task)
    if task.kind == "validity":
        how = "VALID means the input fits the description and breaks no rule. INVALID means the function must raise ValueError."
    else:
        how = "Give the label the function must return, or INVALID if the function must raise ValueError."
    lines = "\n".join(f"{i}. {q(x)}" for i, x in enumerate(inputs, 1))
    return f"""You are checking inputs against a written request. Do not write code and do not explain.

REQUEST
{T.spec(task)}

For each numbered input below, decide what a correct implementation must do with it.
Answer each with exactly one of: {", ".join(labels)}.
{how}
The inputs are written as JSON strings: "" is the empty string, and every character between the quotes counts, including spaces.

INPUTS
{lines}

Reply with one JSON object and nothing else, mapping each number to your answer, like {{"1": "{labels[-1]}", "2": "{labels[0]}"}}."""


def parse_votes(text: str, inputs: list, labels: list) -> dict:
    """input -> label, or None where the juror gave no usable answer."""
    obj = L.last_json_object(text)
    found = {}
    if isinstance(obj, dict):
        found = {str(k).strip(): v for k, v in obj.items()}
    if not any(str(i) in found for i in range(1, len(inputs) + 1)):
        # a numbered list instead of JSON: "3. INVALID" or "3: VALID"
        alt = "|".join(sorted(labels, key=len, reverse=True))
        found = {m.group(1): m.group(2) for m in re.finditer(rf"(?m)^\s*\"?(\d+)\"?\s*[.:)\-=]+\s*\"?({alt})\b", text or "", flags=re.I)}
    out = {}
    for i, x in enumerate(inputs, 1):
        v = found.get(str(i))
        v = v.strip().upper() if isinstance(v, str) else None
        out[x] = v if v in labels else None
    return out


def stage_vote(a, models=None, repeats=None) -> None:
    d = L.run_dir(a.run)
    cases = L.load_json(d / "cases.json", {})
    votes = L.load_json(d / "votes.json", {})
    for model in models or a.jurors:
        for task in a.task_list:
            base = items_of(cases, task)
            for rep in range(repeats or a.repeats):
                order = list(base)
                L.rng("order", task.name, rep).shuffle(order)
                got = {}
                for c in range(0, len(order), a.chunk):
                    part = order[c:c + a.chunk]
                    text = L.dispatch(a.run, model, f"vote-{task.name}-r{rep}-c{c // a.chunk}", prompt_vote(task, part),
                                      {"stage": "vote", "task": task.name, "inputs": part, "rep": rep})
                    got.update(parse_votes(text, part, T.vote_labels(task)))
                votes.setdefault(model, {}).setdefault(task.name, {})[str(rep)] = got
                L.save_json(d / "votes.json", votes)


# -------------------------------------------------------------------------------------------- audit
def show(task: T.Task, out: str) -> str:
    v = json.loads(out)[1]

    def py(o):
        if isinstance(o, list):
            return "(" + ", ".join(py(e) for e in o) + ("," if len(o) == 1 else "") + ")"
        return repr(o)
    return py(v)


def build_tests(task: T.Task) -> list:
    """Eight good tests and four planted bad ones, in shuffled order. Built from the reference."""
    r = L.rng("audit", task.name)
    ref = L.ref(task)
    pool = [x for x in T.domain(task) if len(x) >= 1]
    r.shuffle(pool)
    valid = [x for x in pool if L.truth(task, x) != "INVALID"]
    single: dict = {}
    for x in pool:
        if L.truth(task, x) == "INVALID":
            rules = L.deciding_rules(task, x)
            if len(rules) == 1:
                single.setdefault(rules[0], []).append(x)
        if len(single) == len(T.variant_rules(task)) and all(len(v) >= 3 for v in single.values()):
            break
    fn = task.fn
    tests = []
    for x in valid[:4]:
        tests.append({"text": f"{fn}({q(x)}) returns {show(task, T.outcome(ref, x))}", "kind": "good_valid", "rule": None})
    rules = sorted(single)
    r.shuffle(rules)
    for rule in (rules * 4)[:4]:
        x = single[rule].pop()
        tests.append({"text": f"{fn}({q(x)}) raises ValueError", "kind": "good_invalid", "rule": rule})
    # planted: contradicts the request
    for rule in rules:
        bad = None
        for x in single[rule]:
            out = T.outcome(L.variants(task)[rule], x)
            if out.startswith("["):
                bad = (x, out)
                break
        if bad:
            single[rule].remove(bad[0])
            tests.append({"text": f"{fn}({q(bad[0])}) returns {show(task, bad[1])}", "kind": "contradicts", "rule": rule})
            break
    tests.append({"text": f"{fn}({q(valid[4 % len(valid)])}) raises ValueError", "kind": "contradicts", "rule": None})
    # planted: not required by the request
    rule = next(rl for rl in rules if single[rl])
    x = single[rule].pop()
    try:
        ref(x)
        message = "invalid input"
    except ValueError as e:
        message = str(e)
    tests.append({"text": f"{fn}({q(x)}) raises ValueError with the message {q(message)}", "kind": "not_required", "rule": rule})
    tests.append({"text": f"{fn}({q(valid[5 % len(valid)])}) returns its result in under one millisecond", "kind": "not_required", "rule": None})
    r.shuffle(tests)
    for i, t in enumerate(tests, 1):
        t["id"] = f"T{i:02d}"
    return tests


def prompt_audit(task: T.Task, tests: list) -> str:
    lines = "\n".join(f"{t['id']}. {t['text']}" for t in tests)
    return f"""You are auditing a test suite against a written request. Do not write code and do not explain.

REQUEST
{T.spec(task)}

Each test below states something an implementation is expected to do. For each test choose one verdict:
  REQUIRED      the request requires exactly this behaviour
  NOT_REQUIRED  the request does not say this; a correct implementation could fail the test
  CONTRADICTS   the request requires something different from what the test expects
Also name the one rule that decides it (R1, R2, ...), or "-" if no single rule does.

TESTS
{lines}

Reply with one JSON object and nothing else, like
{{"T01": {{"verdict": "REQUIRED", "rule": "R2"}}, "T02": {{"verdict": "NOT_REQUIRED", "rule": "-"}}}}."""


def parse_audit(text: str, tests: list) -> dict:
    obj = L.last_json_object(text) or {}
    out = {}
    for t in tests:
        v = obj.get(t["id"])
        if isinstance(v, str):
            v = {"verdict": v}
        verdict = str((v or {}).get("verdict", "")).strip().upper().replace(" ", "_") if isinstance(v, dict) else ""
        rule = str((v or {}).get("rule", "")).strip().upper() if isinstance(v, dict) else ""
        out[t["id"]] = {"verdict": verdict if verdict in ("REQUIRED", "NOT_REQUIRED", "CONTRADICTS") else None,
                        "rule": rule if re.fullmatch(r"R\d+", rule) else None}
    return out


def stage_audit(a, models=None) -> None:
    d = L.run_dir(a.run)
    tests = L.load_json(d / "audit_tests.json", {})
    for task in a.task_list:
        if task.name not in tests:
            tests[task.name] = build_tests(task)
    L.save_json(d / "audit_tests.json", tests)
    audit = L.load_json(d / "audit.json", {})
    for model in models or a.jurors:
        for task in a.task_list:
            ts = tests[task.name]
            shown = [{"id": t["id"], "text": t["text"]} for t in ts]
            text = L.dispatch(a.run, model, f"audit-{task.name}", prompt_audit(task, shown), {"stage": "audit", "task": task.name, "tests": ts})
            audit.setdefault(model, {})[task.name] = parse_audit(text, ts)
            L.save_json(d / "audit.json", audit)


# ------------------------------------------------------------------------------------------- review
def prompt_review(task: T.Task, src: str) -> str:
    return f"""You are reviewing an implementation against a written request.

REQUEST
{T.spec(task)}

IMPLEMENTATION
```python
{src}```

Does the implementation do exactly what the request says for every possible input string?

Reply with one JSON object and nothing else:
{{"verdict": "CORRECT" or "INCORRECT", "failing_input": an input string it handles wrongly, or null, "reason": "one sentence"}}"""


def parse_review(text: str) -> dict:
    obj = L.last_json_object(text) or {}
    verdict = str(obj.get("verdict", "")).strip().upper()
    fi = obj.get("failing_input")
    return {"verdict": verdict if verdict in ("CORRECT", "INCORRECT") else None, "failing_input": fi if isinstance(fi, str) else None}


def stage_review(a) -> None:
    d = L.run_dir(a.run)
    reviews = L.load_json(d / "reviews.json", {})
    for model in a.reviewers:
        for task in a.task_list:
            for name, (src, correct, rule) in L.builds(task).items():
                text = L.dispatch(a.run, model, f"review-{task.name}-{name}", prompt_review(task, src),
                                  {"stage": "review", "task": task.name, "build": name, "correct": correct, "rule": rule})
                reviews.setdefault(model, {}).setdefault(task.name, {})[name] = parse_review(text)
                L.save_json(d / "reviews.json", reviews)


# --------------------------------------------------------------------------------------------- main
def plan(a) -> None:
    n = len(a.task_list)
    chunks = -(-(N_GOLD + N_CASES) // a.chunk)
    nb = sum(len(L.builds(t)) for t in a.task_list)
    rows = [("propose", len(a.proposers) * n), ("vote", len(a.jurors) * n * a.repeats * chunks), ("audit", len(a.jurors) * n),
            ("review", len(a.reviewers) * nb), ("arbiter (paid)", n * chunks if a.arbiter else 0)]
    for name, k in rows:
        print(f"  {name:16} {k:4} calls")
    local = sum(k for name, k in rows if "paid" not in name)
    print(f"  local calls {local}; at 45 s each that is about {local * 45 / 3600:.1f} h, plus model loads. Tasks: {', '.join(t.name for t in a.task_list)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Stage 1 of the jury experiment: collect answers")
    ap.add_argument("stage", choices=["plan", "propose", "cases", "vote", "audit", "review", "arbiter", "run"])
    ap.add_argument("--run", default="main")
    ap.add_argument("--tasks", default="")
    ap.add_argument("--jurors", default=",".join(JURORS))
    ap.add_argument("--proposers", default=",".join(PROPOSERS))
    ap.add_argument("--reviewers", default=",".join(REVIEWERS))
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--chunk", type=int, default=CHUNK)
    ap.add_argument("--arbiter", action="store_true", help="also have the paid model vote once on every item")
    ap.add_argument("--deadline", default="", help="local time HH:MM after which no new call is started (the next such time)")
    ap.add_argument("--passes", type=int, default=1, help="`run` only: go through every stage this many times, under one deadline")
    a = ap.parse_args(argv)
    for k in ("jurors", "proposers", "reviewers"):
        setattr(a, k, [m for m in getattr(a, k).split(",") if m])
    names = [n for n in a.tasks.split(",") if n]
    unknown = [n for n in names if n not in T.BY_NAME]
    if unknown:
        raise SystemExit(f"unknown task(s): {unknown}; known: {list(T.BY_NAME)}")
    a.task_list = [T.BY_NAME[n] for n in names] if names else list(T.TASKS)
    if a.stage == "plan":
        plan(a)
        return 0
    steps = {"propose": stage_propose, "cases": stage_cases, "vote": stage_vote, "audit": stage_audit, "review": stage_review,
             "arbiter": lambda a_: stage_vote(a_, models=["paid"], repeats=1)}
    if a.deadline:
        L.set_deadline(a.deadline)
    if a.stage != "run":
        print(f"== {a.stage}", flush=True)
        steps[a.stage](a)
        return 0
    L.keep_awake()
    config = {"tasks": [t.name for t in a.task_list], "jurors": a.jurors, "proposers": a.proposers,
              "reviewers": a.reviewers, "repeats": a.repeats, "chunk": a.chunk, "arbiter": a.arbiter}
    L.save_json(L.run_dir(a.run) / "config.json", config)      # at the start, so a run that dies still says what it was
    try:
        for n in range(a.passes):
            # A later pass reuses every answered call and retries only the ones that got no answer.
            print(f"== pass {n + 1} of {a.passes}", flush=True)
            print("== propose", flush=True)
            stage_propose(a)
            print("== cases", flush=True)
            stage_cases(a)
            primary = set(L.THRESHOLDS["primary_pair"])
            first = [m for m in a.jurors if m in primary]
            for group, label in ((first, "primary pair"), ([m for m in a.jurors if m not in primary], "other jurors")):
                for m in group:
                    print(f"== vote + audit: {m} ({label})", flush=True)
                    stage_vote(a, models=[m])
                    stage_audit(a, models=[m])
                if label == "primary pair" and a.arbiter:
                    print("== arbiter (paid model, one pass)", flush=True)
                    stage_vote(a, models=["paid"], repeats=1)
            print("== review", flush=True)
            stage_review(a)
    except L.Deadline as e:
        print(f"== stopped: {e}. Run the same command again to continue.", flush=True)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
