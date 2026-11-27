"""Independent implementations of eleven small parsers (see SPECS.md)."""

_DIGITS = "0123456789"


def _is_digit(c):
    return len(c) == 1 and c in _DIGITS


def parse_bin(s):
    """Bin code: aisle A/B, level 1-3, optional '-x' or '-y'."""
    if len(s) not in (2, 4):
        raise ValueError("bad bin code")
    aisle = s[0]
    if aisle not in ("A", "B"):
        raise ValueError("bad aisle")
    if s[1] not in ("1", "2", "3"):
        raise ValueError("bad level")
    level = int(s[1])
    if aisle == "B" and level == 3:
        raise ValueError("B has no level 3")
    slot = None
    if len(s) == 4:
        if s[2] != "-" or s[3] not in ("x", "y"):
            raise ValueError("bad slot")
        slot = s[3]
    return (aisle, level, slot)


def parse_span(s):
    """Span: 'd-d' with rules on the digits."""
    if len(s) != 3 or s[1] != "-":
        raise ValueError("bad span")
    if not (_is_digit(s[0]) and _is_digit(s[2])):
        raise ValueError("bad span")
    a, b = int(s[0]), int(s[2])
    if a == 0 or b == 0:
        raise ValueError("zero")
    if a == 7 or b == 7:
        raise ValueError("seven reserved")
    if not a < b:
        raise ValueError("start must be less than end")
    if b - a > 5:
        raise ValueError("too long")
    return (a, b)


def parse_tags(s):
    """Tags: a, b, c joined by '+', strictly alphabetical, at most two."""
    parts = s.split("+")
    if len(parts) > 2:
        raise ValueError("too many tags")
    for p in parts:
        if p not in ("a", "b", "c"):
            raise ValueError("bad tag")
    if len(parts) == 2 and not parts[0] < parts[1]:
        raise ValueError("order or duplicate")
    return tuple(parts)


def parse_level(s):
    """Level reading in halves."""
    body = s
    neg = False
    if body.startswith("-"):
        neg = True
        body = body[1:]
    if "." in body:
        whole, _, frac = body.partition(".")
        if frac != "5":
            raise ValueError("only .5 allowed")
        half = 1
    else:
        whole = body
        half = 0
    if whole == "" or not all(_is_digit(c) for c in whole):
        raise ValueError("bad whole part")
    if len(whole) > 1 and whole[0] == "0":
        raise ValueError("leading zero")
    if len(whole) > 1:
        raise ValueError("whole part above 9")
    w = int(whole)
    if neg and w == 0 and half == 0:
        raise ValueError("minus zero")
    value = w * 2 + half
    return -value if neg else value


def parse_route(s):
    """Route of one to three moves, e.g. N2E1."""
    if len(s) not in (2, 4, 6):
        raise ValueError("bad length")
    moves = []
    for i in range(0, len(s), 2):
        d, n = s[i], s[i + 1]
        if d not in ("N", "E", "S", "W"):
            raise ValueError("bad direction")
        if n not in ("1", "2", "3"):
            raise ValueError("bad steps")
        moves.append((d, int(n)))
    if moves[0][0] == "W":
        raise ValueError("first move W")
    opposite = {"N": "S", "S": "N", "E": "W", "W": "E"}
    for prev, cur in zip(moves, moves[1:]):
        if prev[0] == cur[0]:
            raise ValueError("same direction")
        if opposite[prev[0]] == cur[0]:
            raise ValueError("reversal")
    return tuple(moves)


def parse_slot(s):
    """Slot time h:mm."""
    if len(s) != 4 or s[1] != ":":
        raise ValueError("bad slot time")
    if not (_is_digit(s[0]) and _is_digit(s[2]) and _is_digit(s[3])):
        raise ValueError("bad slot time")
    hour = int(s[0])
    minutes = s[2:]
    if hour > 7:
        raise ValueError("bad hour")
    if minutes not in ("00", "15", "30", "45"):
        raise ValueError("bad minutes")
    m = int(minutes)
    if hour == 7 and m != 0:
        raise ValueError("hour 7 only 7:00")
    if hour == 0 and m == 0:
        raise ValueError("0:00 not a slot")
    return (hour, m)


def classify_hand(s):
    """Three ranks 2-5, non-decreasing."""
    if len(s) != 3:
        raise ValueError("bad length")
    for c in s:
        if c not in ("2", "3", "4", "5"):
            raise ValueError("bad rank")
    a, b, c = int(s[0]), int(s[1]), int(s[2])
    if not (a <= b <= c):
        raise ValueError("not ordered")
    if a == b == c:
        return "TRIPLE"
    if a == b or b == c:
        return "PAIR"
    if b == a + 1 and c == b + 1:
        return "RUN"
    return "PLAIN"


def door_state(s):
    """Door log; returns OPEN, CLOSED or LOCKED."""
    if len(s) > 4:
        raise ValueError("too many events")
    state = "CLOSED"
    for ch in s:
        if ch == "O":
            if state != "CLOSED":
                raise ValueError("cannot open")
            state = "OPEN"
        elif ch == "C":
            if state != "OPEN":
                raise ValueError("cannot close")
            state = "CLOSED"
        elif ch == "L":
            if state != "CLOSED":
                raise ValueError("cannot lock")
            state = "LOCKED"
        elif ch == "U":
            if state != "LOCKED":
                raise ValueError("cannot unlock")
            state = "CLOSED"
        else:
            raise ValueError("bad event")
    return state


def score_band(s):
    """Score 0-20 banded LOW/MID/HIGH."""
    if s == "" or len(s) > 2:
        raise ValueError("bad score")
    if not all(_is_digit(c) for c in s):
        raise ValueError("bad score")
    if len(s) > 1 and s[0] == "0":
        raise ValueError("leading zero")
    v = int(s)
    if v > 20:
        raise ValueError("too high")
    if v <= 7:
        return "LOW"
    if v <= 14:
        return "MID"
    return "HIGH"


def bracket_kind(s):
    """Nested brackets, depth <= 2; ROUND, SQUARE or MIXED."""
    if s == "":
        raise ValueError("empty")
    pairs = {")": "(", "]": "["}
    stack = []
    kinds = set()
    for ch in s:
        if ch in "([" and len(ch) == 1:
            if ch == "(" and stack and stack[-1] == "[":
                raise ValueError("round directly inside square")
            stack.append(ch)
            if len(stack) > 2:
                raise ValueError("too deep")
            kinds.add(ch)
        elif ch in (")", "]"):
            if not stack or stack[-1] != pairs[ch]:
                raise ValueError("mismatch")
            stack.pop()
        else:
            raise ValueError("bad character")
    if stack:
        raise ValueError("unclosed")
    if len(kinds) == 2:
        return "MIXED"
    return "ROUND" if "(" in kinds else "SQUARE"


def parse_pin(s):
    """Four-digit PIN, no leading zero, not all identical."""
    if len(s) != 4 or not all(_is_digit(c) for c in s):
        raise ValueError("bad pin")
    if s[0] == "0":
        raise ValueError("leading zero")
    if s == s[0] * 4:
        raise ValueError("identical digits")
    return s
