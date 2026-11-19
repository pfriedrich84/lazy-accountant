"""One-shot parser subprocess: no Django/database, bounded CPU, address space and input.

Not a complete OS sandbox. Run workers without privileged host mounts/network
credentials beyond those required by the application.
"""

import io
import json
import resource
import sys


def main():
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    from PIL import Image
    from pypdf import PdfReader
    from .camt import parse_camt

    data = sys.stdin.buffer.read(25 * 1024 * 1024 + 1)
    if len(data) > 25 * 1024 * 1024:
        raise ValueError("Parser input limit")
    media = sys.argv[1]
    if len(sys.argv) > 2:
        representation(data, media, sys.argv[2], int(sys.argv[3]))
        return
    if media == "application/xml":
        result = parse_camt(data)
    elif media == "application/pdf":
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("Encrypted PDF")
        if not 0 < len(reader.pages) <= 500:
            raise ValueError("PDF page limit")
        result = {"pages": len(reader.pages)}
    else:
        Image.MAX_IMAGE_PIXELS = 25_000_000
        with Image.open(io.BytesIO(data)) as image:
            expected = {"image/png": "PNG", "image/jpeg": "JPEG"}[media]
            if image.format != expected or image.width * image.height > Image.MAX_IMAGE_PIXELS:
                raise ValueError("Image type/size limit")
            image.verify()
        result = {"pages": 1}
    output = json.dumps(result).encode()
    if len(output) > 8 * 1024 * 1024:
        raise ValueError("Parser output limit")
    sys.stdout.buffer.write(output)


def representation(data, media, operation, page):
    from PIL import Image, ImageOps
    from pypdf import PdfReader
    from .camt import parse_camt

    if not 1 <= page <= 500:
        raise ValueError("Page limit")
    if media == "application/xml":
        if operation == "image":
            raise ValueError("XML has no page image")
        result = {"text": data.decode("utf-8", errors="replace"), "structured": parse_camt(data)}
    elif media.startswith("image/"):
        if page != 1:
            raise ValueError("Page not found")
        if operation == "image":
            with Image.open(io.BytesIO(data)) as original:
                if original.width * original.height > 25_000_000:
                    raise ValueError("Image limit")
                preview = ImageOps.exif_transpose(original)
                preview.thumbnail((2000, 2000))
                output = io.BytesIO()
                preview.convert("RGB").save(output, format="PNG")
                sys.stdout.buffer.write(output.getvalue())
                return
        result = {"text": "", "pages": 1, "image_available": True}
    elif operation == "image":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(data)
        pdf_page = pdf[page - 1]
        width, height = pdf_page.get_size()
        if width <= 0 or height <= 0:
            raise ValueError("Invalid page size")
        bitmap = pdf_page.render(scale=min(1.5, 2000 / max(width, height)))
        output = io.BytesIO()
        bitmap.to_pil().save(output, format="PNG")
        sys.stdout.buffer.write(output.getvalue())
        return
    else:
        reader = PdfReader(io.BytesIO(data))
        result = {
            "text": (reader.pages[page - 1].extract_text() or "")[:80000],
            "page": page,
            "pages": len(reader.pages),
            "image_available": True,
        }
    sys.stdout.buffer.write(json.dumps(result).encode())


if __name__ == "__main__":
    main()
