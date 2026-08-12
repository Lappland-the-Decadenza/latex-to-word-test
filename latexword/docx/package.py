"""DOCX package integrity checks and reference-template copying.

The document builder works with ``python-docx`` objects, but the defects this
module guards against live one level below that API: OPC relationships,
content types, and cross-part references.  Keeping the checks here makes the
validation usable both by the converter and by the standalone diagnostic.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import posixpath
from urllib.parse import unquote, urlsplit
import zipfile

from docx.opc.part import Part
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn
from lxml import etree


CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
NUMBERING_RELTYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
STYLES_WITH_EFFECTS_RELTYPE = "http://schemas.microsoft.com/office/2007/relationships/stylesWithEffects"

_CT = f"{{{CT_NS}}}"
_REL = f"{{{PKG_REL_NS}}}"
_W = f"{{{W_NS}}}"
_WP = f"{{{WP_NS}}}"


def clear_reference_body(doc):
    """Remove source content while retaining template-owned formatting."""
    body = doc._element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)
    content_reltypes = {RT.FOOTNOTES, RT.ENDNOTES, RT.COMMENTS}
    for rel in list(doc.part.rels.values()):
        if rel.reltype in content_reltypes:
            del doc.part.rels[rel.rId]
    settings = doc.settings.element
    for pr_name, ref_name in (("footnotePr", "footnote"), ("endnotePr", "endnote")):
        properties = settings.find(qn("w:" + pr_name))
        if properties is None:
            continue
        for reference in list(properties.findall(qn("w:" + ref_name))):
            properties.remove(reference)


@dataclass(frozen=True)
class PackageIssue:
    """One deterministic, actionable DOCX package finding."""

    part: str
    code: str
    detail: str

    def __str__(self):
        return f"{self.part}: {self.code}: {self.detail}"


class DocxPackageError(Exception):
    """Raised when a saved DOCX package fails integrity validation."""

    def __init__(self, issues):
        self.issues = tuple(issues)
        message = "invalid DOCX package"
        if self.issues:
            message += "\n" + "\n".join(str(issue) for issue in self.issues)
        super().__init__(message)


def _xml_parser():
    return etree.XMLParser(resolve_entities=False, no_network=True, recover=False)


def _is_xml_part(name):
    return name == "[Content_Types].xml" or name.endswith((".xml", ".rels"))


def _normal_part_name(name):
    return unquote(name).replace("\\", "/").lstrip("/")


def _source_part_from_rels(name):
    if name == "_rels/.rels":
        return ""
    marker = "/_rels/"
    if marker not in name or not name.endswith(".rels"):
        return None
    folder, rel_name = name.rsplit(marker, 1)
    return f"{folder}/{rel_name[:-5]}" if folder else rel_name[:-5]


def _resolve_target(source, target):
    """Resolve an OPC internal target and reject traversal out of the root."""
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return None
    target = unquote(parsed.path).replace("\\", "/")
    candidate = target.lstrip("/") if target.startswith("/") else posixpath.join(
        posixpath.dirname(source), target
    )
    resolved = posixpath.normpath(candidate)
    if resolved in ("", ".", "..") or resolved.startswith("../"):
        return None
    return resolved


def _replace_xml(target, source):
    """Replace a part's root content while retaining its part object."""
    target.clear()
    target.attrib.update(deepcopy(source.attrib))
    target.text = source.text
    target.tail = source.tail
    target.extend(deepcopy(list(source)))


def _replace_part_payload(target, source):
    source_element = getattr(source, "element", None)
    target_element = getattr(target, "element", None)
    if source_element is not None and target_element is not None:
        _replace_xml(target_element, source_element)
    else:
        target._blob = source.blob


def _copy_reference_dependency(target_doc, source_rel):
    """Copy a source theme/font-table dependency into the target package."""
    source_part = source_rel.target_part
    target_rel = None
    for rel in target_doc.part.rels.values():
        if rel.is_external:
            continue
        if rel.reltype == source_rel.reltype:
            target_rel = rel
            break
        if getattr(rel.target_part, "partname", None) == source_part.partname:
            target_rel = rel
            break

    if target_rel is not None:
        _replace_part_payload(target_rel.target_part, source_part)
        return

    copied = Part(
        source_part.partname,
        source_part.content_type,
        source_part.blob,
        target_doc.part.package,
    )
    target_doc.part.relate_to(copied, source_rel.reltype)


