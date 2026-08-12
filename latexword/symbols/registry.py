"""One bidirectional symbol registry (PLAN.md §5.2).

Each symbol is declared once -- canonical codepoint, macro, reverse-only
aliases -- and both directions are derived from that single declaration:

- the *reverse* spelling (character -> macro, many-to-one: aliases included),
  which is what a Word document's glyphs are looked up against;
- the *forward* emit target (macro -> canonical character, injective: aliases
  are never emitted, they only survive on the way back).

Before this module existed the forward direction was an inversion of the
reverse table with the winner picked by *insertion order* (the old
``latex2omml._invert_symbol_map`` / ``_DELIM_SPELLING_TO_CHAR``), and the
reverse table's aliases were invisible to that process. The winner is now
declared where the collision lives, so the direction that wins is a fact
about the data, not a property of dict ordering. The six known collisions,
each resolved below with a comment naming which direction wins and why:

1. ``\\bullet`` -- U+2219 canonical, U+2022 reverse-only;
2. ``\\diamond`` -- U+22C4 canonical, U+25CA reverse-only;
3. ``\\nsubseteq`` -- U+2288 canonical, U+2284 reverse-only;
4. ``\\langle``/``\\rangle`` -- U+2329/U+232A canonical, U+27E8/U+27E9 and
   U+3008/U+3009 reverse-only;
5. the unary minus -- U+2212 spells the macro ``-``, which is not a LaTeX
   macro name and so has no forward entry at all (the parser emits the ASCII
   binary minus it parses);
6. the spaces -- the join-safety trailing space is data derived from a
   declaration flag, never stripped off a stored spelling (the old
   ``mathast`` derivation truncated ``\\ `` to a bare backslash, the
   ``SPACE_TO_LATEX`` truncation), and the U+2007/U+2001/U+2000 aliases are
   reverse-only.

Self-validation at import: declaring a macro, a codepoint, or a spelling
twice raises instead of silently overwriting; the forward tables are
injective where a round trip claims bijectivity; and totality is asserted
where the pipeline's own invariants demand it (every delimiter character
has a spelling, every n-ary glyph has a macro). Content is identical to
what mathsyms.py held before the move -- only the mechanism changed.

This module must not import anything from the rest of the project: it is
the base of the dependency graph.
"""

from dataclasses import dataclass


# --- Symbols: one declaration per macro -------------------------------------


@dataclass(frozen=True)
class Symbol:
    """One symbol. `macro` is the LaTeX spelling; ``""`` or a non-macro
    string (like ``"-"``) marks a reverse-only spelling -- it has no forward
    emit target and is excluded from `MACRO_TO_CHAR` (the same rule the old
    `_invert_symbol_map` applied). `char` is the canonical codepoint the
    pipeline emits forward; `aliases` are reverse-only glyphs a real
    hand-authored Word equation may contain instead."""

    macro: str
    char: str
    aliases: tuple = ()
    category: str = "symbol"


