"""Render changed shadow blocks with the production LaTeX document builder."""

from __future__ import annotations

import tempfile
import zipfile
import re
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from ..document.text import prose_escape
from ..docx.package import validate_docx_package
from ..docx.write import convert_latex_to_docx
from .patch_assets import stage_resources
from .shadow_blocks import ShadowBlock

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
XML_NS = "http://www.w3.org/XML/1998/namespace"
PR_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_PLAIN_STYLE_NAMES = {"normal", "body text", "обычный", "обычный текст"}


@dataclass(frozen=True, slots=True)
class RenderedRelationship:
    rid: str
    reltype: str
    target: str
    target_mode: str | None = None


@dataclass(frozen=True, slots=True)
class RenderedPart:
    name: str
    data: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class RenderedBlock:
    elements: tuple[bytes, ...]
    relationships: tuple[RenderedRelationship, ...]
    package_parts: tuple[RenderedPart, ...]
    warnings: tuple[str, ...]


def _literal(source):
    return "\\texttt{" + prose_escape(source) + "}"


def _content_types(root):
    defaults = {}
    for item in root:
        if item.tag == f"{{{CT_NS}}}Default":
            defaults[item.get("Extension", "").lower()] = item.get("ContentType", "")
    return defaults


def _extract(path):
    with zipfile.ZipFile(path) as archive:
        xml = etree.fromstring(archive.read("word/document.xml"))
        body = xml.find(f"{{{W_NS}}}body")
        elements = tuple(
            etree.tostring(child, encoding="utf-8", with_tail=False)
            for child in body if child.tag != f"{{{W_NS}}}sectPr"
        )
        rels = etree.fromstring(archive.read("word/_rels/document.xml.rels"))
        relationships = tuple(RenderedRelationship(
            item.get("Id"), item.get("Type"), item.get("Target"), item.get("TargetMode")
        ) for item in rels)
        types = _content_types(etree.fromstring(archive.read("[Content_Types].xml")))
        parts = []
        for name in archive.namelist():
            if name.startswith("word/media/"):
                suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                parts.append(RenderedPart(name, archive.read(name), types.get(suffix, "application/octet-stream")))
    return elements, relationships, tuple(parts)


def _style_is_plain(template_docx, style_id):
    if not style_id:
        return True
    with zipfile.ZipFile(template_docx) as archive:
        root = etree.fromstring(archive.read("word/styles.xml"))
    names = root.xpath(
        ".//w:style[@w:styleId=$style_id]/w:name/@w:val",
        namespaces={"w": W_NS}, style_id=style_id,
    )
    name = (names[0] if names else style_id).strip().casefold()
    compact = re.sub(r"[^\wа-яё]+", "", name)
    return name in _PLAIN_STYLE_NAMES or compact.endswith("normal")


def _preserve_style(elements, template_docx, style_id, language_hint=None,
                    spacing_hint=None):
    preserve_style = not _style_is_plain(template_docx, style_id)
    if (not preserve_style
            and not language_hint and not spacing_hint):
        return elements
    result = []
    for payload in elements:
        root = etree.fromstring(payload)
        if preserve_style:
            paragraphs = (root,) if root.tag == f"{{{W_NS}}}p" else root.xpath(
                ".//w:p", namespaces={"w": W_NS}
            )
            for paragraph in paragraphs:
                properties = paragraph.find(f"{{{W_NS}}}pPr")
                if properties is None:
                    properties = etree.Element(f"{{{W_NS}}}pPr")
                    paragraph.insert(0, properties)
                style = properties.find(f"{{{W_NS}}}pStyle")
                if style is None:
                    style = etree.Element(f"{{{W_NS}}}pStyle")
                    properties.insert(0, style)
                style.set(f"{{{W_NS}}}val", style_id)
        if language_hint:
            for run in root.xpath(
                ".//w:r | .//m:r", namespaces={"w": W_NS, "m": M_NS}
            ):
                properties = run.find(f"{{{W_NS}}}rPr")
                if properties is None:
                    properties = etree.Element(f"{{{W_NS}}}rPr")
                    run.insert(0, properties)
                language = properties.find(f"{{{W_NS}}}lang")
                if language is None:
                    language = etree.SubElement(properties, f"{{{W_NS}}}lang")
                language.set(f"{{{W_NS}}}val", language_hint)
        if spacing_hint == "word-double-space":
            for text in root.xpath(".//m:t", namespaces={"m": M_NS}):
                if text.text:
                    text.text = text.text.replace("\u2003\u2003", "  ")
                    if "  " in text.text:
                        text.set(f"{{{XML_NS}}}space", "preserve")
        result.append(etree.tostring(root, encoding="utf-8", with_tail=False))
    return tuple(result)


def _one(block, template_docx, resources, style_hint=None, language_hint=None,
         spacing_hint=None):
    temporary_root = Path(template_docx).resolve().parent / ".tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="render-", dir=temporary_root) as directory:
        root = Path(directory)
        tex = root / "block.tex"
        out = root / "block.docx"
        stage_resources(root, resources)
        tex.write_text(
            "\\documentclass{article}\n\\begin{document}"
            + block.latex + "\\end{document}\n",
            encoding="utf-8", newline="\n",
        )
        warnings = []
        try:
            _, converter_warnings = convert_latex_to_docx(
                str(tex), str(out), reference_doc=str(template_docx),
                reference_mode="rewrite",
            )
            warnings.extend(converter_warnings)
            if any("unknown text command" in item or item.startswith("dropped ")
                   for item in converter_warnings):
                raise ValueError("unsupported LaTeX command")
            if validate_docx_package(out):
                raise ValueError("renderer produced an invalid DOCX package")
        except Exception as exc:
            warnings.append(f"block {block.kind} rendered as literal: {exc}")
            tex.write_text(
                "\\documentclass{article}\n\\begin{document}"
                + _literal(block.latex) + "\\end{document}\n",
                encoding="utf-8", newline="\n",
            )
            convert_latex_to_docx(
                str(tex), str(out), reference_doc=str(template_docx),
                reference_mode="rewrite",
            )
        elements, relationships, parts = _extract(out)
        elements = _preserve_style(
            elements, template_docx, style_hint, language_hint, spacing_hint
        )
        if not elements:
            raise ValueError(f"block {block.kind} rendered no Word elements")
        return RenderedBlock(elements, relationships, parts, tuple(warnings))


def render_latex_blocks(blocks, *, template_docx, resources=None, style_hints=None,
                        language_hints=None, spacing_hints=None):
    """Render each changed or inserted block independently."""
    hints = tuple(style_hints or (None for _ in blocks))
    if len(hints) != len(blocks):
        raise ValueError("style hint count does not match block count")
    languages = tuple(language_hints or (None for _ in blocks))
    spacings = tuple(spacing_hints or (None for _ in blocks))
    if len(languages) != len(blocks) or len(spacings) != len(blocks):
        raise ValueError("block hint count does not match block count")
    return tuple(
        _one(block, Path(template_docx), resources or {}, style, language, spacing)
        for block, style, language, spacing in zip(
            blocks, hints, languages, spacings
        )
    )


__all__ = ["RenderedBlock", "RenderedPart", "RenderedRelationship", "render_latex_blocks"]
