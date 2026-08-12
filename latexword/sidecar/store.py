"""Orchestration owner for detached Word-only state."""

from __future__ import annotations

import os
import re
import hashlib
import json
import zipfile

from .capture import capture_object, capture_package_part
from .io import load_manifest, save_manifest
from .model import SidecarAttachment
from .restore import payload, restore_object


_SAFE_ID = re.compile(r"^n[0-9]{8,}$")


class ObjectStore:
    """Read/write one ``<tex-stem>.objects`` sidecar."""

    VERSION = 3

    def __init__(
        self,
        root,
        *,
        archive=None,
        writable=False,
        owns_archive=False,
        source_sha256=None,
        expected_source_sha256=None,
    ):
        self.root = os.path.abspath(root)
        self.archive = archive
        self.writable = writable
        self._owns_archive = owns_archive
        self.source_sha256 = source_sha256
        self._expected_source_sha256 = expected_source_sha256
        self.objects = []
        self._by_id = {}
        self.attachments = []
        self._by_payload = {}
        self._manifest_dirty = False
        if writable:
            os.makedirs(os.path.join(self.root, "parts"), exist_ok=True)
        else:
            self._load()

    @classmethod
    def for_write(cls, tex_path, archive):
        root = os.path.splitext(os.path.abspath(tex_path))[0] + ".objects"
        owned = zipfile.ZipFile(archive.filename) if getattr(archive, "filename", None) else archive
        source_sha256 = _archive_sha256(owned)
        return cls(
            root,
            archive=owned,
            writable=True,
            owns_archive=owned is not archive,
            source_sha256=source_sha256,
        )

    @classmethod
    def for_read(cls, tex_path, source_path=None):
        root = os.path.splitext(os.path.abspath(tex_path))[0] + ".objects"
        if not os.path.isfile(os.path.join(root, "manifest.json")):
            return None
        expected = _file_sha256(source_path) if source_path is not None else None
        return cls(root, expected_source_sha256=expected)

    def _load(self):
        (
            self.objects,
            self._by_id,
            self.source_sha256,
            self.attachments,
        ) = load_manifest(
            self.root,
            self.VERSION,
            _SAFE_ID,
            self._expected_source_sha256,
        )
        self._by_payload = {
            item.payload_id: item for item in self.attachments
        }

    def close(self):
        if self.writable and self._manifest_dirty:
            self._save()
            self._manifest_dirty = False
        if self._owns_archive and self.archive is not None:
            self.archive.close()
            self.archive = None
        if self.writable and not self.objects and not self.attachments:
            try:
                os.rmdir(os.path.join(self.root, "parts"))
                os.rmdir(self.root)
            except OSError:
                pass

    def _save(self):
        save_manifest(
            self.root, self.VERSION, self.objects, self.source_sha256,
            self.attachments,
        )

    def attach(
        self,
        kind,
        payload,
        *,
        owner_id,
        owner_semantic_hash,
        position="inside",
        ordinal=None,
        content_type="application/octet-stream",
        object_id=None,
    ):
        """Store one typed, content-addressed Word-only attachment."""
        if not self.writable:
            raise ValueError("attachment store is not writable")
        if isinstance(payload, str):
            data = payload.encode("utf-8")
        elif isinstance(payload, bytes):
            data = payload
        else:
            data = json.dumps(
                payload, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        payload_id = hashlib.sha256(data).hexdigest()
        rel_path = f"attachments/{payload_id}.bin"
        path = os.path.join(self.root, rel_path)
        if not os.path.isfile(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as stream:
                stream.write(data)
        record = SidecarAttachment(
            payload_id=payload_id,
            kind=kind,
            owner_id=owner_id,
            position=position,
            ordinal=len(self.attachments) if ordinal is None else ordinal,
            owner_semantic_hash=owner_semantic_hash,
            path=rel_path,
            sha256=payload_id,
            content_type=content_type,
            object_id=object_id,
        )
        self.attachments.append(record)
        self._by_payload.setdefault(payload_id, record)
        if kind == "paragraph-style":
            # Paragraph slots are intentionally recorded for every paragraph,
            # including unstyled ones.  Batch their manifest update; saving a
            # growing manifest once per slot turns a large document into an
            # avoidable quadratic filesystem operation.
            self._manifest_dirty = True
        else:
            self._save()
        return record

    def attachment_payload(self, attachment):
        """Read and verify an attachment payload by its content hash."""
        path = os.path.abspath(os.path.join(self.root, attachment.path))
        if os.path.commonpath((self.root, path)) != self.root:
            raise ValueError("sidecar attachment path escapes its directory")
        with open(path, "rb") as stream:
            data = stream.read()
        if hashlib.sha256(data).hexdigest() != attachment.sha256:
            raise ValueError("sidecar attachment payload hash mismatch")
        return data

    def attachments_for(self, owner_id, *, kind=None):
        return tuple(
            item for item in self.attachments
            if item.owner_id == owner_id and (kind is None or item.kind == kind)
        )

    def attachments_at(self, ordinal, *, kind=None):
        return tuple(
            item for item in self.attachments
            if item.ordinal == ordinal and (kind is None or item.kind == kind)
        )

    def nearest_attachments(self, kind, owner_semantic_hash, ordinal):
        candidates = [
            item for item in self.attachments
            if item.kind == kind and item.owner_semantic_hash == owner_semantic_hash
        ]
        if not candidates:
            return None
        exact = tuple(item for item in candidates if item.owner_id.value == f"n{ordinal:08d}")
        if exact:
            return (exact[0],) if len({item.payload_id for item in exact}) == 1 else exact
        distance = min(abs(item.ordinal - ordinal) for item in candidates)
        nearest = tuple(item for item in candidates if abs(item.ordinal - ordinal) == distance)
        return (nearest[0],) if len({item.payload_id for item in nearest}) == 1 else nearest

    def capture(self, root, *, kind, source_part="word/document.xml", context="inline"):
        return capture_object(
            self,
            root,
            kind=kind,
            source_part=source_part,
            context=context,
        )

    def capture_package_part(self, source_part, relationship_type):
        return capture_package_part(self, source_part, relationship_type)

    def _payload(self, obj, entry):
        return payload(self, obj, entry)

    def is_inline(self, object_id):
        obj = self._by_id.get(object_id)
        return bool(obj and obj.context.container == "inline")

    def restore(self, doc_part, object_id, *, paragraph=None, block=False):
        return restore_object(
            self,
            doc_part,
            object_id,
            paragraph=paragraph,
            block=block,
        )


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_sha256(archive):
    filename = getattr(archive, "filename", None)
    if filename:
        return _file_sha256(filename)
    fileobj = getattr(archive, "fp", None)
    if fileobj is None or not fileobj.seekable():
        raise ValueError("sidecar capture requires a seekable source archive")
    position = fileobj.tell()
    try:
        fileobj.seek(0)
        return hashlib.sha256(fileobj.read()).hexdigest()
    finally:
        fileobj.seek(position)