# Collision 1 -- \bullet: the canonical glyph is U+2219 (BULLET OPERATOR),
# not the U+2022 BULLET of list markup. A hand-authored document containing
# U+2022 still reverses to \bullet (it is a reverse-only alias here); the
# forward direction always emits U+2219. Measured on the corpus: U+2022
# never appears in math, U+2219 does.
SYMBOLS = [
    # Greek lowercase
    Symbol("\\alpha", "α", category="greek-lower"),
    Symbol("\\beta", "β", category="greek-lower"),
    Symbol("\\gamma", "γ", category="greek-lower"),
    Symbol("\\delta", "δ", category="greek-lower"),
    Symbol("\\varepsilon", "ε", category="greek-lower"),
    Symbol("\\epsilon", "ϵ", category="greek-lower"),
    Symbol("\\zeta", "ζ", category="greek-lower"),
    Symbol("\\eta", "η", category="greek-lower"),
    Symbol("\\theta", "θ", category="greek-lower"),
    Symbol("\\vartheta", "ϑ", category="greek-lower"),
    Symbol("\\iota", "ι", category="greek-lower"),
    Symbol("\\kappa", "κ", category="greek-lower"),
    Symbol("\\varkappa", "ϰ", category="greek-lower"),
    Symbol("\\lambda", "λ", category="greek-lower"),
    Symbol("\\mu", "μ", category="greek-lower"),
    Symbol("\\nu", "ν", category="greek-lower"),
    Symbol("\\xi", "ξ", category="greek-lower"),
    Symbol("\\pi", "π", category="greek-lower"),
    Symbol("\\varpi", "ϖ", category="greek-lower"),
    Symbol("\\rho", "ρ", category="greek-lower"),
    Symbol("\\varrho", "ϱ", category="greek-lower"),
    Symbol("\\sigma", "σ", category="greek-lower"),
    Symbol("\\varsigma", "ς", category="greek-lower"),
    Symbol("\\tau", "τ", category="greek-lower"),
    Symbol("\\upsilon", "υ", category="greek-lower"),
    Symbol("\\varphi", "φ", category="greek-lower"),
    Symbol("\\phi", "ϕ", category="greek-lower"),
    Symbol("\\chi", "χ", category="greek-lower"),
    Symbol("\\psi", "ψ", category="greek-lower"),
    Symbol("\\omega", "ω", category="greek-lower"),
    # Greek uppercase (only glyphs distinct from Latin)
    Symbol("\\Gamma", "Γ", category="greek-upper"),
    Symbol("\\Delta", "Δ", category="greek-upper"),
    Symbol("\\Theta", "Θ", category="greek-upper"),
    Symbol("\\Lambda", "Λ", category="greek-upper"),
    Symbol("\\Xi", "Ξ", category="greek-upper"),
    Symbol("\\Pi", "Π", category="greek-upper"),
    Symbol("\\Sigma", "Σ", category="greek-upper"),
    Symbol("\\Upsilon", "Υ", category="greek-upper"),
    Symbol("\\Phi", "Φ", category="greek-upper"),
    Symbol("\\Psi", "Ψ", category="greek-upper"),
    Symbol("\\Omega", "Ω", category="greek-upper"),
    # Binary operators
    Symbol("\\pm", "±", category="binary"),
    Symbol("\\mp", "∓", category="binary"),
    Symbol("\\times", "×", category="binary"),
    Symbol("\\div", "÷", category="binary"),
    Symbol("\\cdot", "·", category="binary"),
    Symbol("\\ast", "∗", category="binary"),
    Symbol("\\star", "⋆", category="binary"),
    Symbol("\\circ", "∘", category="binary"),
    Symbol("\\bullet", "∙", ("•",), category="binary"),
    Symbol("\\oplus", "⊕", category="binary"),
    Symbol("\\ominus", "⊖", category="binary"),
    Symbol("\\otimes", "⊗", category="binary"),
    Symbol("\\oslash", "⊘", category="binary"),
    Symbol("\\odot", "⊙", category="binary"),
    Symbol("\\wedge", "∧", category="binary"),
    Symbol("\\vee", "∨", category="binary"),
    Symbol("\\cap", "∩", category="binary"),
    Symbol("\\cup", "∪", category="binary"),
    Symbol("\\setminus", "∖", category="binary"),
    Symbol("\\uplus", "⊎", category="binary"),
    Symbol("\\sqcap", "⊓", category="binary"),
    Symbol("\\sqcup", "⊔", category="binary"),
    Symbol("\\wr", "≀", category="binary"),
    # Relations
    Symbol("\\leq", "≤", category="relation"),
    Symbol("\\geq", "≥", category="relation"),
    Symbol("\\neq", "≠", category="relation"),
    Symbol("\\approx", "≈", category="relation"),
    Symbol("\\equiv", "≡", category="relation"),
    Symbol("\\sim", "∼", category="relation"),
    Symbol("\\simeq", "≃", category="relation"),
    Symbol("\\cong", "≅", category="relation"),
    Symbol("\\asymp", "≍", category="relation"),
    Symbol("\\propto", "∝", category="relation"),
    Symbol("\\prec", "≺", category="relation"),
    Symbol("\\succ", "≻", category="relation"),
    Symbol("\\preceq", "⪯", category="relation"),
    Symbol("\\succeq", "⪰", category="relation"),
    Symbol("\\ll", "≪", category="relation"),
    Symbol("\\gg", "≫", category="relation"),
    Symbol("\\lesssim", "≲", category="relation"),
    Symbol("\\gtrsim", "≳", category="relation"),
    Symbol("\\subset", "⊂", category="relation"),
    Symbol("\\supset", "⊃", category="relation"),
    Symbol("\\subseteq", "⊆", category="relation"),
    Symbol("\\supseteq", "⊇", category="relation"),
    # Collision 3 -- \nsubseteq: the canonical glyph is U+2288, which is
    # what latex2mathml actually emits forward; U+2284 is properly
    # \not\subset and stays reachable only as a reverse spelling for a
    # hand-authored document that used it.
    Symbol("\\nsubseteq", "⊈", ("⊄",), category="relation"),
    Symbol("\\in", "∈", category="relation"),
    Symbol("\\notin", "∉", category="relation"),
    Symbol("\\ni", "∋", category="relation"),
    Symbol("\\vdash", "⊢", category="relation"),
    Symbol("\\models", "⊨", category="relation"),
    Symbol("\\perp", "⊥", category="relation"),
    Symbol("\\top", "⊤", category="relation"),
    Symbol("\\doteq", "≐", category="relation"),
    # Collision 5 -- the unary minus: U+2212 MINUS SIGN spells the macro
    # "-", which is not a LaTeX macro name, so this entry has no forward
    # side at all -- the forward direction emits the ASCII binary minus the
    # parser read, and a reversed unary minus re-parses as binary (both
    # render "-"; the distinction is not recoverable from OMML).
    Symbol("-", "−", category="relation"),
    # Logic / quantifiers / set symbols
    Symbol("\\forall", "∀", category="logic"),
    Symbol("\\exists", "∃", category="logic"),
    Symbol("\\nexists", "∄", category="logic"),
    Symbol("\\neg", "¬", category="logic"),
    Symbol("\\emptyset", "∅", category="logic"),
    Symbol("\\infty", "∞", category="logic"),
    Symbol("\\partial", "∂", category="logic"),
    Symbol("\\nabla", "∇", category="logic"),
    Symbol("\\hbar", "ℏ", category="logic"),
    Symbol("\\ell", "ℓ", category="logic"),
    Symbol("\\aleph", "ℵ", category="logic"),
    Symbol("\\wp", "℘", category="logic"),
    # Collision 2 -- \diamond: the canonical glyph is U+22C4, what
    # latex2mathml actually emits forward; U+25CA (the Lozenge of list
    # glyphs) stays a reverse-only alias.
    Symbol("\\diamond", "⋄", ("◊",), category="logic"),
    Symbol("\\square", "□", category="logic"),
    Symbol("\\triangle", "△", category="logic"),
    # Arrows
    Symbol("\\to", "→", category="arrow"),
    Symbol("\\leftarrow", "←", category="arrow"),
    Symbol("\\leftrightarrow", "↔", category="arrow"),
    Symbol("\\Rightarrow", "⇒", category="arrow"),
    Symbol("\\Leftarrow", "⇐", category="arrow"),
    Symbol("\\Leftrightarrow", "⇔", category="arrow"),
    Symbol("\\mapsto", "↦", category="arrow"),
    Symbol("\\uparrow", "↑", category="arrow"),
    Symbol("\\downarrow", "↓", category="arrow"),
    Symbol("\\updownarrow", "↕", category="arrow"),
    Symbol("\\Uparrow", "⇑", category="arrow"),
    Symbol("\\Downarrow", "⇓", category="arrow"),
    Symbol("\\Updownarrow", "⇕", category="arrow"),
    Symbol("\\nearrow", "↗", category="arrow"),
    Symbol("\\searrow", "↘", category="arrow"),
    Symbol("\\nwarrow", "↖", category="arrow"),
    Symbol("\\swarrow", "↙", category="arrow"),
    Symbol("\\rightleftharpoons", "⇌", category="arrow"),
    Symbol("\\rightharpoonup", "⇀", category="arrow"),
    Symbol("\\leftharpoonup", "↼", category="arrow"),
    # Dots / misc
    Symbol("\\ldots", "…", category="misc"),
    Symbol("\\cdots", "⋯", category="misc"),
    Symbol("\\vdots", "⋮", category="misc"),
    Symbol("\\ddots", "⋱", category="misc"),
    Symbol("\\therefore", "∴", category="misc"),
    Symbol("\\because", "∵", category="misc"),
    Symbol("\\angle", "∠", category="misc"),
    Symbol("\\frown", "⌢", category="misc"),
    Symbol("\\smile", "⌣", category="misc"),
    Symbol("\\|", "‖", category="misc"),
    Symbol("\\parallel", "∥", category="misc"),
    Symbol("\\hookrightarrow", "↪", category="misc"),
    # --- PLAN.md §6.1: the fix-file inventory ------------------------------
    # Every macro in this block was nameable nowhere in the pipeline before
    # §6.1; chars are declared here. Skipped from the detached reference
    # file's SYMBOL_MAP by design, each with its reason in the §6.1 record:
    # the 14 Greek capitals that look like Latin letters (the fix file
    # spells them as bare Latin letters -- not a macro name, and the
    # literal emission renders correctly), the degree forms ('^\\circ',
    # '^\\circ\\text{C}', '^\\circ\\text{F}' -- compound old-walker
    # spellings), and the invisible operators (already declared above).
    # \Finv has two glyphs; U+2132 is canonical, U+214E a reverse-only
    # alias (the \bullet pattern). \rangle \rceil \rfloor double as
    # delimiter spellings (DELIM_LEFTRIGHT) -- the established \parallel
    # precedent; both lookups yield the same macro.
    # misc
    Symbol("\\AA", "Å", category="misc"),
    # binary
    Symbol("\\Bumpeq", "≎", category="binary"),
    # misc
    Symbol("\\Colon", "::", category="misc"),
    Symbol("\\Euler", "ℇ", category="misc"),
    Symbol("\\Finv", "Ⅎ", ("ⅎ",), category="misc"),
    Symbol("\\Game", "⅁", category="misc"),
    # arrow
    Symbol("\\Lleftarrow", "⇚", category="arrow"),
    Symbol("\\Longleftarrow", "⟸", category="arrow"),
    Symbol("\\Longleftrightarrow", "⟺", category="arrow"),
    Symbol("\\Longrightarrow", "⟹", category="arrow"),
    Symbol("\\Lsh", "↲", category="arrow"),
    Symbol("\\Rrightarrow", "⇛", category="arrow"),
    Symbol("\\Rsh", "↳", category="arrow"),
    # relation
    Symbol("\\VDash", "⊫", category="relation"),
    Symbol("\\Vdash", "⊩", category="relation"),
    Symbol("\\Vvdash", "⊪", category="relation"),
    # misc
    Symbol("\\Ydown", "⅄", category="misc"),
    # binary
    Symbol("\\backsim", "∽", category="binary"),
    # arrow
    Symbol("\\barleftarrow", "↸", category="arrow"),
    Symbol("\\barrightarrow", "↹", category="arrow"),
    # misc
    Symbol("\\beth", "ℶ", category="misc"),
    Symbol("\\blacksquare", "■", category="misc"),
    Symbol("\\bowtie", "⋈", category="misc"),
    # binary
    Symbol("\\boxminus", "⊟", category="binary"),
    Symbol("\\boxplus", "⊞", category="binary"),
    Symbol("\\boxtimes", "⊠", category="binary"),
    Symbol("\\capdot", "⩀", category="binary"),
    # arrow
    Symbol("\\carriagereturn", "↵", category="arrow"),
    # binary
    Symbol("\\cbrt", "∛", category="binary"),
    Symbol("\\circeq", "≗", category="binary"),
    # arrow
    Symbol("\\circlearrowleft", "↺", category="arrow"),
    Symbol("\\circlearrowright", "↻", category="arrow"),
    # binary
    Symbol("\\circledast", "⊛", category="binary"),
    Symbol("\\circledcirc", "⊚", category="binary"),
    # misc
    Symbol("\\complement", "∁", category="misc"),
    # binary
    Symbol("\\cupdot", "⩁", category="binary"),
    # relation
    Symbol("\\curlyeqprec", "⋞", category="relation"),
    Symbol("\\curlyeqsucc", "⋟", category="relation"),
    # binary
    Symbol("\\curlymeet", "⋏", category="binary"),
    Symbol("\\curlyvee", "⋎", category="binary"),
    # arrow
    Symbol("\\curvearrowleft", "↶", category="arrow"),
    Symbol("\\curvearrowright", "↷", category="arrow"),
    # misc
    Symbol("\\dagger", "†", category="misc"),
    Symbol("\\daleth", "ℸ", category="misc"),
    # arrow
    Symbol("\\dashleftarrow", "⇠", category="arrow"),
    Symbol("\\dashrightarrow", "⇢", category="arrow"),
    # relation
    Symbol("\\dashv", "⊣", category="relation"),
    # misc
    Symbol("\\ddagger", "‡", category="misc"),
    # relation
    Symbol("\\dotminus", "∸", category="relation"),
    Symbol("\\dotplus", "∔", category="relation"),
    # binary
    Symbol("\\dotsquare", "⊡", category="binary"),
    # arrow
    Symbol("\\downdownarrows", "⇊", category="arrow"),
    # binary
    Symbol("\\eqcolon", "⋕", category="binary"),
    Symbol("\\eqmeasured", "≞", category="binary"),
    Symbol("\\eqring", "≖", category="binary"),
    Symbol("\\equest", "≚", category="binary"),
    Symbol("\\estimates", "≙", category="binary"),
    # misc
    Symbol("\\eth", "ð", category="misc"),
    Symbol("\\flat", "♭", category="misc"),
    # binary
    Symbol("\\fourthroot", "∜", category="binary"),
    Symbol("\\ggg", "⋙", category="binary"),
    # misc
    Symbol("\\gimel", "ℷ", category="misc"),
    # binary
    Symbol("\\gtrapprox", "⪆", category="binary"),
    # arrow
    Symbol("\\hookleftarrow", "↩", category="arrow"),
    # misc
    Symbol("\\iddots", "⋰", category="misc"),
    Symbol("\\imath", "ı", category="misc"),
    Symbol("\\jmath", "ȷ", category="misc"),
    # arrow
    Symbol("\\leftarrowtail", "↢", category="arrow"),
    Symbol("\\leftleftarrows", "⇇", category="arrow"),
    Symbol("\\leftrightarrows", "⇆", category="arrow"),
    Symbol("\\leftrightdasharrow", "⇿", category="arrow"),
    Symbol("\\leftrightharpoons", "⇋", category="arrow"),
    Symbol("\\leftrightsquigarrow", "↭", category="arrow"),
    Symbol("\\leftsquigarrow", "⇜", category="arrow"),
    # binary
    Symbol("\\lessapprox", "⪅", category="binary"),
    Symbol("\\lll", "⋘", category="binary"),
    # arrow
    Symbol("\\longleftarrow", "⟵", category="arrow"),
    Symbol("\\longleftrightarrow", "⟷", category="arrow"),
    Symbol("\\longrightarrow", "⟶", category="arrow"),
    # binary
    Symbol("\\ltimes", "⋉", category="binary"),
    # arrow
    Symbol("\\mapsdown", "↧", category="arrow"),
    Symbol("\\mapsup", "↥", category="arrow"),
    # binary
    Symbol("\\measuredangle", "∡", category="binary"),
    # misc
    Symbol("\\mho", "℧", category="misc"),
    Symbol("\\multimap", "⊷", category="misc"),
    # arrow
    Symbol("\\nLeftarrow", "⇍", category="arrow"),
    Symbol("\\nLeftrightarrow", "⇎", category="arrow"),
    Symbol("\\nRightarrow", "⇏", category="arrow"),
    # relation
    Symbol("\\nVDash", "⊯", category="relation"),
    Symbol("\\nVdash", "⊮", category="relation"),
    # binary
    Symbol("\\napprox", "≉", category="binary"),
    Symbol("\\nasymp", "≏", category="binary"),
    Symbol("\\ncong", "≇", category="binary"),
    Symbol("\\nequiv", "≢", category="binary"),
    Symbol("\\ngeq", "≱", category="binary"),
    # relation
    Symbol("\\ngsim", "≵", category="relation"),
    # binary
    Symbol("\\ngtr", "≯", category="binary"),
    # arrow
    Symbol("\\nleftarrow", "↚", category="arrow"),
    Symbol("\\nleftrightarrow", "↮", category="arrow"),
    # binary
    Symbol("\\nleq", "≰", category="binary"),
    Symbol("\\nless", "≮", category="binary"),
    # relation
    Symbol("\\nlsim", "≴", category="relation"),
    Symbol("\\nmid", "∤", category="relation"),
    Symbol("\\notni", "∌", category="relation"),
    Symbol("\\nparallel", "∦", category="relation"),
    # binary
    Symbol("\\nprec", "⊀", category="binary"),
    # relation
    Symbol("\\npreccurlyeq", "⋠", category="relation"),
    # arrow
    Symbol("\\nrightarrow", "↛", category="arrow"),
    # binary
    Symbol("\\nsim", "≁", category="binary"),
    Symbol("\\nsimeq", "≄", category="binary"),
    Symbol("\\nsucc", "⊁", category="binary"),
    # relation
    Symbol("\\nsucccurlyeq", "⋡", category="relation"),
    # binary
    Symbol("\\nsupset", "⊅", category="binary"),
    Symbol("\\nsupseteq", "⊉", category="binary"),
    # relation
    Symbol("\\ntgtr", "≹", category="relation"),
    Symbol("\\ntless", "≸", category="relation"),
    Symbol("\\ntriangleleft", "⋤", category="relation"),
    Symbol("\\ntrianglelefteq", "⋢", category="relation"),
    Symbol("\\ntriangleright", "⋥", category="relation"),
    Symbol("\\ntrianglerighteq", "⋣", category="relation"),
    Symbol("\\nvDash", "⊭", category="relation"),
    Symbol("\\nvdash", "⊬", category="relation"),
    # misc
    Symbol("\\perspective", "⌆", category="misc"),
    # binary
    Symbol("\\pitchfork", "⋔", category="binary"),
    # relation
    Symbol("\\precnsim", "⋨", category="relation"),
    # binary
    Symbol("\\precsim", "≾", category="binary"),
    Symbol("\\questeq", "≟", category="binary"),
    # misc
    Symbol("\\rangle", "〉", category="misc"),
    Symbol("\\rceil", "⌉", category="misc"),
    Symbol("\\rfloor", "⌋", category="misc"),
    # binary
    Symbol("\\rightangle", "∟", category="binary"),
    # arrow
    Symbol("\\rightarrowtail", "↣", category="arrow"),
    Symbol("\\rightleftarrows", "⇄", category="arrow"),
    Symbol("\\rightrightarrows", "⇉", category="arrow"),
    Symbol("\\rightsquigarrow", "⇝", category="arrow"),
    # binary
    Symbol("\\rtimes", "⋊", category="binary"),
    Symbol("\\sphericalangle", "∢", category="binary"),
    Symbol("\\sqsubset", "⊏", category="binary"),
    Symbol("\\sqsubseteq", "⊑", category="binary"),
    Symbol("\\sqsupset", "⊐", category="binary"),
    Symbol("\\sqsupseteq", "⊒", category="binary"),
    # misc
    Symbol("\\sslash", "⫽", category="misc"),
    # relation
    Symbol("\\succnsim", "⋩", category="relation"),
    # binary
    Symbol("\\succsim", "≿", category="binary"),
    Symbol("\\timesbar", "⨰", category="binary"),
    # arrow
    Symbol("\\twoheaddownarrow", "↡", category="arrow"),
    Symbol("\\twoheadleftarrow", "↞", category="arrow"),
    Symbol("\\twoheadrightarrow", "↠", category="arrow"),
    Symbol("\\twoheaduparrow", "↟", category="arrow"),
    Symbol("\\uplsh", "↰", category="arrow"),
    Symbol("\\uprsh", "↱", category="arrow"),
    Symbol("\\upuparrows", "⇈", category="arrow"),
    # Invisible operators that should simply vanish if they leak into text:
    # macro "" is not a macro name, so this is reverse-only too.
    Symbol("", "⁡", ("⁢", "⁣"), category="invisible"),
]

