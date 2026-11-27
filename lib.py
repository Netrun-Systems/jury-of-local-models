"""Shared pieces of the stage 1 harness: seeds, files, answer parsing, builds, model calls."""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import random
import re
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

import tasks as T

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
SEED = 20261125
CLI = str(Path.home() / ".cargo" / "bin" / "charlotte.exe")
# The paid arbiter's engine name for the dispatcher. Not named in the public copy; set it to rerun.
PAID_ENGINE = os.environ.get("JURY_PAID_ENGINE", "")
THINK_OFF = {"gemma4:12b"}          # crashes with thinking on under Ollama 0.32.14 on this workstation
THRESHOLDS = json.loads((HERE / "thresholds.json").read_text(encoding="utf-8"))


def rng(*parts) -> random.Random:
    """A generator that depends only on SEED and the names given (never on Python's hash())."""
    digest = hashlib.sha256(("|".join(str(p) for p in (SEED, *parts))).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def run_dir(run: str) -> Path:
    d = RUNS / run
    (d / "raw").mkdir(parents=True, exist_ok=True)
    return d


def load_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path: Path, obj) -> None:
    """Write to a temporary file, then swap it in, retrying briefly.

    The first real run's replay pass rewrote votes.json many times a second and Windows refused
    one open with "Invalid argument" (another process had the file for an instant). The run died,
    though no data was lost. A failed swap now leaves the previous file whole and is retried."""
    text = json.dumps(obj, indent=1, ensure_ascii=False) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    last = None
    for attempt in range(8):
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
            return
        except OSError as e:
            last = e
            time.sleep(0.25 * (attempt + 1))
    raise last


def last_json_object(text: str):
    """The last parseable JSON object in a model's answer (fenced or bare). None if there is none."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    dec = json.JSONDecoder()
    outer, pos = None, 0
    for m in re.finditer(r"\{", text):
        if m.start() < pos:
            continue                          # inside an object already taken: keep the outermost
        try:
            obj, end = dec.raw_decode(text[m.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            outer, pos = obj, m.start() + end
    return outer


# ------------------------------------------------------------------------------ truth and builds
_REF: dict = {}


def ref(task: T.Task) -> Callable:
    if task.name not in _REF:
        _REF[task.name] = T.load(T.source(task), task.fn)
    return _REF[task.name]


def truth(task: T.Task, x: str) -> str:
    """The label a juror should give for x (from the reference)."""
    return T.label_of(task, T.outcome(ref(task), x))


def second_source(task: T.Task) -> str:
    """Source of the independently written implementation, with the helpers it relies on."""
    text = (HERE / "refb.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    keep = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant):
            continue                                     # the module docstring
        if isinstance(node, ast.FunctionDef) and node.name != task.fn and not node.name.startswith("_"):
            continue                                     # the other tasks' functions
        keep.append(node)                                # the function, its helpers, imports and constants
    return "\n\n".join(ast.get_source_segment(text, n) for n in keep) + "\n"


def builds(task: T.Task) -> dict:
    """name -> (source, is_correct, dropped_rule). The code a gate or a reviewer is shown."""
    out = {"reference": (T.source(task), True, None), "second": (second_source(task), True, None)}
    for r in T.variant_rules(task):
        out[f"drop-{r}"] = (T.source(task, skip=r), False, r)
    return out


_VARIANTS: dict = {}


def variants(task: T.Task) -> dict:
    """rule -> the reference with that one rule removed."""
    if task.name not in _VARIANTS:
        _VARIANTS[task.name] = {r: T.load(T.source(task, skip=r), task.fn) for r in T.variant_rules(task)}
    return _VARIANTS[task.name]


def deciding_rules(task: T.Task, x: str) -> list:
    """Rules whose deletion alone changes what happens to x. One entry = a single-rule input."""
    base = T.outcome(ref(task), x)
    return [r for r, f in variants(task).items() if T.outcome(f, x) != base]


# ------------------------------------------------------------------------------------ statistics
def interval(x: int, n: int, conf: float = 0.95) -> tuple:
    """Exact (Clopper-Pearson) two-sided interval for x of n."""
    if n == 0:
        return (0.0, 1.0)
    a = (1 - conf) / 2

    def cdf(k, p):
        # In log space: math.comb(n, i) * p ** i overflows a float once n passes about 1,000
        # (the first real run had 1,440 cases and the scorer crashed on it).
        if p <= 0.0:
            return 1.0
        if p >= 1.0:
            return 1.0 if k >= n else 0.0
        lp, lq = math.log(p), math.log1p(-p)
        terms = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq for i in range(0, k + 1)]
        top = max(terms)
        return min(1.0, math.exp(top) * sum(math.exp(t - top) for t in terms))

    def solve(f):
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(mid) else (lo, mid)
        return (lo + hi) / 2

    low = 0.0 if x == 0 else solve(lambda p: 1 - cdf(x - 1, p) < a)
    high = 1.0 if x == n else solve(lambda p: cdf(x, p) > a)
    return (low, high)


def spearman(xs: list, ys: list) -> Optional[float]:
    if len(xs) < 3:
        return None

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sx * sy)


# ------------------------------------------------------------------------------------ model calls
class Deadline(Exception):
    """Raised instead of starting a model call after the run's deadline."""


