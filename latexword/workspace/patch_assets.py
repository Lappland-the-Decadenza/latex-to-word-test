"""Transplant rendered image assets into one atomic OOXML package patch."""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from copy import deepcopy
from pathlib import Path

from lxml import etree


R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


def stage_resources(root, resources):
    for name, source in (resources or {}).items():
        target = root / Path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


class PackageAssets:
    """Own image relationship and media additions for one package patch."""

    def __init__(self, source, conflict_type):
        self._conflict_type = conflict_type
        with zipfile.ZipFile(source) as archive:
            self.names = set(archive.namelist())
            self.replacements = {}
            self.additions = {}
            self.content_types = etree.fromstring(archive.read("[Content_Types].xml"))
            self._source = {name: archive.read(name) for name in self.names if name.endswith(".rels")}

    @staticmethod
    def _rels_name(part):
        path = part.lstrip("/")
        parent, name = path.rsplit("/", 1)
        return f"{parent}/_rels/{name}.rels"

    def _rels_root(self, part):
        name = self._rels_name(part)
        data = self.replacements.get(name) or self._source.get(name)
        root = (
            etree.Element(f"{{{PR_NS}}}Relationships", nsmap={None: PR_NS})
            if data is None else etree.fromstring(data)
        )
        return name, root

    def _ensure_content_type(self, extension, generated_types):
        existing = {
            item.get("Extension", "").lower() for item in self.content_types
            if item.tag == f"{{{CT_NS}}}Default"
        }
        if extension.lower() in existing:
            return
        generated = next((
            item for item in generated_types
            if item.tag == f"{{{CT_NS}}}Default"
            and item.get("Extension", "").lower() == extension.lower()
        ), None)
        if generated is None:
            raise self._conflict_type(f"fragment image type .{extension} has no package content type")
        self.content_types.append(deepcopy(generated))
        self.replacements["[Content_Types].xml"] = etree.tostring(
            self.content_types, encoding="utf-8", xml_declaration=True, standalone=True,
        )

    def adopt(self, payload, fragment_docx, target_part):
        root = etree.fromstring(payload)
        references = list(root.xpath(".//*[@r:embed]", namespaces={"r": R_NS}))
        if not references:
            return payload
        with zipfile.ZipFile(fragment_docx) as archive:
            rels = etree.fromstring(archive.read("word/_rels/document.xml.rels"))
            generated_types = etree.fromstring(archive.read("[Content_Types].xml"))
            by_id = {item.get("Id"): item for item in rels}
            rel_name, target_rels = self._rels_root(target_part)
            used_ids = {item.get("Id") for item in target_rels}
            for reference in references:
                relation = by_id.get(reference.get(f"{{{R_NS}}}embed"))
                target = "" if relation is None else relation.get("Target", "")
                if relation is None or relation.get("TargetMode") == "External" or not target.startswith("media/"):
                    raise self._conflict_type("fragment image relationship is invalid")
                data = archive.read("word/" + target)
                suffix = Path(target).suffix.lower()
                media_name = f"word/media/lw-{hashlib.sha256(data).hexdigest()[:20]}{suffix}"
                if media_name not in self.names and media_name not in self.additions:
                    self.additions[media_name] = data
                index = 1
                while f"rId{index}" in used_ids:
                    index += 1
                new_id = f"rId{index}"
                used_ids.add(new_id)
                etree.SubElement(target_rels, f"{{{PR_NS}}}Relationship", {
                    "Id": new_id, "Type": relation.get("Type"),
                    "Target": "media/" + Path(media_name).name,
                })
                reference.set(f"{{{R_NS}}}embed", new_id)
                self._ensure_content_type(suffix.lstrip("."), generated_types)
            self.replacements[rel_name] = etree.tostring(
                target_rels, encoding="utf-8", xml_declaration=True, standalone=True,
            )
        return etree.tostring(root, encoding="utf-8", with_tail=False)


__all__ = ["PackageAssets", "R_NS", "stage_resources"]
