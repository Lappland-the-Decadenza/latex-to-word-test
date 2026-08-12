"""Assemble mixed original/generated DOCX blocks and OPC dependencies."""

from __future__ import annotations

import hashlib
import os
import uuid
import zipfile
from copy import deepcopy
from pathlib import Path

from lxml import etree

from ..docx.package import validate_docx_package
from .block_diff import DeleteBlock, InsertBlock, ReplaceBlock, ReuseBlock
from .block_render import RenderedBlock, render_latex_blocks

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


class PackageConflict(ValueError):
    """A stale source or invalid generated dependency prevents publication."""


class PackageResult:
    def __init__(self, path, warnings, reused, changed):
        self.path = Path(path)
        self.warnings = tuple(warnings)
        self.reused = reused
        self.changed = changed


def _resolve(root, path):
    cursor = root
    for step in path:
        matches = [item for item in cursor if item.tag == step.qname]
        if step.ordinal >= len(matches):
            raise PackageConflict("stored block location is stale")
        cursor = matches[step.ordinal]
    return cursor


def _source_groups(root, block_map):
    groups = {}
    for record in block_map.records:
        container = _resolve(root, record.location.container_path)
        elements = tuple(_resolve(root, path) for path in record.location.element_paths)
        if any(element.getparent() is not container for element in elements):
            raise PackageConflict("stored block is no longer in its source container")
        payload = b"".join(etree.tostring(item, encoding="utf-8", with_tail=False) for item in elements)
        if hashlib.sha256(payload).hexdigest() != record.original_xml_sha256:
            raise PackageConflict(f"stale block location for label {record.label}")
        groups[record.label] = elements
    return groups


def _new_rid(rels):
    used = {item.get("Id") for item in rels}
    number = 1
    while f"rId{number}" in used:
        number += 1
    return f"rId{number}"


def _adopt(rendered: RenderedBlock, original_rels, media, content_types):
    by_id = {item.rid: item for item in rendered.relationships}
    remapped = {}
    for payload in rendered.elements:
        root = etree.fromstring(payload)
        for element in root.iter():
            for attribute, value in list(element.attrib.items()):
                if not attribute.startswith("{" + R_NS + "}"):
                    continue
                local = attribute.rsplit("}", 1)[-1]
                if local not in {"id", "embed", "link"}:
                    continue
                if value in remapped:
                    element.set(attribute, remapped[value])
                    continue
                relation = by_id.get(value)
                if relation is None:
                    raise PackageConflict("generated XML references an unknown relationship")
                new_id = _new_rid(original_rels)
                remapped[value] = new_id
                if relation.target_mode == "External":
                    target = relation.target
                    target_mode = "External"
                elif relation.target.startswith("media/"):
                    part = next((item for item in rendered.package_parts
                                 if item.name == "word/" + relation.target), None)
                    if part is None:
                        raise PackageConflict("generated media relationship target is missing")
                    digest = hashlib.sha256(part.data).hexdigest()[:20]
                    suffix = Path(part.name).suffix.lower()
                    media_name = f"word/media/lw-{digest}{suffix}"
                    media.setdefault(media_name, part.data)
                    target = "media/" + Path(media_name).name
                    target_mode = None
                    extension = suffix.lstrip(".").lower()
                    content_types.setdefault(extension, part.content_type)
                else:
                    raise PackageConflict("generated block references unsupported internal package part")
                original_rels.append(etree.Element(f"{{{PR_NS}}}Relationship", {
                    "Id": new_id, "Type": relation.reltype, "Target": target,
                    **({"TargetMode": target_mode} if target_mode else {}),
                }))
                element.set(attribute, new_id)
        yield etree.tostring(root, encoding="utf-8", with_tail=False)


def _render_for_actions(edit, records, source, resources, source_groups):
    blocks = []
    style_hints = []
    language_hints = []
    spacing_hints = []
    by_label = {record.label: record for record in records}

    def hints(record):
        elements = source_groups.get(record.label, ())
        language = record.language_hint
        if language is None:
            counts = {}
            for element in elements:
                for node in element.iter(f"{{{W_NS}}}lang"):
                    value = node.get(f"{{{W_NS}}}val")
                    if value:
                        counts[value] = counts.get(value, 0) + 1
            language = max(counts, key=counts.get, default=None)
        spacing = record.spacing_hint
        if spacing is None:
            for element in elements:
                if any(
                    "  " in (node.text or "") and "\u2003" not in (node.text or "")
                    for node in element.iter(f"{{{M_NS}}}t")
                ):
                    spacing = "word-double-space"
                    break
        return language, spacing

    for action in edit.actions:
        if isinstance(action, ReplaceBlock):
            blocks.append(action.edited_block)
            style_hints.append(action.record.style_hint)
            language, spacing = hints(action.record)
            language_hints.append(language)
            spacing_hints.append(spacing)
        elif isinstance(action, InsertBlock):
            blocks.append(action.edited_block)
            record = by_label.get(action.edited_block.label)
            style_hints.append(record.style_hint if record else None)
            language, spacing = hints(record) if record else (None, None)
            language_hints.append(language)
            spacing_hints.append(spacing)
    rendered = iter(render_latex_blocks(
        blocks, template_docx=source, resources=resources,
        style_hints=style_hints,
        language_hints=language_hints, spacing_hints=spacing_hints,
    ))
    by_block = {}
    warnings = []
    for block in blocks:
        value = next(rendered)
        by_block[id(block)] = value
        warnings.extend(value.warnings)
    return by_block, warnings


