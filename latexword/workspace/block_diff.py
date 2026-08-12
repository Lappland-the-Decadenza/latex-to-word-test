"""Deterministic labelled-block diff; no semantic correspondence is used."""

from __future__ import annotations

from dataclasses import dataclass

from .block_schema import BlockRecord
from .shadow_blocks import ShadowBlock, ShadowMetadataError, read_shadow_blocks, typed_labels


@dataclass(frozen=True, slots=True)
class ReuseBlock:
    record: BlockRecord
    edited_block: ShadowBlock


@dataclass(frozen=True, slots=True)
class ReplaceBlock:
    record: BlockRecord
    edited_block: ShadowBlock


@dataclass(frozen=True, slots=True)
class DeleteBlock:
    record: BlockRecord


@dataclass(frozen=True, slots=True)
class InsertBlock:
    edited_block: ShadowBlock
    before_label: int | None
    after_label: int | None


@dataclass(frozen=True, slots=True)
class BlockEdit:
    original: tuple[BlockRecord, ...]
    edited: tuple[ShadowBlock, ...]
    actions: tuple[object, ...]


def _neighbours(blocks, index):
    before = next((item.label for item in reversed(blocks[:index]) if item.label is not None), None)
    after = next((item.label for item in blocks[index + 1:] if item.label is not None), None)
    return before, after


def diff_blocks(records: tuple[BlockRecord, ...], original_shadow: str,
                edited_shadow: str) -> BlockEdit:
    if r"\begin{document}" not in edited_shadow or r"\end{document}" not in edited_shadow:
        raise ShadowMetadataError("shadow is missing document boundaries")
    block_records = tuple(getattr(records, "records", records))
    nested_records = tuple(getattr(records, "nested_records", ()))
    original = read_shadow_blocks(original_shadow)
    edited = read_shadow_blocks(edited_shadow)
    by_label = {item.label: item for item in block_records}
    # Nested identities are persisted separately from replaceable top-level
    # blocks, but they still have to be authored identities, never guesses.
    known_nested = {item.label for item in nested_records}
    known_all = set(by_label) | known_nested
    all_edited_labels = [label for _kind, label in typed_labels(edited_shadow)]
    if len(all_edited_labels) != len(set(all_edited_labels)):
        raise ShadowMetadataError("duplicate block label")
    invented_all = [label for label in all_edited_labels if label not in known_all]
    if invented_all:
        raise ShadowMetadataError("invented block label(s): " + ", ".join(map(str, invented_all)))
    edited_labels = [item.label for item in edited if item.label is not None]
    if len(edited_labels) != len(set(edited_labels)):
        raise ShadowMetadataError("duplicate block label")
    invented = [label for label in edited_labels if label not in by_label]
    if invented:
        raise ShadowMetadataError("invented block label(s): " + ", ".join(map(str, invented)))
    original_labels = [item.label for item in block_records]
    surviving = [label for label in edited_labels if label in by_label]
    old_survivors = [label for label in original_labels if label in surviving]
    moved = surviving != old_survivors
    old_positions = {label: index for index, label in enumerate(old_survivors)}
    new_positions = {label: index for index, label in enumerate(surviving)}
    actions = []
    seen = set()
    for index, block in enumerate(edited):
        if block.label is None:
            before, after = _neighbours(edited, index)
            actions.append(InsertBlock(block, before, after))
            continue
        record = by_label[block.label]
        seen.add(block.label)
        if moved and old_positions[block.label] != new_positions[block.label]:
            actions.append(DeleteBlock(record))
            before, after = _neighbours(edited, index)
            actions.append(InsertBlock(block, before, after))
        elif block.latex == record.original_latex:
            actions.append(ReuseBlock(record, block))
        else:
            actions.append(ReplaceBlock(record, block))
    actions.extend(DeleteBlock(record) for record in block_records if record.label not in seen)
    return BlockEdit(tuple(block_records), edited, tuple(actions))


__all__ = ["BlockEdit", "DeleteBlock", "InsertBlock", "ReplaceBlock",
           "ReuseBlock", "diff_blocks"]
