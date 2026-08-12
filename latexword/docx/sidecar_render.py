"""Apply detached Word identity while building native DOCX content."""

import hashlib
import json

from copy import deepcopy

from docx.oxml.ns import qn
from docx.text.run import Run

from .styles import _ensure_character_style, _set_character_style


def paragraph_style(builder, ordinal, text, *, slot_fallback=False):
    store = getattr(builder.doc.part, "_latexword_object_store", None)
    if store is None:
        return None
    slots = store.attachments_at(ordinal, kind="paragraph-style")
    if slots:
        if len({item.payload_id for item in slots}) > 1:
            builder.warnings.append(
                f"ambiguous paragraph-style attachment at ordinal {ordinal}"
            )
            return None
        try:
            value = json.loads(store.attachment_payload(slots[0]))
        except (OSError, ValueError, TypeError):
            builder.warnings.append(
                f"invalid paragraph-style attachment at ordinal {ordinal}"
            )
            return None
        source_text = value.get("text") or ""
        variants = [text]
        for env in ("center", "flushleft", "flushright", "justify"):
            variants.append(f"\\begin{{{env}}}{text}\\end{{{env}}}")
        slot_matches = source_text in variants
        if slot_fallback and "\\[" in source_text and "\\]" in source_text:
            start = source_text.find("\\[") + 2
            end = source_text.rfind("\\]")
            slot_matches = source_text[start:end].strip() == text.strip()
        if slot_matches:
            return value.get("style_id") or None

    if not text:
        digest = hashlib.sha256(b"").hexdigest()
        candidates = store.nearest_attachments(
            "paragraph-style", digest, ordinal
        )
    else:
        variants = [text]
        for env in ("center", "flushleft", "flushright", "justify"):
            variants.append(f"\\begin{{{env}}}{text}\\end{{{env}}}")
        candidates = None
        for variant in variants:
            digest = hashlib.sha256(variant.encode("utf-8")).hexdigest()
            candidates = store.nearest_attachments(
                "paragraph-style", digest, ordinal
            )
            if candidates is not None:
                break
    if candidates is not None and min(
            abs(item.ordinal - ordinal) for item in candidates) > 10:
        candidates = None

    if candidates is None and slot_fallback:
        candidates = _math_candidates(store, ordinal, text)
    if not candidates:
        return None
    if len(candidates) > 1:
        builder.warnings.append(
            f"ambiguous paragraph-style attachment at ordinal {ordinal}"
        )
        return None
    try:
        value = json.loads(store.attachment_payload(candidates[0]))
    except (OSError, ValueError, TypeError):
        builder.warnings.append(
            f"invalid paragraph-style attachment at ordinal {ordinal}"
        )
        return None
    return value.get("style_id") or None


def _math_candidates(store, ordinal, text):
    matches = []
    wanted = text.strip()
    for attachment in store.attachments:
        if attachment.kind != "paragraph-style":
            continue
        try:
            value = json.loads(store.attachment_payload(attachment))
        except (OSError, ValueError, TypeError):
            continue
        source = (value.get("text") or "").strip()
        if "\\[" not in source or "\\]" not in source:
            continue
        start = source.find("\\[") + 2
        end = source.rfind("\\]")
        if source[start:end].strip() == wanted:
            matches.append(attachment)
    if matches:
        distance = min(abs(item.ordinal - ordinal) for item in matches)
        candidates = tuple(
            item for item in matches if abs(item.ordinal - ordinal) == distance
        )
    else:
        candidates = store.attachments_at(
            ordinal, kind="paragraph-style"
        )
    return tuple(
        item for item in candidates
        if _is_math_attachment(store, item)
    )


def _is_math_attachment(store, attachment):
    try:
        value = json.loads(store.attachment_payload(attachment))
    except (OSError, ValueError, TypeError):
        return False
    source = value.get("text") or ""
    return "\\[" in source or "$$" in source


