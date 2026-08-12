"""Handling for DOCX objects that are outside the carried image model.

Objects such as charts, text boxes and shapes have no canonical LaTeX
spelling in this converter.  This module centralizes their explicit warning
policy so readers do not silently treat an unsupported object as ordinary
text.  Alternate-content fallback branches are also pruned here.
"""

import hashlib
import zipfile

from ..document.identity import NodeId
from ..document.text import prose_escape as _prose_escape


def iter_skip_fallback(node):
    """Yield an OOXML subtree in document order without ``mc:Fallback``."""
    pending = [node]
    while pending:
        element = pending.pop()
        if element.tag.rsplit("}", 1)[-1] == "Fallback":
            continue
        yield element
        pending.extend(reversed(list(element)))


def unsupported_object_warning(kind, index, *, legacy=False):
    """Return the stable warning used for an object with no native shape."""
    if legacy:
        return (
            f"legacy drawing ({kind}) dropped in paragraph {index} "
            "(not reproducible as an image)"
        )
    return (
        f"non-picture drawing ({kind}) dropped in paragraph {index} "
        "(not reproducible as an image)"
    )


def object_kind(root):
    """Classify an opaque OOXML object for diagnostics and sidecar records."""
    local = root.tag.rsplit("}", 1)[-1]
    if local == "sdt":
        return "content"
    if any(
        node.tag.rsplit("}", 1)[-1] in {"txbx", "txbxContent", "textbox"}
        for node in iter_skip_fallback(root)
    ):
        return "textbox"
    return "object"


def object_visible_text(root):
    """Read visible paragraph text from an opaque object."""
    paragraphs = []
    for paragraph in iter_skip_fallback(root):
        if paragraph.tag.rsplit("}", 1)[-1] != "p":
            continue
        text = "".join(
            (node.text or "")
            for node in iter_skip_fallback(paragraph)
            if node.tag.rsplit("}", 1)[-1] == "t"
        )
        if text:
            paragraphs.append(text)
    if not paragraphs:
        return "".join(
            (node.text or "")
            for node in iter_skip_fallback(root)
            if node.tag.rsplit("}", 1)[-1] == "t"
        )
    return "\n\n".join(paragraphs)


def opaque_latex(root, object_store, warnings, index, *, context="inline",
                 active_store=None):
    """Capture an opaque object and return its visible semantic fallback."""
    store = object_store or active_store
    if store is None:
        warnings.append(unsupported_object_warning(object_kind(root), index))
        return None
    try:
        object_id = store.capture(
            root, kind=object_kind(root), context=context,
        )
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        warnings.append(
            f"Word object at paragraph {index} could not be "
            f"sidecar-preserved: {exc}"
        )
        return None
    kind = object_kind(root)
    body = _prose_escape(object_visible_text(root))
    store.attach(
        "opaque-object",
        {"object_id": object_id, "kind": kind, "context": context},
        owner_id=NodeId.allocate(max(0, index)),
        owner_semantic_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        position="inside",
        ordinal=index,
        content_type="application/json",
        object_id=object_id,
    )
    return body