def copy_reference_template(target_doc, reference_path):
    """Copy reference styles, numbering, and their document-level dependencies.

    The target's ``python-docx`` part instances and relationships remain in
    place.  Only their XML/blob payload is replaced, so later builder changes
    continue to operate on the target package objects.
    """
    from docx import Document

    source = Document(reference_path)
    _replace_xml(target_doc.styles.element, source.styles.element)
    source_numbering = next(
        (
            rel.target_part
            for rel in source.part.rels.values()
            if not rel.is_external and rel.reltype == NUMBERING_RELTYPE
        ),
        None,
    )
    if source_numbering is not None:
        _replace_xml(target_doc.part.numbering_part.element, source_numbering.element)

    source_styles_with_effects = next(
        (
            rel
            for rel in source.part.rels.values()
            if not rel.is_external and rel.reltype == STYLES_WITH_EFFECTS_RELTYPE
        ),
        None,
    )
    target_styles_with_effects = [
        rel
        for rel in target_doc.part.rels.values()
        if not rel.is_external and rel.reltype == STYLES_WITH_EFFECTS_RELTYPE
    ]
    if source_styles_with_effects is None:
        for rel in target_styles_with_effects:
            del target_doc.part.rels[rel.rId]
    else:
        _copy_reference_dependency(target_doc, source_styles_with_effects)

    dependency_types = {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme",
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable",
    }
    for rel in source.part.rels.values():
        if not rel.is_external and rel.reltype in dependency_types:
            _copy_reference_dependency(target_doc, rel)


def _validate_content_types(names, roots, issues):
    root = roots.get("[Content_Types].xml")
    if root is None:
        issues.append(PackageIssue("[Content_Types].xml", "missing", "content types part is missing or invalid"))
        return

    defaults = {}
    overrides = {}
    for child in root:
        if child.tag == _CT + "Default":
            ext = (child.get("Extension") or "").lower()
            if ext in defaults:
                issues.append(PackageIssue("[Content_Types].xml", "duplicate-default", ext))
            defaults[ext] = child.get("ContentType") or ""
        elif child.tag == _CT + "Override":
            part = _normal_part_name(child.get("PartName") or "")
            if part in overrides:
                issues.append(PackageIssue("[Content_Types].xml", "duplicate-override", part))
            overrides[part] = child.get("ContentType") or ""

    for part in sorted(overrides):
        if part not in names:
            issues.append(PackageIssue("[Content_Types].xml", "missing-part", part))

    for name in sorted(names):
        if name == "[Content_Types].xml" or name.endswith("/"):
            continue
        if name in overrides:
            continue
        extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if extension not in defaults:
            issues.append(PackageIssue(name, "missing-content-type", extension or "<none>"))


def _validate_relationships(names, roots, issues):
    relationships = {}
    for rels_name in sorted(name for name in names if name.endswith(".rels")):
        source = _source_part_from_rels(rels_name)
        root = roots.get(rels_name)
        if source is None or root is None:
            continue
        if source and source not in names:
            issues.append(PackageIssue(rels_name, "missing-source", source))
        rel_map = {}
        for rel in root.findall(_REL + "Relationship"):
            rid = rel.get("Id") or ""
            if not rid:
                issues.append(PackageIssue(rels_name, "relationship-id", "empty relationship ID"))
                continue
            if rid in rel_map:
                issues.append(PackageIssue(rels_name, "duplicate-relationship-id", rid))
                continue
            target = rel.get("Target") or ""
            rel_map[rid] = rel
            if (rel.get("TargetMode") or "").lower() == "external":
                continue
            resolved = _resolve_target(source, target)
            if resolved is None:
                issues.append(PackageIssue(rels_name, "invalid-target", target))
            elif resolved not in names:
                issues.append(PackageIssue(rels_name, "missing-target", resolved))
        if source in relationships:
            issues.append(PackageIssue(rels_name, "duplicate-source", source))
        relationships[source] = rel_map
    return relationships


def _validate_relationship_references(names, roots, relationships, issues):
    for part in sorted(names):
        if part.endswith(".rels") or part == "[Content_Types].xml":
            continue
        root = roots.get(part)
        if root is None:
            continue
        rel_map = relationships.get(part, {})
        for element in root.iter():
            for attr, value in element.attrib.items():
                if attr.startswith("{" + R_NS + "}") and attr.rsplit("}", 1)[-1] in {
                    "id", "embed", "link"
                }:
                    if value not in rel_map:
                        local = attr.rsplit("}", 1)[-1]
                        issues.append(PackageIssue(part, "missing-relationship-reference", f"{local}={value}"))


