"""Score a stage 1 run from its saved answers. No model is called.

  python analyze.py --run main      # writes runs/main/summary.json and runs/main/RESULTS.md

Every threshold comes from thresholds.json, which was committed before the run (PROTOCOL.md).
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys

import lib as L
import tasks as T

TH = L.THRESHOLDS


def pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def rate(x: int, n: int) -> dict:
    lo, hi = L.interval(x, n)
    return {"x": x, "n": n, "rate": (x / n) if n else None, "low": lo if n else None, "high": hi if n else None}


def show(r: dict) -> str:
    return f"{r['x']} of {r['n']}" + (f" ({pct(r['rate'])}; 95% interval {pct(r['low'])} to {pct(r['high'])})" if r["n"] else "")


def analyze(run: str, primary_pair=None) -> dict:
    """The analysis for one seated pair. primary_pair overrides thresholds.json: used by the smoke
    test, and by analyze_all() to score a pair declared after the protocol was fixed."""
    pp = list(primary_pair or TH["primary_pair"])
    d = L.run_dir(run)
    cases = L.load_json(d / "cases.json", {})
    votes = L.load_json(d / "votes.json", {})
    audit = L.load_json(d / "audit.json", {})
    tests = L.load_json(d / "audit_tests.json", {})
    reviews = L.load_json(d / "reviews.json", {})
    names = [n for n in cases if not T.BY_NAME[n].practice] or list(cases)
    tasks = [T.BY_NAME[n] for n in names]
    jurors = sorted(m for m in votes if m != "paid")

    # ---- per task: items, truth, and what every build does with every case
    info = {}
    for t in tasks:
        c = cases[t.name]
        inputs = [it["input"] for it in c["cases"]]
        truth = {x: L.truth(t, x) for x in [*c["gold"], *inputs]}
        built = {name: (T.load(src, t.fn), ok, rule) for name, (src, ok, rule) in L.builds(t).items()}
        outs = {name: {x: T.outcome(f, x) for x in inputs} for name, (f, _, _) in built.items()}
        info[t.name] = {"gold": c["gold"], "inputs": inputs, "truth": truth, "builds": built, "outs": outs,
                        "stratum": {it["input"]: it["stratum"] for it in c["cases"]},
                        "blind": {it["input"] for it in c["cases"] if it["stratum"] != "valid-sample"}}
        I_ = info[t.name]
        # a missing rule counts as caught only on cases chosen WITHOUT the reference
        I_["catchable"] = {name: any(outs[name][x] != outs["reference"][x] for x in I_["blind"]) for name in built}

    def reps(model, tname):
        return votes.get(model, {}).get(tname, {})

    # ---- jurors
    juror = {}
    seated = {}
    for m in [*jurors, *(["paid"] if "paid" in votes else [])]:
        g_ok = g_n = c_ok = c_ans = c_n = seat_n = seat_k = flips = flip_n = 0
        for t in tasks:
            I = info[t.name]
            rv = reps(m, t.name)
            for rep, v in rv.items():
                gk = sum(1 for x in I["gold"] if v.get(x) == I["truth"][x])
                g_ok, g_n = g_ok + gk, g_n + len(I["gold"])
                ok = bool(I["gold"]) and gk / len(I["gold"]) >= TH["seat_min_gold"]
                seated[(m, t.name, rep)] = ok
                seat_n, seat_k = seat_n + 1, seat_k + ok
                c_n += len(I["inputs"])
                c_ans += sum(1 for x in I["inputs"] if v.get(x) is not None)
                c_ok += sum(1 for x in I["inputs"] if v.get(x) == I["truth"][x])
            if "0" in rv:
                for rep, v in rv.items():
                    if rep == "0":
                        continue
                    both = [x for x in I["inputs"] if v.get(x) is not None and rv["0"].get(x) is not None]
                    flip_n += len(both)
                    flips += sum(1 for x in both if v[x] != rv["0"][x])
        juror[m] = {"gold": rate(g_ok, g_n), "cases_correct_of_all": rate(c_ok, c_n), "cases_correct_of_answered": rate(c_ok, c_ans),
                    "no_answer": rate(c_n - c_ans, c_n), "seated": rate(seat_k, seat_n), "changed_between_repeats": rate(flips, flip_n)}

    # ---- pairs
    def pair_cells(a, b):
        cells = []
        for t in tasks:
            I = info[t.name]
            for rep in sorted(set(reps(a, t.name)) & set(reps(b, t.name))):
                va, vb = reps(a, t.name)[rep], reps(b, t.name)[rep]
                key = {x: va[x] for x in I["inputs"] if va.get(x) is not None and va.get(x) == vb.get(x)}
                wrong = [x for x, lab in key.items() if lab != I["truth"][x]]
                cells.append({"task": t.name, "rep": rep, "n": len(I["inputs"]), "key": key, "wrong": wrong,
                              "seated": seated.get((a, t.name, rep), False) and seated.get((b, t.name, rep), False)})
        return cells

    def gate(tname, key):
        """verdict per build for one answer key"""
        I = info[tname]
        t = T.BY_NAME[tname]
        out = {}
        for name in I["builds"]:
            bad = False
            for x, lab in key.items():
                exp = T.expected(t, x, lab)
                if exp is not None and I["outs"][name][x] != exp:
                    bad = True
                    break
            out[name] = "FAIL" if bad else ("PASS" if len(key) >= TH["gate_min_settled"] else "INCONCLUSIVE")
        return out

    pairs = {}
    for a, b in itertools.combinations(jurors, 2):
        cells = pair_cells(a, b)
        if not cells:
            continue
        res = {}
        for scope, sel in (("all", cells), ("seated", [c for c in cells if c["seated"]])):
            n = sum(c["n"] for c in sel)
            settled = sum(len(c["key"]) for c in sel)
            wrong = sum(len(c["wrong"]) for c in sel)
            lenient = sum(1 for c in sel for x in c["wrong"] if info[c["task"]]["truth"][x] == "INVALID")
            caught = missed = uncatchable = fa = clean = incon = 0
            for c in sel:
                g = gate(c["task"], c["key"])
                gb = gate(c["task"], {x: lab for x, lab in c["key"].items() if x in info[c["task"]]["blind"]})
                for name, (_, ok, _) in info[c["task"]]["builds"].items():
                    if ok:
                        fa += g[name] == "FAIL"
                        clean += g[name] == "PASS"
                        incon += g[name] == "INCONCLUSIVE"
                    elif gb[name] == "FAIL":
                        caught += 1
                    elif info[c["task"]]["catchable"][name]:
                        missed += 1
                    else:
                        uncatchable += 1
            res[scope] = {"cells": len(sel), "cases": n, "settled": rate(settled, n), "wrong": rate(wrong, settled),
                          "tasks_with_a_wrong_answer": len({c["task"] for c in sel if c["wrong"]}), "tasks": len({c["task"] for c in sel}),
                          "wrong_that_accept_invalid_input": lenient,
                          "variants_caught": rate(caught, caught + missed + uncatchable), "variants_missed_though_catchable": missed,
                          "variants_no_case_could_catch": uncatchable,
                          "correct_builds_failed": rate(fa, fa + clean + incon), "correct_builds_inconclusive": incon,
                          "coverage_by_repeat": {rep: round(sum(len(c["key"]) for c in sel if c["rep"] == rep) / max(1, sum(c["n"] for c in sel if c["rep"] == rep)), 4)
                                                 for rep in sorted({c["rep"] for c in sel})}}
        res["wrong_answers"] = [{"task": c["task"], "rep": c["rep"], "input": x, "adopted": c["key"][x], "truth": info[c["task"]]["truth"][x],
                                 "stratum": info[c["task"]]["stratum"][x], "seated": c["seated"]} for c in cells for x in c["wrong"]]
        pairs[f"{a} + {b}"] = res

    primary = " + ".join(pp)
    if primary not in pairs:
        primary = " + ".join(reversed(pp)) if " + ".join(reversed(pp)) in pairs else None
    P = pairs.get(primary) if primary else None
    hyp = {}

    # ---- H1: the agreement rule keeps wrong answers out
    if P and P["seated"]["settled"]["x"]:
        w = P["seated"]["wrong"]
        cells = [c for c in pair_cells(*primary.split(" + ")) if c["seated"]]
        by_task = {}
        for c in cells:
            e = by_task.setdefault(c["task"], [0, 0])
            e[0] += len(c["wrong"])
            e[1] += len(c["key"])
        r = L.rng("bootstrap", run)
        tn = sorted(by_task)
        boots = []
        for _ in range(2000):
            pick = [by_task[r.choice(tn)] for _ in tn]
            s = sum(p[1] for p in pick)
            boots.append(sum(p[0] for p in pick) / s if s else 0.0)
        boots.sort()
        enough = w["n"] >= TH["H1_min_settled"]
        if w["rate"] > TH["H1_refuted_above"]:
            verdict = "REFUTED"
        elif enough and w["rate"] <= TH["H1_supported_at_or_below"] and P["seated"]["tasks_with_a_wrong_answer"] <= TH["H1_max_tasks_with_a_wrong_answer"]:
            verdict = "SUPPORTED"
        else:
            verdict = "INCONCLUSIVE"
        others = {k: v["seated"]["wrong"] for k, v in pairs.items() if v["seated"]["wrong"]["n"] >= 100}
        hyp["H1"] = {"verdict": verdict, "primary_pair": primary, "wrong": w, "enough_cases": enough,
                     "tasks_with_a_wrong_answer": P["seated"]["tasks_with_a_wrong_answer"], "tasks": P["seated"]["tasks"],
                     "interval_resampling_tasks": [boots[49], boots[1949]],
                     "other_pairs_over_the_refutation_line": sorted(k for k, v in others.items() if v["rate"] > TH["H1_refuted_above"]),
                     "pairs_compared": len(others)}
    else:
        hyp["H1"] = {"verdict": "NOT RUN", "reason": "the primary pair has no seated votes"}

    # ---- H2: juror quality sets coverage
    xs, ys = [], []
    for k, v in pairs.items():
        a, b = k.split(" + ")
        ra, rb = juror[a]["cases_correct_of_all"]["rate"], juror[b]["cases_correct_of_all"]["rate"]
        if ra is not None and rb is not None and v["all"]["settled"]["rate"] is not None:
            xs.append(min(ra, rb))
            ys.append(v["all"]["settled"]["rate"])
    rho = L.spearman(xs, ys)
    hyp["H2"] = {"verdict": "NOT RUN" if rho is None else ("SUPPORTED" if rho >= TH["H2_min_spearman"] else "NOT SUPPORTED"), "spearman": rho, "pairs": len(xs)}

    # ---- H3: the gate against a single reviewer, on the same builds
    def balanced(tp, fn, tn, fp):
        if tp + fn == 0 or tn + fp == 0:
            return None
        return (tp / (tp + fn) + tn / (tn + fp)) / 2

    gate_bal = None
    h3_tasks = None           # H3 compares both sides on the same builds: tasks where the primary pair is seated in repeat 0
    if P:
        tp = fn = tn = fp = 0
        cells0 = [c for c in pair_cells(*primary.split(" + ")) if c["rep"] == "0" and c["seated"]]
        h3_tasks = {c["task"] for c in cells0}
        for c in cells0:
            g = gate(c["task"], c["key"])
            gb = gate(c["task"], {x: lab for x, lab in c["key"].items() if x in info[c["task"]]["blind"]})
            for name, (_, ok, _) in info[c["task"]]["builds"].items():
                flagged = (g if ok else gb)[name] == "FAIL"
                tp, fn, tn, fp = tp + (flagged and not ok), fn + (not flagged and not ok), tn + (not flagged and ok), fp + (flagged and ok)
        gate_bal = {"caught_bad": tp, "missed_bad": fn, "passed_good": tn, "failed_good": fp, "balanced_accuracy": balanced(tp, fn, tn, fp)}
    reviewer = {}
    for m, by_task in reviews.items():
        tp = fn = tn = fp = unusable = ev_ok = ev_n = 0
        for tname, rv in by_task.items():
            if tname not in info or (h3_tasks is not None and tname not in h3_tasks):
                continue
            I = info[tname]
            reff = I["builds"]["reference"][0]
            for name, r_ in rv.items():
                f, ok, _ = I["builds"][name]
                if r_["verdict"] is None:
                    unusable += 1
                flagged = r_["verdict"] == "INCORRECT"
                tp, fn, tn, fp = tp + (flagged and not ok), fn + (not flagged and not ok), tn + (not flagged and ok), fp + (flagged and ok)
                if flagged and r_.get("failing_input") is not None:
                    ev_n += 1
                    ev_ok += T.outcome(f, r_["failing_input"]) != T.outcome(reff, r_["failing_input"])
        reviewer[m] = {"caught_bad": tp, "missed_bad": fn, "passed_good": tn, "failed_good": fp, "no_usable_verdict": unusable,
                       "balanced_accuracy": balanced(tp, fn, tn, fp), "failing_inputs_that_really_fail": rate(ev_ok, ev_n)}
    best_rev = max((v["balanced_accuracy"] for v in reviewer.values() if v["balanced_accuracy"] is not None), default=None)
    if gate_bal and gate_bal["balanced_accuracy"] is not None and best_rev is not None:
        lead = gate_bal["balanced_accuracy"] - best_rev
        hyp["H3"] = {"verdict": "SUPPORTED" if lead >= TH["H3_min_gate_lead"] else "NOT SUPPORTED", "gate": gate_bal, "reviewers": reviewer, "gate_lead": lead}
    else:
        hyp["H3"] = {"verdict": "NOT RUN", "gate": gate_bal, "reviewers": reviewer}

    # ---- H4: a missing requirement is caught
    if P and P["seated"]["variants_caught"]["n"]:
        v = P["seated"]["variants_caught"]
        hyp["H4"] = {"verdict": "SUPPORTED" if v["rate"] >= TH["H4_min_variants_caught"] else "NOT SUPPORTED", "variants_caught": v,
                     "missed_though_a_case_could_catch_it": P["seated"]["variants_missed_though_catchable"],
                     "no_case_could_catch_it": P["seated"]["variants_no_case_could_catch"]}
    else:
        hyp["H4"] = {"verdict": "NOT RUN"}

    # ---- H5: the test audit
    def flagged(m, tname, tid):
        v = audit.get(m, {}).get(tname, {}).get(tid, {}).get("verdict")
        return None if v is None else v in ("NOT_REQUIRED", "CONTRADICTS")

    aud = {}
    for m in sorted(audit):
        pc = pn = gf = gn = cite_ok = cite_n = none = 0
        for tname, ts in tests.items():
            if tname not in info or tname not in audit[m]:
                continue
            for t_ in ts:
                f = flagged(m, tname, t_["id"])
                none += f is None
                if t_["kind"] in ("contradicts", "not_required"):
                    pn, pc = pn + 1, pc + bool(f)
                else:
                    gn, gf = gn + 1, gf + bool(f)
                    if t_["kind"] == "good_invalid" and f is False:
                        cite_n += 1
                        cite_ok += audit[m][tname][t_["id"]].get("rule") == t_["rule"]
        aud[m] = {"planted_caught": rate(pc, pn), "good_flagged": rate(gf, gn), "right_rule_cited": rate(cite_ok, cite_n), "no_usable_verdict": none}
    if primary and all(m in audit for m in primary.split(" + ")):
        a, b = primary.split(" + ")
        pc = pn = gf = gn = 0
        for tname, ts in tests.items():
            if tname not in info or tname not in audit[a] or tname not in audit[b]:
                continue
            for t_ in ts:
                both = bool(flagged(a, tname, t_["id"])) and bool(flagged(b, tname, t_["id"]))
                if t_["kind"] in ("contradicts", "not_required"):
                    pn, pc = pn + 1, pc + both
                else:
                    gn, gf = gn + 1, gf + both
        pr, gr = rate(pc, pn), rate(gf, gn)
        ok = pn and pr["rate"] >= TH["H5_min_planted_caught"] and gr["rate"] <= TH["H5_max_good_flagged"]
        hyp["H5"] = {"verdict": "SUPPORTED" if ok else "NOT SUPPORTED", "planted_tests_both_flagged": pr, "good_tests_both_flagged": gr, "jurors": aud}
    else:
        hyp["H5"] = {"verdict": "NOT RUN", "jurors": aud}

    # ---- H6: the shared blind spot is leniency
    seen, lenient, total = set(), 0, 0
    for k, v in pairs.items():
        for w in v["wrong_answers"]:
            if not w["seated"]:
                continue
            total += 1
            lenient += w["truth"] == "INVALID"
            seen.add((w["task"], w["input"]))
    if total:
        lr = rate(lenient, total)
        hyp["H6"] = {"verdict": "SUPPORTED" if lr["rate"] >= TH["H6_min_leniency_share"] else "NOT SUPPORTED", "wrong_answers_that_accept_invalid_input": lr,
                     "distinct_inputs": len(seen)}
    else:
        hyp["H6"] = {"verdict": "NOT RUN", "reason": "no seated pair adopted a wrong answer"}

    # ---- the arbiter and the audit sample
    arbiter = None
    if "paid" in votes:
        caught = n = 0
        detect = []
        for k, v in pairs.items():
            for w in v["wrong_answers"]:
                pv = reps("paid", w["task"]).get("0", {}).get(w["input"])
                n += 1
                caught += pv == w["truth"]
        if P:
            for c in pair_cells(*primary.split(" + ")):
                s, w = len(c["key"]), len(c["wrong"])
                if w:
                    m_ = max(1, math.ceil(TH["audit_sample_fraction"] * s))
                    detect.append(1 - math.comb(s - w, m_) / math.comb(s, m_))
        arbiter = {"accuracy": juror["paid"]["cases_correct_of_all"], "wrong_answers_it_would_correct": rate(caught, n),
                   "chance_a_sample_contains_a_wrong_answer": detect}

    return {"run": run, "tasks": names, "jurors": juror, "pairs": pairs, "primary_pair": primary, "hypotheses": hyp, "arbiter": arbiter,
            "thresholds": TH, "calls": sum(1 for _ in (d / "calls.jsonl").open(encoding="utf-8")) if (d / "calls.jsonl").exists() else 0}


PAIR_HYPOTHESES = ("H1", "H3", "H4", "H5")      # the ones that depend on which pair is seated; H2 and H6 do not


def analyze_all(run: str, primary_pair=None, additions=None) -> dict:
    """The protocol's analysis, plus the same pair-dependent hypotheses for every pair declared
    AFTER the protocol was fixed (thresholds.json `declared_additional_pairs`). An addition is
    scored by the same code and thresholds, and is never mixed into the primary pair's verdicts."""
    s = analyze(run, primary_pair)
    s["declared_additions"] = []
    for add in (TH.get("declared_additional_pairs", []) if additions is None else additions):
        t = analyze(run, add["pair"])
        s["declared_additions"].append({"pair": t["primary_pair"], "declared": add.get("declared"), "why": add.get("why"),
                                        "hypotheses": {k: t["hypotheses"][k] for k in PAIR_HYPOTHESES}})
    return s


