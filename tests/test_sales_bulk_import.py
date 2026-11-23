"""Regression tests for bulk Sales import writes."""
import asyncio
from datetime import date
from routes.sales import _save_records, INSERT_SQL


class FakeConnection:
    def __init__(self):
        self.calls = []

    async def executemany(self, sql, args):
        self.calls.append((sql, list(args)))


def test_batch_inserts_preserve_all_fields_and_bound_batch_size():
    conn = FakeConnection()
    rows = [
        {"sale_date": date(2026, 11, 23), "total_amount": i, "payment_method": "Наличные",
         "source_restaurant": "Мега Белая Дача"}
        for i in range(1001)
    ]
    asyncio.run(_save_records(conn, 123, "rest-1", rows))
    assert [len(args) for _, args in conn.calls] == [500, 500, 1]
    assert all(sql == INSERT_SQL for sql, _ in conn.calls)
    assert all(len(row) == 18 for _, batch in conn.calls for row in batch)
    assert conn.calls[0][1][0][0:3] == (123, "rest-1", date(2026, 11, 23))
    assert conn.calls[-1][1][0][9] == 1000


def test_empty_or_invalid_dates_are_not_written():
    conn = FakeConnection()
    asyncio.run(_save_records(conn, 1, "rest-1", [{"sale_date": None}]))
    assert conn.calls == []