def _validate_styles_and_numbering(roots, issues):
    styles = roots.get("word/styles.xml")
    numbering = roots.get("word/numbering.xml")
    num_ids = set()
    if numbering is not None:
        abstract_ids = {}
        for abstract in numbering.findall(_W + "abstractNum"):
            value = abstract.get(_W + "abstractNumId")
            if value in abstract_ids:
                issues.append(PackageIssue("word/numbering.xml", "duplicate-abstract-num-id", value or "<missing>"))
            abstract_ids[value] = abstract
        for num in numbering.findall(_W + "num"):
            value = num.get(_W + "numId")
            if value in num_ids:
                issues.append(PackageIssue("word/numbering.xml", "duplicate-num-id", value or "<missing>"))
            num_ids.add(value)
            abstract_ref = num.find(_W + "abstractNumId")
            abstract_id = abstract_ref.get(_W + "val") if abstract_ref is not None else None
            if abstract_id not in abstract_ids:
                issues.append(PackageIssue("word/numbering.xml", "missing-abstract-num", f"numId={value}, abstractNumId={abstract_id}"))

    if styles is None:
        return
    style_ids = {}
    for style in styles.findall(_W + "style"):
        style_id = style.get(_W + "styleId")
        if style_id in style_ids:
            issues.append(PackageIssue("word/styles.xml", "duplicate-style-id", style_id or "<missing>"))
        style_ids[style_id] = style

    for style in styles.findall(_W + "style"):
        style_id = style.get(_W + "styleId") or "<missing>"
        for child_name in ("basedOn", "next", "link"):
            child = style.find(_W + child_name)
            if child is not None:
                target = child.get(_W + "val")
                if target not in style_ids:
                    issues.append(PackageIssue("word/styles.xml", "missing-style-target", f"{style_id}.{child_name}={target}"))
        for num_id in style.findall(".//" + _W + "numId"):
            value = num_id.get(_W + "val")
            try:
                nonzero = int(value) != 0
            except (TypeError, ValueError):
                nonzero = True
            if nonzero and value not in num_ids:
                issues.append(PackageIssue("word/styles.xml", "missing-style-num-id", f"{style_id}={value}"))


def _validate_bookmarks_and_drawings(roots, issues):
    bookmark_ids = {}
    drawing_ids = {}
    for part in sorted(roots):
        root = roots[part]
        starts = Counter()
        ends = Counter()
        for element in root.iter(_W + "bookmarkStart"):
            value = element.get(_W + "id")
            starts[value] += 1
        for element in root.iter(_W + "bookmarkEnd"):
            value = element.get(_W + "id")
            ends[value] += 1
        if starts or ends:
            bookmark_ids[part] = (starts, ends)

        for doc_pr in root.iter(_WP + "docPr"):
            value = doc_pr.get("id")
            if value is None:
                issues.append(PackageIssue(part, "missing-doc-pr-id", "drawing docPr has no id"))
            elif value in drawing_ids:
                issues.append(PackageIssue(part, "duplicate-doc-pr-id", value))
            else:
                drawing_ids[value] = part

        for element in root.iter():
            for attr in element.attrib:
                if attr.startswith(_WP):
                    issues.append(PackageIssue(
                        part,
                        "namespaced-drawing-attribute",
                        f"{element.tag.rsplit('}', 1)[-1]}.{attr.rsplit('}', 1)[-1]}",
                    ))
        required = {
            _WP + "anchor": ("relativeHeight", "behindDoc", "locked", "layoutInCell", "allowOverlap"),
            _WP + "simplePos": ("x", "y"),
            _WP + "positionH": ("relativeFrom",),
            _WP + "positionV": ("relativeFrom",),
            _WP + "wrapSquare": ("wrapText",),
        }
        for tag, attributes in required.items():
            for element in root.iter(tag):
                for attr in attributes:
                    if element.get(attr) is None:
                        issues.append(PackageIssue(
                            part,
                            "missing-drawing-attribute",
                            f"{tag.rsplit('}', 1)[-1]}.{attr}",
                        ))

    for part, (starts, ends) in bookmark_ids.items():
        for value in sorted(set(starts) | set(ends), key=lambda item: "" if item is None else str(item)):
            if starts[value] != ends[value]:
                issues.append(PackageIssue(part, "unpaired-bookmark", str(value)))


def _ids_in_part(root, tag):
    return {element.get(_W + "id") for element in root.iter(tag)}


