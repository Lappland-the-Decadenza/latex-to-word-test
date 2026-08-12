"""Image resolution, geometry and DrawingML metadata for DOCX."""

import hashlib
import json
import os
import re
import zipfile

from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu
from lxml import etree

from ..document.identity import NodeId
from .image_convert import convert_metafile_to_png


WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
VML_NS = "urn:schemas-microsoft-com:vml"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PICTURE_URI = "http://schemas.openxmlformats.org/drawingml/2006/picture"


def _resolve_image_path(path, img_base):
    if not path:
        return None
    if os.path.isabs(path) and os.path.exists(path):
        return path
    if img_base:
        candidate = os.path.join(img_base, path)
        if os.path.exists(candidate):
            return candidate
    return path if os.path.exists(path) else None


def _wp(tag):
    return f"{{{WP_NS}}}{tag}"


def _a(tag):
    return f"{{{A_NS}}}{tag}"


def _pic(tag):
    return f"{{{PIC_NS}}}{tag}"


def _r(tag):
    return f"{{{R_NS}}}{tag}"


def _apply_anchor_metadata(drawing, inline, metadata, warnings):
    anchor_value = metadata.get("anchor")
    if isinstance(anchor_value, bool):
        anchor_value = "anchor" if anchor_value else "inline"
    anchor_name = (anchor_value or "inline").strip().lower()
    if anchor_name not in ("inline", "anchor"):
        if warnings is not None:
            warnings.append(f"unknown image anchor mode {anchor_name!r}; using inline")
        anchor_name = "inline"
    if anchor_name != "anchor":
        return inline

    children = list(inline)
    anchor = OxmlElement("wp:anchor")
    for name, value in (
        ("distT", "0"), ("distB", "0"), ("distL", "0"), ("distR", "0"),
        ("simplePos", "0"), ("relativeHeight", "0"), ("behindDoc", "0"),
        ("locked", "0"), ("layoutInCell", "1"), ("allowOverlap", "1"),
    ):
        anchor.set(name, value)
    simple_pos = OxmlElement("wp:simplePos")
    simple_pos.set("x", "0")
    simple_pos.set("y", "0")
    anchor.append(simple_pos)
    pos_h = OxmlElement("wp:positionH")
    pos_h.set("relativeFrom", "column")
    pos_offset = OxmlElement("wp:posOffset")
    pos_offset.text = "0"
    pos_h.append(pos_offset)
    anchor.append(pos_h)
    pos_v = OxmlElement("wp:positionV")
    pos_v.set("relativeFrom", "paragraph")
    pos_offset = OxmlElement("wp:posOffset")
    pos_offset.text = "0"
    pos_v.append(pos_offset)
    anchor.append(pos_v)
    for name in ("extent", "effectExtent"):
        child = inline.find(_wp(name))
        if child is not None:
            anchor.append(child)
    wrap_name = (metadata.get("wrap") or "none").strip().lower()
    wrap_tag = {
        "none": "wrapNone", "square": "wrapSquare", "tight": "wrapTight",
        "through": "wrapThrough", "topandbottom": "wrapTopAndBottom",
        "top-and-bottom": "wrapTopAndBottom",
    }.get(wrap_name)
    if wrap_tag is None:
        if warnings is not None:
            warnings.append(f"unknown image wrap mode {wrap_name!r}; using none")
        wrap_tag = "wrapNone"
    wrap_el = OxmlElement("wp:" + wrap_tag)
    if wrap_tag == "wrapSquare":
        wrap_el.set("wrapText", "bothSides")
    anchor.append(wrap_el)
    moved = {_wp("extent"), _wp("effectExtent")}
    for child in children:
        if child.tag not in moved:
            anchor.append(child)
    drawing.replace(inline, anchor)
    return anchor


