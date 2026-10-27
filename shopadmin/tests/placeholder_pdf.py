"""v2.11.0: placeholder accessory PDFs for the tests (real PDFs come later).
A tiny PDF writer: text lines (Helvetica) and JPEG pictures, nothing else."""
from __future__ import annotations

import io

from PIL import Image


def jpeg(color=(200, 30, 30), size=(64, 48)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "JPEG")
    return buffer.getvalue()


def _pdf(pages: list[list[tuple]]) -> bytes:
    """A small PDF: per page ("text", y, str) lines and ("image", x, y, w, h, jpeg)."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pages_id = len(objects) + 1 + 0
    objects.append(b"")          # placeholder for the page tree
    kids = []
    for page in pages:
        content, xobjects = [], []
        for part in page:
            if part[0] == "text":
                _kind, y, text = part
                safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                content.append(f"BT /F1 12 Tf 50 {y} Td ({safe}) Tj ET")
            else:
                _kind, x, y, w, hgt, data = part
                image = Image.open(io.BytesIO(data))
                ref = add(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                          b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
                          b"/Length %d >>\nstream\n" % (image.width, image.height, len(data))
                          + data + b"\nendstream")
                name = f"Im{len(xobjects) + 1}"
                xobjects.append(f"/{name} {ref} 0 R")
                content.append(f"q {w} 0 0 {hgt} {x} {y} cm /{name} Do Q")
        stream = "\n".join(content).encode("latin-1")
        contents = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        resources = f"<< /Font << /F1 {font} 0 R >> /XObject << {' '.join(xobjects)} >> >>"
        kids.append(add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 792] "
                        f"/Resources {resources} /Contents {contents} 0 R >>".encode()))
    objects[pages_id - 1] = (f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
                             f"/Count {len(kids)} >>").encode()
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
              % (len(objects) + 1, catalog, xref))
    return out.getvalue()


PLACEHOLDER_PDF_PAGES = [
    [("text", 760, "Accessories 2026"),          # a header is an item without specs
     ("text", 720, "Anker 737 Power Bank"),
     ("text", 700, "Capacity: 24000 mAh"),
     ("text", 684, "Output: 140W"),
     ("image", 50, 520, 200, 150, jpeg((20, 20, 200), (200, 150))),
     ("text", 480, "Baseus Bowie Earbuds"),
     ("text", 460, "Bluetooth: 5.3"),
     ("image", 50, 300, 160, 140, jpeg((20, 200, 20), (160, 140))),
     ("image", 400, 760, 20, 20, jpeg((0, 0, 0), (20, 20))),       # a logo: ignored
     ("text", 40, "Page 1")],
    [("text", 740, "Clear Case iPhone 17"),
     ("text", 720, "Material: TPU")],
]