def _validate_note_and_comment_references(roots, issues):
    footnote_ids = _ids_in_part(roots["word/footnotes.xml"], _W + "footnote") if "word/footnotes.xml" in roots else set()
    endnote_ids = _ids_in_part(roots["word/endnotes.xml"], _W + "endnote") if "word/endnotes.xml" in roots else set()
    comment_ids = _ids_in_part(roots["word/comments.xml"], _W + "comment") if "word/comments.xml" in roots else set()

    checks = {
        "footnoteReference": footnote_ids,
        "endnoteReference": endnote_ids,
        "commentReference": comment_ids,
        "commentRangeStart": comment_ids,
        "commentRangeEnd": comment_ids,
    }
    for part in sorted(roots):
        root = roots[part]
        for local, valid_ids in checks.items():
            for element in root.iter(_W + local):
                value = element.get(_W + "id")
                if value not in valid_ids:
                    issues.append(PackageIssue(part, "missing-note-comment", f"{local}={value}"))

    settings = roots.get("word/settings.xml")
    if settings is not None:
        for kind, valid_ids in (("footnote", footnote_ids), ("endnote", endnote_ids)):
            properties = settings.find(_W + kind + "Pr")
            if properties is None:
                continue
            for reference in properties.findall(_W + kind):
                value = reference.get(_W + "id")
                if value not in valid_ids:
                    issues.append(PackageIssue(
                        "word/settings.xml",
                        "missing-note-comment",
                        f"{kind}={value}",
                    ))


def validate_docx_package(path):
    """Return all integrity issues found in a DOCX/OPC package.

    The function never mutates the package and never raises for a malformed
    input archive; malformed input is represented by one or more issues.
    """
    issues = []
    roots = {}
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        return [PackageIssue(str(path), "zip", str(exc))]

    with archive:
        names_in_order = [_normal_part_name(name) for name in archive.namelist()]
        names = set(names_in_order)
        for name, count in sorted(Counter(names_in_order).items()):
            if count > 1:
                issues.append(PackageIssue(name, "duplicate-zip-entry", str(count)))
        try:
            bad = archive.testzip()
        except (OSError, zipfile.BadZipFile) as exc:
            bad = None
            issues.append(PackageIssue(str(path), "zip", str(exc)))
        if bad is not None:
            issues.append(PackageIssue(_normal_part_name(bad), "zip-crc", "CRC check failed"))

        for name in sorted(names):
            if not _is_xml_part(name):
                continue
            try:
                roots[name] = etree.fromstring(archive.read(name), _xml_parser())
            except (OSError, KeyError, zipfile.BadZipFile, etree.XMLSyntaxError) as exc:
                issues.append(PackageIssue(name, "xml", str(exc)))

        _validate_content_types(names, roots, issues)
        relationships = _validate_relationships(names, roots, issues)
        _validate_relationship_references(names, roots, relationships, issues)
        _validate_styles_and_numbering(roots, issues)
        _validate_bookmarks_and_drawings(roots, issues)
        _validate_note_and_comment_references(roots, issues)

    return sorted(issues, key=lambda issue: (issue.part, issue.code, issue.detail))



# Relationship readers used by the reverse OOXML adapter.
def relationship_target(rels, rid):
    """Return a relationship target by id, or None for a missing id."""
    if not rid:
        return None
    return rels.get(rid)


def read_part_relationships(z, part_name):
    """Read external relationship targets for one package part."""
    rels_name = "word/_rels/" + part_name.rsplit("/", 1)[-1] + ".rels"
    if rels_name not in z.namelist():
        return {}
    root = etree.fromstring(z.read(rels_name))
    return {
        rel.get("Id"): rel.get("Target") or ""
        for rel in root.findall(f"{{{PKG_REL_NS}}}Relationship")
        if (rel.get("TargetMode") or "Internal") == "External"
    }


def read_document_relationships(z):
    """Read external relationships from document.xml."""
    return read_part_relationships(z, "word/document.xml")


def read_media_relationships(z):
    """Read internal document relationships whose targets are media files."""
    name = "word/_rels/document.xml.rels"
    if name not in z.namelist():
        return {}
    root = etree.fromstring(z.read(name))
    out = {}
    for rel in root.findall(f"{{{PKG_REL_NS}}}Relationship"):
        if (rel.get("TargetMode") or "Internal") == "External":
            continue
        target = (rel.get("Target") or "").replace("\\", "/")
        if target.startswith("media/") or "/media/" in target:
            out[rel.get("Id")] = target
    return out
