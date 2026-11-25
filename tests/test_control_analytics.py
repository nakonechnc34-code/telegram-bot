from datetime import date
import pytest
from routes.control import analytics_period

def test_inclusive_period():
    assert analytics_period({"start":"2026-11-01","end":"2026-11-25"}) == (date(2026,11,1),date(2026,11,26))

@pytest.mark.parametrize("body",[{"start":"2026-11-02","end":"2026-11-01"},{"start":"2025-01-01","end":"2026-11-01"},{"start":"invalid","end":"2026-11-01"}])
def test_invalid_period(body):
    with pytest.raises(ValueError):
        analytics_period(body)
