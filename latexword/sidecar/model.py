"""Typed records for the detached Word-only manifest."""

from __future__ import annotations

from dataclasses import dataclass

from ..document.identity import NodeId


@dataclass(frozen=True, slots=True)
class SidecarRelationship:
    relationship_id: str
    relationship_type: str
    external: bool
    target: str
    part: str | None = None

    @classmethod
    def from_manifest(cls, value):
        part = value.get("part")
        return cls(
            relationship_id=value["id"],
            relationship_type=value["type"],
            external=bool(value.get("external")),
            target=value["target"],
            part=part,
        )

    def to_manifest(self):
        value = {
            "id": self.relationship_id,
            "type": self.relationship_type,
            "external": self.external,
            "target": self.target,
        }
        if self.part is not None:
            value["part"] = self.part
        return value


@dataclass(frozen=True, slots=True)
class SidecarPart:
    source: str
    path: str
    content_type: str
    sha256: str
    relationships: tuple[SidecarRelationship, ...] = ()

    @classmethod
    def from_manifest(cls, value):
        return cls(
            source=value["source"],
            path=value["path"],
            content_type=value["content_type"],
            sha256=value["sha256"],
            relationships=tuple(
                SidecarRelationship.from_manifest(item)
                for item in value.get("relationships", [])
            ),
        )

    def to_manifest(self):
        return {
            "source": self.source,
            "path": self.path,
            "content_type": self.content_type,
            "sha256": self.sha256,
            "relationships": [item.to_manifest() for item in self.relationships],
        }


@dataclass(frozen=True, slots=True)
class SidecarContext:
    container: str | None
    parent: str | None

    @classmethod
    def from_manifest(cls, value):
        return cls(value.get("container"), value.get("parent"))

    def to_manifest(self):
        return {"container": self.container, "parent": self.parent}


@dataclass(frozen=True, slots=True)
class SidecarObject:
    node_id: NodeId
    kind: str
    source_part: str
    content_type: str
    root_xml: str
    relationships: tuple[SidecarRelationship, ...]
    parts: tuple[SidecarPart, ...]
    context: SidecarContext
    package_source: str | None = None
    package_relationship_type: str | None = None

    @property
    def object_id(self):
        return self.node_id.value

    @classmethod
    def from_manifest(cls, value):
        return cls(
            node_id=NodeId(value["id"]),
            kind=value["kind"],
            source_part=value["source_part"],
            content_type=value["content_type"],
            root_xml=value["root_xml"],
            relationships=tuple(
                SidecarRelationship.from_manifest(item)
                for item in value.get("relationships", [])
            ),
            parts=tuple(
                SidecarPart.from_manifest(item) for item in value.get("parts", [])
            ),
            context=SidecarContext.from_manifest(value.get("context", {})),
            package_source=value.get("package_source"),
            package_relationship_type=value.get("package_relationship_type"),
        )

    def to_manifest(self):
        value = {
            "id": self.object_id,
            "kind": self.kind,
            "source_part": self.source_part,
            "content_type": self.content_type,
            "root_xml": self.root_xml,
            "relationships": [item.to_manifest() for item in self.relationships],
            "parts": [item.to_manifest() for item in self.parts],
            "context": self.context.to_manifest(),
        }
        if self.package_source is not None:
            value["package_source"] = self.package_source
        if self.package_relationship_type is not None:
            value["package_relationship_type"] = self.package_relationship_type
        return value


@dataclass(frozen=True, slots=True)
class SidecarAttachment:
    """A typed Word-only payload attached to a semantic node span."""

    payload_id: str
    kind: str
    owner_id: NodeId
    position: str
    ordinal: int
    owner_semantic_hash: str
    path: str
    sha256: str
    content_type: str = "application/octet-stream"
    object_id: str | None = None

    @classmethod
    def from_manifest(cls, value):
        return cls(
            payload_id=value["payload_id"],
            kind=value["kind"],
            owner_id=NodeId(value["owner_id"]),
            position=value["position"],
            ordinal=int(value["ordinal"]),
            owner_semantic_hash=value["owner_semantic_hash"],
            path=value["path"],
            sha256=value["sha256"],
            content_type=value.get("content_type", "application/octet-stream"),
            object_id=value.get("object_id"),
        )

    def to_manifest(self):
        value = {
            "payload_id": self.payload_id,
            "kind": self.kind,
            "owner_id": self.owner_id.value,
            "position": self.position,
            "ordinal": self.ordinal,
            "owner_semantic_hash": self.owner_semantic_hash,
            "path": self.path,
            "sha256": self.sha256,
            "content_type": self.content_type,
        }
        if self.object_id is not None:
            value["object_id"] = self.object_id
        return value


__all__ = [
    "SidecarAttachment",
    "SidecarContext",
    "SidecarObject",
    "SidecarPart",
    "SidecarRelationship",
]
