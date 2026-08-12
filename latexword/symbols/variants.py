"""Math alphanumeric variants and primes (PLAN.md §5.3).

One-directional character families: the Mathematical Alphanumeric Symbols
block mapping (`_VARIANT_BASES`/`_VARIANT_HOLES`, with the derived reverse
lookup `VARIANT_REVERSE`) and the compound-prime glyphs (`_COMPOUND_PRIMES`).
Re-exported by `latexword/mathsyms.py`; import from there, never from here.
"""

# Word applies no styling for @mathvariant, so a variant left as an attribute
# renders as plain text. Mapping to the Unicode Mathematical Alphanumeric
# Symbols block instead makes the style part of the character itself, which
# survives the XSL untouched (forward direction) and is trivially recognised
# on the way back (reverse direction).
_UC, _LC, _DG = 0, 1, 2

_VARIANT_BASES = {
    "bold": (0x1D400, 0x1D41A, 0x1D7CE),
    "italic": (0x1D434, 0x1D44E, None),
    "bold-italic": (0x1D468, 0x1D482, None),
    "script": (0x1D49C, 0x1D4B6, None),
    "bold-script": (0x1D4D0, 0x1D4EA, None),
    "fraktur": (0x1D504, 0x1D51E, None),
    "bold-fraktur": (0x1D56C, 0x1D586, None),
    "double-struck": (0x1D538, 0x1D552, 0x1D7D8),
    "sans-serif": (0x1D5A0, 0x1D5BA, 0x1D7E2),
    "bold-sans-serif": (0x1D5D4, 0x1D5EE, 0x1D7EC),
    "sans-serif-italic": (0x1D608, 0x1D622, None),
    "sans-serif-bold-italic": (0x1D63C, 0x1D656, None),
    "monospace": (0x1D670, 0x1D68A, 0x1D7F6),
}

# The Mathematical Alphanumeric block has holes where a letter was already
# encoded as a Letterlike Symbol; those code points are reserved and unusable.
_VARIANT_HOLES = {
    "italic": {"h": "ℎ"},
    "script": {
        "B": "ℬ", "E": "ℰ", "F": "ℱ", "H": "ℋ",
        "I": "ℐ", "L": "ℒ", "M": "ℳ", "R": "ℛ",
        "e": "ℯ", "g": "ℊ", "o": "ℴ",
    },
    "fraktur": {
        "C": "ℭ", "H": "ℌ", "I": "ℑ", "R": "ℜ",
        "Z": "ℨ",
    },
    "double-struck": {
        "C": "ℂ", "H": "ℍ", "N": "ℕ", "P": "ℙ",
        "Q": "ℚ", "R": "ℝ", "Z": "ℤ",
    },
}

# Reverse of the mapping above: Unicode variant character -> (plain base
# character, variant name). Derived, not hand-maintained, so it cannot drift
# out of sync with `_VARIANT_BASES`/`_VARIANT_HOLES`.
VARIANT_REVERSE = {}
for _variant, (_uc, _lc, _dg) in _VARIANT_BASES.items():
    for _i in range(26):
        if _uc:
            VARIANT_REVERSE[chr(_uc + _i)] = (chr(ord("A") + _i), _variant)
        if _lc:
            VARIANT_REVERSE[chr(_lc + _i)] = (chr(ord("a") + _i), _variant)
    if _dg:
        for _i in range(10):
            VARIANT_REVERSE[chr(_dg + _i)] = (chr(ord("0") + _i), _variant)
for _variant, _holes in _VARIANT_HOLES.items():
    for _base_letter, _variant_char in _holes.items():
        VARIANT_REVERSE[_variant_char] = (_base_letter, _variant)


# latex2mathml folds repeated ' into a single "compound prime" codepoint --
# U+2033 DOUBLE PRIME for '', U+2034 TRIPLE for ''', U+2057 QUADRUPLE for
# ''''. Those are real Unicode characters, but they're the arcminute/arcsecond
# ditto-mark glyphs, not derivative notation: both LaTeX's own fonts and
# Word's native "type f then ''" autocorrect render repeated *single* primes
# (U+2032) side by side instead, which is why f'' visibly differs from a
# hand-typed f'' next to it in Word -- different glyph, different kerning.
_COMPOUND_PRIMES = {
    "″": "′" * 2,
    "‴": "′" * 3,
    "⁗": "′" * 4,
}
