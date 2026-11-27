"""The ten fresh tasks for stage 1, plus one practice task that is never analysed.

Each task is a small function of one string with numbered rules. The reference is written as
marked source: a line ending in `#R3` belongs to rule R3. That gives, from one text:

  * the reference            = every line
  * a rule-deletion variant  = every line except those marked with that rule

so a variant is literally "the reference with one requirement missing", and both have natural
source that a reviewer can be shown. Truth is always the reference's behaviour; nothing here is
shown to a model except `spec(task)` and, for the reviewer, build source.

`value` (validity tasks only) computes the result of an input ASSUMED to be valid. Jurors only say
VALID or INVALID; the harness computes values (rule 4 of the first experiment).
"""
from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Task:
    name: str
    fn: str
    kind: str                      # "validity" | "label"
    alphabet: str
    maxlen: int
    intro: str
    rules: dict
    returns: str
    examples: list
    marked: str
    labels: list = field(default_factory=list)      # label tasks: every label except INVALID
    value: Optional[Callable] = None
    practice: bool = False


_MARK = re.compile(r"\s+#(R\d+)$")


def source(task: Task, skip: Optional[str] = None) -> str:
    out = []
    for line in task.marked.strip("\n").split("\n"):
        m = _MARK.search(line)
        if m and m.group(1) == skip:
            continue
        out.append(_MARK.sub("", line).rstrip())
    return "\n".join(out) + "\n"


def variant_rules(task: Task) -> list:
    return sorted({m.group(1) for line in task.marked.split("\n") if (m := _MARK.search(line))}, key=lambda r: int(r[1:]))


def load(src: str, fn: str) -> Callable:
    ns: dict = {}
    exec(compile(src, f"<{fn}>", "exec"), ns)       # noqa: S102 - our own task source, or a build under test
    return ns[fn]


def outcome(f: Callable, x: str) -> str:
    """Canonical result of f(x): a JSON value, 'ValueError', or 'CRASH:<type>'."""
    try:
        v = f(x)
    except ValueError:
        return "ValueError"
    except Exception as e:  # noqa: BLE001 - a build may fail in any way; that is an outcome
        return f"CRASH:{type(e).__name__}"
    try:
        return json.dumps(["ok", v])
    except TypeError:
        return f"CRASH:unserialisable {type(v).__name__}"


def domain(task: Task):
    for n in range(task.maxlen + 1):
        for t in itertools.product(task.alphabet, repeat=n):
            yield "".join(t)


def vote_labels(task: Task) -> list:
    return ["VALID", "INVALID"] if task.kind == "validity" else [*task.labels, "INVALID"]


def label_of(task: Task, out: str) -> str:
    """The label a result corresponds to (what a juror is asked to give for that input)."""
    if out == "ValueError":
        return "INVALID"
    if out.startswith("CRASH"):
        return "CRASH"
    return "VALID" if task.kind == "validity" else json.loads(out)[1]


def expected(task: Task, x: str, label: str) -> Optional[str]:
    """The outcome a build must produce for input x if `label` is the adopted answer.
    None = the harness cannot compute it (the label says VALID but the input is not computable)."""
    if label == "INVALID":
        return "ValueError"
    if task.kind == "label":
        return json.dumps(["ok", label])
    out = outcome(task.value, x)
    return out if out.startswith("[") else None


def spec(task: Task) -> str:
    rules = "\n".join(f"{k}. {v}" for k, v in task.rules.items())
    ex = ", ".join(f"`{e}`" for e in task.examples)
    return (f"Write a Python function `{task.fn}(s)` that takes one string.\n\n{task.intro}\n"
            f"Examples of valid input: {ex}.\n\nRules:\n{rules}\n\n{task.returns}\n"
            "Any input that does not fit the description, or breaks any rule, raises ValueError. "
            "Nothing is trimmed or corrected: the input is taken exactly as given. Use only the standard library.")


