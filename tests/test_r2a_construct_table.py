"""R2a -- construct table structural checks.

`mathast.py` self-validates at import time (a malformed entry is an import
error, not a runtime surprise), so most of what this file checks is already
enforced just by `import mathast` succeeding. This test makes those
invariants explicit and independently re-checkable, and adds the one
cross-module check the module itself cannot perform on itself: that its own
`OMML_ELEMENTS` set really is the Rule 0 closed set of 20 named in
`REWRITE_FORWARD.md`, not a set the module invented and then validated
itself against. The count grew from 20 to 22 when PLAN.md §6.2 (tolerance
as vocabulary) added `borderBox` and `phant` for the measured corpus
macros `\boxed`/`\phantom`; the exact-equality assertion below is what
keeps any future growth honest (it must be a plan-authorized change, not
a silent widening).
"""

from latexword.math import ast as mathast


def test_table_covers_every_ast_node_type():
    covered = {c.node for c in mathast.CONSTRUCTS}
    assert covered == set(mathast.ALL_NODE_TYPES)
    # And each exactly once.
    node_counts = {}
    for c in mathast.CONSTRUCTS:
        node_counts[c.node] = node_counts.get(c.node, 0) + 1
    assert all(n == 1 for n in node_counts.values()), node_counts


def test_omml_elements_are_within_rule_0_closed_set():
    # Rule 0 target inventory, REWRITE_FORWARD.md ("Target inventory"): a
    # closed set of exactly 22 elements (20 original + §6.2's authorized
    # `borderBox`/`phant`). Anything outside it is a validation error, not
    # a best-effort conversion (CANONICAL.md Rule 15).
    rule_0_set = {
        "oMath", "oMathPara", "r", "t", "e",
        "sSub", "sSup", "sSubSup", "sPre",
        "f", "rad", "nary", "d", "func", "acc", "bar",
        "limLow", "limUpp", "groupChr", "m",
        "borderBox", "phant",
    }
    assert len(rule_0_set) == 22
    assert mathast.OMML_ELEMENTS == rule_0_set

    used = set()
    for c in mathast.CONSTRUCTS:
        names = c.omml if isinstance(c.omml, tuple) else (c.omml,)
        used.update(n for n in names if n is not None)
    assert used <= rule_0_set


def test_no_two_entries_share_a_latex_spelling():
    spellings = [c.latex for c in mathast.CONSTRUCTS if c.latex is not None]
    assert len(spellings) == len(set(spellings)), spellings


def test_arity_matches_slot_count_where_declared():
    for c in mathast.CONSTRUCTS:
        if c.arity is not None:
            assert len(c.slots) == c.arity, (c.name, c.arity, c.slots)


def test_every_entry_declares_parse_emit_serialize():
    for c in mathast.CONSTRUCTS:
        assert c.parse is not None, c.name
        assert c.emit is not None, c.name
        assert c.serialize is not None, c.name


def test_lookup_dicts_agree_with_the_table():
    assert set(mathast.CONSTRUCTS_BY_NAME) == {c.name for c in mathast.CONSTRUCTS}
    assert set(mathast.CONSTRUCTS_BY_NODE) == {c.node for c in mathast.CONSTRUCTS}


def test_exactly_one_of_latex_variants_no_macro():
    """Part 4: a macro-bearing construct declares its vocabulary exactly
    one way; a no_macro primitive declares neither. (Also checked at
    import time -- this is the same invariant, independently
    re-verifiable without relying on import-time side effects.)"""
    for c in mathast.CONSTRUCTS:
        macro_fields = (c.latex is not None) + (c.variants is not None)
        if c.no_macro:
            assert macro_fields == 0, c.name
        else:
            assert macro_fields == 1, c.name


def test_macro_to_construct_is_injective_and_covers_expected_families():
    # Injectivity is also asserted at import time; re-checking here makes
    # it independent of import-time side effects and gives a normal
    # pytest failure (with a clear "which macro, which two constructs")
    # instead of a raw AssertionError from module import if it regresses.
    seen = {}
    for construct in mathast.CONSTRUCTS:
        if construct.latex is not None:
            spellings = {construct.latex}
        elif construct.variants is not None:
            spellings = set(construct.variants)
        else:
            continue
        for macro in spellings:
            assert macro not in seen, (
                f"{macro!r} claimed by both {seen.get(macro)!r} and {construct.name!r}"
            )
            seen[macro] = construct.name
    assert seen == {m: c.name for m, (c, _) in mathast.MACRO_TO_CONSTRUCT.items()}

    # Coordinator's "cover at least" list.
    expected_macros = {
        r"\frac", r"\dfrac", r"\tfrac", r"\binom",
        r"\int", r"\sum", r"\vec", r"\overline", r"\overbrace",
        r"\underset", r"\overset",
        "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix", "cases", "matrix",
        "(", "[", r"\{", r"\langle", "|", r"\|", r"\lceil", r"\lfloor",
    }
    assert expected_macros <= set(mathast.MACRO_TO_CONSTRUCT)


def test_every_macro_resolves_to_a_construct_within_the_closed_omml_set():
    for macro, (construct, _props) in mathast.MACRO_TO_CONSTRUCT.items():
        omml_names = construct.omml if isinstance(construct.omml, tuple) else (construct.omml,)
        for elem in omml_names:
            assert elem is None or elem in mathast.OMML_ELEMENTS, (macro, elem)


def test_derived_families_are_non_empty():
    # A derivation from a mathsyms table that silently produces nothing
    # (source table emptied or renamed out from under this module) must
    # fail loudly, not quietly shrink the vocabulary.
    for name in ("opname", "accent", "nary", "space"):
        count = sum(1 for _m, (c, _p) in mathast.MACRO_TO_CONSTRUCT.items() if c.name == name)
        assert count > 0, name


def test_stub_inventory_is_visible():
    """List which construct entries still hold R2b/R3 stubs for parse/emit,
    so the remaining work is visible rather than only discoverable by
    reading the module. Not a pass/fail gate on *how many* stubs exist --
    R2a is table-only by design, so every structural construct having
    stubs right now is expected, not a regression."""
    stubs = sorted(
        c.name
        for c in mathast.CONSTRUCTS
        if getattr(c.parse, "stage", None) or getattr(c.emit, "stage", None)
    )
    # Sanity: the stub-detection itself isn't vacuous (this test would
    # silently stop meaning anything if _stub ever changed shape without
    # this test's `getattr` still recognising it).
    assert stubs, "no stubbed constructs found -- has _stub's marker changed?"
    print(f"\nR2a stub inventory ({len(stubs)} of {len(mathast.CONSTRUCTS)} constructs): {stubs}")
