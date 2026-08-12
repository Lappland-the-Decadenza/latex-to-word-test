"""Regression coverage for typed recursive table-cell content."""

from lxml import etree

from latexword.docx import read as docx_to_latex
from latexword.docx import write as latex_to_docx


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def test_nested_table_and_display_math_in_cell_round_trip(tmp_path):
    source = tmp_path / "nested.tex"
    source.write_text(
        r"""\documentclass{article}
\begin{document}
\begin{tabular}{ll}
outer & \begin{tabular}{c}inner\\x\end{tabular} \\
math & \[x^2\] \\
\end{tabular}
\end{document}
""",
        encoding="utf-8",
    )
    first = tmp_path / "first.docx"
    _, warnings = latex_to_docx.convert_latex_to_docx(str(source), str(first))
    assert not warnings

    from zipfile import ZipFile

    with ZipFile(first) as package:
        document = etree.fromstring(package.read("word/document.xml"))
    tables = document.findall(".//" + W + "tbl")
    assert len(tables) >= 2
    assert document.find(".//" + M + "oMathPara") is not None

    tex, reverse_warnings = docx_to_latex.docx_to_latex(
        str(first), tex_path=str(tmp_path / "back.tex")
    )
    (tmp_path / "back.tex").write_text(tex, encoding="utf-8")
    assert "\\wordtable{" not in tex
    assert not reverse_warnings

    second = tmp_path / "second.docx"
    _, forward_warnings = latex_to_docx.convert_latex_to_docx(
        str(tmp_path / "back.tex"), str(second), str(first), reference_mode="copy"
    )
    assert not forward_warnings