# ---------------------------------------------------------------------------------------------
BIN = Task(
    name="bin_code", fn="parse_bin", kind="validity", alphabet="ABC01234xyz-", maxlen=5,
    intro="A bin code names a storage bin. It is an aisle letter, then a level digit, then optionally a hyphen and a slot letter.",
    rules={"R1": "The aisle is the capital letter `A` or `B`.",
           "R2": "The level is a digit from `1` to `3`.",
           "R3": "A slot, when present, is a hyphen followed by the lowercase letter `x` or `y`.",
           "R4": "Aisle `B` has no level 3.",
           "R5": "Nothing may follow the slot."},
    returns="Return a tuple `(aisle, level, slot)`: the aisle letter, the level as an integer, and the slot letter, or `None` when there is no slot. `parse_bin(\"B1-x\")` returns `(\"B\", 1, \"x\")`.",
    examples=["A2", "B1-x", "A3-y"],
    value=lambda s: (s[0], int(s[1]), s[3] if len(s) == 4 else None),
    marked='''
def parse_bin(s):
    aisle, level, rest = s[:1], s[1:2], s[2:]
    if not aisle.isalpha() or not level.isdigit():
        raise ValueError("not a bin code")
    if aisle not in ("A", "B"):                                             #R1
        raise ValueError("unknown aisle")                                   #R1
    if level not in ("1", "2", "3"):                                        #R2
        raise ValueError("level out of range")                              #R2
    if rest and (rest[:1] != "-" or rest[1:2] not in ("x", "y")):           #R3
        raise ValueError("bad slot")                                        #R3
    if aisle == "B" and level == "3":                                       #R4
        raise ValueError("aisle B has no level 3")                          #R4
    if len(rest) > 2:                                                       #R5
        raise ValueError("unexpected characters after the slot")            #R5
    return (aisle, int(level), rest[1:2] or None)
''')

SPAN = Task(
    name="span", fn="parse_span", kind="validity", alphabet="0123456789-", maxlen=4,
    intro="A span is written as a start digit, a hyphen and an end digit: exactly three characters.",
    rules={"R1": "Neither digit may be `0`.",
           "R2": "The start must be less than the end.",
           "R3": "The end may be at most 5 more than the start.",
           "R4": "The digit `7` is reserved and may not be used at either end."},
    returns="Return a tuple `(start, end)` of integers. `parse_span(\"2-6\")` returns `(2, 6)`.",
    examples=["2-6", "1-2", "4-9"],
    value=lambda s: (int(s[0]), int(s[2])),
    marked='''
def parse_span(s):
    if len(s) != 3 or not s[0].isdigit() or s[1] != "-" or not s[2].isdigit():
        raise ValueError("not a span")
    start, end = int(s[0]), int(s[2])
    if start == 0 or end == 0:                                              #R1
        raise ValueError("zero is not allowed")                             #R1
    if start >= end:                                                        #R2
        raise ValueError("start must be less than end")                     #R2
    if end - start > 5:                                                     #R3
        raise ValueError("span too long")                                   #R3
    if start == 7 or end == 7:                                              #R4
        raise ValueError("7 is reserved")                                   #R4
    return (start, end)
''')

TAGS = Task(
    name="tags", fn="parse_tags", kind="validity", alphabet="abcd+", maxlen=6,
    intro="A tag list is one or more tags joined by `+`. Each tag is a single lowercase letter.",
    rules={"R1": "The only tags are `a`, `b` and `c`.",
           "R2": "A tag may appear only once.",
           "R3": "Tags must not be out of alphabetical order: a later tag may not come before an earlier letter.",
           "R4": "A list holds at most two tags."},
    returns="Return a tuple of the tags in the order given. `parse_tags(\"a+c\")` returns `(\"a\", \"c\")`.",
    examples=["a", "a+c", "b+c"],
    value=lambda s: tuple(s.split("+")),
    marked='''
def parse_tags(s):
    parts = s.split("+")
    if any(len(p) != 1 or not p.isalpha() for p in parts):
        raise ValueError("not a tag list")
    if any(p not in ("a", "b", "c") for p in parts):                        #R1
        raise ValueError("unknown tag")                                     #R1
    if len(set(parts)) != len(parts):                                       #R2
        raise ValueError("repeated tag")                                    #R2
    if any(x > y for x, y in zip(parts, parts[1:])):                        #R3
        raise ValueError("tags out of order")                               #R3
    if len(parts) > 2:                                                      #R4
        raise ValueError("too many tags")                                   #R4
    return tuple(parts)
''')


def _level_value(s):
    negative = s.startswith("-")
    whole, _, frac = (s[1:] if negative else s).partition(".")
    halves = int(whole) * 2 + (1 if frac == "5" else 0)
    return -halves if negative else halves


