"""Image normalization for the uniform JPEG OPDS-PSE contract."""

from io import BytesIO

from PIL import Image, ImageOps


def page_as_jpeg(data: bytes) -> bytes:
    """Validate actual bytes; preserve JPEGs and convert other first frames."""
    with Image.open(BytesIO(data)) as image:
        image.load()  # Reject corrupt/truncated images, including JPEGs.
        if image.format == "JPEG":
            return data
        oriented = ImageOps.exif_transpose(image)
        if "A" in oriented.getbands() or "transparency" in oriented.info:
            rgba = oriented.convert("RGBA")
            rgb = Image.new("RGB", rgba.size, "white")
            rgb.paste(rgba, mask=rgba.getchannel("A"))
        else:
            rgb = oriented.convert("RGB")
        output = BytesIO()
        rgb.save(output, format="JPEG", quality=95, subsampling=0)
        return output.getvalue()