# Reverse spelling (many-to-one) and forward emit target (injective).
# A character that appears twice -- as a canonical glyph and as another
# macro's alias -- would make the reverse lookup ambiguous and the forward
# table non-injective; both are import-time errors, never a silent
# overwrite. `MACRO_TO_CHAR` is keyed by macro only for real macro names,
# exactly the old `_invert_symbol_map` rule, so the reverse-only entries
# (macro "" and "-") stay out of it.
SYMBOL_MAP = {}
MACRO_TO_CHAR = {}
for _sym in SYMBOLS:
    if _sym.macro in MACRO_TO_CHAR:
        raise AssertionError(
            f"symbol macro {_sym.macro!r} declared twice in registry")
    if _sym.macro.startswith("\\") and len(_sym.macro) > 1:
        MACRO_TO_CHAR[_sym.macro] = _sym.char
    for _ch in (_sym.char,) + _sym.aliases:
        if _ch in SYMBOL_MAP:
            raise AssertionError(
                f"symbol character {_ch!r} mapped twice in registry")
        SYMBOL_MAP[_ch] = _sym.macro


# --- Delimiters: one declaration per spelling -------------------------------


@dataclass(frozen=True)
class Delim:
    """One delimiter spelling (what follows ``\\left``/``\\right``). `char`
    is the canonical codepoint the emitter writes for the spelling;
    `aliases` are glyphs a document may contain that mean the same
    delimiter."""

    spelling: str
    char: str
    aliases: tuple = ()


