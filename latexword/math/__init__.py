"""The math pipeline (PLAN.md §5.3): parse, the construct table, spell and
load.

- `ast.py` -- the construct table: structural truth (the single source for
  each construct's OMML shape, properties, variants and canonical spelling).
- `tokenize.py` / `macros.py` -- lexical scanning and user-macro expansion.
- `parse.py` -- recursive-descent parser driven by `ast.py`.
- `serialize.py` -- the one canonical AST->LaTeX speller.
- `emit.py` -- AST->OMML emitter.
- `latex2omml.py` -- compatibility facade re-exporting the math API.
- `load.py` -- the OMML->AST loader (the reverse direction's walker).
- `omml2latex.py` -- the public reverse API: `to_latex` = `load` +
  `serialize`, plus the prose/`\\href` escaping shared with the document
  layer.

`mathsyms.py` (character truth) and `math.ast` (structural truth) are the
two sources of truth everything else reads from.
"""
