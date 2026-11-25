import pytest
from routes.control import validate_document

def test_valid_document():
    assert validate_document({"title":" Standard ","content":" Text ","category":"standards"})==("Standard","Text","standards",None)

@pytest.mark.parametrize("changes",[{"title":""},{"content":""},{"category":"unknown"},{"restaurant_key":True},{"content":"x"*100001}])
def test_invalid_document(changes):
    body={"title":"Standard","content":"Text","category":"standards"}
    body.update(changes)
    with pytest.raises(ValueError):
        validate_document(body)
