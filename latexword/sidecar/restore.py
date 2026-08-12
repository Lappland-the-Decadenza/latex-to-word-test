"""Restore detached Word objects into a new OPC package."""

from __future__ import annotations

import hashlib
import os
import posixpath

from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import OxmlElement
from lxml import etree

from .paths import validate_relative


R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_R = "{" + R_NS + "}"
_WP = "{" + WP_NS + "}"


def local_name(element):
    return element.tag.rsplit("}", 1)[-1]


def rewrite_relationship_ids(root, mapping):
    for element in root.iter():
        for attr in list(element.attrib):
            if attr.startswith(_R) and attr.rsplit("}", 1)[-1] in {"id", "embed", "link"}:
                old = element.attrib[attr]
                if old in mapping:
                    element.set(attr, mapping[old])


def fresh_drawing_ids(package, root):
    used = set()
    for part in package.iter_parts():
        element = getattr(part, "element", None)
        if element is None:
            continue
        for doc_pr in element.iter(_WP + "docPr"):
            if doc_pr.get("id") is not None:
                used.add(doc_pr.get("id"))
    next_id = 1
    for doc_pr in root.iter(_WP + "docPr"):
        while str(next_id) in used:
            next_id += 1
        doc_pr.set("id", str(next_id))
        used.add(str(next_id))
        next_id += 1


def payload(store, obj, entry):
    rel_path = validate_relative(entry.path)
    path = os.path.abspath(os.path.join(store.root, rel_path))
    if os.path.commonpath((store.root, path)) != store.root:
        raise ValueError("sidecar path escapes its directory")
    with open(path, "rb") as stream:
        data = stream.read()
    if hashlib.sha256(data).hexdigest() != entry.sha256:
        raise ValueError("sidecar payload hash mismatch")
    return data


def _parts(store, doc_part, obj, object_id):
    by_source = {}
    used_names = {
        str(part.partname)
        for part in doc_part.package.iter_parts()
        if getattr(part, "partname", None) is not None
    }
    for index, entry in enumerate(obj.parts):
        ext = posixpath.splitext(entry.path)[1] or ".bin"
        # Image relationships are inspected by Word (and by the fidelity
        # instrument) as media parts.  Keeping a restored image under
        # ``word/objects`` makes it render, but makes a media hash look
        # missing.  Restore image payloads into the package's media namespace;
        # XML and other auxiliary parts remain private object parts.
        if (entry.content_type or "").startswith("image/"):
            stem = f"/word/media/sidecar_{object_id}_{index:04d}"
        else:
            stem = f"/word/objects/{object_id}/part{index:04d}"
        name_text = stem + ext
        suffix = 1
        while name_text in used_names:
            name_text = f"{stem}_{suffix}{ext}"
            suffix += 1
        name = PackURI(name_text)
        used_names.add(name_text)
        by_source[entry.source] = Part(
            name, entry.content_type, payload(store, obj, entry), doc_part.package
        )
    return by_source


def _link(doc_part, obj, by_source, source, rels):
    mapping = {}
    source_part = doc_part if source == obj.source_part else by_source[source]
    for rel in rels:
        if rel.external:
            new_id = source_part.relate_to(
                rel.target, rel.relationship_type, is_external=True
            )
        else:
            target = by_source.get(rel.part)
            if target is None:
                raise ValueError("sidecar relationship graph is incomplete")
            new_id = source_part.relate_to(target, rel.relationship_type)
        mapping[rel.relationship_id] = new_id
    return mapping


def _rewrite_parts(doc_part, obj, by_source):
    for entry in obj.parts:
        mapping = _link(
            doc_part, obj, by_source, entry.source, entry.relationships
        )
        part = by_source[entry.source]
        data = part.blob
        if entry.content_type.endswith("+xml") or data.lstrip().startswith(b"<?xml"):
            xml_root = etree.fromstring(data)
            rewrite_relationship_ids(xml_root, mapping)
            part._blob = etree.tostring(xml_root, encoding="UTF-8", xml_declaration=True)


def _insert_root(doc_part, root, paragraph, block):
    if block:
        if local_name(root) in {"sdt", "p", "tbl"}:
            doc_part.element.body.append(root)
        else:
            paragraph_root = OxmlElement("w:p")
            run = OxmlElement("w:r")
            run.append(root)
            paragraph_root.append(run)
            doc_part.element.body.append(paragraph_root)
    elif paragraph is not None:
        if local_name(root) in {"sdt", "p", "tbl"}:
            paragraph._p.append(root)
        else:
            run = OxmlElement("w:r")
            run.append(root)
            paragraph._p.append(run)
    else:
        raise ValueError("sidecar restore needs a paragraph or block context")


def restore_object(store, doc_part, object_id, *, paragraph=None, block=False):
    obj = store._by_id.get(object_id)
    if obj is None:
        return False
    by_source = _parts(store, doc_part, obj, object_id)
    _rewrite_parts(doc_part, obj, by_source)
    if obj.package_source:
        package_part = by_source.get(obj.package_source)
        if package_part is None:
            raise ValueError("package sidecar source is missing")
        doc_part.relate_to(package_part, obj.package_relationship_type)
        return True
    root_mapping = _link(
        doc_part, obj, by_source, obj.source_part, obj.relationships
    )
    root = etree.fromstring(obj.root_xml.encode("utf-8"))
    rewrite_relationship_ids(root, root_mapping)
    fresh_drawing_ids(doc_part.package, root)
    _insert_root(doc_part, root, paragraph, block)
    return True
