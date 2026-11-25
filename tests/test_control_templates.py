import pytest
from routes.control import validate_template

def template():
    return {"title":"Кухня","sections":[{"title":"Чистота","questions":[{"text":"Стол чистый?","type":"yes_no_na","weight":5,"required":True}]}]}

def test_valid():
    assert validate_template(template())["title"] == "Кухня"

@pytest.mark.parametrize("weight", [-1, 101, True, "5"])
def test_invalid_weight(weight):
    body=template()
    body["sections"][0]["questions"][0]["weight"]=weight
    with pytest.raises(ValueError):
        validate_template(body)

def test_empty_sections():
    with pytest.raises(ValueError):
        validate_template({"title":"Кухня","sections":[]})

@pytest.mark.parametrize("category",["checklist","audit","mystery_guest"])
def test_category(category):
    assert validate_template(dict(template(),category=category))["category"]==category

def test_legacy_category():
    assert validate_template(template())["category"]=="checklist"

def test_invalid_category():
    with pytest.raises(ValueError):
        validate_template(dict(template(),category="unknown"))