# The opening and closing character sets a delimiter slot can receive --
# membership on a string would treat the empty text of a "\left." delimiter
# as a match. "|" and "‖" live in both sets (AMBIGUOUS_CHARS); they are only
# ever tagged via explicit @form or by position around a matrix.
OPEN_CHARS = set("([{|‖⌈⌊⟨〈〈/⎡⎣")
CLOSE_CHARS = set(")]}|‖⌉⌋⟩〉〉\\⎤⎦")
AMBIGUOUS_CHARS = OPEN_CHARS & CLOSE_CHARS

DELIMS = [
    Delim("(", "("),
    Delim(")", ")"),
    Delim("\\{", "{"),
    Delim("\\}", "}"),
    # Collision 4 -- \langle/\rangle: the canonical glyphs are U+2329/U+232A,
    # what every hand-authored Word equation in the corpus actually uses
    # (measured: 39 occurrences of U+2329, 0 of U+27E8 and U+3008). The
    # deprecated-by-Unicode codepoint wins because it is the one that keeps a
    # round trip glyph-identical for every document this converter has seen;
    # U+27E8/U+27E9 and U+3008/U+3009 remain reverse-only aliases. Spelled
    # with \\u escapes because the two families' glyphs are visually
    # indistinguishable in most fonts -- a transcription error here silently
    # breaks the round trip it exists to protect.
    Delim("\\langle", "〈", ("⟨", "〈")),
    Delim("\\rangle", "〉", ("⟩", "〉")),
    Delim("\\lceil", "⌈"),
    Delim("\\rceil", "⌉"),
    Delim("\\lfloor", "⌊"),
    Delim("\\rfloor", "⌋"),
    Delim("|", "|"),
    Delim("\\|", "‖"),
    # U+23A1/U+23A3 and U+23A4/U+23A6: the corner pieces Word uses to render
    # a square bracket taller than one glyph. They are pieces of the
    # stretchy brackets, so they are aliases of "["/"]" -- a round trip
    # re-spells them as \left[ / \right], which renders identically and
    # reaches a fixed point instead of emitting the raw glyph (which the
    # parser then rejects as "not a delimiter").
    Delim("[", "[", ("⎡", "⎣")),
    Delim("]", "]", ("⎤", "⎦")),
    # Both "\\" and "/" can reach a delimiter slot (they are in
    # OPEN_CHARS/CLOSE_CHARS); a missing spelling made the reverse walker
    # fall through to the raw character: `\right\` is a lone backslash --
    # not a delimiter, not valid LaTeX, and it cost 7 math zones across the
    # corpus before being mapped. Every character in the two sets needs a
    # spelling for exactly that reason (asserted below).
    Delim("\\backslash", "\\"),
    Delim("/", "/"),
    # The empty delimiter: `\left.` / `\right.` (a real case).
    Delim(".", ""),
]