LEVEL = Task(
    name="level", fn="parse_level", kind="validity", alphabet="0159.-", maxlen=5,
    intro="A level reading is an optional minus sign, then one or more digits (the whole part), then optionally a decimal point and exactly one digit.",
    rules={"R1": "The whole part has no leading zero, unless it is the single digit `0`.",
           "R2": "The only fraction allowed is `.5`.",
           "R3": "The whole part must be 9 or less.",
           "R4": "Minus zero is not allowed: `-0` is invalid. `-0.5` is valid."},
    returns="Return the reading counted in halves, as an integer. `parse_level(\"1.5\")` returns `3`, `parse_level(\"-5\")` returns `-10`, `parse_level(\"0\")` returns `0`.",
    examples=["5", "-1.5", "0.5", "9"],
    value=_level_value,
    marked='''
def parse_level(s):
    negative = s.startswith("-")
    body = s[1:] if negative else s
    whole, dot, frac = body.partition(".")
    if not whole.isdigit() or (dot and (len(frac) != 1 or not frac.isdigit())):
        raise ValueError("not a level reading")
    if len(whole) > 1 and whole[0] == "0":                                  #R1
        raise ValueError("leading zero")                                    #R1
    if dot and frac != "5":                                                 #R2
        raise ValueError("only .5 is allowed")                              #R2
    if int(whole) > 9:                                                      #R3
        raise ValueError("out of range")                                    #R3
    if negative and int(whole) == 0 and not dot:                            #R4
        raise ValueError("minus zero")                                      #R4
    halves = int(whole) * 2 + (1 if frac == "5" else 0)
    return -halves if negative else halves
''')

ROUTE = Task(
    name="route", fn="parse_route", kind="validity", alphabet="NESW01234", maxlen=6,
    intro="A route is one, two or three moves written one after another. Each move is a direction letter (`N`, `E`, `S` or `W`) followed by one digit, the number of steps.",
    rules={"R1": "The number of steps is from `1` to `3`.",
           "R2": "Two moves in a row may not have the same direction.",
           "R3": "A move may not directly reverse the move before it: `N` after `S`, `S` after `N`, `E` after `W`, `W` after `E`.",
           "R4": "The first move may not be `W`."},
    returns="Return a tuple of `(direction, steps)` pairs, steps as integers. `parse_route(\"N2E1\")` returns `((\"N\", 2), (\"E\", 1))`.",
    examples=["N2", "N2E1", "S1E3N2"],
    value=lambda s: tuple((s[i], int(s[i + 1])) for i in range(0, len(s), 2)),
    marked='''
def parse_route(s):
    if len(s) not in (2, 4, 6) or any(c not in "NESW" for c in s[0::2]) or not s[1::2].isdigit():
        raise ValueError("not a route")
    moves = [(s[i], int(s[i + 1])) for i in range(0, len(s), 2)]
    if any(n < 1 or n > 3 for _, n in moves):                               #R1
        raise ValueError("bad step count")                                  #R1
    if any(a[0] == b[0] for a, b in zip(moves, moves[1:])):                 #R2
        raise ValueError("same direction twice in a row")                   #R2
    if any({a[0], b[0]} in ({"N", "S"}, {"E", "W"}) for a, b in zip(moves, moves[1:])):   #R3
        raise ValueError("direct reversal")                                 #R3
    if moves[0][0] == "W":                                                  #R4
        raise ValueError("a route cannot start west")                       #R4
    return tuple(moves)
''')

SLOT = Task(
    name="slot_time", fn="parse_slot", kind="validity", alphabet="0134578:", maxlen=5,
    intro="A slot time is an hour digit, a colon and two minute digits: exactly four characters.",
    rules={"R1": "The hour is from `0` to `7`.",
           "R2": "The minutes are `00`, `15`, `30` or `45`.",
           "R3": "Hour `7` is the last slot: `7:00` is the only time allowed in hour 7.",
           "R4": "`0:00` is not a slot."},
    returns="Return a tuple `(hour, minutes)` of integers. `parse_slot(\"3:15\")` returns `(3, 15)`.",
    examples=["3:15", "0:30", "7:00", "5:45"],
    value=lambda s: (int(s[0]), int(s[2:])),
    marked='''
def parse_slot(s):
    if len(s) != 4 or not s[0].isdigit() or s[1] != ":" or not s[2:].isdigit():
        raise ValueError("not a slot time")
    hour, minutes = int(s[0]), int(s[2:])
    if hour > 7:                                                            #R1
        raise ValueError("no such hour")                                    #R1
    if minutes not in (0, 15, 30, 45):                                      #R2
        raise ValueError("minutes must be a quarter hour")                  #R2
    if hour == 7 and minutes != 0:                                          #R3
        raise ValueError("7:00 is the last slot")                           #R3
    if hour == 0 and minutes == 0:                                          #R4
        raise ValueError("0:00 is not a slot")                              #R4
    return (hour, minutes)
''')

