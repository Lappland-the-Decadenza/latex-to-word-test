"""Windows-native conversion for vector media that TeX cannot read."""

import ctypes
import os
import uuid
from ctypes import Structure, byref, c_bool, c_uint, c_void_p, c_wchar_p
from ctypes import c_int, c_ubyte


class _StartupInput(Structure):
    _fields_ = [
        ("version", c_uint),
        ("callback", c_void_p),
        ("suppress_thread", c_bool),
        ("suppress_codecs", c_bool),
    ]


_PNG_CLSID = (c_ubyte * 16).from_buffer_copy(
    uuid.UUID("{557CF406-1A04-11D3-9A73-0000F81EF32E}").bytes_le
)
_ARGB32 = 0x26200A


def _function(library, name, result, *arguments):
    function = getattr(library, name)
    function.restype = result
    function.argtypes = list(arguments)
    return function


def convert_metafile_to_png(source, target):
    """Render an EMF/WMF through Windows GDI+; return whether it succeeded."""
    if os.name != "nt":
        return False
    try:
        gdiplus = ctypes.WinDLL("gdiplus")
    except OSError:
        return False
    startup = _function(
        gdiplus, "GdiplusStartup", c_int, ctypes.POINTER(c_void_p),
        ctypes.POINTER(_StartupInput), c_void_p,
    )
    shutdown = _function(gdiplus, "GdiplusShutdown", None, c_void_p)
    create = _function(
        gdiplus, "GdipCreateMetafileFromFile", c_int, c_wchar_p,
        ctypes.POINTER(c_void_p),
    )
    width = _function(gdiplus, "GdipGetImageWidth", c_int, c_void_p, ctypes.POINTER(c_uint))
    height = _function(gdiplus, "GdipGetImageHeight", c_int, c_void_p, ctypes.POINTER(c_uint))
    make_bitmap = _function(
        gdiplus, "GdipCreateBitmapFromScan0", c_int, c_int, c_int, c_int,
        c_int, c_void_p, ctypes.POINTER(c_void_p),
    )
    make_graphics = _function(
        gdiplus, "GdipGetImageGraphicsContext", c_int, c_void_p,
        ctypes.POINTER(c_void_p),
    )
    clear = _function(gdiplus, "GdipGraphicsClear", c_int, c_void_p, c_uint)
    draw = _function(
        gdiplus, "GdipDrawImageRectI", c_int, c_void_p, c_void_p,
        c_int, c_int, c_int, c_int,
    )
    save = _function(
        gdiplus, "GdipSaveImageToFile", c_int, c_void_p, c_wchar_p,
        ctypes.POINTER(c_ubyte), c_void_p,
    )
    delete_graphics = _function(gdiplus, "GdipDeleteGraphics", c_int, c_void_p)
    dispose_image = _function(gdiplus, "GdipDisposeImage", c_int, c_void_p)

    token = c_void_p()
    if startup(byref(token), byref(_StartupInput(1, None, False, False)), None):
        return False
    metafile = bitmap = graphics = None
    try:
        metafile = c_void_p()
        if create(os.fspath(source), byref(metafile)) or not metafile.value:
            return False
        image_width, image_height = c_uint(), c_uint()
        if width(metafile, byref(image_width)) or height(metafile, byref(image_height)):
            return False
        bitmap = c_void_p()
        if make_bitmap(image_width.value, image_height.value, 0, _ARGB32, None, byref(bitmap)):
            return False
        graphics = c_void_p()
        if make_graphics(bitmap, byref(graphics)) or clear(graphics, 0xFFFFFFFF):
            return False
        if draw(graphics, metafile, 0, 0, image_width.value, image_height.value):
            return False
        return save(bitmap, os.fspath(target), _PNG_CLSID, None) == 0
    except (OSError, TypeError, ValueError):
        return False
    finally:
        if graphics is not None and graphics.value:
            delete_graphics(graphics)
        if bitmap is not None and bitmap.value:
            dispose_image(bitmap)
        if metafile is not None and metafile.value:
            dispose_image(metafile)
        shutdown(token)


__all__ = ["convert_metafile_to_png"]
