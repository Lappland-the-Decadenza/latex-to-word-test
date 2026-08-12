"""Atomic manifest persistence and payload validation."""

from __future__ import annotations

import hashlib
import json
import os
import re

from .paths import validate_relative
from .model import SidecarAttachment, SidecarObject


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _validate_relationships(raw, known_parts, label):
    relationships = raw.get("relationships", [])
    if not isinstance(relationships, list):
        raise ValueError(f"invalid {label} relationship list")
    seen = set()
    for relation in relationships:
        if not isinstance(relation, dict):
            raise ValueError(f"invalid {label} relationship")
        relationship_id = relation.get("id")
        if not isinstance(relationship_id, str) or not relationship_id:
            raise ValueError(f"invalid {label} relationship id")
        if relationship_id in seen:
            raise ValueError(f"ambiguous {label} relationship id")
        seen.add(relationship_id)
        external = bool(relation.get("external"))
        part = relation.get("part")
        if external:
            if part is not None:
                raise ValueError("external sidecar relationship has a package part")
        elif not isinstance(part, str) or part not in known_parts:
            raise ValueError("sidecar relationship graph is incomplete")


def _load_attachments(root, attachments):
    if not isinstance(attachments, list):
        raise ValueError("invalid Word attachment manifest")
    records = []
    for raw in attachments:
        if not isinstance(raw, dict):
            raise ValueError("invalid Word attachment")
        payload_id = raw.get("payload_id")
        owner_hash = raw.get("owner_semantic_hash")
        if not isinstance(payload_id, str) or not _SHA256.fullmatch(payload_id):
            raise ValueError("invalid Word attachment payload id")
        if not isinstance(owner_hash, str) or not _SHA256.fullmatch(owner_hash):
            raise ValueError("invalid Word attachment owner hash")
        if not isinstance(raw.get("ordinal"), int) or raw["ordinal"] < 0:
            raise ValueError("invalid Word attachment ordinal")
        rel_path = validate_relative(raw.get("path", ""))
        path = os.path.abspath(os.path.join(root, rel_path))
        if os.path.commonpath((root, path)) != root:
            raise ValueError("sidecar attachment path escapes its directory")
        with open(path, "rb") as stream:
            data = stream.read()
        if hashlib.sha256(data).hexdigest() != raw.get("sha256"):
            raise ValueError("sidecar attachment payload hash mismatch")
        if payload_id != raw.get("sha256"):
            raise ValueError("sidecar attachment id is not its content hash")
        records.append(SidecarAttachment.from_manifest(raw))
    return records


def _load_objects(root, objects, id_pattern):
    if not isinstance(objects, list):
        raise ValueError("invalid Word object sidecar manifest")
    records, by_id = [], {}
    for raw in objects:
        if not isinstance(raw, dict):
            raise ValueError("invalid Word object")
        object_id = raw.get("id")
        if not isinstance(object_id, str) or not id_pattern.fullmatch(object_id):
            raise ValueError("invalid Word object id")
        if object_id in by_id:
            raise ValueError("duplicate Word object id")
        parts = raw.get("parts")
        if not isinstance(parts, list):
            raise ValueError("invalid Word object part list")
        known_parts, paths = set(), set()
        for entry in parts:
            if not isinstance(entry, dict):
                raise ValueError("invalid Word object part")
            source = entry.get("source")
            if not isinstance(source, str) or not source or source in known_parts:
                raise ValueError("duplicate or invalid sidecar part source")
            known_parts.add(source)
            rel_path = validate_relative(entry.get("path", ""))
            if rel_path in paths:
                raise ValueError("duplicate sidecar payload path")
            paths.add(rel_path)
            path = os.path.abspath(os.path.join(root, rel_path))
            if os.path.commonpath((root, path)) != root:
                raise ValueError("sidecar path escapes its directory")
            with open(path, "rb") as stream:
                data = stream.read()
            if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
                raise ValueError("sidecar payload hash mismatch")
        for entry in parts:
            _validate_relationships(entry, known_parts, "part")
        _validate_relationships(raw, known_parts, "object")
        package_source = raw.get("package_source")
        if package_source is not None and package_source not in known_parts:
            raise ValueError("package sidecar source is missing")
        if package_source is not None and not isinstance(raw.get("package_relationship_type"), str):
            raise ValueError("package sidecar relationship type is missing")
        record = SidecarObject.from_manifest(raw)
        records.append(record)
        by_id[object_id] = record
    return records, by_id


def load_manifest(root, version, id_pattern, expected_source_sha256=None):
    with open(os.path.join(root, "manifest.json"), encoding="utf-8") as stream:
        manifest = json.load(stream)
    if manifest.get("version") != version:
        raise ValueError("unsupported Word object sidecar version")
    source_sha256 = manifest.get("source_sha256")
    if not isinstance(source_sha256, str) or len(source_sha256) != 64:
        raise ValueError("invalid Word object source hash")
    if expected_source_sha256 is not None and source_sha256 != expected_source_sha256:
        raise ValueError("Word object sidecar source hash mismatch")
    attachment_records = _load_attachments(root, manifest.get("attachments", []))
    records, by_id = _load_objects(root, manifest.get("objects"), id_pattern)
    return records, by_id, source_sha256, attachment_records


def save_manifest(root, version, objects, source_sha256, attachments=()):
    manifest = {
        "version": version,
        "source_sha256": source_sha256,
        "objects": [obj.to_manifest() for obj in objects],
        "attachments": [item.to_manifest() for item in attachments],
    }
    path = os.path.join(root, "manifest.json")
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temporary, path)