DELIM_LEFTRIGHT = {}
DELIM_SPELLING_TO_CHAR = {}
for _delim in DELIMS:
    if _delim.spelling in DELIM_SPELLING_TO_CHAR:
        raise AssertionError(
            f"delimiter spelling {_delim.spelling!r} declared twice")
    DELIM_SPELLING_TO_CHAR[_delim.spelling] = _delim.char
    for _ch in (_delim.char,) + _delim.aliases:
        if _ch in DELIM_LEFTRIGHT:
            raise AssertionError(
                f"delimiter character {_ch!r} mapped twice in registry")
        DELIM_LEFTRIGHT[_ch] = _delim.spelling

# Totality (moved from mathsyms.py's import-time assertion): every
# character that can reach a delimiter slot needs a spelling, or the
# reverse walker silently falls through to the raw character. Fails loudly
# at import, never at a round trip in the middle of a corpus sweep.
_MISSING_DELIM_SPELLINGS = (OPEN_CHARS | CLOSE_CHARS) - set(DELIM_LEFTRIGHT)
if _MISSING_DELIM_SPELLINGS:
    raise AssertionError(
        "delimiter character(s) without a DELIM_LEFTRIGHT spelling: "
        + " ".join(sorted(_MISSING_DELIM_SPELLINGS))
    )


