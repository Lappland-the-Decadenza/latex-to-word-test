"""A3 -- the active symbol registry is bijective by construction."""

from latexword.mathsyms import (
    DELIM_LEFTRIGHT, MACRO_TO_CHAR, NARY_CHARS, SYMBOL_MAP,
)
from latexword.symbols.registry import NARY_CHAR_TO_MACRO


def test_symbol_registry_is_bijective_without_external_snapshots():
    assert len(MACRO_TO_CHAR) == len(set(MACRO_TO_CHAR))
    assert len(MACRO_TO_CHAR.values()) == len(set(MACRO_TO_CHAR.values()))
    for macro, character in MACRO_TO_CHAR.items():
        assert SYMBOL_MAP[character] == macro


def test_delimiters_and_nary_operators_reverse_through_the_live_tables():
    for character, macro in DELIM_LEFTRIGHT.items():
        assert DELIM_LEFTRIGHT[character] == macro
    assert set(NARY_CHARS) == set(NARY_CHAR_TO_MACRO)
