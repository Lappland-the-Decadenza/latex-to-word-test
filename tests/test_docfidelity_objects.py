"""The document fidelity instrument must distinguish pictures from objects."""

from lxml import etree

from tests import docfidelity
from latexword.docx.inline import parse_image_args


class _Package:
    def media_hash(self, rid):
        return "hash" if rid == "rId1" else None


def _xml(text):
    return etree.fromstring(text.encode("utf-8"))


def test_drawing_shape_is_not_an_image_record():
    drawing = _xml(
        '<w:drawing xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart">'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">'
        '<c:chart/></a:graphicData></a:graphic></w:drawing>')
    assert docfidelity._read_drawing(drawing, _Package()) is None


def test_picture_and_vml_image_are_image_records():
    drawing = _xml(
        '<w:drawing xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<wp:inline><wp:extent cx="1" cy="2"/><a:graphic><a:graphicData '
        'uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<a:blip r:embed="rId1"/></a:graphicData></a:graphic></wp:inline></w:drawing>')
    pict = _xml(
        '<w:pict xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<v:shape><v:imagedata r:id="rId1"/></v:shape></w:pict>')
    assert docfidelity._read_drawing(drawing, _Package())[0] == "hash"
    assert docfidelity._read_vml(pict, _Package())[0] == "hash"


def test_native_image_options_are_grammar_safe():
    opts, path, metadata, _ = parse_image_args(
        r"[width=1bp]{asset.png}", 0
    )
    assert path == "asset.png"
    assert opts == "width=1bp"
    assert metadata is None
