"""Import DOCX provenance during the sole reverse-conversion traversal."""

from __future__ import annotations

import shutil
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import re
from lxml import etree

from ..docx.package import validate_docx_package
from ..docx.read import docx_to_latex_with_blocks
from .block_schema import (
    BlockLocation, BlockMap, BlockRecord, BlockSession, NestedRecord, PathStep,
    digest_bytes, write_json,
)
from .diagnostics import append_diagnostics
from .shadow_blocks import read_shadow_blocks


class WorkspaceError(ValueError):
    """The immutable authoritative-shadow workspace cannot be created."""


def classify_warnings(warnings):
    """Retain the diagnostic classifier for non-AI compatibility callers."""

    deferred = tuple(item for item in warnings if "was not sidecar-preserved" in item)
    unknown = tuple(item for item in warnings if item not in deferred)
    return (), deferred, unknown


def _stage(reporter, name):
    return reporter.stage(name) if reporter is not None else nullcontext()


def _path(root, element):
    steps = []
    cursor = element
    while cursor is not root:
        parent = cursor.getparent()
        if parent is None:
            raise WorkspaceError("reader provenance element is outside document root")
        ordinal = sum(1 for item in parent[:parent.index(cursor)] if item.tag == cursor.tag)
        steps.append(PathStep(cursor.tag, ordinal))
        cursor = parent
    return tuple(reversed(steps))


def _xml_hash(elements):
    payload = b"".join(etree.tostring(item, encoding="utf-8", with_tail=False) for item in elements)
    return digest_bytes(payload)


def _hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _created_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def import_docx(staging: Path, source: Path, *, original_source=None, reporter=None):
    """Create shadow, provenance, and the current/original document copies."""

    current = staging / "current.docx"
    shutil.copyfile(source, current)
    original = Path(original_source or source).resolve()
    if not original.is_file():
        raise WorkspaceError(f"original DOCX does not exist: {original}")
    shutil.copyfile(original, staging / "original.docx")
    shadow_path = staging / "shadow.tex"
    with _stage(reporter, "convert"):
        result = docx_to_latex_with_blocks(str(source), str(shadow_path))
    append_diagnostics(staging, "import", result.warnings)
    shadow_path.write_text(result.latex, encoding="utf-8", newline="\n")
    with _stage(reporter, "provenance"):
        blocks = read_shadow_blocks(result.latex)
        if len(blocks) != len(result.blocks):
            raise WorkspaceError("direct reader block count does not match labelled shadow")
        records = []
        for order, (shadow, converted) in enumerate(zip(blocks, result.blocks)):
            if shadow.label is None:
                raise WorkspaceError("reader emitted an unlabelled source block")
            elements = tuple(origin.element for origin in converted.elements)
            root = elements[0].getroottree().getroot()
            body = root.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}body")
            location = BlockLocation(
                converted.part, _path(root, body),
                tuple(_path(root, element) for element in elements),
                converted.block_kind,
            )
            records.append(BlockRecord(
                shadow.label, location, shadow.latex, _xml_hash(elements), order,
                converted.style_hint,
                converted.language_hint, converted.spacing_hint,
            ))
    source_hash = _hash_file(current)
    nested = []
    item_pattern = re.compile(r"%lw:item:(\d+)\s*\n\\item\b")
    for record, shadow, converted in zip(records, blocks, result.blocks):
        if record.location.block_kind != "list":
            continue
        matches = list(item_pattern.finditer(shadow.latex))
        for item_order, match in enumerate(matches):
            if item_order >= len(converted.elements):
                break
            end = matches[item_order + 1].start() if item_order + 1 < len(matches) else len(shadow.latex)
            item_latex = shadow.latex[match.end():end].strip()
            element = converted.elements[item_order].element
            nested.append(NestedRecord(
                int(match.group(1)), record.label, "item", item_latex, item_order,
                BlockLocation(converted.part, _path(root, body), (_path(root, element),), "item"),
                _xml_hash((element,)),
            ))
    block_map = BlockMap(source_hash, 0, tuple(records), tuple(nested))
    map_path = staging / "shadow.map.json"
    write_json(map_path, block_map.to_json())
    session = BlockSession(source_hash, _hash_file(shadow_path), _hash_file(map_path))
    write_json(staging / "session.json", session.to_json())
    (staging / "proposals").mkdir()
    return session, block_map


__all__ = ["WorkspaceError", "classify_warnings", "import_docx", "validate_docx_package"]