# --- N-ary operators --------------------------------------------------------


@dataclass(frozen=True)
class NaryOp:
    """One n-ary operator: macro, glyph, and whether its limits sit above
    and below (the sum/union family) or to the side (integrals)."""

    macro: str
    char: str
    underover: bool = False


NARY_OPS = [
    NaryOp("\\int", "∫"),
    NaryOp("\\iint", "∬"),
    NaryOp("\\iiint", "∭"),
    NaryOp("\\oint", "∮"),
    NaryOp("\\oiint", "∯"),
    NaryOp("\\oiiint", "∰"),
    # §6.1 additions: the multiple-integral family (side limits, like the
    # other integrals).
    NaryOp("\\iiiint", "⨌"),
    NaryOp("\\fint", "⨍"),
    NaryOp("\\sqint", "⨎"),
    NaryOp("\\sum", "∑", True),
    NaryOp("\\prod", "∏", True),
    NaryOp("\\coprod", "∐", True),
    NaryOp("\\bigcup", "⋃", True),
    NaryOp("\\bigcap", "⋂", True),
    NaryOp("\\bigodot", "⨀", True),
    NaryOp("\\bigoplus", "⨁", True),
    NaryOp("\\bigotimes", "⨂", True),
    NaryOp("\\biguplus", "⨄", True),
    NaryOp("\\bigsqcup", "⨆", True),
    # §6.1 additions: the missing big operators (underover, like the rest
    # of the \big family).
    NaryOp("\\bigwedge", "⋀", True),
    NaryOp("\\bigvee", "⋁", True),
]

