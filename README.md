# A jury of local models: stage 1 protocol, data and scoring code

This folder holds everything needed to check the headline numbers of the second jury experiment
("stage 1", run 2026-11-25 to 26). Five local models voted blind on the answers to ten small,
invented coding tasks, and a paid model arbitrated. The protocol and its pass/fail lines were
written before any model ran.

**Status: staged, not published.** Licensed under the MIT License; see `LICENSE`.

## Headline numbers, and how to reproduce them

| Claim | Figure | Where `analyze.py` prints it |
|---|---|---|
| One strong juror plus a second that must agree: the pre-registered pair `gpt-oss:20b` + `gemma4:12b` | 0 wrong answers of 1,019 settled cases (95% interval 0.0% to 0.4%) | `runs/main/RESULTS.md`, H1 row and the first row of "Pairs" |
| Every pair that included `gpt-oss:20b` | 0 wrong of 1,019, 1,110, 956 and 642 settled | "Pairs", first four rows |
| The six pairs without `gpt-oss:20b` | wrong answers in 1.0% (10 of 997) to 3.2% (19 of 601) of settled cases | "Pairs", last six rows |

Standard library only; checked with Python 3.13. No model is called.

```
python -B analyze.py --run main      # rewrites runs/main/summary.json and runs/main/RESULTS.md
python -B verify_run.py --run main   # re-parses every raw model answer and checks the saved votes match
python -B verify_tasks.py            # checks the tasks by exhaustive enumeration; rewrites verified.json
python -B smoke.py                   # the whole pipeline with scripted jurors (writes runs/smoke/)
```

On the staged copy, `analyze.py` reproduced `RESULTS.md` and `summary.json` byte for byte.
`verify_run.py` reported 10,264 saved answers matching the raw outputs, 0 raw files missing and 3
votes with no usable answer. `verify_tasks.py` reproduced `verified.json` exactly, and `smoke.py`
passed 30 of 30 checks.

Run the commands on a copy if you want to keep the shipped `RESULTS.md` and `summary.json` for
comparison: `analyze.py` overwrites them.

## Files

**Protocol, fixed before the run**

| File | What it is |
|---|---|
| `PROTOCOL.md` | The thesis, six hypotheses with their supported and refuted lines, the named primary pair, the design, the scoring rules, and the deviations recorded after the run. Its link to the first experiment's report points into the original repository and does not resolve here. |
| `thresholds.json` | The same pass/fail lines as data. `analyze.py` reads them. The only post-run addition is `declared_additional_pairs`, recorded as deviation 5. |
| `SPECS.md` | The ten task requests exactly as the models saw them, plus the practice task. |

**Tasks and their checking**

| File | What it is |
|---|---|
| `tasks.py` | The ten tasks: rules, reference implementations, input alphabets and gold items. |
| `refb.py` | A second implementation of every task, written separately from the requests alone. |
| `verify_tasks.py`, `verified.json` | Checks that the two implementations agree on every input up to each task's length limit (about 964,000 in all) and that removing any rule changes behaviour. |

**Harness and scoring**

| File | What it is |
|---|---|
| `stage1.py` | The harness as run: prompts, answer parsing, case building, votes, test audit, single reviewer. |
| `lib.py` | Shared code: seeds, file handling, gate scoring, exact intervals, and the model call. |
| `analyze.py` | Scores a run against `thresholds.json` and writes `RESULTS.md` and `summary.json`. |
| `verify_run.py` | Re-parses every raw answer and checks the saved votes match. |
| `smoke.py`, `fakes.py` | Pipeline test with scripted jurors whose faults are known. No model is called. |

**Data from the run (`runs/main/`)**

| File | What it is |
|---|---|
| `raw/` | 454 files: every raw model answer, one file per step and model (`vote-*`, `propose-*`, `audit-*`, `review-*`). |
| `votes.json` | Every juror's parsed vote, per task, repeat and case. |
| `cases.json` | Per task: the 12 gold items and up to 48 cases, each with its stratum. The right answers are not stored; `tasks.py` computes them. |
| `proposals.json` | The inputs the two primary jurors proposed. |
| `audit.json`, `audit_tests.json` | The test audit: the tests shown, planted bad ones marked, and each juror's labels. |
| `reviews.json` | The single reviewer's verdicts on each build. |
| `calls.jsonl` | One line per model call: step, model, time, wall-clock seconds, answered or not (468 calls). |
| `RESULTS.md`, `summary.json` | The scored results as committed after the run. |

Total size: about 0.86 MB in 477 files, so nothing was dropped. The raw answers are 0.24 MB of it.

## Changes from the copy as run

This public copy names no paid model. Six places that named the paid arbiter's vendor were reworded after the run: two in this README, three in `PROTOCOL.md` (the arbiter line, the note on who wrote the two reference implementations, and the matching limit), and the engine name in `lib.py`, which now reads it from the `JURY_PAID_ENGINE` environment variable. Nothing else changed. The pass/fail lines, tasks, scoring code, raw answers, `RESULTS.md` and `summary.json` are byte for byte as run.

## Rerunning the model calls

Scoring needs no model. To rerun the calls themselves you need Ollama with the five models
(`gpt-oss:20b`, `gemma4:12b`, `phi4:latest`, `deepseek-r1:14b`, `qwen3.5:9b`) and a way to call
them. `lib._real` called a local command-line dispatcher (`charlotte dispatch`) that forwarded each
prompt to Ollama at `OLLAMA_URL` with tools off, and the paid arbiter through a
subscription (set `JURY_PAID_ENGINE` to that engine's name). To use your own client, replace `lib._real` with a function that sends the prompt to
`OLLAMA_URL` for the named model and returns the text of the answer. Then:

```
python -B stage1.py plan --arbiter
python -B stage1.py run --run mine --arbiter
python -B analyze.py --run mine
```

Answered calls are saved under `runs/<run>/raw/` and reused, so a run can be resumed.

## Limits

- **Small tasks.** Ten short text-parsing and classification functions with four to six rules
  each. Nothing here says how the method does on larger code.
- **One workstation, one run.** A single 16 GB graphics card, Ollama 0.32.14, model versions as
  served that night. `gemma4:12b` crashed on 33 of its 80 first attempts, which cost the
  pre-registered pair half its task-repeats.
- **One strong juror model.** Every clean pair contained `gpt-oss:20b`. The data shows a strong
  juror was needed; it cannot say what makes a juror strong enough, or whether another model
  would do.
- **References from one vendor family.** Both implementations that define the right answers were
  written by models from one vendor, the same vendor as the paid arbiter. Their agreement rules
  out a slip by one author, not a misreading they would share.
- **One pair was added after the interim results** (`gpt-oss:20b` + `deepseek-r1:14b`, deviation
  5). It is weaker evidence than the pair named in advance.
- 67 of the 84 wrong answers adopted by seated pairs were inputs wrapped in literal quote
  characters. Only `gemma4:12b` proposed such inputs (deviation 4).
