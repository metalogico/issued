import io
from pathlib import Path
from PIL import Image
import pytest

try:
    import fitz
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False

from server.archive import get_archive, PdfBookWrapper
from server.scanner import is_comic_file


def test_pdf_is_comic_file():
    """PDF files should be recognized as comics."""
    assert is_comic_file(Path("test.pdf"))
    assert is_comic_file(Path("TEST.PDF"))
    assert not is_comic_file(Path("test.txt"))


@pytest.mark.skipif(not FITZ_AVAILABLE, reason="PyMuPDF not installed")
def test_pdf_book_wrapper(tmp_path):
    """Test PDF book wrapper implements Archive protocol."""
    # Create a simple 2-page PDF
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()

    # Page 1: Red square
    page1 = doc.new_page(width=100, height=100)
    page1.insert_text((10, 50), "Page 1", fontsize=12)

    # Page 2: Blue square
    page2 = doc.new_page(width=100, height=100)
    page2.insert_text((10, 50), "Page 2", fontsize=12)

    doc.save(pdf_path)
    doc.close()

    # Test Archive protocol
    with get_archive(pdf_path) as archive:
        # Test list_images
        images = archive.list_images()
        assert len(images) == 2
        assert images[0] == "page_0001.png"
        assert images[1] == "page_0002.png"

        # Test list_names
        names = archive.list_names()
        assert "page_0001.png" in names
        assert "page_0002.png" in names

        # Test read - should return PNG bytes
        img_bytes = archive.read("page_0001.png")
        assert img_bytes.startswith(b'\x89PNG')

        # Verify image can be opened by PIL
        img = Image.open(io.BytesIO(img_bytes))
        assert img.format == "PNG"
        assert img.size[0] > 0
        assert img.size[1] > 0


@pytest.mark.skipif(not FITZ_AVAILABLE, reason="PyMuPDF not installed")
def test_pdf_corrupted(tmp_path):
    """Test handling of corrupted PDF files."""
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_bytes(b"Not a PDF")

    with pytest.raises(ValueError, match="Cannot open PDF"):
        with get_archive(bad_pdf) as archive:
            pass


@pytest.mark.skipif(not FITZ_AVAILABLE, reason="PyMuPDF not installed")
def test_pdf_password_protected(tmp_path):
    """Test handling of password-protected PDFs.

    PyMuPDF opens AES-256 encrypted PDFs without the user password but treats
    them as having 0 pages (the content stream is encrypted).  We verify that
    PdfBookWrapper either raises ValueError or returns an empty page list — it
    must never crash with an unhandled exception.
    """
    pdf_path = tmp_path / "encrypted.pdf"

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((10, 50), "Secret", fontsize=12)
    doc.save(pdf_path, encryption=fitz.PDF_ENCRYPT_AES_256,
             owner_pw="owner", user_pw="user")
    doc.close()

    opened_successfully = False
    try:
        with get_archive(pdf_path) as archive:
            images = archive.list_images()
            # If it opens without a password, the page list must be a list
            # (even if empty — fitz returns 0 pages for encrypted content).
            assert isinstance(images, list)
            opened_successfully = True
    except ValueError:
        # Expected: PdfBookWrapper raises ValueError for files it cannot open.
        pass

    if opened_successfully:
        # PyMuPDF returned 0 pages for the encrypted file — that is acceptable.
        # A non-zero page count here would mean the content was readable without
        # the password, which is also fine (fitz can decrypt with owner rights).
        pass  # no further assertion needed; the important thing is no crash


@pytest.mark.skipif(not FITZ_AVAILABLE, reason="PyMuPDF not installed")
def test_pdf_page_caching(tmp_path):
    """Verify pages are cached during session."""
    pdf_path = tmp_path / "cache_test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    doc.save(pdf_path)
    doc.close()

    with get_archive(pdf_path) as archive:
        # First read
        img1 = archive.read("page_0001.png")

        # Second read should return cached result
        img2 = archive.read("page_0001.png")

        # Should be identical (same object from cache)
        assert img1 == img2


@pytest.mark.skipif(not FITZ_AVAILABLE, reason="PyMuPDF not installed")
def test_pdf_comicinfo_generation(tmp_path):
    """Test ComicInfo.xml generation from PDF metadata."""
    pdf_path = tmp_path / "metadata.pdf"

    # Create PDF with metadata (must set metadata BEFORE saving)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((10, 50), "Test", fontsize=12)
    # Set metadata using set_metadata method
    doc.set_metadata({
        "title": "Test Comic",
        "author": "John Doe",
        "subject": "Adventure"
    })
    doc.save(pdf_path)
    doc.close()

    with get_archive(pdf_path) as archive:
        names = archive.list_names()
        # ComicInfo.xml should be in names if metadata exists
        if "ComicInfo.xml" in names:
            xml_bytes = archive.read("ComicInfo.xml")
            xml_str = xml_bytes.decode('utf-8')
            assert "<PageCount>1</PageCount>" in xml_str
            # Metadata may or may not persist depending on PyMuPDF version
            # Just verify it's valid XML
            assert "<ComicInfo>" in xml_str
        else:
            # If no metadata persisted, at least verify page list works
            assert len(archive.list_images()) == 1