def assemble_docx(source, edit, block_map, output, *, resources=None):
    """Build a complete candidate beside the source; never writes source in place."""

    source = Path(source).resolve()
    output = Path(output).resolve()
    if source == output:
        raise PackageConflict("candidate output must differ from source")
    if output.parent != source.parent and not output.parent.is_dir():
        raise PackageConflict("candidate output parent does not exist")
    with zipfile.ZipFile(source) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    document = etree.fromstring(parts["word/document.xml"])
    body = document.find(f"{{{W_NS}}}body")
    groups = _source_groups(document, block_map)
    rendered_by_block, warnings = _render_for_actions(
        edit, block_map.records, source, resources or {}, groups
    )
    reusable = {}
    generated = {}
    for action in edit.actions:
        if isinstance(action, ReuseBlock):
            reusable[action.edited_block.label] = tuple(deepcopy(item) for item in groups[action.record.label])
        elif isinstance(action, ReplaceBlock):
            generated[id(action.edited_block)] = rendered_by_block[id(action.edited_block)]
        elif isinstance(action, InsertBlock):
            generated[id(action.edited_block)] = rendered_by_block[id(action.edited_block)]
    original_elements = {id(item) for group in groups.values() for item in group}
    first_index = min((index for index, item in enumerate(body) if id(item) in original_elements), default=len(body) - 1)
    desired = []
    for block in edit.edited:
        if block.label is not None and block.label in reusable:
            desired.extend(reusable[block.label])
            continue
        rendered = generated.get(id(block))
        if rendered is None:
            raise PackageConflict(f"no rendered payload for block at source position {block.start}")
        desired.extend(etree.fromstring(item) for item in rendered.elements)
    rel_root = etree.fromstring(parts["word/_rels/document.xml.rels"])
    media = {}
    content_types_root = etree.fromstring(parts["[Content_Types].xml"])
    content_types = {item.get("Extension", "").lower(): item.get("ContentType", "")
                     for item in content_types_root if item.tag == f"{{{CT_NS}}}Default"}
    adopted = []
    for block in edit.edited:
        if block.label is not None and block.label in reusable:
            continue
        rendered = generated[id(block)]
        adopted.extend(etree.fromstring(item) for item in _adopt(rendered, rel_root, media, content_types))
    # Rebuild desired order with adopted generated elements and exact reused elements.
    cursor = 0
    final_desired = []
    for block in edit.edited:
        if block.label is not None and block.label in reusable:
            final_desired.extend(reusable[block.label])
        else:
            count = len(generated[id(block)].elements)
            final_desired.extend(adopted[cursor:cursor + count])
            cursor += count
    for child in list(body):
        if id(child) in original_elements:
            body.remove(child)
    insertion = min(first_index, len(body))
    for offset, child in enumerate(final_desired):
        body.insert(insertion + offset, child)
    for extension, content_type in content_types.items():
        if not any(item.tag == f"{{{CT_NS}}}Default" and item.get("Extension", "").lower() == extension
                   for item in content_types_root):
            content_types_root.append(etree.Element(f"{{{CT_NS}}}Default", {
                "Extension": extension, "ContentType": content_type,
            }))
    parts["word/document.xml"] = etree.tostring(document, encoding="utf-8", xml_declaration=True, standalone=True)
    parts["word/_rels/document.xml.rels"] = etree.tostring(rel_root, encoding="utf-8", xml_declaration=True, standalone=True)
    parts["[Content_Types].xml"] = etree.tostring(content_types_root, encoding="utf-8", xml_declaration=True, standalone=True)
    temporary = output.parent / f".{output.name}.candidate-{uuid.uuid4()}"
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in parts.items():
                archive.writestr(name, data)
            for name, data in media.items():
                archive.writestr(name, data)
        issues = validate_docx_package(temporary)
        if issues:
            raise PackageConflict("candidate package is invalid: " + "; ".join(map(str, issues[:3])))
        os.replace(temporary, output)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    return PackageResult(output, warnings, len(reusable), len(edit.edited) - len(reusable))


__all__ = ["PackageConflict", "PackageResult", "assemble_docx"]