def table_style(builder):
    """Consume the next detached table slot, if one was recorded."""
    store = getattr(builder.doc.part, "_latexword_object_store", None)
    if store is None:
        return None
    builder._state.sidecar_ordinal += 1
    slots = [item for item in store.attachments if item.kind == "table-style"]
    ordinal = builder._state.sidecar_table_ordinal
    builder._state.sidecar_table_ordinal += 1
    if ordinal >= len(slots):
        return None
    try:
        value = json.loads(store.attachment_payload(slots[ordinal]))
    except (OSError, ValueError, TypeError):
        builder.warnings.append(
            f"invalid table-style attachment at slot {ordinal}"
        )
        return None
    return value.get("style_id") or None


def opaque(builder, ordinal, text):
    store = getattr(builder.doc.part, "_latexword_object_store", None)
    if store is None:
        return None
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    for attachment in store.attachments_at(ordinal, kind="opaque-object"):
        if attachment.owner_semantic_hash != digest or not attachment.object_id:
            continue
        try:
            value = json.loads(store.attachment_payload(attachment))
        except (OSError, ValueError, TypeError):
            continue
        if value.get("object_id") == attachment.object_id:
            return value
    return None


def restore_character_state(builder, paragraph, ordinal):
    """Apply detached Word character identity to generated text ranges."""
    store = getattr(builder.doc.part, "_latexword_object_store", None)
    if store is None:
        return
    records = []
    for attachment in store.attachments:
        if attachment.kind != "character-state" or attachment.ordinal != ordinal:
            continue
        try:
            value = json.loads(store.attachment_payload(attachment))
        except (OSError, ValueError, TypeError):
            continue
        records.append((attachment, value))
    if not records:
        return
    runs = []
    for generated_index, element in enumerate(
            paragraph._element.iter(qn("w:r"))):
        run = Run(element, paragraph)
        visible = run.text or ""
        if visible:
            runs.append((generated_index, run, visible))
    stream = "".join(visible for _, _, visible in runs)
    spans = _character_spans(records, stream)

    stream_cursor = 0
    for _generated_index, run, visible in runs:
        run_start = stream.find(visible, stream_cursor)
        if run_start < 0:
            continue
        run_end = run_start + len(visible)
        stream_cursor = run_end
        affected = [
            (max(start, run_start), min(end, run_end), value)
            for start, end, value in spans
            if start < run_end and end > run_start
        ]
        if not affected:
            continue
        cuts = {0, len(visible)}
        for start, end, _value in affected:
            cuts.add(start - run_start)
            cuts.add(end - run_start)
        pieces = split_character_run(paragraph, run, sorted(cuts))
        for local_start, _local_end, piece in pieces:
            absolute_start = run_start + local_start
            value = next(
                (candidate for start, end, candidate in affected
                 if start <= absolute_start < end),
                None,
            )
            if value is None:
                continue
            style_id = value.get("style_id")
            if style_id and _ensure_character_style(
                    builder.doc, style_id, create=not builder._reference_doc):
                _set_character_style(piece, style_id)
            if value.get("hidden"):
                piece.font.hidden = True


def _character_spans(records, stream):
    spans = []
    search_from = 0
    for _attachment, value in sorted(
            records, key=lambda item: item[1].get("run_index", 0)):
        target = value.get("text")
        if not target:
            continue
        hint = value.get("text_offset")
        if isinstance(hint, int) and 0 <= hint <= len(stream):
            occurrences = []
            cursor = stream.find(target)
            while cursor >= 0:
                occurrences.append(cursor)
                cursor = stream.find(target, cursor + 1)
            start = min(occurrences, key=lambda item: abs(item - hint),
                        default=-1)
        else:
            start = stream.find(target, search_from)
            if start < 0:
                start = stream.find(target)
        if start < 0:
            continue
        spans.append((start, start + len(target), value))
        search_from = start + len(target)
    return spans


def split_character_run(paragraph, run, boundaries):
    """Split a plain text run at local offsets, retaining its rPr."""
    text = run.text or ""
    if len(boundaries) <= 2:
        return [(0, len(text), run)]
    element = run._r
    parent = element.getparent()
    insert_at = parent.index(element)
    pieces = []
    for start, end in zip(boundaries, boundaries[1:]):
        clone = deepcopy(element)
        piece = Run(clone, paragraph)
        piece.text = text[start:end]
        parent.insert(insert_at + len(pieces), clone)
        pieces.append((start, end, piece))
    parent.remove(element)
    return pieces
