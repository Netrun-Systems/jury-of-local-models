"""End-to-end check of the harness with scripted jurors. No model is called.

Runs every stage on every task with jurors whose faults are known (fakes.py), then checks that
the scorer reports what those faults must produce. If this fails, do not trust a real run.

  python smoke.py
"""
from __future__ import annotations

import shutil
import sys

import analyze as A
import lib as L
import stage1 as S

RUN = "smoke"
FAKES = ["oracle", "oracle2", "blindA", "blindB", "blindC", "noisy", "lister", "mute"]


def main() -> int:
    target = L.RUNS / RUN
    if target.exists() and target.name == RUN and target.parent == L.RUNS:
        shutil.rmtree(target)
    S.main(["run", "--run", RUN, "--repeats", "2",
            "--jurors", ",".join(f"fake:{k}" for k in FAKES),
            "--proposers", "fake:oracle,fake:noisy", "--reviewers", "fake:oracle,fake:blindA"])
    checks = []

    def check(name, ok, detail=""):
        checks.append(ok)
        print(f"  {'ok  ' if ok else 'FAIL'} {name}{'  ' + str(detail) if detail else ''}")

    s = A.analyze(RUN, primary_pair=["fake:oracle", "fake:oracle2"])
    j, p, h = s["jurors"], s["pairs"], s["hypotheses"]
    check("ten tasks analysed, the practice task left out", len(s["tasks"]) == 10 and "practice_pin" not in s["tasks"], s["tasks"])
    for m in ("fake:oracle", "fake:oracle2", "fake:lister"):
        check(f"{m} is right on every case and always seated", j[m]["cases_correct_of_all"]["rate"] == 1.0 and j[m]["seated"]["x"] == j[m]["seated"]["n"])
    check("the numbered-list answer was parsed (no missing answers)", j["fake:lister"]["no_answer"]["x"] == 0)
    check("the mute juror has no answers and is never seated", j["fake:mute"]["no_answer"]["rate"] == 1.0 and j["fake:mute"]["seated"]["x"] == 0)
    check("the noisy juror is right 75% to 93% of the time", 0.75 <= j["fake:noisy"]["cases_correct_of_all"]["rate"] <= 0.93, j["fake:noisy"]["cases_correct_of_all"]["rate"])
    check("the noisy juror's answers change between repeats", j["fake:noisy"]["changed_between_repeats"]["x"] > 0)
    check("a perfect juror's answers do not change between repeats", j["fake:oracle"]["changed_between_repeats"]["x"] == 0)

    oo = p["fake:oracle + fake:oracle2"]["seated"]
    check("two perfect jurors settle everything, with nothing wrong", oo["settled"]["rate"] == 1.0 and oo["wrong"]["x"] == 0)
    check("their gate never fails a correct build", oo["correct_builds_failed"]["x"] == 0 and oo["correct_builds_failed"]["n"] > 0)
    check("their gate catches every missing rule a case could catch", oo["variants_missed_though_catchable"] == 0 and oo["variants_caught"]["x"] > 0, oo["variants_caught"])
    check("H1 is supported for the perfect pair", h["H1"]["verdict"] == "SUPPORTED", h["H1"]["verdict"])
    check("H4 counts the caught variants", h["H4"]["verdict"] in ("SUPPORTED", "NOT SUPPORTED") and h["H4"]["variants_caught"]["n"] > 0, h["H4"])

    ob = p["fake:blindA + fake:oracle"]["all"]
    check("perfect + blind: nothing wrong adopted, but less settled", ob["wrong"]["x"] == 0 and ob["settled"]["rate"] < 1.0, ob["settled"]["rate"])
    bb = p["fake:blindA + fake:blindB"]
    check("two jurors with the same blind spot adopt wrong answers", bb["all"]["wrong"]["x"] > 0, bb["all"]["wrong"])
    check("every one of those accepts an invalid input", bb["all"]["wrong_that_accept_invalid_input"] == bb["all"]["wrong"]["x"])
    check("that key fails correct builds (false alarms)", bb["all"]["correct_builds_failed"]["x"] > 0, bb["all"]["correct_builds_failed"])
    check("the gold items unseat a rule-blind juror on most tasks", j["fake:blindA"]["seated"]["rate"] < 0.5, j["fake:blindA"]["seated"])
    bc = p["fake:blindA + fake:blindC"]["all"]
    check("different blind spots: fewer wrong answers than the same blind spot", bc["wrong"]["x"] < bb["all"]["wrong"]["x"], (bc["wrong"]["x"], bb["all"]["wrong"]["x"]))

    rv = h["H3"]["reviewers"]
    check("the perfect reviewer scores 100%, and its failing inputs really fail", rv["fake:oracle"]["balanced_accuracy"] == 1.0
          and rv["fake:oracle"]["failing_inputs_that_really_fail"]["rate"] == 1.0, rv["fake:oracle"])
    check("the reviewer that approves everything scores 50%", rv["fake:blindA"]["balanced_accuracy"] == 0.5, rv["fake:blindA"]["balanced_accuracy"])
    au = h["H5"]["jurors"]
    check("audit: a perfect juror catches every planted test and flags no good one", au["fake:oracle"]["planted_caught"]["rate"] == 1.0
          and au["fake:oracle"]["good_flagged"]["x"] == 0 and au["fake:oracle"]["right_rule_cited"]["rate"] == 1.0, au["fake:oracle"])
    check("audit: a juror that approves everything catches none", au["fake:blindA"]["planted_caught"]["x"] == 0)
    check("H5 is supported for the perfect pair", h["H5"]["verdict"] == "SUPPORTED", h["H5"]["verdict"])
    check("H2 has a rank correlation", h["H2"]["spearman"] is not None, h["H2"])

    s2 = A.analyze(RUN, primary_pair=["fake:blindA", "fake:blindB"])
    check("with a blind pair as primary, H1 is not supported", s2["hypotheses"]["H1"]["verdict"] != "SUPPORTED", s2["hypotheses"]["H1"])
    s3 = A.analyze_all(RUN, primary_pair=["fake:oracle", "fake:oracle2"],
                       additions=[{"pair": ["fake:blindA", "fake:blindB"], "declared": "in the smoke test", "why": "A pair with a shared blind spot."}])
    add = s3["declared_additions"][0]
    check("a declared additional pair is scored separately, by the same rules", add["hypotheses"]["H1"]["verdict"] == s2["hypotheses"]["H1"]["verdict"]
          and set(add["hypotheses"]) == {"H1", "H3", "H4", "H5"}, add["hypotheses"]["H1"]["verdict"])
    check("declaring an addition leaves the primary pair's verdicts untouched", s3["hypotheses"] == s["hypotheses"])
    text = A.report(s3)
    check("the report renders, with the addition marked as outside the protocol", "## Hypotheses" in text and "| H1" in text
          and "## Declared addition" in text and "Not part of the original protocol" in text)
    (target / "RESULTS.md").write_text(text, encoding="utf-8")
    print(f"\n{sum(checks)} of {len(checks)} checks passed")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
