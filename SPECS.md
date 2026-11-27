## bin_code

Write a Python function `parse_bin(s)` that takes one string.

A bin code names a storage bin. It is an aisle letter, then a level digit, then optionally a hyphen and a slot letter.
Examples of valid input: `A2`, `B1-x`, `A3-y`.

Rules:
R1. The aisle is the capital letter `A` or `B`.
R2. The level is a digit from `1` to `3`.
R3. A slot, when present, is a hyphen followed by the lowercase letter `x` or `y`.
R4. Aisle `B` has no level 3.
R5. Nothing may follow the slot.

Return a tuple `(aisle, level, slot)`: the aisle letter, the level as an integer, and the slot letter, or `None` when there is no slot. `parse_bin("B1-x")` returns `("B", 1, "x")`.
Any input that does not fit the description, or breaks any rule, raises ValueError. Nothing is trimmed or corrected: the input is taken exactly as given. Use only the standard library.

## span

Write a Python function `parse_span(s)` that takes one string.

A span is written as a start digit, a hyphen and an end digit: exactly three characters.
Examples of valid input: `2-6`, `1-2`, `4-9`.

Rules:
R1. Neither digit may be `0`.
R2. The start must be less than the end.
R3. The end may be at most 5 more than the start.
R4. The digit `7` is reserved and may not be used at either end.

Return a tuple `(start, end)` of integers. `parse_span("2-6")` returns `(2, 6)`.
Any input that does not fit the description, or breaks any rule, raises ValueError. Nothing is trimmed or corrected: the input is taken exactly as given. Use only the standard library.

## tags

Write a Python function `parse_tags(s)` that takes one string.

A tag list is one or more tags joined by `+`. Each tag is a single lowercase letter.
Examples of valid input: `a`, `a+c`, `b+c`.

Rules:
R1. The only tags are `a`, `b` and `c`.
R2. A tag may appear only once.
R3. Tags must not be out of alphabetical order: a later tag may not come before an earlier letter.
R4. A list holds at most two tags.

Return a tuple of the tags in the order given. `parse_tags("a+c")` returns `("a", "c")`.
Any input that does not fit the description, or breaks any rule, raises ValueError. Nothing is trimmed or corrected: the input is taken exactly as given. Use only the standard library.

## level

Write a Python function `parse_level(s)` that takes one string.

A level reading is an optional minus sign, then one or more digits (the whole part), then optionally a decimal point and exactly one digit.
Examples of valid input: `5`, `-1.5`, `0.5`, `9`.

Rules:
R1. The whole part has no leading zero, unless it is the single digit `0`.
R2. The only fraction allowed is `.5`.
R3. The whole part must be 9 or less.
R4. Minus zero is not allowed: `-0` is invalid. `-0.5` is valid.

Return the reading counted in halves, as an integer. `parse_level("1.5")` returns `3`, `parse_level("-5")` returns `-10`, `parse_level("0")` returns `0`.
Any input that does not fit the description, or breaks any rule, raises ValueError. Nothing is trimmed or corrected: the input is taken exactly as given. Use only the standard library.

## route

Write a Python function `parse_route(s)` that takes one string.

A route is one, two or three moves written one after another. Each move is a direction letter (`N`, `E`, `S` or `W`) followed by one digit, the number of steps.
Examples of valid input: `N2`, `N2E1`, `S1E3N2`.

Rules:
R1. The number of steps is from `1` to `3`.
R2. Two moves in a row may not have the same direction.
R3. A move may not directly reverse the move before it: `N` after `S`, `S` after `N`, `E` after `W`, `W` after `E`.
R4. The first move may not be `W`.

Return a tuple of `(direction, steps)` pairs, steps as integers. `parse_route("N2E1")` returns `(("N", 2), ("E", 1))`.
Any input that does not fit the description, or breaks any rule, raises ValueError. Nothing is trimmed or corrected: the input is taken exactly as given. Use only the standard library.

## slot_time

Write a Python function `parse_slot(s)` that takes one string.

A slot time is an hour digit, a colon and two minute digits: exactly four characters.
Examples of valid input: `3:15`, `0:30`, `7:00`, `5:45`.

Rules:
R1. The hour is from `0` to `7`.
R2. The minutes are `00`, `15`, `30` or `45`.
R3. Hour `7` is the last slot: `7:00` is the only time allowed in hour 7.
R4. `0:00` is not a slot.

