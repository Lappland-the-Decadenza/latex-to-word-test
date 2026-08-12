"""Persisted identities and source locations for authoritative shadow blocks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PathStep:
    qname: str
    ordinal: int

    def to_json(self):
        return {"qname": self.qname, "ordinal": self.ordinal}

    @classmethod
    def from_json(cls, value):
        return cls(value["qname"], int(value["ordinal"]))


@dataclass(frozen=True, slots=True)
class BlockLocation:
    part: str
    container_path: tuple[PathStep, ...]
    element_paths: tuple[tuple[PathStep, ...], ...]
    block_kind: str

    def to_json(self):
        return {
            "part": self.part,
            "container_path": [item.to_json() for item in self.container_path],
            "element_paths": [[item.to_json() for item in path] for path in self.element_paths],
            "block_kind": self.block_kind,
        }

    @classmethod
    def from_json(cls, value):
        return cls(
            value["part"],
            tuple(PathStep.from_json(item) for item in value["container_path"]),
            tuple(tuple(PathStep.from_json(item) for item in path) for path in value["element_paths"]),
            value["block_kind"],
        )


@dataclass(frozen=True, slots=True)
class BlockRecord:
    label: int
    location: BlockLocation
    original_latex: str
    original_xml_sha256: str
    source_order: int
    style_hint: str | None = None
    language_hint: str | None = None
    spacing_hint: str | None = None

    def to_json(self):
        return {
            "label": self.label,
            "location": self.location.to_json(),
            "original_latex": self.original_latex,
            "original_xml_sha256": self.original_xml_sha256,
            "source_order": self.source_order,
            "style_hint": self.style_hint,
            "language_hint": self.language_hint,
            "spacing_hint": self.spacing_hint,
        }

    @classmethod
    def from_json(cls, value):
        return cls(
            int(value["label"]), BlockLocation.from_json(value["location"]),
            value["original_latex"], value["original_xml_sha256"],
            int(value["source_order"]), value.get("style_hint"),
            value.get("language_hint"),
            value.get("spacing_hint") or (
                "word-double-space" if "\\qquad" in value["original_latex"] else None
            ),
        )


@dataclass(frozen=True, slots=True)
class NestedRecord:
    label: int
    parent_label: int
    kind: str
    original_latex: str
    source_order: int
    location: BlockLocation | None = None
    original_xml_sha256: str | None = None

    def to_json(self):
        return {
            "label": self.label, "parent_label": self.parent_label,
            "kind": self.kind, "original_latex": self.original_latex,
            "source_order": self.source_order,
            "location": self.location.to_json() if self.location else None,
            "original_xml_sha256": self.original_xml_sha256,
        }

    @classmethod
    def from_json(cls, value):
        location = value.get("location")
        return cls(int(value["label"]), int(value["parent_label"]), value["kind"],
                   value["original_latex"], int(value["source_order"]),
                   BlockLocation.from_json(location) if location else None,
                   value.get("original_xml_sha256"))


@dataclass(frozen=True, slots=True)
class BlockMap:
    source_docx_sha256: str
    generation: int
    records: tuple[BlockRecord, ...]
    nested_records: tuple[NestedRecord, ...] = ()

    def to_json(self):
        return {
            "schema": "lw-authoritative-block-map/v1",
            "source_docx_sha256": self.source_docx_sha256,
            "generation": self.generation,
            "records": [item.to_json() for item in self.records],
            "nested_records": [item.to_json() for item in self.nested_records],
        }

    @classmethod
    def from_json(cls, value):
        if value.get("schema") != "lw-authoritative-block-map/v1":
            raise ValueError("unsupported block map schema")
        return cls(
            value["source_docx_sha256"], int(value["generation"]),
            tuple(BlockRecord.from_json(item) for item in value["records"]),
            tuple(NestedRecord.from_json(item) for item in value.get("nested_records", ())),
        )


@dataclass(frozen=True, slots=True)
class BlockSession:
    source_docx_sha256: str
    shadow_sha256: str
    map_sha256: str
    generation: int = 0

    def to_json(self):
        return {
            "schema": "lw-authoritative-session/v1",
            "source_docx_sha256": self.source_docx_sha256,
            "shadow_sha256": self.shadow_sha256,
            "map_sha256": self.map_sha256,
            "generation": self.generation,
        }

    @classmethod
    def from_json(cls, value):
        if value.get("schema") != "lw-authoritative-session/v1":
            raise ValueError("unsupported block session schema")
        return cls(value["source_docx_sha256"], value["shadow_sha256"],
                   value["map_sha256"], int(value["generation"]))


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value):
    path.write_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")).encode("utf-8") + b"\n")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = ["BlockLocation", "BlockMap", "BlockRecord", "BlockSession", "NestedRecord",
           "PathStep", "digest_bytes", "read_json", "write_json"]
