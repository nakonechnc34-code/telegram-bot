"""Read the active SALES rows and attributed, confirmed legacy payouts."""

from decimal import Decimal

ZERO = Decimal(0)
HUNDRED = Decimal(100)


def kol_metrics(turnover, paid, target, *, complete=True):
    actual = paid * HUNDRED / turnover if complete and turnover is not None and turnover > 0 else None
    planned = target * HUNDRED / turnover if target is not None and turnover is not None and turnover > 0 else None
    return {
        "turnover": turnover, "paid": paid, "target_amount": target, "percentage": actual,
        "planned_percentage": planned,
        "difference_pp": actual - planned if actual is not None and planned is not None else None,
        "difference_rubles": paid - target if actual is not None and target is not None else None,
    }


def load_period(cursor, start, end, restaurant_keys, *, all_restaurants):
    cursor.execute("""
        WITH sales AS (
            SELECT sr.restaurant_key, sr.sale_date, SUM(sr.total_amount) AS turnover
            FROM sales_records sr
            WHERE sr.sale_date BETWEEN %s AND %s AND sr.restaurant_key = ANY(%s)
            GROUP BY sr.restaurant_key, sr.sale_date
        ), sales_totals AS (
            SELECT sales.restaurant_key, SUM(turnover) AS turnover,
                   CASE WHEN COUNT(plan.percentage) = COUNT(*)
                        THEN SUM(turnover * plan.percentage / 100) ELSE NULL END AS target
            FROM sales
            LEFT JOIN LATERAL (
                SELECT percentage FROM timesheet_kol_plans kp
                WHERE kp.restaurant_key = sales.restaurant_key AND kp.effective_from <= sales.sale_date
                ORDER BY effective_from DESC LIMIT 1
            ) plan ON TRUE
            GROUP BY sales.restaurant_key
        ), payouts AS (
            SELECT pl.restaurant_key, SUM(p.amount) AS paid
            FROM payments p JOIN timesheet_kol_payment_locations pl ON pl.payment_id = p.id
            WHERE p.status = 'approved' AND p.record_type = 'payout'
                AND p.payment_date BETWEEN %s AND %s AND pl.restaurant_key = ANY(%s)
            GROUP BY pl.restaurant_key
        )
        SELECT r.key, r.name, r.territory_manager_id, s.turnover, s.target, COALESCE(p.paid,0) AS paid
        FROM restaurants r LEFT JOIN sales_totals s ON s.restaurant_key = r.key
        LEFT JOIN payouts p ON p.restaurant_key = r.key
        WHERE r.key = ANY(%s) ORDER BY r.name, r.key
    """, (start, end, restaurant_keys, start, end, restaurant_keys, restaurant_keys))
    source = cursor.fetchall()
    cursor.execute("""
        SELECT COUNT(*) AS count, COALESCE(SUM(p.amount),0) AS amount
        FROM payments p LEFT JOIN timesheet_kol_payment_locations l ON l.payment_id = p.id
        WHERE p.status = 'approved' AND p.record_type = 'payout'
          AND p.payment_date BETWEEN %s AND %s AND l.payment_id IS NULL
    """, (start, end))
    unknown = cursor.fetchone()

    def aggregate(rows, include_unallocated=False):
        turnover = sum((r["turnover"] for r in rows if r["turnover"] is not None), ZERO)
        has_turnover = any(r["turnover"] is not None for r in rows)
        paid = sum((r["paid"] for r in rows), ZERO)
        if include_unallocated:
            paid += unknown["amount"]
        sold = [r for r in rows if r["turnover"] is not None]
        target = sum((r["target"] for r in sold), ZERO) if sold and all(r["target"] is not None for r in sold) else None
        return kol_metrics(turnover if has_turnover else None, paid, target,
                           complete=include_unallocated or not unknown["count"])

    return {
        "start": start.isoformat(), "end": end.isoformat(),
        "restaurants": [{"key": r["key"], "name": r["name"], "territory_manager_id": r["territory_manager_id"],
                         **kol_metrics(r["turnover"], r["paid"], r["target"], complete=not unknown["count"])}
                        for r in source],
        "territories": [
            {"territory_manager_id": manager,
             **aggregate([r for r in source if r["territory_manager_id"] == manager])}
            for manager in dict.fromkeys(r["territory_manager_id"] for r in source)
        ],
        "total": aggregate(source, all_restaurants),
        "unattributed": unknown,
    }
