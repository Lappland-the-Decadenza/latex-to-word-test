"""Repairs applied to OMML after the external MathML transform."""

from lxml import etree


OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_BAR_ACCENT_CHARS = {"―", "‾", "¯", "–", "—", "\u0305", "\u0304"}


def _m(tag):
    return f"{{{OMML_NS}}}{tag}"


def hide_empty_nary_limits(root):
    """Hide absent n-ary limits so Word does not draw placeholders."""
    for nary in root.iter(_m("nary")):
        properties = nary.find(_m("naryPr"))
        if properties is None:
            continue
        for name, hide in (("sub", "subHide"), ("sup", "supHide")):
            element = nary.find(_m(name))
            empty = element is None or (
                len(element) == 0 and not (element.text or "").strip()
            )
            flag = properties.find(_m(hide))
            if flag is None:
                flag = etree.SubElement(properties, _m(hide))
            flag.set(_m("val"), "on" if empty else "off")


def accents_to_bars(root):
    """Turn full-width overline accents into Word bar objects."""
    for accent in list(root.iter(_m("acc"))):
        properties = accent.find(_m("accPr"))
        character = (
            properties.find(_m("chr")) if properties is not None else None
        )
        if (
            character is None
            or character.get(_m("val")) not in _BAR_ACCENT_CHARS
        ):
            continue
        expression = accent.find(_m("e"))
        if expression is None:
            continue
        bar = etree.Element(_m("bar"))
        bar_properties = etree.SubElement(bar, _m("barPr"))
        etree.SubElement(bar_properties, _m("pos")).set(_m("val"), "top")
        bar.append(expression)
        parent = accent.getparent()
        parent.replace(accent, bar)


def postprocess_omml(root):
    hide_empty_nary_limits(root)
    accents_to_bars(root)
    etree.cleanup_namespaces(root)
    return root