def _set_picture_metadata(run, metadata, warnings):
    if not metadata:
        return
    drawing = run._element.find(qn("w:drawing"))
    if drawing is None:
        return
    inline = drawing.find(".//" + _wp("inline"))
    if inline is None:
        return

    picture = _apply_anchor_metadata(drawing, inline, metadata, warnings)

    docpr = picture.find(".//" + _wp("docPr"))
    alt = metadata.get("alt", "")
    if docpr is not None and alt:
        docpr.set("descr", alt)
    title = metadata.get("title", "")
    if docpr is not None and title:
        docpr.set("title", title)

    crop = metadata.get("crop") or ""
    if not isinstance(crop, str):
        crop = str(crop)
    crop = crop.strip()
    if crop:
        values = [part.strip() for part in crop.split(",")]
        if len(values) != 4 or any(not re.fullmatch(r"-?\d+", part) for part in values):
            if warnings is not None:
                warnings.append(f"malformed image crop {crop!r}; omitted")
        else:
            blip_fill = drawing.find(".//" + _pic("blipFill"))
            if blip_fill is not None:
                src_rect = blip_fill.find(_a("srcRect"))
                if src_rect is None:
                    src_rect = OxmlElement("a:srcRect")
                    blip = blip_fill.find(_a("blip"))
                    if blip is None:
                        blip_fill.insert(0, src_rect)
                    else:
                        blip.addnext(src_rect)
                for key, value in zip(("l", "t", "r", "b"), values):
                    src_rect.set(key, value)

    rotation = metadata.get("rotation") or ""
    if not isinstance(rotation, str):
        rotation = str(rotation)
    rotation = rotation.strip()
    if rotation:
        if not re.fullmatch(r"-?\d+", rotation):
            if warnings is not None:
                warnings.append(f"malformed image rotation {rotation!r}; omitted")
        else:
            xfrm = drawing.find(".//" + _a("xfrm"))
            if xfrm is None:
                sp_pr = drawing.find(".//" + _pic("spPr"))
                if sp_pr is not None:
                    xfrm = OxmlElement("a:xfrm")
                    sp_pr.insert(0, xfrm)
            if xfrm is not None:
                xfrm.set("rot", rotation)


def _sidecar_image_metadata(paragraph, path, metadata):
    """Merge detached image metadata into a native image insertion.

    The portable LaTeX projection carries the image path and dimensions.
    Crop, alt/title, anchor and wrap state are Word-only and therefore come
    from the sidecar. Repeated uses of one image are resolved by nearest source
    ordinal, while explicit LaTeX metadata remains authoritative.
    """
    store = getattr(paragraph.part, "_latexword_object_store", None)
    if store is None:
        return metadata
    ordinal = getattr(
        paragraph, "_latexword_sidecar_ordinal",
        getattr(paragraph.part, "_latexword_sidecar_ordinal", 0),
    )
    wanted = os.path.normcase(os.path.normpath(path or ""))
    candidates = []
    for attachment in store.attachments:
        if attachment.kind != "image-metadata":
            continue
        try:
            value = json.loads(store.attachment_payload(attachment))
        except (OSError, ValueError, TypeError):
            continue
        stored = os.path.normcase(
            os.path.normpath(value.get("path") or "")
        )
        if stored == wanted:
            candidates.append(
                (abs(attachment.ordinal - ordinal), attachment, value)
            )
    if not candidates:
        return metadata
    distance = min(item[0] for item in candidates)
    nearest = [item for item in candidates if item[0] == distance]
    value = dict(sorted(nearest, key=lambda item: item[1].ordinal)[0][2])
    merged = dict(value)
    merged.update(metadata or {})
    anchor = merged.get("anchor")
    if isinstance(anchor, bool):
        merged["anchor"] = "anchor" if anchor else "inline"
    crop = merged.get("crop")
    if isinstance(crop, (tuple, list)):
        merged["crop"] = ",".join(str(item) for item in crop)
    return merged


_EMU_PER_UNIT = {
    "cm": 360000, "mm": 36000, "in": 914400,
    "pt": 914400 / 72.27, "bp": 12700,
}
_WIDTH_RE = re.compile(r"width\s*=\s*([\d.]+)\s*(cm|mm|in|pt|bp)")
_HEIGHT_RE = re.compile(r"height\s*=\s*([\d.]+)\s*(cm|mm|in|pt|bp)")

_RAW_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".emf": "image/x-emf",
    ".wmf": "image/x-wmf",
    ".svg": "image/svg+xml",
}


class ImageContext:
    """Extract reverse-conversion media into the output figures directory."""

    def __init__(self, media_rels, media_bytes, figures_dirname, figures_dir_abs):
        self.media_rels = media_rels
        self.media_bytes = media_bytes
        self.figures_dirname = figures_dirname
        self.figures_dir_abs = figures_dir_abs
        self._made_dir = False

    def write(self, target):
        """Write one related media blob and return its LaTeX-relative path."""
        src_name = "word/" + target.lstrip("/")
        data = self.media_bytes.get(src_name)
        if data is None:
            return None
        filename = os.path.basename(target)
        # A restored opaque image carries an internal sidecar object id in
        # its package media name.  That id is allowed to change when the
        # package is rebuilt, but it must not leak into canonical LaTeX: use
        # the image bytes as the stable filename identity instead.
        if re.match(r"sidecar_n\d+_\d+\.", filename, re.IGNORECASE):
            filename = (
                "sidecar_" + hashlib.sha256(data).hexdigest()[:16]
                + os.path.splitext(filename)[1].lower()
            )
        if not self._made_dir:
            os.makedirs(self.figures_dir_abs, exist_ok=True)
            self._made_dir = True
        raw_path = os.path.join(self.figures_dir_abs, filename)
        with open(raw_path, "wb") as stream:
            stream.write(data)
        ext = os.path.splitext(filename)[1].lower()
        if ext in {".emf", ".wmf"}:
            rendered_name = filename + ".png"
            rendered_path = os.path.join(self.figures_dir_abs, rendered_name)
            if convert_metafile_to_png(raw_path, rendered_path):
                return f"{self.figures_dirname}/{rendered_name}"
        return f"{self.figures_dirname}/{filename}"


