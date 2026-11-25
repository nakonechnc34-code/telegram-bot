from datetime import datetime
from routes.control import next_schedule_due

def test_month_end():
    first=datetime.fromisoformat("2026-01-31T09:00:00+03:00")
    second=next_schedule_due(first,"monthly",31)
    assert second.day==28
    assert next_schedule_due(second,"monthly",31).day==31

def test_daily_weekly():
    first=datetime.fromisoformat("2026-11-25T09:00:00+03:00")
    assert next_schedule_due(first,"daily",25).day==26
    assert next_schedule_due(first,"weekly",25).day==2