Return a tuple `(hour, minutes)` of integers. `parse_slot("3:15")` returns `(3, 15)`.
Any input that does not fit the description, or breaks any rule, raises ValueError. Nothing is trimmed or corrected: the input is taken exactly as given. Use only the standard library.

## hand

Write a Python function `classify_hand(s)` that takes one string.

A hand is three card ranks written as three digits.
Examples of valid input: `235`, `335`, `444`, `345`.

Rules:
R1. Each rank is from `2` to `5`.
R2. The ranks must be written from lowest to highest; equal ranks may sit next to each other. Any other order is invalid.
R3. Three equal ranks are `TRIPLE`.
R4. Exactly two equal ranks are `PAIR`.
R5. Three consecutive ranks, such as `345`, are `RUN`.
R6. Every other valid hand is `PLAIN`.

Return one of the strings `TRIPLE`, `PAIR`, `RUN`, `PLAIN`. `classify_hand("335")` returns `"PAIR"`.
Any input that does not fit the description, or breaks any rule, raises ValueError. Nothing is trimmed or corrected: the input is taken exactly as given. Use only the standard library.

## door

Write a Python function `door_state(s)` that takes one string.

A door log is a string of events read left to right: `O` open, `C` close, `L` lock, `U` unlock. The door starts closed and unlocked. A locked door is closed. An empty log is valid.
Examples of valid input: `O`, `OC`, `L`, `LUO`.

Rules:
R1. An open door cannot be opened again, and a door that is not open cannot be closed.
R2. Only a closed, unlocked door can be locked.
R3. A locked door cannot be opened.
R4. Only a locked door can be unlocked.
R5. A log may hold at most four events.

Return the door's final state, one of the strings `OPEN`, `CLOSED`, `LOCKED`. `door_state("OC")` returns `"CLOSED"` and `door_state("")` returns `"CLOSED"`.
Any input that does not fit the description, or breaks any rule, raises ValueError. Nothing is trimmed or corrected: the input is taken exactly as given. Use only the standard library.

## score_band

Write a Python function `score_band(s)` that takes one string.

A score is a whole number written in digits only.
Examples of valid input: `0`, `7`, `12`, `20`.

Rules:
R1. A score has no leading zero, unless it is the single digit `0`.
R2. Scores run from 0 to 20. Anything higher is invalid.
R3. 0 to 7 is `LOW`.
R4. 8 to 14 is `MID`.
R5. 15 to 20 is `HIGH`.

Return one of the strings `LOW`, `MID`, `HIGH`. `score_band("12")` returns `"MID"`.
Any input that does not fit the description, or breaks any rule, raises ValueError. Nothing is trimmed or corrected: the input is taken exactly as given. Use only the standard library.

## brackets

Write a Python function `bracket_kind(s)` that takes one string.

A bracket string uses round brackets `(` `)` and square brackets `[` `]`. Every opening bracket must be closed, every closing bracket must close an opening one, and brackets must be properly nested.
Examples of valid input: `()`, `[]`, `()[]`, `([])`, `(())`.

Rules:
R1. A closing bracket must be the same kind as the bracket it closes.
R2. Brackets may be nested at most two deep: `(())` is valid, `((()))` is not.
R3. The empty string is invalid.
R4. A string that uses only round brackets is `ROUND`; one that uses only square brackets is `SQUARE`.
R5. A string that uses both kinds is `MIXED`.
R6. A round bracket may not open directly inside a square one: `[()]` is invalid, `([])` is valid.

Return one of the strings `ROUND`, `SQUARE`, `MIXED`. `bracket_kind("()[]")` returns `"MIXED"`.
Any input that does not fit the description, or breaks any rule, raises ValueError. Nothing is trimmed or corrected: the input is taken exactly as given. Use only the standard library.

## practice_pin

Write a Python function `parse_pin(s)` that takes one string.

A PIN is exactly four digits.
Examples of valid input: `1290`, `9911`.

Rules:
R1. A PIN may not start with `0`.
R2. A PIN may not be four identical digits.

Return the PIN unchanged, as a string. `parse_pin("1290")` returns `"1290"`.
Any input that does not fit the description, or breaks any rule, raises ValueError. Nothing is trimmed or corrected: the input is taken exactly as given. Use only the standard library.

