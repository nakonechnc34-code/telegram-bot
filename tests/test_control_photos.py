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
