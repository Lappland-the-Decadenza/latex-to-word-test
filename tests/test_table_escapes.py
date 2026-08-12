"""Guard: no LaTeX macro in a shared table may contain a control character.

A LaTeX macro written in a plain Python string is one letter away from silent
corruption, because `\\r`, `\\n`, `\\t`, `\\f`, `\\b`, `\\a` and `\\v` are real
escapes. `"\\rangle"` is not the macro `\\rangle`; it is a carriage return
followed by `angle`.

This is not hypothetical. When `DELIM_LEFTRIGHT` moved from `word2latex.py`
(where it was written `"\\\\rangle"`) into `mathsyms.py`, one backslash was
lost, and `\\rangle`, `\\rceil` and `\\rfloor` silently became control
characters. Every right angle bracket, right ceiling and right floor in every
document was corrupted -- and the whole suite stayed green, because nothing
covered those three delimiters.

Testing the *class* rather than those three entries is the point: the next
table to gain a `\\r`-prefixed macro would reintroduce exactly this bug, and no
amount of care while editing prevents it. `CANONICAL.md` clause 3 says the
converter must never mutate content silently; this is that clause applied to
our own source code.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from latexword import mathsyms

# Everything a macro string may never contain. This is precisely Python's set
# of single-letter string escapes that produce a control character.
CONTROL = {
    "\a": r"\a (bell)",
    "\b": r"\b (backspace)",
    "\f": r"\f (form feed)",
    "\n": r"\n (newline)",
    "\r": r"\r (carriage return)",
    "\t": r"\t (tab)",
    "\v": r"\v (vertical tab)",
}

# Tables whose *values* are LaTeX macros or plain delimiter characters.
VALUE_TABLES = [
    "DELIM_LEFTRIGHT",
    "SYMBOL_MAP",
    "SPACE_TO_LATEX",
    "ACCENT_REVERSE",
    "KNOWN_FUNC_MACROS",
]


def _tables():
    for name in VALUE_TABLES:
        table = getattr(mathsyms, name, None)
        if table is not None:
            yield name, table


def test_all_expected_tables_exist():
    # Otherwise a renamed table would quietly drop out of this guard while
    # every test below kept passing over the remaining ones.
    missing = [n for n in VALUE_TABLES if getattr(mathsyms, n, None) is None]
    assert not missing, f"tables missing from mathsyms: {missing}"


@pytest.mark.parametrize("name", VALUE_TABLES)
def test_no_control_characters_in_macro_values(name):
    table = getattr(mathsyms, name, None)
    if table is None:
        pytest.skip(f"{name} not present")
    bad = []
    for key, value in table.items():
        if not isinstance(value, str):
            continue
        for ch, label in CONTROL.items():
            if ch in value:
                bad.append((key, value, label))
    assert not bad, "\n".join(
        f"{name}[{k!r}] = {v!r} contains {label} -- write it as a raw string "
        f"(r\"\\...\") or double the backslash"
        for k, v, label in bad
    )


def test_backslash_macros_are_well_formed():
    """A value that starts with a backslash must be followed by a letter or a
    known punctuation macro. A backslash followed by anything else means the
    escape was eaten and what survives is not the macro that was intended."""
    bad = []
    for name, table in _tables():
        for key, value in table.items():
            if not isinstance(value, str) or not value.startswith("\\"):
                continue
            rest = value[1:]
            if not rest:
                bad.append((name, key, value, "bare backslash"))
            # LaTeX's punctuation macros: grouping (`\{` `\}`), the norm bar
            # (`\|`), the spacing family (`\,` `\;` `\:` `\!` `\ `) and `\.`.
            elif not (rest[0].isalpha() or rest[0] in "{}|,;:!. \\"):
                bad.append((name, key, value, f"unexpected {rest[0]!r} after backslash"))
    assert not bad, "\n".join(
        f"{n}[{k!r}] = {v!r}: {why}" for n, k, v, why in bad
    )