def size_opts(cx, cy, preserve_zero=False):
    """Return exact big-point width and height options for a picture."""
    parts = []
    if cx > 0 or preserve_zero:
        parts.append(f"width={cx / 12700:.5f}bp")
    if cy > 0 or preserve_zero:
        parts.append(f"height={cy / 12700:.5f}bp")
    return ",".join(parts)


def _capture_image_state(
    drawing, object_store, warnings, index, rel_path, anchor, wrap,
    alt, title, crop, rotation, cx=None, cy=None,
):
    if object_store is None:
        return
    try:
        object_id = object_store.capture(
            drawing, kind="image-metadata", context="inline"
        )
        visible = rel_path + (alt or "") + (title or "")
        object_store.attach(
            "image-metadata",
            {
                "object_id": object_id,
                "path": rel_path,
                "anchor": anchor is not None,
                "wrap": wrap,
                "alt": alt,
                "title": title,
                "crop": crop,
                "rotation": rotation,
                "cx": cx,
                "cy": cy,
            },
            owner_id=NodeId.allocate(max(0, index)),
            owner_semantic_hash=hashlib.sha256(visible.encode("utf-8")).hexdigest(),
            position="inside",
            ordinal=index,
            content_type="application/json",
            object_id=object_id,
        )
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        warnings.append(f"image metadata at paragraph {index} was not sidecar-preserved: {exc}")


def _opaque_image(root, object_store, warnings, index, opaque_renderer):
    if opaque_renderer is None:
        return None
    return opaque_renderer(root, object_store, warnings, index)


def drawing_to_latex(drawing, img_ctx, warnings, index, object_store=None,
                     opaque_renderer=None):
    """Convert a DrawingML picture to its canonical LaTeX representation."""
    graphic_data = drawing.find(f".//{_a('graphicData')}")
    uri = graphic_data.get("uri") if graphic_data is not None else None
    blip = drawing.find(f".//{_a('blip')}")
    if blip is None or uri != PICTURE_URI:
        return _opaque_image(
            drawing, object_store, warnings, index, opaque_renderer
        )
    rid = blip.get(_r("embed"))
    target = img_ctx.media_rels.get(rid) if rid and img_ctx else None
    if not target:
        return _opaque_image(
            drawing, object_store, warnings, index, opaque_renderer
        )
    rel_path = img_ctx.write(target)
    if rel_path is None:
        return _opaque_image(
            drawing, object_store, warnings, index, opaque_renderer
        )
    extent = drawing.find(f".//{_wp('extent')}")
    cx = int(extent.get("cx") or 0) if extent is not None else 0
    cy = int(extent.get("cy") or 0) if extent is not None else 0
    opts = size_opts(cx, cy, preserve_zero=(cx == 0 or cy == 0))
    anchor = drawing.find(f".//{_wp('anchor')}")
    inline = drawing.find(f".//{_wp('inline')}")
    wrap = "inline"
    if anchor is not None:
        wrap = "none"
        for child in anchor:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag.startswith("wrap"):
                wrap = tag[4:].lower() or "none"
                break
    elif inline is None:
        wrap = "none"
    docpr = drawing.find(f".//{_wp('docPr')}")
    alt = (docpr.get("descr") or "").strip() if docpr is not None else ""
    title = (docpr.get("title") or "").strip() if docpr is not None else ""
    src_rect = drawing.find(f".//{_a('srcRect')}")
    crop = None
    if src_rect is not None:
        crop = tuple(src_rect.get(key) or "0" for key in ("l", "t", "r", "b"))
    xfrm = drawing.find(f".//{_a('xfrm')}")
    rotation = xfrm.get("rot") if xfrm is not None else None
    if anchor is not None or alt or title or crop is not None or rotation:
        _capture_image_state(
            drawing, object_store, warnings, index, rel_path, anchor, wrap,
            alt, title, crop, rotation, cx, cy,
        )
    if opts:
        return f"\\includegraphics[{opts}]{{{rel_path}}}"
    return f"\\includegraphics{{{rel_path}}}"


