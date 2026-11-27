# Jury experiment, stage 1: protocol

**Written 2026-11-25, before any model was run on these tasks.** The thresholds below are also in
`thresholds.json`, which `analyze.py` reads. Changing either after a run is a deviation and must
be recorded at the end of this file.

Follows [the first experiment](../2026-11-24-offline-jury/REPORT.md), which rested on two tasks
and 148 cases.

## The thesis under test

> When two competent models vote blind and must agree, their individual mistakes become unsettled
> cases, not wrong answers. Which models are seated changes how much gets settled, far more than
> how much is wrong. The remaining risk is a shared blind spot, mostly leniency toward malformed
> input.

## Hypotheses and what would count

The **primary pair** is fixed in advance: `gpt-oss:20b` + `gemma4:12b`. A juror is **seated** for
a task when it gets at least 90% of that task's gold items right (11 of 12). Only seated votes
count toward H1, H4 and H6.

| | Claim | Supported if | Refuted if |
|---|---|---|---|
| H1 | The agreement rule keeps wrong answers out | Primary pair adopts wrong answers in at most 1.0% of settled cases, over at least 299 settled cases, with a wrong answer in at most 1 task of 10 | The rate is above 2.0% |
| H2 | Juror quality sets coverage | Across all pairs, rank correlation of at least 0.6 between the weaker juror's accuracy and the share of cases the pair settles | Below 0.6 |
| H3 | The gate beats a single model reviewer | On the same builds, the gate's balanced accuracy is at least 15 points above the reviewer's | The lead is smaller |
| H4 | A missing requirement is caught | The primary pair's gate fails at least 80% of builds that have one rule removed | Below 80% |
| H5 | Planted bad tests are caught | Both jurors of the primary pair flag at least 75% of planted bad tests, and both flag at most 15% of good ones | Either fails |
| H6 | Shared mistakes are leniency | Of wrong answers adopted by seated pairs, at least 60% accept an input that should be rejected | Below 60% |

H1 between 1.0% and 2.0%, or on fewer than 299 settled cases, is **inconclusive**, not supported.

## Tasks

Ten small functions, invented for this experiment so no model can have memorised them
(`tasks.py`, requests in `SPECS.md`). Six return a parsed value or raise an error; four return a
label. Each has four to six numbered rules. One more task, `practice_pin`, exists only to check
the plumbing with real models and is never analysed.

Checked by `verify_tasks.py`, with no model involved:

- A second implementation of every task was written by a separate agent from the written request
  alone. It agrees with the first on **every** string of each task's alphabet up to its length
  limit: about 964,000 inputs, 0 disagreements.
- Every rule matters: removing any one rule changes the function's behaviour on at least one input.

Both implementations were written by models from one vendor. Agreement rules out a slip by one author. It
does not rule out a misreading both would share.

## Design

For each task:

1. **Proposals.** The two primary jurors each propose inputs for every rule: three that break only
   that rule, two valid ones close to breaking it, and six varied valid inputs.
2. **Cases.** Up to 48 per task, in four strata.
   - `proposal`, `edit` (one small edit away from an input someone called valid) and `random` are
     chosen **without** the reference, as the method would run in real use.
   - `valid-sample` is drawn **with** the reference. Blind generation yields almost only invalid
     inputs, and a wrongly rejected valid input must be measurable.
   - An input the two implementations disagree on is dropped and listed.
3. **Gold items.** Twelve inputs with known answers are mixed into every vote. They decide whether
   a juror is seated. A rule with fewer than six single-rule inputs gives none to the gold items,
   so gold never uses up a rule's only way of being caught.
4. **Votes.** Each juror answers every item blind, three times, in a different order each time, in
   chunks of 30. For value tasks a juror says only VALID or INVALID; the harness computes values.
5. **Test audit.** Each juror audits 12 tests per task: 8 good, and 4 planted bad ones (2 that
   contradict the request, 2 that assert something the request never says). The juror must name
   the rule that decides each.
6. **Builds.** The reference, the second implementation, and one build per rule with that rule
   removed. Source for a rule-removed build is the reference with those lines deleted.
7. **Single reviewer.** `qwen3.5:9b`, the default local model, reads each build and says correct or
   incorrect. If it names a failing input, the harness runs it.
8. **Arbiter.** The paid model (a subscription, tools off) votes once on every item.

Jurors: `gpt-oss:20b`, `gemma4:12b`, `phi4:latest`, `deepseek-r1:14b`, `qwen3.5:9b`.

## Scoring rules fixed in advance

- A case is **settled** when both jurors gave the same usable answer. No usable answer counts as
  no vote; the case is unsettled.