def pair_rows(h: dict) -> list:
    """Table rows for the hypotheses that depend on the pair."""
    out = []

    def row(label, text):
        out.append(f"| {label} | **{h[label.split()[0]]['verdict']}** | {text} |")

    h1 = h["H1"]
    row("H1 agreement keeps wrong answers out", f"{h1['primary_pair']}: wrong answers {show(h1['wrong'])}; tasks with a wrong answer {h1['tasks_with_a_wrong_answer']} of {h1['tasks']}; resampling tasks, {pct(h1['interval_resampling_tasks'][0])} to {pct(h1['interval_resampling_tasks'][1])}" if "wrong" in h1 else h1.get("reason", ""))
    row("H3 gate beats a single reviewer", f"gate {pct(h['H3']['gate']['balanced_accuracy'])}, best reviewer {pct(h['H3']['gate']['balanced_accuracy'] - h['H3']['gate_lead'])}" if "gate_lead" in h["H3"] else "not run")
    row("H4 a missing requirement is caught", f"{show(h['H4']['variants_caught'])}; missed though catchable {h['H4']['missed_though_a_case_could_catch_it']}; no case could catch {h['H4']['no_case_could_catch_it']}" if "variants_caught" in h["H4"] else "not run")
    row("H5 planted bad tests are caught", f"both flagged {show(h['H5']['planted_tests_both_flagged'])} of planted; both flagged {show(h['H5']['good_tests_both_flagged'])} of good" if "planted_tests_both_flagged" in h["H5"] else "not run")
    return out