def pict_to_latex(pict, img_ctx, warnings, index, object_store=None,
                  opaque_renderer=None):
    """Convert a VML image when it has a real media relationship."""
    imagedata = pict.find(f".//{{{VML_NS}}}imagedata")
    rid = imagedata.get(_r("id")) if imagedata is not None else None
    target = img_ctx.media_rels.get(rid) if rid and img_ctx else None
    if not target:
        return _opaque_image(
            pict, object_store, warnings, index, opaque_renderer
        )
    rel_path = img_ctx.write(target)
    if rel_path is None:
        return _opaque_image(
            pict, object_store, warnings, index, opaque_renderer
        )
    if object_store is not None:
        _capture_image_state(
            pict, object_store, warnings, index, rel_path, None, "vml",
            "", "", None, None, 0, 0,
        )
    return f"\\includegraphics[width=0bp,height=0bp]{{{rel_path}}}"


def _parse_len_emu(opts, pattern):
    if not opts:
        return None
    match = pattern.search(opts)
    if not match:
        return None
    value, unit = float(match.group(1)), match.group(2)
    return int(round(value * _EMU_PER_UNIT[unit]))


def parse_width_emu(opts):
    return _parse_len_emu(opts, _WIDTH_RE)


def parse_height_emu(opts):
    return _parse_len_emu(opts, _HEIGHT_RE)


def _next_docpr_id(document):
    values = []
    # wp:docPr identifiers are package-wide in Word's repair logic.  A
    # reference template can already use IDs in headers or footers, which
    # python-docx's document-body allocator does not see.
    for part in document.part.package.iter_parts():
        root = getattr(part, "element", None)
        if root is None:
            root = getattr(part, "_element", None)
        if root is None:
            continue
        for el in root.iter(_wp("docPr")):
            try:
                values.append(int(el.get("id") or 0))
            except ValueError:
                pass
    return max(values, default=0) + 1


def _raw_vml_picture(paragraph, path, warnings):
    """Embed a legacy VML picture without converting its carrier type."""
    ext = os.path.splitext(path)[1].lower()
    content_type = _RAW_IMAGE_TYPES.get(ext)
    if content_type is None:
        return False
    try:
        with open(path, "rb") as stream:
            blob = stream.read()
        package = paragraph.part.package
        partname = package.next_partname(PackURI("/word/media/image%d" + ext))
        image_part = Part(partname, content_type, blob, package)
        rid = paragraph.part.relate_to(image_part, RT.IMAGE)
        run = paragraph.add_run()
        pict = OxmlElement("w:pict")
        shape = etree.Element(f"{{{VML_NS}}}shape", nsmap={"v": VML_NS})
        shape.set("style", "width:0pt;height:0pt")
        imagedata = etree.Element(f"{{{VML_NS}}}imagedata")
        imagedata.set(qn("r:id"), rid)
        shape.append(imagedata)
        pict.append(shape)
        run._element.append(pict)
        return True
    except Exception as exc:  # pragma: no cover - package-specific fallback
        if warnings is not None:
            warnings.append(f"failed to embed raw VML image {path}: {exc}")
        return True


