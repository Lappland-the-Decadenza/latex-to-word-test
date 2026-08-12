from pathlib import Path

from tools.architecture_check import check


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _codes(root: Path) -> set[str]:
    return {violation.code for violation in check(root)}


def test_forbidden_edges_and_wildcards_are_reported(tmp_path):
    _write(tmp_path, "latexword/document/model.py", "from latexword.docx import read\n")
    _write(tmp_path, "latexword/math/latex/core.py", "from .ast import *\n")

    assert {"FORBIDDEN_EDGE", "WILDCARD_IMPORT"} <= _codes(tmp_path)


def test_cross_package_cycle_is_reported(tmp_path):
    _write(tmp_path, "latexword/document/model.py", "from latexword.latex import parse\n")
    _write(tmp_path, "latexword/latex/parse.py", "from latexword.document import model\n")

    assert "IMPORT_CYCLE" in _codes(tmp_path)


def test_waiver_requires_expiry_stage(tmp_path):
    _write(tmp_path, "latexword/document/model.py", "# architecture-waiver: FORBIDDEN_EDGE temporary\n")

    assert "WAIVER_INVALID" in _codes(tmp_path)


def test_new_oversized_file_is_reported(tmp_path):
    body = "\n".join(f"    value_{i} = {i}" for i in range(260))
    _write(tmp_path, "latexword/document/model.py", f"def build():\n{body}\n")

    assert "FILE_OVER_SOFT" in _codes(tmp_path)


def test_removed_word_carrier_is_reported(tmp_path):
    _write(tmp_path, "latexword/document/model.py", r'VALUE = r"\hlight"' + "\n")

    assert "FORBIDDEN_CARRIER" in _codes(tmp_path)