- A **wrong answer** is a settled case whose label differs from the reference.
- The **gate** fails a build if it disagrees with any settled case, passes it if none disagree and
  at least 10 cases are settled, and is otherwise inconclusive.
- **A missing rule only counts as caught on the three blind strata.** Cases chosen with the
  reference cannot earn credit for H3 or H4.
- For H3 both sides are scored on the same builds: those of the tasks where the primary pair is
  seated in the first repeat. Flagging a bad build is a hit; flagging a good one is a false alarm.
  Balanced accuracy is the mean of the two rates.
- For H5 a planted test is caught when the juror answers NOT_REQUIRED or CONTRADICTS.
- An empty answer from a model is retried once with thinking off. `gemma4:12b` always runs with
  thinking off, because it crashes with thinking on under this workstation's Ollama 0.32.14.
- Intervals are exact 95% intervals over cases. Cases within a task are not independent, so H1
  also reports an interval from resampling whole tasks.

## What this stage cannot show

- Ten tasks is still few. They are all small text-parsing and classification functions.
- Truth is two implementations written by one vendor's models that agree.
- `tags` has only six valid inputs in its whole domain, so it tests wrongly rejected inputs weakly.
- One run on one workstation. Model versions are whatever Ollama serves on the night.

## How to run

```
python verify_tasks.py                 # the tasks themselves, by exhaustive enumeration
python smoke.py                        # the whole pipeline with scripted jurors, no model
python stage1.py plan --arbiter        # how many calls a run makes
python stage1.py run --run main --arbiter --deadline 07:30
python analyze.py --run main           # writes runs/main/RESULTS.md
```

A run is resumable: every answered call is saved under `runs/<run>/raw/` and reused.

## Deviations

Recorded 2026-11-25, after the first run window.

1. **The run was started early and stopped by its deadline.** At Daniel's request it ran from
   15:36 to 18:20 PT on 2026-11-25, not overnight. It reached the last juror. Still to run: most
   of `qwen3.5:9b` (3 of 10 tasks done), the whole single-reviewer stage, and the second pass
   that retries unanswered calls. The 23:00 task resumes it. **Results read before then are
   interim.** No threshold was changed after reading them.
2. **A scorer bug was fixed after the run.** `lib.interval` overflowed on counts above about
   1,000 and `analyze.py` crashed, so no results file was written. The interval is now computed
   in log space. It matches the old formula to 13 decimal places wherever the old one worked. No
   scoring rule changed.
3. **`gemma4:12b` crashed with thinking off too.** The protocol assumed thinking-off avoids the
   Ollama crash. In this run 33 of its 80 calls failed on the first attempt with the same CUDA
   error, and 14 failed twice. Those 14 have no answer yet. A chunk with no answer leaves its gold
   items unanswered, which unseats the juror for that task and repeat, as the scoring rules say.
4. **One proposer wrapped inputs in quote characters.** 57 of `gemma4:12b`'s 292 proposed inputs
   contain literal quote characters; none of `gpt-oss:20b`'s do. They are legitimate inputs (the
   right answer is "invalid"), but they make up 29 of the 48 cases for `tags` and 19 of 48 for
   `score_band`. Any figure "without quote-wrapped inputs" in a report is a post hoc sensitivity
   check, not part of this protocol.
5. **A second pair was declared after the interim results.** `gpt-oss:20b` + `deepseek-r1:14b`,
   on Daniel's decision, because `gemma4:12b`'s crashes cost the primary pair half its
   task-repeats. It is reported in its own section for H1, H3, H4 and H5, scored by the same code
   against the same thresholds. It does not replace the primary pair, and no primary verdict
   changes. **It was chosen knowing its interim result** (0 wrong answers of 956 settled), so it is
   weaker evidence than a pair fixed in advance. `thresholds.json` lists it under
   `declared_additional_pairs`; every other value in that file is unchanged.
6. **The run finished in a second window, and its replay pass crashed.** The 23:00 task ran
   from 23:00 on 2026-11-25 to 01:18 on 2026-11-26 and completed every stage: 130 more calls, all
   answered, including the 14 `gemma4:12b` calls that had failed. The second pass, which only
   replays saved answers, then died on a Windows file error while rewriting `votes.json`
   ("Invalid argument"). No data was lost: `verify_run.py` re-parsed every raw answer and all
   10,264 saved answers match, with nothing missing. Three single votes have no usable answer.
   Since then `lib.save_json` writes to a temporary file and swaps it in with retries, and
   `config.json` is written at the start of a run. This run has no `config.json` for that reason.
