"""Capture opaque package parts and their referenced OPC closure."""

from __future__ import annotations

import hashlib
import os
import posixpath

from lxml import etree

from ..document.identity import NodeId
from .model import SidecarContext, SidecarObject, SidecarPart, SidecarRelationship
from .paths import rels_name, resolve_target


CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CT = "{" + CT_NS + "}"
_REL = "{" + REL_NS + "}"
_R = "{" + R_NS + "}"


def content_types(archive):
    root = etree.fromstring(archive.read("[Content_Types].xml"))
    defaults = {
        el.get("Extension", "").lower(): el.get("ContentType", "")
        for el in root.findall(_CT + "Default")
    }
    overrides = {
        el.get("PartName", "").lstrip("/"): el.get("ContentType", "")
        for el in root.findall(_CT + "Override")
    }

    def get(name):
        if name in overrides:
            return overrides[name]
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        return defaults.get(ext, "application/octet-stream")

    return get


def relationships(archive, source):
    name = rels_name(source)
    if name not in archive.namelist():
        return []
    root = etree.fromstring(archive.read(name))
    return [
        {
            "id": rel.get("Id", ""),
            "type": rel.get("Type", ""),
            "external": (rel.get("TargetMode") or "").lower() == "external",
            "target": rel.get("Target", ""),
            "resolved": (
                None
                if (rel.get("TargetMode") or "").lower() == "external"
                else resolve_target(source, rel.get("Target", ""))
            ),
        }
        for rel in root.findall(_REL + "Relationship")
    ]


def referenced_relationship_ids(root):
    ids = set()
    for element in root.iter():
        for attr in element.attrib:
            if attr.startswith(_R) and attr.rsplit("}", 1)[-1] in {"id", "embed", "link"}:
                ids.add(element.attrib[attr])
    return ids


def _relationship_records(store, source_part, used, collect_part):
    records = []
    for rel in relationships(store.archive, source_part):
        if rel["id"] not in used:
            continue
        part = None
        if not rel["external"]:
            target = rel["resolved"]
            if target is None:
                raise ValueError("unsafe sidecar relationship target")
            collect_part(target)
            part = target
        records.append(
            SidecarRelationship(
                relationship_id=rel["id"],
                relationship_type=rel["type"],
                external=rel["external"],
                target=rel["target"],
                part=part,
            )
        )
    return tuple(records)


def _collect_part(store, object_id, parts, source_part, content_type):
    if source_part in parts:
        return
    if source_part not in store.archive.namelist():
        raise ValueError(f"missing sidecar relationship target: {source_part}")
    data = store.archive.read(source_part)
    part_index = len(parts)
    ext = posixpath.splitext(source_part)[1].lstrip(".") or "bin"
    rel_path = f"parts/{object_id}/part{part_index:04d}.{ext}"
    full_path = os.path.join(store.root, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "wb") as stream:
        stream.write(data)
    entry = SidecarPart(
        source=source_part,
        path=rel_path,
        content_type=content_type(source_part),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    parts[source_part] = entry
    try:
        xml_root = etree.fromstring(data)
        used = referenced_relationship_ids(xml_root)
    except (etree.XMLSyntaxError, ValueError):
        used = set()
    parts[source_part] = SidecarPart(
        source=entry.source,
        path=entry.path,
        content_type=entry.content_type,
        sha256=entry.sha256,
        relationships=_relationship_records(
            store,
            source_part,
            used,
            lambda target: _collect_part(
                store, object_id, parts, target, content_type
            ),
        ),
    )


def capture_object(store, root, *, kind, source_part, context):
    if not store.writable or store.archive is None:
        raise ValueError("object store is not writable")
    object_id = NodeId.allocate(len(store.objects) + 1)
    type_for = content_types(store.archive)
    parts = {}
    used = referenced_relationship_ids(root)
    root_relationships = _relationship_records(
        store,
        source_part,
        used,
        lambda target: _collect_part(
            store, object_id.value, parts, target, type_for
        ),
    )
    obj = SidecarObject(
        node_id=object_id,
        kind=kind,
        source_part=source_part,
        content_type=type_for(source_part),
        root_xml=etree.tostring(root, encoding="unicode"),
        relationships=root_relationships,
        parts=tuple(parts.values()),
        context=SidecarContext(
            container=context,
            parent=root.getparent().tag.rsplit("}", 1)[-1]
            if root.getparent() is not None
            else None,
        ),
    )
    store.objects.append(obj)
    store._by_id[obj.object_id] = obj
    store._save()
    return obj.object_id


def capture_package_part(store, source_part, relationship_type):
    rels = relationships(store.archive, source_part)
    fake = etree.Element("sidecarPackagePart", nsmap={"r": R_NS})
    for rel in rels:
        child = etree.SubElement(fake, "relationship")
        child.set(_R + "id", rel["id"])
    object_id = capture_object(
        store, fake, kind="package", source_part=source_part, context="package"
    )
    obj = store._by_id[object_id]
    data = store.archive.read(source_part)
    index = len(obj.parts)
    ext = posixpath.splitext(source_part)[1].lstrip(".") or "bin"
    rel_path = f"parts/{object_id}/part{index:04d}.{ext}"
    full_path = os.path.join(store.root, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "wb") as stream:
        stream.write(data)
    package_relationships = tuple(
        SidecarRelationship(
            relationship_id=rel["id"],
            relationship_type=rel["type"],
            external=rel["external"],
            target=rel["target"],
            part=None if rel["external"] else rel["resolved"],
        )
        for rel in rels
    )
    package_part = SidecarPart(
        source=source_part,
        path=rel_path,
        content_type=content_types(store.archive)(source_part),
        sha256=hashlib.sha256(data).hexdigest(),
        relationships=package_relationships,
    )
    obj = SidecarObject(
        node_id=obj.node_id,
        kind=obj.kind,
        source_part=obj.source_part,
        content_type=obj.content_type,
        root_xml=obj.root_xml,
        relationships=obj.relationships,
        parts=(*obj.parts, package_part),
        context=obj.context,
        package_source=source_part,
        package_relationship_type=relationship_type,
    )
    store.objects[-1] = obj
    store._by_id[object_id] = obj
    store._save()
    return object_id
