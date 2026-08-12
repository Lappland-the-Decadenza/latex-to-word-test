"""Public OMML loader facade and dispatcher."""

from . import load_shared as _shared
globals().update({name: getattr(_shared, name) for name in _shared.__all__})
from . import load_text as _text
from . import load_structures as _structures
globals().update({name: getattr(_text, name) for name in dir(_text) if name.startswith("_load")})
globals().update({name: getattr(_structures, name) for name in dir(_structures) if name.startswith("_load")})

def load(el):
    """OMML element -> AST node, or `None` when the element is not content
    (property containers, empty runs). Unknown structural elements recurse
    so their text survives, exactly like the old walker's fallback."""
    if el is None:
        return None
    tag = ln(el)
    if tag.endswith("Pr"):
        return None
    if tag in ("oMath", "oMathPara"):
        items = [node for c in el if ln(c) != "oMathParaPr"
                 for node in ([load(c)] if load(c) is not None else [])]
        return Row(tuple(items))
    if tag == "r":
        return _load_run(el)
    if tag == "t":
        # A stray m:t outside an m:r -- not content Word ever writes, but
        # the old walker emitted its raw text; load it like a run so the
        # text survives either way.
        return _load_plain_text(el.text or "") if el.text else None
    if tag == "e":
        return _row_or_single(el)
    if tag in ("sSub", "sSup", "sSubSup"):
        return _load_script(el)
    if tag == "f":
        return _load_frac(el)
    if tag == "rad":
        return _load_rad(el)
    if tag == "nary":
        return _load_nary(el)
    if tag == "d":
        return _load_delim(el)
    if tag == "func":
        return _load_func(el)
    if tag == "acc":
        return _load_acc(el)
    if tag == "bar":
        return _load_bar(el)
    if tag == "borderBox":
        return _load_borderbox(el)
    if tag == "phant":
        return _load_phant(el)
    if tag == "limLow":
        return _load_lim(el, under=True)
    if tag == "limUpp":
        return _load_lim(el, under=False)
    if tag == "m":
        return _load_matrix(el)
    if tag == "eqArr":
        return _load_eqarr(el)
    if tag == "groupChr":
        return _load_groupchr(el)
    if tag == "sPre":
        return PreScript(_arg(el, "e"), _arg(el, "sub"), _arg(el, "sup"))
    if tag == "box":
        return _arg(el, "e")
    # Unknown structural element: recurse so text content survives.
    items = _children(el)
    if not items:
        return None
    return Row(tuple(items))

_shared.load = load
_text.load = load
_structures.load = load

__all__ = ["load"]
