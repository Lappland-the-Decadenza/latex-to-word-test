"""Mutable state shared by the forward document builder."""

from dataclasses import dataclass


@dataclass
class BuilderState:
    """State shared by a document builder and nested child builders."""

    doc: object
    warnings: list
    reference_doc: bool
    reference_mode: str
    missing_reference_styles: set
    img_base: str | None = None
    sidecar_ordinal: int = 0
    sidecar_table_ordinal: int = 0