_DEADLINE: Optional[float] = None


def set_deadline(hhmm: str) -> None:
    """Stop starting new model calls at the next local HH:MM."""
    global _DEADLINE
    h, m = (int(p) for p in hhmm.split(":"))
    now = time.localtime()
    target = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, h, m, 0, 0, 0, -1))
    _DEADLINE = target if target > time.time() else target + 86400
    print(f"  no new call will start after {time.strftime('%Y-%m-%d %H:%M', time.localtime(_DEADLINE))}", flush=True)


def keep_awake() -> None:
    """Ask Windows not to sleep while this process runs (released when it exits). No setting is changed."""
    try:
        import ctypes  # noqa: PLC0415
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    except Exception:  # noqa: BLE001 - not Windows, or not allowed: the run simply does not hold the system awake
        pass


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)


def dispatch(run: str, model: str, step: str, prompt: str, meta: Optional[dict] = None) -> str:
    """One model call, saved raw and reused on a rerun. Returns "" for a failed call (logged).

    model: an Ollama tag, "paid" (the paid model, through a subscription, tools off), or "fake:<kind>"
    (scripted jurors for the smoke test: no model is called)."""
    d = run_dir(run)
    raw = d / "raw" / f"{_safe(step)}__{_safe(model)}.txt"
    if raw.exists() and raw.read_text(encoding="utf-8").strip():
        return raw.read_text(encoding="utf-8")
    if _DEADLINE is not None and time.time() > _DEADLINE and not model.startswith("fake:"):
        raise Deadline(f"the deadline passed before {step} for {model}")
    t0 = time.time()
    rec = {"step": step, "model": model, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if model.startswith("fake:"):
        import fakes  # noqa: PLC0415
        out = fakes.answer(model.split(":", 1)[1], meta or {})
    else:
        out = _real(model, prompt, rec)
        if not out.strip() and model != "paid":
            # A thinking model can spend its whole turn thinking and answer nothing. One retry, thinking off.
            rec["retried_thinking_off"] = True
            out = _real(model, prompt, rec, think_off=True)
    rec["wall_s"] = round(time.time() - t0, 1)
    rec["answered"] = bool(out.strip())
    with (d / "calls.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    if out.strip():
        raw.write_text(out, encoding="utf-8")
    print(f"  [{step}] {model} {rec['wall_s']}s {'ok' if out.strip() else 'NO ANSWER'}", flush=True)
    return out


def _real(model: str, prompt: str, rec: dict, think_off: bool = False) -> str:
    paid = model == "paid"
    if paid and not PAID_ENGINE:
        raise SystemExit("set JURY_PAID_ENGINE to the dispatcher engine name for the paid arbiter")
    cmd = [CLI, "dispatch", "--stdin", "--engine", PAID_ENGINE if paid else "ollama", "--no-failover", "--no-tools", "--json"]
    if not paid:
        cmd += ["--model", model]
    env = dict(os.environ)
    if not paid and (think_off or model in THINK_OFF):
        env["CHARLOTTE_OLLAMA_THINK"] = "false"
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=1800, env=env)
    except subprocess.TimeoutExpired:
        rec["error"] = "timeout after 1800 s"
        return ""
    out = p.stdout or ""
    try:
        d = json.loads(out[out.index("{"):])
    except (ValueError, json.JSONDecodeError):
        rec["error"] = (out[-200:] + (p.stderr or "")[-200:]).strip()
        return ""
    want = PAID_ENGINE if paid else "ollama"
    tried = [a.get("engine") for a in d.get("attempts") or [] if isinstance(a, dict)]
    answered_by = d.get("engine")
    if any(e and not str(e).startswith(want) for e in [answered_by, *tried] if e):
        raise SystemExit(f"[{rec['step']}] ENGINE VIOLATION: wanted {want}, saw {answered_by} / {tried}")
    if d.get("ok") is False or not answered_by:
        rec["error"] = str(d.get("error"))[:300]
        return ""
    if not paid and d.get("model") != model:
        raise SystemExit(f"[{rec['step']}] MODEL VIOLATION: asked for {model}, answered by {d.get('model')}")
    return re.sub(r"<think>.*?</think>", "", d.get("output") or "", flags=re.S)