NARY_MACROS = {}
NARY_CHAR_TO_MACRO = {}
NARY_CHARS = set()
NARY_UNDOVR = set()
for _nary in NARY_OPS:
    if _nary.macro in NARY_MACROS or _nary.char in NARY_CHARS:
        raise AssertionError(
            f"n-ary operator {_nary.macro!r}/{_nary.char!r} declared twice")
    NARY_MACROS[_nary.macro] = _nary.char
    NARY_CHAR_TO_MACRO[_nary.char] = _nary.macro
    NARY_CHARS.add(_nary.char)
    if _nary.underover:
        NARY_UNDOVR.add(_nary.char)

# Totality (moved from mathast.py's assertion pair): every glyph mathsyms
# classifies as an n-ary operator has exactly one macro declaration here.
assert NARY_CHARS == NARY_CHAR_TO_MACRO.keys(), "n-ary glyph mismatch"
assert NARY_UNDOVR <= NARY_CHARS, "n-ary underover glyph not declared"


# --- Accents ----------------------------------------------------------------


@dataclass(frozen=True)
class Accent:
    """One accent: the macro name (`"hat"`, `"bar"`, ...), the canonical
    combining character the emitter writes, and reverse-only combining
    aliases a document may contain instead."""

    macro: str
    char: str
    aliases: tuple = ()


# \bar's canonical mark is U+0305 COMBINING OVERLINE -- what Word actually
# writes (census: 73 occurrences vs 0 of U+0304 COMBINING MACRON). U+0304
# renders identically and is kept as a reverse-only alias so a document
# written with it still reverses to \bar; it must not become a second
# forward entry, because the accent construct derives its macro->mark
# vocabulary from the canonical direction and two marks per macro would
# break MACRO_TO_CONSTRUCT's injectivity.
ACCENTS = [
    Accent("vec", "⃗"),
    Accent("ddot", "̈"),
    Accent("hat", "̂"),
    Accent("dot", "̇"),
    Accent("bar", "̅", ("̄",)),
    Accent("tilde", "̃"),
    Accent("check", "̌"),
    Accent("acute", "́"),
    Accent("grave", "̀"),
    Accent("breve", "̆"),
    Accent("dddot", "⃛"),
    Accent("ddddot", "⃜"),
]

ACCENT_REVERSE = {}
ACCENT_REVERSE_ALIASES = {}
ACCENT_TO_CHAR = {}
for _acc in ACCENTS:
    if _acc.macro in ACCENT_TO_CHAR:
        raise AssertionError(
            f"accent macro {_acc.macro!r} declared twice in registry")
    ACCENT_TO_CHAR[_acc.macro] = _acc.char
    if _acc.char in ACCENT_REVERSE:
        raise AssertionError(
            f"accent character {_acc.char!r} mapped twice in registry")
    # Canonical marks drive both directions; aliases are reverse-only (the
    # forward accent vocabulary must stay one macro per mark, or
    # MACRO_TO_CONSTRUCT's injectivity assertion trips).
    ACCENT_REVERSE[_acc.char] = _acc.macro
    for _alias in _acc.aliases:
        if _alias in ACCENT_REVERSE or _alias in ACCENT_REVERSE_ALIASES:
            raise AssertionError(
                f"accent alias {_alias!r} mapped twice in registry")
        ACCENT_REVERSE_ALIASES[_alias] = _acc.macro


# --- Spaces ------------------------------------------------------------------


@dataclass(frozen=True)
class Space:
    """One space: the glyph, its bare LaTeX spelling (no join-safety
    trailing space -- that is derived data, see `SPACE_TO_LATEX` below,
    never stripped off a stored spelling), whether a join-safety trailing
    space is added on emission, and whether the spelling is a macro an
    author types (macro-visible)."""

    glyph: str
    spelling: str
    join: bool
    visible: bool


