"""
JPEG derivatives for optional optimized ImageField columns (original uploads unchanged).
"""
from __future__ import annotations

import io
import os

from django.core.files.base import ContentFile


MAX_EDGE_PIXELS = 2560


def build_jpeg_derivative(source_field, *, quality: int):
    """
    Build an optimized JPEG from an ImageFieldFile; returns (ContentFile, filename) or (None, "").
    """
    if not source_field:
        return None, ""

    try:
        from PIL import Image, ImageOps
    except Exception:
        return None, ""

    try:
        source_field.open("rb")
        with Image.open(source_field) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "P"):
                rgba = im.convert("RGBA")
                bg = Image.new("RGB", rgba.size, (255, 255, 255))
                bg.paste(rgba, mask=rgba.split()[-1])
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")

            w, h = im.size
            if w > MAX_EDGE_PIXELS or h > MAX_EDGE_PIXELS:
                im.thumbnail((MAX_EDGE_PIXELS, MAX_EDGE_PIXELS), Image.Resampling.LANCZOS)

            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=int(quality), optimize=True)
            buf.seek(0)

            base, _ = os.path.splitext(os.path.basename(getattr(source_field, "name", "") or "photo"))
            base = base or "photo"
            filename = f"{base}_opt.jpg"
            return ContentFile(buf.read()), filename
    except Exception:
        return None, ""
    finally:
        try:
            source_field.close()
        except Exception:
            pass
