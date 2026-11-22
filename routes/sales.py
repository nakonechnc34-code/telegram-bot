"""
Routes для дашборда Товарооборот.
Загрузка Excel/CSV, аналитика, агрегации.
"""

import io
import csv
import json
import os
import asyncio
import uuid
from datetime import datetime, date, timedelta
from functools import wraps

from aiohttp import web
import openpyxl
from asyncpg.exceptions import UndefinedTableError

import db
from middleware.auth import require_admin
from utils.auth_helpers import get_admin_user, denied, _is_tu, _sync_get_tu_rests

routes = web.RouteTableDef()


# ==================== ХЕЛПЕРЫ ====================

def admin_required(handler):
    """Декоратор: требует админа + кладёт его в request['admin']."""
    @wraps(handler)
    async def wrapper(request):
        admin, err = await get_admin_user(request)
        if err:
            return denied(err)
        request['admin'] = admin
        return await handler(request)
    return wrapper


def _to_date(val):
    if val is None or val == "":
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    try:
        return datetime.strptime(str(val).strip()[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _upload_dir():
    base = os.getenv("DATA_DIR") or ("/data" if os.path.exists("/data") else os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    return os.path.join(base, "data", "uploads", "sales")


async def _allowed_rests(user):
    return await db._run(_sync_get_tu_rests, user["user_id"]) if _is_tu(user) else None


def _where(conditions, params):
    return f"WHERE {' AND '.join(conditions)}" if conditions else "", params


# ==================== ПАРСЕРЫ ====================

def _parse_iiko_daily(ws) -> list[dict]:
    """Парсит сводный 'Дневной отчет' iiko."""
    rows = list(ws.iter_rows(values_only=True))
    header_idx = next(
        (i for i, row in enumerate(rows)
         if row and any(c and ("учетный день" in str(c).lower() or "тип оплаты" in str(c).lower()) for c in row)),
        -1
    )
    if header_idx == -1:
        return []

    headers = [str(c).strip().lower() if c else "" for c in rows[header_idx]]
    def col(*names): return next((i for i, h in enumerate(headers) if any(n in h for n in names)), -1)

    i_date, i_rest, i_pay = col("учетный день", "дата"), col("торговое предприятие", "ресторан"), col("тип оплаты", "оплата")
    i_sum, i_chk = col("сумма со скидкой", "сумма"), col("чеков", "кол-во")
    i_hour = col("час открытия")

    if i_sum == -1 or i_pay == -1 or i_rest == -1 or i_date == -1:
        return []

    records, cur_date, cur_rest, cur_hour = [], None, None, None
    for row in rows[header_idx + 1:]:
        if not row or all(v is None or str(v).strip() == "" for v in row):
            continue
        get = lambda i: row[i] if 0 <= i < len(row) else None
        raw_date, raw_rest, raw_pay, raw_sum, raw_chk = get(i_date), get(i_rest), get(i_pay), get(i_sum), get(i_chk)

        if raw_rest and "всего" in str(raw_rest).lower(): continue
        if raw_date and "всего" in str(raw_date).lower(): continue

        cur_date = _to_date(raw_date) or cur_date
        if raw_rest:
            cur_rest = str(raw_rest).strip()
            cur_hour = None
        raw_hour = get(i_hour)
        if raw_hour is not None and str(raw_hour).strip():
            hour_text = str(raw_hour).strip()
            if 'всего' in hour_text.lower():
                cur_hour = None
                continue
            try:
                hour = int(float(hour_text.split(':')[0].replace(',', '.')))
                cur_hour = hour if 0 <= hour <= 23 else None
            except (ValueError, TypeError):
                cur_hour = None

        if raw_pay is None or raw_sum is None or cur_date is None: continue
        if "всего" in str(raw_pay).lower(): continue
        try: total = float(str(raw_sum).replace(",", ".").strip())
        except (ValueError, TypeError): continue
        try: checks = int(float(str(raw_chk).replace(",", "."))) if raw_chk else 0
        except (ValueError, TypeError): checks = 0

        records.append({
            "sale_date": cur_date, "payment_method": str(raw_pay).strip(),
            "total_amount": total, "quantity": checks or 1,
            "category": None, "product_name": None,
            "cost_amount": 0, "profit_amount": 0,
            "source_restaurant": cur_rest,
            "opening_hour": cur_hour,
        })
    return records


FLAT_FIELDS = {
    "дата": "sale_date", "дата продажи": "sale_date",
    "категория": "category", "группа": "category",
    "блюдо": "product_name", "наименование": "product_name", "товар": "product_name",
    "количество": "quantity", "кол-во": "quantity",
    "сумма": "total_amount", "сумма продажи": "total_amount",
    "себестоимость": "cost_amount",
    "оплата": "payment_method",
    "скидка": "discount_amount",
}
NUM_FIELDS = {"quantity", "shift_number"}
MONEY_FIELDS = {"unit_price", "total_amount", "cost_amount", "profit_amount", "discount_amount"}


def _normalize(record: dict) -> dict:
    """Приводит строку из Excel/CSV к sales_records."""
    rec = {}
    for src, val in record.items():
        key = src.lower().strip() if isinstance(src, str) else str(src)
        key = FLAT_FIELDS.get(key, key)
        if key in NUM_FIELDS:
            try: val = int(val) if val is not None else 0
            except (ValueError, TypeError): val = 0
        elif key in MONEY_FIELDS:
            try: val = float(str(val).replace(",", ".")) if val is not None else 0.0
            except (ValueError, TypeError): val = 0.0
        elif key == "sale_date":
            val = _to_date(val) or val
        elif val is not None:
            val = str(val).strip() if val else None
        rec[key] = val
    if "sale_date" not in rec or "total_amount" not in rec:
        return {}
    rec.setdefault("quantity", 1)
    rec.setdefault("unit_price", rec["total_amount"])
    rec.setdefault("category", None)
    rec.setdefault("product_name", None)
    rec.setdefault("payment_method", None)
    return rec


def _parse_flat(ws) -> list[dict]:
    rows = list(ws.iter_rows(values_only=True))
    if not rows: return []
    headers = [str(c).lower().strip() if c else "" for c in rows[0]]
    records = []
    for row in rows[1:]:
        if not any(v is not None for v in row): continue
        raw = {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
        rec = _normalize(raw)
        if rec: records.append(rec)
    return records


def _parse_excel(file_obj: io.BytesIO) -> list[dict]:
    wb = openpyxl.load_workbook(file_obj, read_only=True, data_only=True)
    ws = wb.active
    try:
        iiko = _parse_iiko_daily(ws)
        return iiko if iiko else _parse_flat(ws)
    finally:
        wb.close()


def _parse_csv(text: str) -> list[dict]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\\t")
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    except csv.Error:
        reader = csv.DictReader(io.StringIO(text))
    return [rec for row in reader if (rec := _normalize(row))]


# ==================== СОХРАНЕНИЕ ====================

EXTRA_KEYS = {"sale_date", "category", "subcategory", "product_name", "sku", "quantity",
              "unit_price", "total_amount", "cost_amount", "profit_amount", "profit_margin",
              "payment_method", "shift_number", "employee_name", "discount_amount"}

INSERT_SQL = """
    INSERT INTO sales_records (
        import_id, restaurant_key, sale_date, category, subcategory,
        product_name, sku, quantity, unit_price, total_amount,
        cost_amount, profit_amount, profit_margin, payment_method,
        shift_number, employee_name, discount_amount, extra_data
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
"""


async def _save_records(conn, import_id, restaurant_key, records):
    for rec in records:
        sale_date = _to_date(rec.get("sale_date"))
        if sale_date is None: continue
        extra = {k: v for k, v in rec.items() if k not in EXTRA_KEYS}
        await conn.execute(INSERT_SQL,
            import_id, restaurant_key, sale_date,
            rec.get("category"), rec.get("subcategory"), rec.get("product_name"), rec.get("sku"),
            rec.get("quantity", 1), rec.get("unit_price", 0), rec.get("total_amount", 0),
            rec.get("cost_amount", 0), rec.get("profit_amount", 0), rec.get("profit_margin"),
            rec.get("payment_method"), rec.get("shift_number"), rec.get("employee_name"),
            rec.get("discount_amount", 0), json.dumps(extra) if extra else None)


async def _recalc_summary(conn, restaurant_key):
    """Пересчитывает дневные сводки."""
    await conn.execute("DELETE FROM sales_daily_summary WHERE restaurant_key = $1", restaurant_key)
    rows = await conn.fetch("""
        SELECT sale_date,
            SUM(total_amount) AS total_sales, SUM(cost_amount) AS total_cost,
            SUM(profit_amount) AS total_profit,
            CASE WHEN SUM(total_amount) > 0
                 THEN ROUND(SUM(profit_amount)*100.0 / NULLIF(SUM(total_amount),0), 2)
                 ELSE 0 END AS avg_margin,
            SUM(quantity) AS total_items_sold,
            COUNT(DISTINCT id) AS total_transactions,
            SUM(CASE WHEN payment_method IN ('Наличные','cash') THEN total_amount ELSE 0 END) AS cash_sales,
            SUM(CASE WHEN payment_method IN ('Карта','card','ВТБ БАНК') THEN total_amount ELSE 0 END) AS card_sales,
            SUM(CASE WHEN payment_method IN ('Онлайн','online') OR payment_method LIKE 'Яндекс%' THEN total_amount ELSE 0 END) AS online_sales,
            COUNT(DISTINCT product_name) AS unique_products
        FROM sales_records WHERE restaurant_key = $1 GROUP BY sale_date ORDER BY sale_date
    """, restaurant_key)
    for r in rows:
        ts = float(r["total_sales"] or 0); items = r["total_items_sold"] or 0
        await conn.execute("""
            INSERT INTO sales_daily_summary
            (restaurant_key, summary_date, total_sales, total_cost, total_profit,
             avg_margin, total_items_sold, total_transactions, avg_check,
             cash_sales, card_sales, online_sales, unique_products)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
        """, restaurant_key, r["sale_date"], ts, float(r["total_cost"] or 0), float(r["total_profit"] or 0),
            float(r["avg_margin"] or 0), items, r["total_transactions"] or 0,
            round(ts / items, 2) if items else 0,
            float(r["cash_sales"] or 0), float(r["card_sales"] or 0), float(r["online_sales"] or 0),
            r["unique_products"] or 0)


# ==================== РОУТЫ ====================

@routes.post("/api/sales/upload")
@require_admin
async def upload_sales_file(request: web.Request) -> web.Response:
    user = request["user"]
    reader = await request.post()
    f = reader.get("file")
    if not isinstance(f, web.FileField) or not f.filename: return web.json_response({"error": "Файл не найден"}, status=400)
    key = (reader.get("restaurant_key") or "").strip()
    if not key: return web.json_response({"error": "Укажите restaurant_key"}, status=400)

    allowed = await _allowed_rests(user)
    if allowed is not None and key not in allowed:
        return web.json_response({"error": "Нет прав"}, status=403)

    pool = db.get_pool(request.app)
    async with pool.acquire() as conn:
        if not await conn.fetchrow("SELECT 1 FROM restaurants WHERE key = $1", key):
            return web.json_response({"error": "Ресторан не найден"}, status=404)

    filename = os.path.basename(f.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".xlsx", ".csv"):
        return web.json_response({"error": "Форматы: .xlsx, .csv"}, status=400)

    os.makedirs(_upload_dir(), exist_ok=True)
    stored = f"{datetime.utcnow():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}{ext}"
    path = os.path.join(_upload_dir(), stored)
    # Bound uploads before parsing: large XLSX/CSV can exhaust worker memory.
    data = await asyncio.to_thread(f.file.read, 10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        return web.json_response({"error": "Максимальный размер файла — 10 МБ"}, status=413)
    if not data:
        return web.json_response({"error": "Пустой файл"}, status=400)
    with open(path, "wb") as fp: fp.write(data)

    async with pool.acquire() as conn:
        import_id = (await conn.fetchrow(
            "INSERT INTO sales_imports (restaurant_key, filename, file_path, uploaded_by, status) "
            "VALUES ($1, $2, $3, $4, 'processing') RETURNING id",
            key, filename, path, user["user_id"]))["id"]

    try:
        records = (await asyncio.to_thread(_parse_excel, io.BytesIO(data))
                   if ext == ".xlsx" else _parse_csv(data.decode("utf-8-sig")))
        if not records:
            raise ValueError("В файле нет распознанных строк продаж")
        # Route every restaurant in a multi-restaurant iiko daily report to
        # its own database key; reject unknown/ambiguous or unauthorized names.
        daily = any("source_restaurant" in rec for rec in records)
        by_key = {}
        if daily:
            async with pool.acquire() as conn:
                db_rests = await conn.fetch("SELECT key, name FROM restaurants")
            def norm_name(value):
                import re
                value = str(value or "").casefold().replace("ё", "е")
                value = re.sub(r"^\s*(?:wokker|воккер)\s*[-–—:]\s*", "", value)
                # iiko may omit the shopping-centre prefix and use spaces
                # instead of hyphens (e.g. "Белая дача" / "Мега Белая Дача").
                value = re.sub(r"[^\w\s]", " ", value)
                value = " ".join(value.split())
                return re.sub(r"^мега\s+", "", value)
            matches = {}
            for restaurant in db_rests:
                matches.setdefault(norm_name(restaurant["name"]), []).append(restaurant["key"])
            unknown = []
            for rec in records:
                name = rec.get("source_restaurant")
                candidates = matches.get(norm_name(name), [])
                if len(candidates) != 1:
                    unknown.append(name or "(без названия)")
                    continue
                rest_key = candidates[0]
                if allowed is not None and rest_key not in allowed:
                    raise PermissionError("Нет прав на ресторан: " + str(name))
                by_key.setdefault(rest_key, []).append(rec)
            if unknown:
                raise ValueError("Не удалось однозначно сопоставить рестораны: " + ", ".join(sorted(set(unknown))))
        else:
            by_key[key] = records

        async with pool.acquire() as conn:
            async with conn.transaction():
                for rest_key in sorted(by_key):
                    await conn.fetchval("SELECT key FROM restaurants WHERE key = $1 FOR UPDATE", rest_key)
                for rest_key, grouped in by_key.items():
                    # One authoritative snapshot per restaurant and report date.
                    # Replace only dates included in this file, preserving all
                    # other dates, restaurants and the import audit history.
                    report_dates = sorted({d for rec in grouped
                                           if (d := _to_date(rec.get("sale_date"))) is not None})
                    if not report_dates:
                        raise ValueError("В отчёте отсутствуют корректные даты продаж")
                    await conn.execute(
                        "DELETE FROM sales_records WHERE restaurant_key=$1 AND sale_date=ANY($2::date[])",
                        rest_key, report_dates)
                    await _save_records(conn, import_id, rest_key, grouped)
                    await _recalc_summary(conn, rest_key)
                # Mark fully superseded imports; retain their audit records.
                await conn.execute("""
                    UPDATE sales_imports si SET status='replaced'
                    WHERE si.status='completed'
                      AND NOT EXISTS (SELECT 1 FROM sales_records sr WHERE sr.import_id=si.id)
                """)
                await conn.execute(
                    "UPDATE sales_imports SET status='completed', rows_count=$1, processed_at=NOW() WHERE id=$2",
                    len(records), import_id,
                )
        return web.json_response({"success": True, "import_id": import_id, "rows_count": len(records),
                                  "restaurants_count": len(by_key),
                                  "message": f"Загружено {len(records)} записей"})
    except Exception as e:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE sales_imports SET status='error', error_message=$1 WHERE id=$2",
                str(e)[:1000], import_id)
        return web.json_response({"error": f"Ошибка: {str(e)[:500]}", "import_id": import_id}, status=500)


# Configurable payment-method mapping. Persisted centrally for every Sales user.
DEFAULT_ORDER_TYPES = {
    "ВТБ БАНК": "Зал", "Наличные": "Зал", "Starter": "Зал",
    "Магнит": "Зал", "Яндекс.Еда": "Доставка", "Я.Бейдж!": "Доставка",
}


async def _order_type_mapping(conn):
    try:
        saved = await conn.fetchval("SELECT mapping FROM sales_order_type_settings WHERE id = 1")
    except UndefinedTableError:
        # Migration 004 is not applied yet; keep the dashboard readable.
        return dict(DEFAULT_ORDER_TYPES)
    return (json.loads(saved) if isinstance(saved, str) else dict(saved)) if saved is not None else dict(DEFAULT_ORDER_TYPES)


@routes.post("/api/sales/order-type-settings")
@admin_required
async def sales_order_type_settings(request: web.Request) -> web.Response:
    user = request["admin"]
    body = await request.json()
    action = body.get("action", "get")
    if action not in ("get", "save"):
        return web.json_response({"error": "Неизвестное действие"}, status=400)
    if action == "save" and not user.get("is_super_admin"):
        return web.json_response({"error": "Редактирование доступно администратору сети"}, status=403)
    pool = db.get_pool(request.app)
    async with pool.acquire() as conn:
        if action == "save":
            mapping = body.get("mapping")
            if (not isinstance(mapping, dict) or len(mapping) > 200 or
                any(not isinstance(k, str) or not k.strip() or len(k) > 120 or
                    v not in ("Зал", "Доставка", "Не распределено")
                    for k, v in mapping.items())):
                return web.json_response({"error": "Некорректные настройки"}, status=400)
            try:
                await conn.execute("""
                INSERT INTO sales_order_type_settings (id, mapping, updated_at)
                VALUES (1, $1::jsonb, NOW())
                ON CONFLICT (id) DO UPDATE SET mapping=EXCLUDED.mapping, updated_at=NOW()
                """, json.dumps(mapping, ensure_ascii=False))
            except UndefinedTableError:
                return web.json_response({"error": "Требуется миграция database/004_sales_order_type_settings.sql"}, status=503)
        mapping = await _order_type_mapping(conn)
        # Discover methods actually present in accessible Sales records.
        allowed = await _allowed_rests(user)
        if allowed is None:
            rows = await conn.fetch("SELECT DISTINCT payment_method FROM sales_records WHERE payment_method IS NOT NULL ORDER BY payment_method")
        else:
            rows = await conn.fetch("SELECT DISTINCT payment_method FROM sales_records WHERE restaurant_key = ANY($1) AND payment_method IS NOT NULL ORDER BY payment_method", allowed)
    methods = sorted(set(mapping) | {r["payment_method"] for r in rows})
    return web.json_response({"success": True, "data": {
        "mapping": mapping, "methods": methods, "can_edit": bool(user.get("is_super_admin")),
    }})


@routes.post("/api/sales/dashboard")
@admin_required
async def sales_dashboard(request: web.Request) -> web.Response:
    user = request['admin']
    body = await request.json()
    period = body.get("period", "30d")
    key = body.get("restaurant_key")
    allowed = await _allowed_rests(user)
    if allowed is not None and key and key not in allowed:
        return web.json_response({"error": "Forbidden"}, status=403)
    # None means all restaurants (unrestricted admin). An empty list means no
    # restaurants. Never silently replace "all" with the TU's first restaurant.
    scoped_keys = [key] if key else allowed
    days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 30)
    date_from = datetime.utcnow().date() - timedelta(days=days - 1)
    conditions = ["sr.sale_date >= $1"]
    params = [date_from]
    if scoped_keys is not None:
        conditions.append("sr.restaurant_key = ANY($2)")
        params.append(scoped_keys)
    w, _ = _where(conditions, params)

    pool = db.get_pool(request.app)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT COALESCE(SUM(sr.total_amount), 0) AS s, COALESCE(SUM(sr.cost_amount), 0) AS c, "
            f"COALESCE(SUM(sr.profit_amount), 0) AS p, COALESCE(SUM(sr.quantity), 0) AS i "
            f"FROM sales_records sr {w}", *params)
        ts, tc, tp, ti = float(row["s"]), float(row["c"]), float(row["p"]), int(row["i"])
        overview = {
            "total_sales": ts, "total_cost": tc, "total_profit": tp,
            "avg_margin": round(tp * 100 / ts, 2) if ts else 0,
            "total_items_sold": ti, "period_days": days,
        }
        daily_trend = await conn.fetch(
            f"SELECT sr.sale_date, SUM(sr.total_amount) s, SUM(sr.cost_amount) c, "
            f"SUM(sr.profit_amount) p, SUM(sr.quantity) q "
            f"FROM sales_records sr {w} GROUP BY sr.sale_date ORDER BY sr.sale_date", *params)

        # Restrict both the LEFT JOIN and restaurant rows to the same scope.
        rest_filter = "WHERE r.key = ANY($2)" if scoped_keys is not None else ""
        join_filter = "AND sr.restaurant_key = ANY($2)" if scoped_keys is not None else ""
        by_rest = await conn.fetch(f"""
            SELECT r.name, r.key, COALESCE(SUM(sr.total_amount),0) total,
                   COALESCE(SUM(sr.profit_amount),0) profit
            FROM restaurants r LEFT JOIN sales_records sr
              ON sr.restaurant_key = r.key AND sr.sale_date >= $1 {join_filter}
            {rest_filter}
            GROUP BY r.key, r.name ORDER BY total DESC""", *params)

        # Aggregate only records that carry a valid opening hour.
        hour_conditions = conditions + [
            "sr.extra_data IS NOT NULL",
            "(sr.extra_data::jsonb->>'opening_hour') ~ '^(?:[0-9]|1[0-9]|2[0-3])$'"
        ]
        hour_where, _ = _where(hour_conditions, params)
        hourly = await conn.fetch(
            f"""SELECT (sr.extra_data::jsonb->>'opening_hour')::int AS opening_hour,
                       SUM(sr.total_amount) sales, SUM(sr.quantity) checks
                FROM sales_records sr {hour_where}
                GROUP BY 1 ORDER BY 1""", *params)

        order_mapping = await _order_type_mapping(conn)
        order_rows = await conn.fetch(
            f"""SELECT sr.payment_method method, SUM(sr.total_amount) sales,
                       SUM(sr.quantity) checks
                FROM sales_records sr {w}
                GROUP BY sr.payment_method""", *params)
        order_types = {name: {"type": name, "sales": 0.0, "checks": 0}
                       for name in ("Зал", "Доставка", "Не распределено")}
        for item in order_rows:
            method = item["method"] or ""
            category = order_mapping.get(method, "Не распределено")
            if category not in order_types:
                category = "Не распределено"
            order_types[category]["sales"] += float(item["sales"] or 0)
            order_types[category]["checks"] += int(item["checks"] or 0)

        by_payment = await conn.fetch(
            f"SELECT COALESCE(sr.payment_method,'Не указан') method, "
            f"SUM(sr.total_amount) total, COUNT(*) c "
            f"FROM sales_records sr {w} GROUP BY sr.payment_method ORDER BY total DESC", *params)

        import_filter = "WHERE si.restaurant_key = ANY($1)" if scoped_keys is not None else ""
        imports = await conn.fetch(f"""
            SELECT si.*, u.full_name uploader_name FROM sales_imports si
            LEFT JOIN users u ON u.user_id = si.uploaded_by
            {import_filter} ORDER BY si.upload_date DESC LIMIT 20""",
            *([scoped_keys] if scoped_keys is not None else []))

        summary_filter = "AND restaurant_key = ANY($2)" if scoped_keys is not None else ""
        summaries = await conn.fetch(
            f"SELECT * FROM sales_daily_summary WHERE summary_date >= $1 {summary_filter} "
            f"ORDER BY summary_date DESC LIMIT 30", *params)

    return web.json_response({"success": True, "data": {
        "overview": overview,
        "daily_trend": [{"date": str(r["sale_date"]), "sales": float(r["s"] or 0),
                         "cost": float(r["c"] or 0), "profit": float(r["p"] or 0),
                         "items": int(r["q"] or 0)} for r in daily_trend],
        "by_order_type": list(order_types.values()),
        "hourly_revenue": [{"hour": int(r["opening_hour"]), "sales": float(r["sales"] or 0),
                            "checks": int(r["checks"] or 0)} for r in hourly],
        "by_restaurant": [{"key": r["key"], "name": r["name"],
                           "total_sales": float(r["total"] or 0), "profit": float(r["profit"] or 0)} for r in by_rest],
        "by_payment": [{"method": r["method"], "total_sales": float(r["total"] or 0),
                        "count": int(r["c"] or 0)} for r in by_payment],
        "imports": [{"id": i["id"], "filename": i["filename"], "restaurant_key": i["restaurant_key"],
                     "upload_date": str(i["upload_date"]), "rows_count": int(i["rows_count"] or 0),
                     "status": i["status"], "error_message": i["error_message"],
                     "uploader_name": i["uploader_name"]} for i in imports],
        "daily_summaries": [{"date": str(s["summary_date"]), "total_sales": float(s["total_sales"] or 0),
                             "total_cost": float(s["total_cost"] or 0), "total_profit": float(s["total_profit"] or 0),
                             "avg_margin": float(s["avg_margin"] or 0), "items_sold": int(s["total_items_sold"] or 0),
                             "transactions": int(s["total_transactions"] or 0), "avg_check": float(s["avg_check"] or 0),
                             "cash_sales": float(s["cash_sales"] or 0), "card_sales": float(s["card_sales"] or 0),
                             "online_sales": float(s["online_sales"] or 0),
                             "unique_products": int(s["unique_products"] or 0)} for s in summaries],
    }})



@routes.post("/api/sales/products")
@admin_required
async def sales_products(request: web.Request) -> web.Response:
    """Aggregated products and categories, scoped to authorized restaurants."""
    user = request["admin"]
    body = await request.json()
    key = body.get("restaurant_key")
    allowed = await _allowed_rests(user)
    if allowed is not None and key and key not in allowed:
        return web.json_response({"error": "Forbidden"}, status=403)

    days = {"7d": 7, "30d": 30, "90d": 90}.get(body.get("period"), 30)
    since = datetime.utcnow().date() - timedelta(days=days - 1)
    scoped = [key] if key else allowed
    conditions = ["sr.sale_date >= $1", "NULLIF(TRIM(sr.product_name), '') IS NOT NULL"]
    params = [since]
    if scoped is not None:
        conditions.append("sr.restaurant_key = ANY($2)")
        params.append(scoped)
    where, _ = _where(conditions, params)
    pool = db.get_pool(request.app)
    async with pool.acquire() as conn:
        products = await conn.fetch(
            f"""SELECT sr.product_name name, COALESCE(sr.category, 'Без категории') category,
                 SUM(sr.quantity) quantity, SUM(sr.total_amount) sales,
                 SUM(sr.cost_amount) cost, SUM(sr.profit_amount) profit
                 FROM sales_records sr {where}
                 GROUP BY sr.product_name, COALESCE(sr.category, 'Без категории')
                 ORDER BY sales DESC LIMIT 100""", *params)
        categories = await conn.fetch(
            f"""SELECT COALESCE(sr.category, 'Без категории') name,
                 SUM(sr.quantity) quantity, SUM(sr.total_amount) sales,
                 SUM(sr.profit_amount) profit
                 FROM sales_records sr {where}
                 GROUP BY COALESCE(sr.category, 'Без категории')
                 ORDER BY sales DESC LIMIT 50""", *params)
    def normalize(rows, include_product_fields=False):
        return [{"name": r["name"],
                 "category": r["category"] if include_product_fields else None,
                 "quantity": float(r["quantity"] or 0),
                 "sales": float(r["sales"] or 0),
                 "profit": float(r["profit"] or 0),
                 **({"cost": float(r["cost"] or 0)} if include_product_fields else {})} for r in rows]
    return web.json_response({"success": True, "data": {
        "products": normalize(products, True), "categories": normalize(categories),
        "period_days": days,
    }})


@routes.post("/api/sales/records")
@admin_required
async def sales_records(request: web.Request) -> web.Response:
    user = request['admin']
    body = await request.json()
    key = body.get("restaurant_key")
    df, dt = _to_date(body.get("date_from")), _to_date(body.get("date_to"))
    cat = body.get("category"); prod = body.get("product_name")
    page = max(1, int(body.get("page", 1) or 1)); limit = max(1, min(500, int(body.get("limit", 100) or 100)))
    allowed = await _allowed_rests(user)

    cond, params, idx = [], [], 1
    if allowed is not None:
        if key and key not in allowed: return web.json_response({"error": "Forbidden"}, status=403)
        cond.append(f"sr.restaurant_key = ANY(${idx})"); params.append([key] if key else allowed); idx += 1
    elif key:
        cond.append(f"sr.restaurant_key = ${idx}"); params.append(key); idx += 1
    if df: cond.append(f"sr.sale_date >= ${idx}"); params.append(df); idx += 1
    if dt: cond.append(f"sr.sale_date <= ${idx}"); params.append(dt); idx += 1
    if cat: cond.append(f"sr.category ILIKE ${idx}"); params.append(f"%{cat}%"); idx += 1
    if prod: cond.append(f"sr.product_name ILIKE ${idx}"); params.append(f"%{prod}%"); idx += 1
    w, _ = _where(cond, params)

    pool = db.get_pool(request.app)
    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM sales_records sr {w}", *params)
        rows = await conn.fetch(
            f"SELECT sr.*, r.name restaurant_name FROM sales_records sr "
            f"LEFT JOIN restaurants r ON r.key = sr.restaurant_key {w} "
            f"ORDER BY sr.sale_date DESC, sr.id DESC LIMIT ${idx} OFFSET ${idx+1}",
            *params, limit, (page - 1) * limit)

    return web.json_response({"success": True, "data": {
        "records": [_rec_to_json(r) for r in rows],
        "total": total, "page": page, "limit": limit,
        "pages": (total + limit - 1) // limit if limit > 0 else 1,
    }})


def _rec_to_json(r):
    return {"id": r["id"], "restaurant_key": r["restaurant_key"], "restaurant_name": r["restaurant_name"],
            "sale_date": str(r["sale_date"]), "category": r["category"], "subcategory": r["subcategory"],
            "product_name": r["product_name"], "sku": r["sku"], "quantity": int(r["quantity"] or 0),
            "unit_price": float(r["unit_price"] or 0), "total_amount": float(r["total_amount"] or 0),
            "cost_amount": float(r["cost_amount"] or 0), "profit_amount": float(r["profit_amount"] or 0),
            "profit_margin": float(r["profit_margin"] or 0), "payment_method": r["payment_method"],
            "shift_number": int(r["shift_number"] or 0), "employee_name": r["employee_name"],
            "discount_amount": float(r["discount_amount"] or 0)}


@routes.post("/api/sales/restaurants")
@admin_required
async def sales_restaurants(request: web.Request) -> web.Response:
    user = request['admin']
    allowed = await _allowed_rests(user)
    pool = db.get_pool(request.app)
    async with pool.acquire() as conn:
        if allowed is not None:
            rows = await conn.fetch("""
                SELECT r.key, r.name, r.address,
                  (SELECT COUNT(*) FROM sales_records sr WHERE sr.restaurant_key = r.key) total_records,
                  (SELECT COALESCE(SUM(total_amount),0) FROM sales_records sr WHERE sr.restaurant_key = r.key) total_sales,
                  (SELECT MAX(sale_date) FROM sales_records sr WHERE sr.restaurant_key = r.key) last_sale_date
                FROM restaurants r WHERE r.key = ANY($1) ORDER BY r.sort NULLS FIRST, r.name""", allowed)
        else:
            rows = await conn.fetch("""
                SELECT r.key, r.name, r.address,
                  (SELECT COUNT(*) FROM sales_records sr WHERE sr.restaurant_key = r.key) total_records,
                  (SELECT COALESCE(SUM(total_amount),0) FROM sales_records sr WHERE sr.restaurant_key = r.key) total_sales,
                  (SELECT MAX(sale_date) FROM sales_records sr WHERE sr.restaurant_key = r.key) last_sale_date
                FROM restaurants r ORDER BY r.sort NULLS FIRST, r.name""")
    return web.json_response({"success": True, "data": [
        {"key": r["key"], "name": r["name"], "address": r["address"],
         "total_records": int(r["total_records"] or 0), "total_sales": float(r["total_sales"] or 0),
         "last_sale_date": str(r["last_sale_date"]) if r["last_sale_date"] else None} for r in rows]})


@routes.post("/api/sales/export")
@admin_required
async def export_sales(request: web.Request) -> web.Response:
    user = request['admin']
    body = await request.json()
    key = body.get("restaurant_key")
    df, dt = _to_date(body.get("date_from")), _to_date(body.get("date_to"))
    if not df and isinstance(body.get("period"), str):
        days = {"7d": 7, "30d": 30, "90d": 90}.get(body["period"], 30)
        df = datetime.utcnow().date() - timedelta(days=days)
    allowed = await _allowed_rests(user)

    cond, params, idx = [], [], 1
    if allowed is not None:
        if key and key not in allowed: return web.json_response({"error": "Forbidden"}, status=403)
        cond.append(f"sr.restaurant_key = ANY(${idx})"); params.append([key] if key else allowed); idx += 1
    elif key:
        cond.append(f"sr.restaurant_key = ${idx}"); params.append(key); idx += 1
    if df: cond.append(f"sr.sale_date >= ${idx}"); params.append(df); idx += 1
    if dt: cond.append(f"sr.sale_date <= ${idx}"); params.append(dt); idx += 1
    w, _ = _where(cond, params)

    pool = db.get_pool(request.app)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT sr.sale_date, sr.restaurant_key, r.name restaurant_name, sr.category, "
            f"sr.product_name, sr.quantity, sr.unit_price, sr.total_amount, sr.cost_amount, "
            f"sr.profit_amount, sr.payment_method, sr.employee_name "
            f"FROM sales_records sr LEFT JOIN restaurants r ON r.key = sr.restaurant_key {w} "
            f"ORDER BY sr.sale_date DESC", *params)

    def make_xlsx():
        from openpyxl.styles import Font, PatternFill
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Товарооборот"
        ws.append(["Дата", "Ресторан", "Ключ", "Категория", "Товар", "Кол-во",
                   "Цена", "Сумма", "Себестоимость", "Прибыль", "Оплата", "Сотрудник"])
        fill = PatternFill("solid", start_color="667eea")
        for c in ws[1]: c.fill = fill; c.font = Font(bold=True, color="FFFFFF")
        for r in rows:
            ws.append([r["sale_date"], r["restaurant_name"], r["restaurant_key"], r["category"],
                       r["product_name"], r["quantity"], r["unit_price"], r["total_amount"],
                       r["cost_amount"], r["profit_amount"], r["payment_method"], r["employee_name"]])
        for col in ws.columns:
            width = max((len(str(c.value)) for c in col if c.value), default=0) + 4
            ws.column_dimensions[col[0].column_letter].width = min(width, 40)
        out = io.BytesIO(); wb.save(out); out.seek(0); wb.close()
        return out.read()

    data = await asyncio.to_thread(make_xlsx)
    return web.Response(body=data,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=sales_{datetime.utcnow():%Y%m%d_%H%M%S}.xlsx"})


@routes.get("/api/sales/template")
@require_admin
async def sales_template(request: web.Request) -> web.Response:
    def make():
        from openpyxl.styles import Font, PatternFill
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Шаблон"
        headers = ["sale_date", "restaurant_key", "category", "subcategory", "product_name", "sku",
                   "quantity", "unit_price", "total_amount", "cost_amount", "profit_amount",
                   "profit_margin", "payment_method", "shift_number", "employee_name", "discount_amount"]
        ws.append(headers)
        ws.append(["2026-11-20", "restaurant_1", "Напитки", "Кофе", "Капучино", "SKU001",
                   15, 250, 3750, 1200, 2550, 68.0, "Карта", 1, "Иванов И.И.", 0])
        fill = PatternFill("solid", start_color="667eea")
        for c in ws[1]: c.fill = fill; c.font = Font(bold=True, color="FFFFFF")
        out = io.BytesIO(); wb.save(out); out.seek(0); wb.close()
        return out.read()
    data = await asyncio.to_thread(make)
    return web.Response(body=data,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=sales_template.xlsx"})