HAND = Task(
    name="hand", fn="classify_hand", kind="label", alphabet="23456", maxlen=4,
    intro="A hand is three card ranks written as three digits.",
    rules={"R1": "Each rank is from `2` to `5`.",
           "R2": "The ranks must be written from lowest to highest; equal ranks may sit next to each other. Any other order is invalid.",
           "R3": "Three equal ranks are `TRIPLE`.",
           "R4": "Exactly two equal ranks are `PAIR`.",
           "R5": "Three consecutive ranks, such as `345`, are `RUN`.",
           "R6": "Every other valid hand is `PLAIN`."},
    returns="Return one of the strings `TRIPLE`, `PAIR`, `RUN`, `PLAIN`. `classify_hand(\"335\")` returns `\"PAIR\"`.",
    examples=["235", "335", "444", "345"],
    labels=["TRIPLE", "PAIR", "RUN", "PLAIN"],
    marked='''
def classify_hand(s):
    if len(s) != 3 or not s.isdigit():
        raise ValueError("not a hand")
    if any(c not in "2345" for c in s):                                     #R1
        raise ValueError("unknown rank")                                    #R1
    if list(s) != sorted(s):                                                #R2
        raise ValueError("ranks out of order")                              #R2
    a, b, c = (int(ch) for ch in s)
    if a == b == c:                                                         #R3
        return "TRIPLE"                                                     #R3
    if a == b or b == c or a == c:                                          #R4
        return "PAIR"                                                       #R4
    if b == a + 1 and c == b + 1:                                           #R5
        return "RUN"                                                        #R5
    return "PLAIN"
''')

DOOR = Task(
    name="door", fn="door_state", kind="label", alphabet="OCLUx", maxlen=5,
    intro="A door log is a string of events read left to right: `O` open, `C` close, `L` lock, `U` unlock. The door starts closed and unlocked. A locked door is closed. An empty log is valid.",
    rules={"R1": "An open door cannot be opened again, and a door that is not open cannot be closed.",
           "R2": "Only a closed, unlocked door can be locked.",
           "R3": "A locked door cannot be opened.",
           "R4": "Only a locked door can be unlocked.",
           "R5": "A log may hold at most four events."},
    returns="Return the door's final state, one of the strings `OPEN`, `CLOSED`, `LOCKED`. `door_state(\"OC\")` returns `\"CLOSED\"` and `door_state(\"\")` returns `\"CLOSED\"`.",
    examples=["O", "OC", "L", "LUO"],
    labels=["OPEN", "CLOSED", "LOCKED"],
    marked='''
def door_state(s):
    if any(e not in "OCLU" for e in s):
        raise ValueError("unknown event")
    if len(s) > 4:                                                          #R5
        raise ValueError("log too long")                                    #R5
    state = "CLOSED"
    for e in s:
        if e == "O":
            if state == "OPEN":                                             #R1
                raise ValueError("already open")                            #R1
            if state == "LOCKED":                                           #R3
                raise ValueError("the door is locked")                      #R3
            if state == "CLOSED":
                state = "OPEN"
        elif e == "C":
            if state != "OPEN":                                             #R1
                raise ValueError("the door is not open")                    #R1
            if state == "OPEN":
                state = "CLOSED"
        elif e == "L":
            if state != "CLOSED":                                           #R2
                raise ValueError("cannot lock")                             #R2
            if state == "CLOSED":
                state = "LOCKED"
        else:
            if state != "LOCKED":                                           #R4
                raise ValueError("the door is not locked")                  #R4
            if state == "LOCKED":
                state = "CLOSED"
    return state
''')

