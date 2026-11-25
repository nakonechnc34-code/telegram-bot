import pytest
from routes.control import photo_content_type, score_check

@pytest.mark.parametrize("data", [b"", b"<svg/>", b"GIF89a", b"x"*(5*1024*1024+1)])
def test_reject_invalid_photo(data):
    with pytest.raises(ValueError):
        photo_content_type(data)

def test_required_photo():
    definition={"sections":[{"questions":[{"type":"yes_no_na","weight":1,"required":True,"photo_required":True}]}]}
    with pytest.raises(ValueError,match="photo_required"):
        score_check(definition,{"0:0":"yes"})
    assert score_check(definition,{"0:0":"yes"},{"0:0"})[0]==100
    assert score_check(definition,{"0:0":"no"},{"0:0"})[0]==0
    assert score_check(definition,{"0:0":"na"})[0] is None


from io import BytesIO
from PIL import Image, PngImagePlugin
from routes.control import sanitize_photo

def test_jpeg_metadata_removed():
    buf = BytesIO()
    image = Image.new("RGB", (16, 12), "white")
    exif = image.getexif()
    exif[271] = "Private camera"
    exif[315] = "Private author"
    image.save(buf, format="JPEG", exif=exif)
    cleaned, mime = sanitize_photo(buf.getvalue())
    assert mime == "image/jpeg"
    with Image.open(BytesIO(cleaned)) as result:
        assert not result.getexif()
        assert result.size == (16, 12)
    assert b"Private author" not in cleaned

def test_png_metadata_removed():
    buf = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Author", "Private author")
    Image.new("RGB", (16, 12)).save(buf, format="PNG", pnginfo=metadata)
    cleaned, mime = sanitize_photo(buf.getvalue())
    assert mime == "image/png"
    with Image.open(BytesIO(cleaned)) as result:
        assert "Author" not in result.info

@pytest.mark.parametrize("data", [
    b"\xff\xd8\xfffake\xff\xd9",
    b"\x89PNG\r\n\x1a\nfakeIEND\xaeB\x60\x82",
])
def test_fake_image_rejected(data):
    with pytest.raises(ValueError):
        sanitize_photo(data)
