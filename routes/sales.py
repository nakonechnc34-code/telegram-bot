"""
Routes для дашборда Товарооборот.
Загрузка Excel/CSV файлов, аналитика, графики, агрегации.
"""

import io
import csv
import json
import os
from datetime import datetime, date, timedelta
from typing import Any

from aiohttp import web
import openpyxl

import db
from middleware.auth import require_admin
from utils.auth_helpers import get_current_user

routes = web.RouteTableDef()


# =============================================================================
# Загрузка файлов
# =============================================================================

@routes.post("/api/sales/upload")
@require_admin
async def upload_sales_file(request: web.Request) -> web.Response:
    """Загрузка Excel (.xlsx/.xls) или CSV файла с данными товарооборота."""
    reader = await request.post()
    admin_user = await get_current_user(request)
    if not admin_user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    file_upload = reader.get("file")
    if not file_upload or not file_upload.filename:
        return web.json_response({"error": "Файл не найден"}, status=400)

    restaurant_key = reader.get("restaurant_key")
    if not restaurant_key:
        return web.json_response({"error": "Укажите restaurant_key"}, status=400)

    # Проверка ресторана
    pool = db.get_pool(request.app)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT key FROM restaurants WHERE key = $1", restaurant_key)
        if not row:
            return web.json_response({"error": "Ресторан не найден"}, status=404)

    filename = file_upload.filename
    ext = os.path.splitext(filename)[1].lower()

    if ext not in (".xlsx", ".xls", ".csv"):
        return web.json_response({"error": "Поддерживаемые форматы: .xlsx, .xls, .csv"}, status=400)

    # Сохраняем файл
    uploads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads", "sales")
    os.makedirs(uploads_dir, exist_ok=True)

    file_path = os.path.join(uploads_dir, f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{filename}")
    data = await file_upload.read()

    with open(file_path, "wb") as f:
        f.write(data)

    # Создаём запись импорта
    async with pool.acquire() as conn:
        result = await conn.fetchrow(
            """
            INSERT INTO sales_imports (restaurant_key, filename, file_path, uploaded_by, status)
            VALUES ($1, $2, $3, $4, 'processing')
            RETURNING id
            """,
            restaurant_key, filename, file_path, admin_user.get("user_id")
        )
        import_id = result["id"]

    # Парсим файл в зависимости от формата
    try:
        if ext in (".xlsx", ".xls"):
            records = _parse_excel(io.BytesIO(data))
        else:
            text = data.decode("utf-8")
            records = _parse_csv(text)

        # Сохраняем записи
        await _save_sales_records(pool, import_id, restaurant_key, records)

        # Обновляем статус импорта
        await conn.execute(
            "UPDATE sales_imports SET status = 'completed', rows_count = $1, processed_at = NOW() WHERE id = $2",
            len(records), import_id
        )

        # Пересчитываем агрегации
        await _recalculate_daily_summary(pool, restaurant_key)

        return web.json_response({
            "success": True,
            "import_id": import_id,
            "rows_count": len(records),
            "message": f"Загружено {len(records)} записей"
        })

    except Exception as e:
        await conn.execute(
            "UPDATE sales_imports SET status = 'error', error_message = $1 WHERE id = $2",
            str(e)[:1000], import_id
        )
        return web.json_response({
            "error": f"Ошибка парсинга: {str(e)[:500]}",
            "import_id": import_id
        }, status=500)


# =============================================================================
# Парсеры
# =============================================================================

def _parse_excel(file_obj: io.BytesIO) -> list[dict]:
    """Парсит Excel файл. Ожидает колонки в первой строке (заголовки)."""
    wb = openpyxl.load_workbook(file_obj, read_only=True, data_only=True)
    ws = wb.active

    records = []
    headers = None

    for row_idx, row in enumerate(ws.iter_rows(), start=1):
        values = [cell.value for cell in row]
        if not any(v is not None for v in values):
            continue

        if headers is None:
            headers = [str(h).lower().strip() if h else "" for h in values]
            continue

        record = {}
        for i, val in enumerate(values):
            if i < len(headers):
                header = headers[i]
                if val is None:
                    record[header] = None
                elif header in ("quantity", "shift_number"):
                    record[header] = int(val) if val is not None else 0
                elif header in ("unit_price", "total_amount", "cost_amount",
                                "profit_amount", "discount_amount"):
                    record[header] = float(val) if val is not None else 0.0
                elif header in ("sale_date",):
                    if isinstance(val, datetime):
                        record[header] = val.date()
                    elif isinstance(val, date):
                        record[header] = val
                    else:
                        record[header] = val
                else:
                    record[header] = str(val) if val else None

        # Обязательные поля
        if "sale_date" in record and "total_amount" in record:
            record.setdefault("quantity", 1)
            record.setdefault("unit_price", record.get("total_amount", 0))
            record.setdefault("total_amount", 0)
            record.setdefault("category", None)
            record.setdefault("product_name", None)
            record.setdefault("payment_method", None)
            records.append(record)

    wb.close()
    return records


def _parse_csv(text: str) -> list[dict]:
    """Парсит CSV файл. Первая строка — заголовки."""
    reader = csv.DictReader(text.splitlines())
    records = []

    for row in reader:
        cleaned = {}
        for key, val in row.items():
            k = key.lower().strip() if key else ""
            if k:
                cleaned[k] = val.strip() if val else None

        if not cleaned:
            continue

        # Парсим числовые поля
        for num_field in ("quantity", "shift_number"):
            if num_field in cleaned and cleaned[num_field]:
                try:
                    cleaned[num_field] = int(cleaned[num_field])
                except (ValueError, TypeError):
                    cleaned[num_field] = 0

        for money_field in ("unit_price", "total_amount", "cost_amount",
                            "profit_amount", "discount_amount"):
            if money_field in cleaned and cleaned[money_field]:
                try:
                    cleaned[money_field] = float(cleaned[money_field].replace(",", "."))
                except (ValueError, TypeError):
                    cleaned[money_field] = 0.0

        # Парсим дату
        if "sale_date" in cleaned and cleaned["sale_date"]:
            for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    cleaned["sale_date"] = datetime.strptime(cleaned["sale_date"], fmt).date()
                    break
                except ValueError:
                    continue

        # Обязательные поля
        if "sale_date" in cleaned and "total_amount" in cleaned:
            cleaned.setdefault("quantity", 1)
            cleaned.setdefault("unit_price", cleaned.get("total_amount", 0))
            cleaned.setdefault("total_amount", 0)
            cleaned.setdefault("category", None)
            cleaned.setdefault("product_name", None)
            cleaned.setdefault("payment_method", None)
            records.append(cleaned)

    return records


async def _save_sales_records(pool, import_id: int, restaurant_key: str, records: list[dict]) -> None:
    """Сохраняет парсенные записи в БД."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            for rec in records:
                await conn.execute(
                    """
                    INSERT INTO sales_records (
                        import_id, restaurant_key, sale_date, category, subcategory,
                        product_name, sku, quantity, unit_price, total_amount,
                        cost_amount, profit_amount, profit_margin, payment_method,
                        shift_number, employee_name, discount_amount, extra_data
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
                    """,
                    import_id,
                    restaurant_key,
                    rec.get("sale_date"),
                    rec.get("category"),
                    rec.get("subcategory"),
                    rec.get("product_name"),
                    rec.get("sku"),
                    rec.get("quantity", 1),
                    rec.get("unit_price", 0),
                    rec.get("total_amount", 0),
                    rec.get("cost_amount", 0),
                    rec.get("profit_amount", 0),
                    rec.get("profit_margin"),
                    rec.get("payment_method"),
                    rec.get("shift_number"),
                    rec.get("employee_name"),
                    rec.get("discount_amount", 0),
                    json.dumps({k: v for k, v in rec.items() if k not in [
                        "sale_date", "category", "subcategory", "product_name",
                        "sku", "quantity", "unit_price", "total_amount",
                        "cost_amount", "profit_amount", "profit_margin",
                        "payment_method", "shift_number", "employee_name", "discount_amount"
                    ]}) if any(k not in [
                        "sale_date", "category", "subcategory", "product_name",
                        "sku", "quantity", "unit_price", "total_amount",
                        "cost_amount", "profit_amount", "profit_margin",
                        "payment_method", "shift_number", "employee_name", "discount_amount"
                    ] for k in rec) else None
                )


# =============================================================================
# Еодневная агрегация
# =============================================================================

async def _recalculate_daily_summary(pool, restaurant_key: str) -> None:
    """Пересчитывает дневные сводки для ресторана."""
    async with pool.acquire() as conn:
        # Удаляем старые сводки для ресторана
        await conn.execute(
            "DELETE FROM sales_daily_summary WHERE restaurant_key = $1", restaurant_key
        )

        # Пересчитываем все даты
        rows = await conn.fetch("""
            SELECT
                sale_date,
                SUM(total_amount) as total_sales,
                SUM(cost_amount) as total_cost,
                SUM(profit_amount) as total_profit,
                CASE WHEN SUM(total_amount) > 0
                    THEN ROUND(SUM(profit_amount) * 100.0 / NULLIF(SUM(total_amount), 0), 2)
                    ELSE 0 END as avg_margin,
                SUM(quantity) as total_items_sold,
                COUNT(DISTINCT id) as total_transactions,
                SUM(CASE WHEN payment_method = 'Наличные' OR payment_method = 'cash' THEN total_amount ELSE 0 END) as cash_sales,
                SUM(CASE WHEN payment_method = 'Карта' OR payment_method = 'card' THEN total_amount ELSE 0 END) as card_sales,
                SUM(CASE WHEN payment_method = 'Онлайн' OR payment_method = 'online' THEN total_amount ELSE 0 END) as online_sales,
                COUNT(DISTINCT category) as unique_categories,
                COUNT(DISTINCT product_name) as unique_products
            FROM sales_records
            WHERE restaurant_key = $1
            GROUP BY sale_date
            ORDER BY sale_date
        """, restaurant_key)

        for row in rows:
            total_sales = float(row["total_sales"] or 0)
            avg_check = round(total_sales / row["total_items_sold"], 2) if row["total_items_sold"] and row["total_items_sold"] > 0 else 0

            await conn.execute(
                """
                INSERT INTO sales_daily_summary (
                    restaurant_key, summary_date, total_sales, total_cost, total_profit,
                    avg_margin, total_items_sold, total_transactions, avg_check,
                    cash_sales, card_sales, online_sales, unique_products
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                restaurant_key,
                row["sale_date"],
                total_sales,
                float(row["total_cost"] or 0),
                float(row["total_profit"] or 0),
                float(row["avg_margin"] or 0),
                row["total_items_sold"] or 0,
                row["total_transactions"] or 0,
                avg_check,
                float(row["cash_sales"] or 0),
                float(row["card_sales"] or 0),
                float(row["online_sales"] or 0),
                row["unique_products"] or 0
            )


# =============================================================================
# API: Дашборд — общая сводка
# =============================================================================

@routes.post("/api/sales/dashboard")
@require_admin
async def sales_dashboard(request: web.Request) -> web.Response:
    """Основная сводка дашборда товарооборота."""
    admin_user = await get_current_user(request)
    if not admin_user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    period = request.json.get("period", "30d")  # 7d, 30d, 90d, custom
    restaurant_key = request.json.get("restaurant_key")  # None = все рестораны

    pool = db.get_pool(request.app)
    results = {}

    async with pool.acquire() as conn:
        if restaurant_key:
            date_filter = f"WHERE sr.restaurant_key = '{restaurant_key}'"
            summary_filter = f"WHERE sds.restaurant_key = '{restaurant_key}'"
        else:
            date_filter = ""
            summary_filter = ""

        # Определяем date range
        days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 30)
        date_from = (datetime.utcnow().date() - timedelta(days=days)).isoformat()

        # Общие метрики
        total_sales = await conn.fetchval(
            f"SELECT COALESCE(SUM(total_amount), 0) FROM sales_records sr {date_filter} AND sr.sale_date >= '{date_from}'",
        )
        total_cost = await conn.fetchval(
            f"SELECT COALESCE(SUM(cost_amount), 0) FROM sales_records sr {date_filter} AND sr.sale_date >= '{date_from}'",
        )
        total_profit = await conn.fetchval(
            f"SELECT COALESCE(SUM(profit_amount), 0) FROM sales_records sr {date_filter} AND sr.sale_date >= '{date_from}'",
        )
        total_items = await conn.fetchval(
            f"SELECT COALESCE(SUM(quantity), 0) FROM sales_records sr {date_filter} AND sr.sale_date >= '{date_from}'",
        )

        margin = round(float(total_profit) * 100 / max(float(total_sales), 1), 2) if float(total_sales) > 0 else 0

        results["overview"] = {
            "total_sales": float(total_sales or 0),
            "total_cost": float(total_cost or 0),
            "total_profit": float(total_profit or 0),
            "avg_margin": margin,
            "total_items_sold": int(total_items or 0),
            "period_days": days
        }

        # Динамика по дням (для графика)
        daily_trend = await conn.fetch(f"""
            SELECT
                sale_date,
                SUM(total_amount) as daily_sales,
                SUM(cost_amount) as daily_cost,
                SUM(profit_amount) as daily_profit,
                SUM(quantity) as daily_items
            FROM sales_records
            {date_filter} AND sale_date >= '{date_from}'
            GROUP BY sale_date
            ORDER BY sale_date
        """)

        results["daily_trend"] = [
            {
                "date": str(r["sale_date"]),
                "sales": float(r["daily_sales"] or 0),
                "cost": float(r["daily_cost"] or 0),
                "profit": float(r["daily_profit"] or 0),
                "items": int(r["daily_items"] or 0)
            }
            for r in daily_trend
        ]

        # Выручка по ресторанам
        restaurant_sales = await conn.fetch(f"""
            SELECT
                r.name,
                r.key,
                COALESCE(SUM(sr.total_amount), 0) as total,
                COALESCE(SUM(sr.profit_amount), 0) as profit
            FROM restaurants r
            LEFT JOIN sales_records sr ON sr.restaurant_key = r.key {date_filter}
            GROUP BY r.key, r.name
            ORDER BY total DESC
        """)

        results["by_restaurant"] = [
            {
                "key": r["key"],
                "name": r["name"],
                "total_sales": float(r["total"] or 0),
                "profit": float(r["profit"] or 0)
            }
            for r in restaurant_sales
        ]

        # Топ-10 товаров
        top_products = await conn.fetch(f"""
            SELECT
                product_name,
                SUM(quantity) as qty,
                SUM(total_amount) as total
            FROM sales_records
            {date_filter} AND product_name IS NOT NULL
            GROUP BY product_name
            ORDER BY total DESC
            LIMIT 10
        """)

        results["top_products"] = [
            {
                "name": r["product_name"],
                "quantity": int(r["qty"] or 0),
                "total_sales": float(r["total"] or 0)
            }
            for r in top_products if r["product_name"]
        ]

        # Выручка по категориям
        by_category = await conn.fetch(f"""
            SELECT
                COALESCE(category, 'Без категории') as cat,
                COUNT(*) as count,
                SUM(total_amount) as total,
                SUM(profit_amount) as profit
            FROM sales_records
            {date_filter}
            GROUP BY category
            ORDER BY total DESC
        """)

        results["by_category"] = [
            {
                "category": r["cat"],
                "count": int(r["count"] or 0),
                "total_sales": float(r["total"] or 0),
                "profit": float(r["profit"] or 0)
            }
            for r in by_category
        ]

        # Способы оплаты
        by_payment = await conn.fetch(f"""
            SELECT
                COALESCE(payment_method, 'Не указан') as method,
                SUM(total_amount) as total,
                COUNT(*) as count
            FROM sales_records
            {date_filter}
            GROUP BY payment_method
            ORDER BY total DESC
        """)

        results["by_payment"] = [
            {
                "method": r["method"],
                "total_sales": float(r["total"] or 0),
                "count": int(r["count"] or 0)
            }
            for r in by_payment
        ]

        # Пиковые часы (агрегация по часам)
        peak_hours = await conn.fetch(f"""
            SELECT
                EXTRACT(HOUR FROM sale_date::timestamp) as hour,
                SUM(total_amount) as total,
                COUNT(*) as transactions
            FROM sales_records
            {date_filter}
            GROUP BY hour
            ORDER BY total DESC
            LIMIT 5
        """)

        results["peak_hours"] = [
            {
                "hour": int(r["hour"]),
                "total_sales": float(r["total"] or 0),
                "transactions": int(r["transactions"] or 0)
            }
            for r in peak_hours
        ]

        # Ежедневные сводки (для детального просмотра)
        daily_summaries = await conn.fetch(f"""
            SELECT * FROM sales_daily_summary
            {summary_filter.replace('WHERE', 'WHERE').strip()} AND summary_date >= '{date_from}'
            ORDER BY summary_date DESC
            LIMIT 30
        """)

        results["daily_summaries"] = [
            {
                "date": str(s["summary_date"]),
                "total_sales": float(s["total_sales"] or 0),
                "total_cost": float(s["total_cost"] or 0),
                "total_profit": float(s["total_profit"] or 0),
                "avg_margin": float(s["avg_margin"] or 0),
                "items_sold": int(s["total_items_sold"] or 0),
                "transactions": int(s["total_transactions"] or 0),
                "avg_check": float(s["avg_check"] or 0),
                "cash_sales": float(s["cash_sales"] or 0),
                "card_sales": float(s["card_sales"] or 0),
                "online_sales": float(s["online_sales"] or 0),
                "unique_products": int(s["unique_products"] or 0)
            }
            for s in daily_summaries
        ]

        # Загруженные файлы
        imports = await conn.fetch(f"""
            SELECT si.*, u.full_name as uploader_name
            FROM sales_imports si
            LEFT JOIN users u ON u.user_id = si.uploaded_by
            {date_filter.replace('', 'AND sr.restaurant_key = si.restaurant_key')}
            ORDER BY si.upload_date DESC
            LIMIT 20
        """)

        results["imports"] = [
            {
                "id": i["id"],
                "filename": i["filename"],
                "restaurant_key": i["restaurant_key"],
                "upload_date": str(i["upload_date"]),
                "rows_count": int(i["rows_count"] or 0),
                "status": i["status"],
                "error_message": i["error_message"],
                "uploader_name": i["uploader_name"]
            }
            for i in imports
        ]

    return web.json_response({"success": True, "data": results})


# =============================================================================
# API: Детализация по транзакциям
# =============================================================================

@routes.post("/api/sales/records")
@require_admin
async def sales_records(request: web.Request) -> web.Response:
    """Получение списка транзакций с пагинацией и фильтрами."""
    admin_user = await get_current_user(request)
    if not admin_user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    body = request.json or {}
    restaurant_key = body.get("restaurant_key")
    date_from = body.get("date_from")
    date_to = body.get("date_to")
    category = body.get("category")
    product_name = body.get("product_name")
    page = body.get("page", 1)
    limit = body.get("limit", 100)

    pool = db.get_pool(request.app)
    conditions = []
    params = []
    param_idx = 1

    if restaurant_key:
        conditions.append(f"sr.restaurant_key = ${param_idx}")
        params.append(restaurant_key)
        param_idx += 1

    if date_from:
        conditions.append(f"sr.sale_date >= ${param_idx}")
        params.append(date_from)
        param_idx += 1

    if date_to:
        conditions.append(f"sr.sale_date <= ${param_idx}")
        params.append(date_to)
        param_idx += 1

    if category:
        conditions.append(f"sr.category ILIKE ${param_idx}")
        params.append(f"%{category}%")
        param_idx += 1

    if product_name:
        conditions.append(f"sr.product_name ILIKE ${param_idx}")
        params.append(f"%{product_name}%")
        param_idx += 1

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    offset = (page - 1) * limit

    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM sales_records sr {where_clause}", *params
        )

        records = await conn.fetch(f"""
            SELECT sr.*, r.name as restaurant_name
            FROM sales_records sr
            LEFT JOIN restaurants r ON r.key = sr.restaurant_key
            {where_clause}
            ORDER BY sr.sale_date DESC, sr.id DESC
            LIMIT ${{param_idx}} OFFSET ${{param_idx + 1}}
        ", *params, limit, offset)

        return web.json_response({
            "success": True,
            "data": {
                "records": [
                    {
                        "id": r["id"],
                        "restaurant_key": r["restaurant_key"],
                        "restaurant_name": r["restaurant_name"],
                        "sale_date": str(r["sale_date"]),
                        "category": r["category"],
                        "subcategory": r["subcategory"],
                        "product_name": r["product_name"],
                        "sku": r["sku"],
                        "quantity": int(r["quantity"] or 0),
                        "unit_price": float(r["unit_price"] or 0),
                        "total_amount": float(r["total_amount"] or 0),
                        "cost_amount": float(r["cost_amount"] or 0),
                        "profit_amount": float(r["profit_amount"] or 0),
                        "profit_margin": float(r["profit_margin"] or 0),
                        "payment_method": r["payment_method"],
                        "shift_number": int(r["shift_number"] or 0),
                        "employee_name": r["employee_name"],
                        "discount_amount": float(r["discount_amount"] or 0)
                    }
                    for r in records
                ],
                "total": total,
                "page": page,
                "limit": limit,
                "pages": (total + limit - 1) // limit if limit > 0 else 1
            }
        })


# =============================================================================
# API: Список ресторанов для товарооборота
# =============================================================================

@routes.post("/api/sales/restaurants")
@require_admin
async def sales_restaurants(request: web.Request) -> web.Response:
    """Получение списка ресторанов с метриками товарооборота."""
    admin_user = await get_current_user(request)
    if not admin_user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    pool = db.get_pool(request.app)

    async with pool.acquire() as conn:
        restaurants = await conn.fetch("""
            SELECT
                r.key,
                r.name,
                r.address,
                (SELECT COUNT(*) FROM sales_records sr WHERE sr.restaurant_key = r.key) as total_records,
                (SELECT COALESCE(SUM(total_amount), 0) FROM sales_records sr WHERE sr.restaurant_key = r.key) as total_sales,
                (SELECT MAX(sale_date) FROM sales_records sr WHERE sr.restaurant_key = r.key) as last_sale_date
            FROM restaurants r
            ORDER BY r.sort NULLS FIRST, r.name
        """)

        return web.json_response({
            "success": True,
            "data": [
                {
                    "key": r["key"],
                    "name": r["name"],
                    "address": r["address"],
                    "total_records": int(r["total_records"] or 0),
                    "total_sales": float(r["total_sales"] or 0),
                    "last_sale_date": str(r["last_sale_date"]) if r["last_sale_date"] else None
                }
                for r in restaurants
            ]
        })


# =============================================================================
# API: Экспорт данных
# =============================================================================

@routes.post("/api/sales/export")
@require_admin
async def export_sales_data(request: web.Request) -> web.Response:
    """Экспорт данных товарооборота в Excel."""
    admin_user = await get_current_user(request)
    if not admin_user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    body = request.json or {}
    restaurant_key = body.get("restaurant_key")
    date_from = body.get("date_from")
    date_to = body.get("date_to")

    pool = db.get_pool(request.app)
    conditions = []
    params = []

    if restaurant_key:
        conditions.append(f"sr.restaurant_key = '{restaurant_key}'")
    if date_from:
        conditions.append(f"sr.sale_date >= '{date_from}'")
    if date_to:
        conditions.append(f"sr.sale_date <= '{date_to}'")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with pool.acquire() as conn:
        records = await conn.fetch(f"""
            SELECT
                sr.sale_date,
                sr.restaurant_key,
                r.name as restaurant_name,
                sr.category,
                sr.product_name,
                sr.quantity,
                sr.unit_price,
                sr.total_amount,
                sr.cost_amount,
                sr.profit_amount,
                sr.payment_method,
                sr.employee_name
            FROM sales_records sr
            LEFT JOIN restaurants r ON r.key = sr.restaurant_key
            {where_clause}
            ORDER BY sr.sale_date DESC
        """)

    # Создаём Excel файл
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Товарооборот"

    # Заголовки
    headers = [
        "Дата", "Ресторан", "Ключ", "Категория", "Товар", "Кол-во",
        "Цена", "Сумма", "Себестоимость", "Прибыль", "Оплата", "Сотрудник"
    ]
    ws.append(headers)

    # Стилизуем заголовки
    from openpyxl.styles import Font, PatternFill
    header_fill = PatternFill(start_color="667eea", end_color="667eea", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font

    for r in records:
        ws.append([
            r["sale_date"],
            r["restaurant_name"],
            r["restaurant_key"],
            r["category"],
            r["product_name"],
            r["quantity"],
            r["unit_price"],
            r["total_amount"],
            r["cost_amount"],
            r["profit_amount"],
            r["payment_method"],
            r["employee_name"]
        ])

    # Автоширина колонок
    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except (ValueError, TypeError):
                pass
        ws.column_dimensions[column].width = min(max_length + 4, 40)

    # Сохраняем в память
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    wb.close()

    filename = f"sales_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return web.Response(
        body=output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# =============================================================================
# API: Шаблоны для загрузки
# =============================================================================

@routes.get("/api/sales/template")
@require_admin
async def sales_template(request: web.Request) -> web.Response:
    """Скачивание шаблона Excel для загрузки данных товарооборота."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Шаблон"

    headers = [
        "sale_date", "restaurant_key", "category", "subcategory",
        "product_name", "sku", "quantity", "unit_price", "total_amount",
        "cost_amount", "profit_amount", "profit_margin",
        "payment_method", "shift_number", "employee_name", "discount_amount"
    ]
    ws.append(headers)

    # Пример данных
    ws.append([
        "2026-11-20", "restaurant_1", "Напитки", "Кофе",
        "Капучино 300мл", "SKU001", 15, 250, 3750,
        1200, 2550, 68.0,
        "Карта", 1, "Иванов И.И.", 0
    ])
    ws.append([
        "2026-11-20", "restaurant_1", "Еда", "Бургеры",
        "Чизбургер", "SKU002", 8, 350, 2800,
        1400, 1400, 50.0,
        "Наличные", 1, "Петров П.П.", 50
    ])

    from openpyxl.styles import Font, PatternFill
    header_fill = PatternFill(start_color="667eea", end_color="667eea", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    example_fill = PatternFill(start_color="f0f0ff", end_color="f0f0ff", fill_type="solid")
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
    for cell in ws[2]:
        cell.fill = example_fill

    for cell in ws[3]:
        cell.fill = example_fill

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    wb.close()

    return web.Response(
        body=output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=sales_template.xlsx"}
    )