def report(s: dict) -> str:
    L_ = [f"# Stage 1 results: run `{s['run']}`", "",
          f"Generated by `analyze.py` from saved answers. Tasks: {len(s['tasks'])}. Model calls logged: {s['calls']}.",
          "Thresholds are the ones committed in `thresholds.json` before the run.", "", "## Hypotheses", "",
          "| | Verdict | Measured |", "|---|---|---|"]
    h = s["hypotheses"]

    def row(label, text):
        L_.append(f"| {label} | **{h[label.split()[0]]['verdict']}** | {text} |")

    rows = pair_rows(h)
    L_.append(rows[0])
    row("H2 juror quality sets coverage", f"rank correlation {h['H2']['spearman']:.2f} over {h['H2']['pairs']} pairs" if h["H2"]["spearman"] is not None else "too few pairs")
    L_ += rows[1:]
    row("H6 shared mistakes are leniency", show(h["H6"]["wrong_answers_that_accept_invalid_input"]) if "wrong_answers_that_accept_invalid_input" in h["H6"] else h["H6"].get("reason", ""))
    for add in s.get("declared_additions") or []:
        L_ += ["", f"## Declared addition: `{add['pair']}`", "",
               f"**Not part of the original protocol.** Declared {add['declared']}. {add['why']}",
               "Scored by the same code against the same thresholds. It does not replace or change the primary pair's verdicts above.", "",
               "| | Verdict | Measured |", "|---|---|---|", *pair_rows(add["hypotheses"])]
    L_ += ["", "## Jurors", "", "| Juror | Gold items right | Cases right | No answer | Seated | Changed between repeats |", "|---|---|---|---|---|---|"]
    for m, j in s["jurors"].items():
        L_.append(f"| `{m}` | {pct(j['gold']['rate'])} | {pct(j['cases_correct_of_all']['rate'])} | {pct(j['no_answer']['rate'])} | {j['seated']['x']} of {j['seated']['n']} | {pct(j['changed_between_repeats']['rate'])} |")
    L_ += ["", "## Pairs (seated only: both jurors passed the gold items for that task)", "",
           "| Pair | Settled | Wrong answers adopted | Tasks with a wrong answer | Missing-rule builds caught | Correct builds failed |", "|---|---|---|---|---|---|"]
    for k, v in sorted(s["pairs"].items(), key=lambda kv: (kv[1]["seated"]["wrong"]["rate"] or 0, -(kv[1]["seated"]["settled"]["rate"] or 0))):
        p = v["seated"]
        L_.append(f"| `{k}` | {pct(p['settled']['rate'])} of {p['cases']} | {show(p['wrong'])} | {p['tasks_with_a_wrong_answer']} of {p['tasks']} | {pct(p['variants_caught']['rate'])} | {p['correct_builds_failed']['x']} of {p['correct_builds_failed']['n']} |")
    wrongs = [(k, w) for k, v in s["pairs"].items() for w in v["wrong_answers"] if w["seated"]]
    L_ += ["", f"## Wrong answers adopted by seated pairs ({len(wrongs)})", ""]
    for k, w in wrongs[:60]:
        L_.append(f"- `{k}`, {w['task']}, repeat {w['rep']}: {json.dumps(w['input'])} adopted as {w['adopted']}, truth {w['truth']} ({w['stratum']})")
    if h["H5"].get("jurors"):
        L_ += ["", "## Test audit, juror by juror", "", "| Juror | Planted bad tests caught | Good tests flagged | Right rule cited |", "|---|---|---|---|"]
        for m, a in h["H5"]["jurors"].items():
            L_.append(f"| `{m}` | {show(a['planted_caught'])} | {show(a['good_flagged'])} | {show(a['right_rule_cited'])} |")
    if h["H3"].get("reviewers"):
        L_ += ["", "## Single reviewer", "", "| Reviewer | Bad builds caught | Bad builds missed | Good builds passed | Good builds failed | Claimed failing inputs that really fail |", "|---|---|---|---|---|---|"]
        for m, r in h["H3"]["reviewers"].items():
            L_.append(f"| `{m}` | {r['caught_bad']} | {r['missed_bad']} | {r['passed_good']} | {r['failed_good']} | {show(r['failing_inputs_that_really_fail'])} |")
    if s["arbiter"]:
        a = s["arbiter"]
        L_ += ["", "## Arbiter (paid model)", "", f"- Cases right: {show(a['accuracy'])}", f"- Wrong answers adopted by a pair that it would correct: {show(a['wrong_answers_it_would_correct'])}"]
    return "\n".join(L_) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="main")
    a = ap.parse_args(argv)
    s = analyze_all(a.run)
    d = L.run_dir(a.run)
    L.save_json(d / "summary.json", s)
    (d / "RESULTS.md").write_text(report(s), encoding="utf-8")
    for k, v in s["hypotheses"].items():
        print(f"  {k}: {v['verdict']}")
    for add in s["declared_additions"]:
        print(f"  declared addition {add['pair']}: " + ", ".join(f"{k} {v['verdict']}" for k, v in add["hypotheses"].items()))
    print(f"  wrote {d / 'RESULTS.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