def _raw_picture(paragraph, path, opts, metadata, warnings):
    """Embed a media blob without asking Pillow/python-docx to decode it."""
    ext = os.path.splitext(path)[1].lower()
    content_type = _RAW_IMAGE_TYPES.get(ext)
    if content_type is None:
        return False
    try:
        with open(path, "rb") as stream:
            blob = stream.read()
        package = paragraph.part.package
        partname = package.next_partname(PackURI("/word/media/image%d" + ext))
        image_part = Part(partname, content_type, blob, package)
        rid = paragraph.part.relate_to(image_part, RT.IMAGE)
        width = parse_width_emu(opts) or 0
        height = parse_height_emu(opts) or 0
        run = paragraph.add_run()
        drawing = OxmlElement("w:drawing")
        inline = OxmlElement("wp:inline")
        for name in ("distT", "distB", "distL", "distR"):
            inline.set(name, "0")
        extent = OxmlElement("wp:extent")
        extent.set("cx", str(width))
        extent.set("cy", str(height))
        inline.append(extent)
        docpr = OxmlElement("wp:docPr")
        docpr.set("id", str(_next_docpr_id(paragraph.part.document)))
        docpr.set("name", os.path.basename(path))
        inline.append(docpr)
        frame = OxmlElement("wp:cNvGraphicFramePr")
        frame.append(OxmlElement("a:graphicFrameLocks"))
        inline.append(frame)
        graphic = OxmlElement("a:graphic")
        graphic_data = OxmlElement("a:graphicData")
        graphic_data.set("uri", "http://schemas.openxmlformats.org/drawingml/2006/picture")
        pic = OxmlElement("pic:pic")
        nv = OxmlElement("pic:nvPicPr")
        c_nv = OxmlElement("pic:cNvPr")
        c_nv.set("id", "0")
        c_nv.set("name", os.path.basename(path))
        nv.append(c_nv)
        nv.append(OxmlElement("pic:cNvPicPr"))
        pic.append(nv)
        fill = OxmlElement("pic:blipFill")
        blip = OxmlElement("a:blip")
        blip.set(qn("r:embed"), rid)
        fill.append(blip)
        stretch = OxmlElement("a:stretch")
        stretch.append(OxmlElement("a:fillRect"))
        fill.append(stretch)
        pic.append(fill)
        shape = OxmlElement("pic:spPr")
        xfrm = OxmlElement("a:xfrm")
        off = OxmlElement("a:off")
        off.set("x", "0")
        off.set("y", "0")
        ext_el = OxmlElement("a:ext")
        ext_el.set("cx", str(width))
        ext_el.set("cy", str(height))
        xfrm.extend([off, ext_el])
        shape.append(xfrm)
        geom = OxmlElement("a:prstGeom")
        geom.set("prst", "rect")
        geom.append(OxmlElement("a:avLst"))
        shape.append(geom)
        pic.append(shape)
        graphic_data.append(pic)
        graphic.append(graphic_data)
        inline.append(graphic)
        drawing.append(inline)
        run._element.append(drawing)
        _set_picture_metadata(run, metadata, warnings)
        return True
    except Exception as exc:  # pragma: no cover - package-specific fallback
        if warnings is not None:
            warnings.append(f"failed to embed raw image {path}: {exc}")
        return True


def add_inline_picture(paragraph, path, opts, img_base, warnings, metadata=None):
    """Insert one embedded picture, reporting missing/bad files as warnings."""
    metadata = _sidecar_image_metadata(paragraph, path, metadata)
    if path is None:
        if warnings is not None:
            warnings.append("malformed \\includegraphics (missing path argument)")
        return
    full_path = _resolve_image_path(path, img_base)
    if full_path is None:
        if warnings is not None:
            warnings.append(f"image file not found, skipped: {path}")
        return
    width_emu = parse_width_emu(opts)
    height_emu = parse_height_emu(opts)
    # A normal image has a portable LaTeX spelling, but the sidecar also
    # carries the original package relationship and drawing tree.  Reinsert
    # that tree when the authored dimensions still agree; this preserves an
    # original EMF/VML carrier byte-for-byte while leaving an edited LaTeX
    # size authoritative and native.
    store = getattr(paragraph.part, "_latexword_object_store", None)
    object_id = metadata.get("object_id") if metadata else None
    if store is not None and object_id:
        try:
            sidecar_width = metadata.get("cx")
            sidecar_height = metadata.get("cy")
            dimensions_match = (
                sidecar_width is None or sidecar_height is None or
                (width_emu or 0) == int(sidecar_width) and
                (height_emu or 0) == int(sidecar_height)
            )
            if dimensions_match and store.restore(
                paragraph.part, object_id, paragraph=paragraph
            ):
                return
        except (OSError, TypeError, ValueError, KeyError):
            # A stale or incomplete sidecar must never make image insertion
            # fail; the portable LaTeX image remains the fallback.
            pass
    ext = os.path.splitext(full_path)[1].lower()
    if metadata and (metadata.get("wrap") or "").strip().lower() == "vml":
        if _raw_vml_picture(paragraph, full_path, warnings):
            return
    if (width_emu == 0 or height_emu == 0
            or ext in {".emf", ".wmf", ".svg"}):
        if _raw_picture(paragraph, full_path, opts, metadata, warnings):
            return
    run = paragraph.add_run()
    kwargs = {}
    if width_emu is not None:
        kwargs["width"] = Emu(width_emu)
    if height_emu is not None:
        kwargs["height"] = Emu(height_emu)
    docpr_id = _next_docpr_id(paragraph.part.document)
    try:
        run.add_picture(full_path, **kwargs)
        docpr = run._element.find(".//" + _wp("docPr"))
        if docpr is not None:
            docpr.set("id", str(docpr_id))
        _set_picture_metadata(run, metadata, warnings)
    except Exception as exc:  # pragma: no cover
        if warnings is not None:
            warnings.append(f"failed to insert image {path}: {exc}")