BAND = Task(
    name="score_band", fn="score_band", kind="label", alphabet="0124578-", maxlen=3,
    intro="A score is a whole number written in digits only.",
    rules={"R1": "A score has no leading zero, unless it is the single digit `0`.",
           "R2": "Scores run from 0 to 20. Anything higher is invalid.",
           "R3": "0 to 7 is `LOW`.",
           "R4": "8 to 14 is `MID`.",
           "R5": "15 to 20 is `HIGH`."},
    returns="Return one of the strings `LOW`, `MID`, `HIGH`. `score_band(\"12\")` returns `\"MID\"`.",
    examples=["0", "7", "12", "20"],
    labels=["LOW", "MID", "HIGH"],
    marked='''
def score_band(s):
    if not s.isdigit():
        raise ValueError("not a score")
    if len(s) > 1 and s[0] == "0":                                          #R1
        raise ValueError("leading zero")                                    #R1
    n = int(s)
    if n > 20:                                                              #R2
        raise ValueError("score too high")                                  #R2
    if n <= 7:                                                              #R3
        return "LOW"                                                        #R3
    if n <= 14:                                                             #R4
        return "MID"                                                        #R4
    return "HIGH"
''')

BRACKETS = Task(
    name="brackets", fn="bracket_kind", kind="label", alphabet="()[]", maxlen=6,
    intro="A bracket string uses round brackets `(` `)` and square brackets `[` `]`. Every opening bracket must be closed, every closing bracket must close an opening one, and brackets must be properly nested.",
    rules={"R1": "A closing bracket must be the same kind as the bracket it closes.",
           "R2": "Brackets may be nested at most two deep: `(())` is valid, `((()))` is not.",
           "R3": "The empty string is invalid.",
           "R4": "A string that uses only round brackets is `ROUND`; one that uses only square brackets is `SQUARE`.",
           "R5": "A string that uses both kinds is `MIXED`.",
           "R6": "A round bracket may not open directly inside a square one: `[()]` is invalid, `([])` is valid."},
    returns="Return one of the strings `ROUND`, `SQUARE`, `MIXED`. `bracket_kind(\"()[]\")` returns `\"MIXED\"`.",
    examples=["()", "[]", "()[]", "([])", "(())"],
    labels=["ROUND", "SQUARE", "MIXED"],
    marked='''
def bracket_kind(s):
    if any(c not in "()[]" for c in s):
        raise ValueError("unknown character")
    if s == "":                                                             #R3
        raise ValueError("empty string")                                    #R3
    stack = []
    for c in s:
        if c in "([":
            if c == "(" and stack and stack[-1] == "[":                     #R6
                raise ValueError("round bracket inside a square one")       #R6
            stack.append(c)
            if len(stack) > 2:                                              #R2
                raise ValueError("nested too deep")                         #R2
        else:
            if not stack:
                raise ValueError("nothing to close")
            opener = stack.pop()
            if (opener, c) not in (("(", ")"), ("[", "]")):                 #R1
                raise ValueError("mismatched kinds")                        #R1
    if stack:
        raise ValueError("unclosed bracket")
    if "(" in s and "[" in s:                                               #R5
        return "MIXED"                                                      #R5
    return "SQUARE" if "[" in s else "ROUND"
''')

PIN = Task(
    name="practice_pin", fn="parse_pin", kind="validity", alphabet="0129", maxlen=5, practice=True,
    intro="A PIN is exactly four digits.",
    rules={"R1": "A PIN may not start with `0`.",
           "R2": "A PIN may not be four identical digits."},
    returns="Return the PIN unchanged, as a string. `parse_pin(\"1290\")` returns `\"1290\"`.",
    examples=["1290", "9911"],
    value=lambda s: s,
    marked='''
def parse_pin(s):
    if len(s) != 4 or not s.isdigit():
        raise ValueError("not a PIN")
    if s[0] == "0":                                                         #R1
        raise ValueError("leading zero")                                    #R1
    if len(set(s)) == 1:                                                    #R2
        raise ValueError("four identical digits")                           #R2
    return s
''')

TASKS = [BIN, SPAN, TAGS, LEVEL, ROUTE, SLOT, HAND, DOOR, BAND, BRACKETS]
ALL = [*TASKS, PIN]
BY_NAME = {t.name: t for t in ALL}

if __name__ == "__main__":
    for t in ALL:
        print(f"## {t.name}\n\n{spec(t)}\n")
