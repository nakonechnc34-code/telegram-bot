import pytest
from routes.control import score_check

def definition():
    return {"sections":[{"questions":[{"type":"yes_no_na","weight":3,"required":True},{"type":"yes_no_na","weight":1,"required":True}]}]}

def test_weighted():
    score, violations=score_check(definition(),{"0:0":"yes","0:1":"no"})
    assert score==75
    assert len(violations)==1

def test_na():
    assert score_check(definition(),{"0:0":"na","0:1":"yes"})[0]==100
    assert score_check(definition(),{"0:0":"na","0:1":"na"})[0] is None

def test_missing():
    with pytest.raises(ValueError):
        score_check(definition(),{"0:0":"yes"})
