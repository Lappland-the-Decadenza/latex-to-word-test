"""The document layer (PLAN.md §5.3).

- `read.py` -- docx -> LaTeX: paragraphs, lists, tables, sections, images,
  named styles, preamble generation; every math zone goes through
  `math.omml2latex.to_latex`.
- `write.py` -- LaTeX -> docx: block scanning, environments, nested lists,
  images, styling, the builder and the `.docx` build.

The finer responsibility split (blocks, lists, tables, images, styles,
package) is the plan's sketch of this layer; the two files remain the
boundary until a split pays for itself.
"""
