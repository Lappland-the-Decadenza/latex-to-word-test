"""Regression coverage for nested-list builder state isolation."""

import os
import sys
import zipfile

import docx
from PIL import Image
from docx.oxml.ns import qn

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from latexword.docx.package import validate_docx_package
from latexword.docx.write import DocxBuilder

OMML = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def test_nested_list_child_builder_shares_document_state(tmp_path):
    image_path = tmp_path / "pixel.png"
    Image.new("RGB", (2, 2), "white").save(image_path)

    builder = DocxBuilder()
    builder.img_base = str(tmp_path)
    builder.parse(
        r"""
\begin{itemize}
\item Outer prose \footnote{note body} \includegraphics{pixel.png}
\begin{enumerate}
\item Inner prose and \[x^2\]
\end{enumerate}
\end{itemize}
"""
    )

    output = tmp_path / "nested.docx"
    builder.doc.save(output)
    assert validate_docx_package(output) == []
    assert builder.warnings == []
    with zipfile.ZipFile(output) as package:
        names = set(package.namelist())
    assert "word/footnotes.xml" in names
    assert any(name.startswith("word/media/") for name in names)

    document = docx.Document(output)
    paragraphs = document.paragraphs
    assert any("Outer prose" in paragraph.text for paragraph in paragraphs)
    assert any("Inner prose" in paragraph.text for paragraph in paragraphs)
    assert any(any(node.tag == OMML + "oMath" for node in paragraph._p.iter())
               for paragraph in paragraphs)
    levels = []
    for paragraph in paragraphs:
        ilvl = paragraph._p.find("./" + qn("w:pPr") + "/" + qn("w:numPr") + "/" + qn("w:ilvl"))
        if ilvl is not None:
            levels.append(ilvl.get(qn("w:val")))
    assert levels[:2] == ["0", "1"]
