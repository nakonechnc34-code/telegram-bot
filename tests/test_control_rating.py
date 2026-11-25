from routes.control import calculate_control_rating, RATING_WEIGHTS

def test_no_data():
    result=calculate_control_rating({})
    assert result["rating"] is None
    assert result["provisional"] is None
    assert result["coverage"]==0

def test_partial_rating():
    result=calculate_control_rating({"checklists":90,"haccp":100,"tasks":0})
    assert result["rating"] is None
    assert result["coverage"]==55
    assert result["provisional"]==69.09

def test_full_rating():
    result=calculate_control_rating({k:80 for k in RATING_WEIGHTS})
    assert result["rating"]==80
    assert result["coverage"]==100