SPACES = [
    # U+2009 THIN SPACE -> \,
    Space(" ", "\\,", True, True),
    # U+2005 FOUR-PER-EM SPACE -> \:
    Space(" ", "\\:", True, True),
    # U+2004 THREE-PER-EM SPACE -> \; (thickspace, 5/18em): wider than \:'s
    # four-per-em glyph, narrower than \quad's full em -- matching the
    # relative ordering \, < \: < \; < \quad the other entries encode.
    Space(" ", "\\;", True, True),
    Space(" ", "\\quad", True, True),
    # U+2006 SIX-PER-EM SPACE is the internal gap inside compound names
    # ("lim sup"), not a macro an author types -- reverse-only, excluded
    # from the macro-visible table below exactly as the old strip-based
    # derivation dropped it (a bare " " spelling strips to nothing).
    Space(" ", " ", False, False),
    # Collision 6a -- the control space: the forward target is ORDINARY
    # U+0020, not U+2007 FIGURE SPACE (defect 1): a literal ASCII space in a
    # math run must come back as one space, not get inflated into
    # \quad/an EM SPACE. U+0020 <-> "\ " is a clean bijection. Its spelling
    # ends in the one character -- a literal space -- that makes it that
    # macro at all, so `join` is False: that space already *is* the join
    # separator, and adding another would double it. This is the exact case
    # the old `mathast` derivation truncated ("\ ".strip() == "\\", a bare,
    # meaningless backslash); the registry's bare spelling is never stripped,
    # so there is nothing left to truncate.
    Space(" ", "\\ ", False, True),
    # U+00A0 NO-BREAK SPACE is LaTeX's tie, `~` -- a *full* two-way entry,
    # not an alias, because `~` is the one form that keeps both the ordinary
    # width and the no-break-here meaning. No join space: `~` is a single
    # character, not a macro name, so nothing can glue onto it. Escaped
    # explicitly: the NBSP glyph is indistinguishable from an ordinary space
    # in source, and a transcription slip here silently turns the tie into
    # the control space (two entries sharing one key, last one wins).
    Space(" ", "~", False, True),
]

# Collision 6b -- the reverse-only space aliases: characters a real Word
# equation (or an older run of this converter) may contain that mean the
# same spacing as an entry above. They must not join SPACE_TO_LATEX itself:
# a second codepoint for an existing spelling would silently repoint that
# macro's canonical forward glyph (the old derivation picked last-wins).
# Declared as (alias, target glyph) so the reverse spelling is taken from
# the target's own entry, never re-typed.
SPACE_ALIASES = (
    # U+2007 FIGURE SPACE -- this project's old (pre-defect-1) forward
    # target for `\ ` (the control space, U+0020).
    (" ", " "),
    # U+2001 EM QUAD -- same width as U+2003, already \quad.
    (" ", " "),
    # U+2000 EN QUAD -- half that width; no existing glyph is exactly EN
    # width, so it maps to the nearest of the four established proportional
    # spellings, \; (5/18em), rather than being silently dropped as an
    # unrecognised character.
    (" ", " "),
)

SPACE_CHARS = {_s.glyph for _s in SPACES}
# The emitted spelling: bare spelling plus a join-safety space when the
# macro's own spelling does not already end in one.
SPACE_TO_LATEX = {
    _s.glyph: _s.spelling + (" " if _s.join else "")
    for _s in SPACES
}
# The macro-visible bare spellings, keyed by spelling: the space construct's
# variant vocabulary (mathast.py derives it from here with no stripping, so
# the truncation class of bug is structurally gone).
SPACE_MACRO_TO_GLYPH = {
    _s.spelling: _s.glyph for _s in SPACES if _s.visible
}
SPACE_CHAR_ALIASES = {
    _alias: SPACE_TO_LATEX[_target]
    for _alias, _target in SPACE_ALIASES
}
CONTROL_SPACE_CHAR = " "
CONTROL_SPACE_LATEX = "\\ "
NBSP_CHAR = " "

# --- \text{...} content escapes (CANONICAL.md Rule 9) -----------------------
#
# \text{...} switches LaTeX to text mode, where a handful of ASCII
# characters stay special (%, &, _, $, #, {, }) and two more have no literal
# spelling at all and need a named macro (~ is LaTeX's active tie character
# even in text mode; ^ starts an accent). One declaration per escape, both
# directions derived: the decode side keys on the spelling without a leading
# backslash, the encode side writes "\" + spelling, with an empty group
# after the named macros -- never a space, since text mode renders every
# space literally and "{}" is invisible and disambiguates just as well.


@dataclass(frozen=True)
class Escape:
    """One escape: the literal character and the spelling that encodes it
    inside ``\\text{...}`` (no leading backslash)."""

    char: str
    spelling: str


ESCAPES = [
    Escape("~", "textasciitilde"),
    Escape("^", "textasciicircum"),
    Escape("%", "%"),
    Escape("&", "&"),
    Escape("_", "_"),
    Escape("$", "$"),
    Escape("#", "#"),
    Escape("{", "{"),
    Escape("}", "}"),
]

TEXT_ESCAPE_TO_CHAR = {}
TEXT_CHAR_TO_ESCAPE = {}
for _esc in ESCAPES:
    if _esc.char in TEXT_CHAR_TO_ESCAPE:
        raise AssertionError(
            f"escape character {_esc.char!r} declared twice in registry")
    TEXT_ESCAPE_TO_CHAR[_esc.spelling] = _esc.char
    if _esc.spelling.isalpha():
        TEXT_CHAR_TO_ESCAPE[_esc.char] = "\\" + _esc.spelling + "{}"
    else:
        TEXT_CHAR_TO_ESCAPE[_esc.char] = "\\" + _esc.spelling
