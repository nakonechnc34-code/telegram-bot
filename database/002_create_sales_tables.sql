-- Миграция: создание таблиц для дашборда Товарооборот
-- Дата: 2026-11-21

-- Таблица загруженных файлов товарооборота
CREATE TABLE IF NOT EXISTS sales_imports (
    id SERIAL PRIMARY KEY,
    restaurant_key TEXT NOT NULL REFERENCES restaurants(key),
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    upload_date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    uploaded_by BIGINT REFERENCES users(user_id),
    rows_count INT DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'processing',  -- processing, completed, error
    error_message TEXT,
    processed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sales_imports_restaurant ON sales_imports(restaurant_key);
CREATE INDEX IF NOT EXISTS idx_sales_imports_upload_date ON sales_imports(upload_date);
CREATE INDEX IF NOT EXISTS idx_sales_imports_status ON sales_imports(status);

-- Таблица строк товарооборота (сырые данные из загруженных файлов)
CREATE TABLE IF NOT EXISTS sales_records (
    id SERIAL PRIMARY KEY,
    import_id INT NOT NULL REFERENCES sales_imports(id) ON DELETE CASCADE,
    restaurant_key TEXT NOT NULL REFERENCES restaurants(key),
    
    -- Дата операции
    sale_date DATE NOT NULL,
    
    -- Категории и позиции
    category TEXT,              -- Категория товара (напитки, еда, десерты и т.д.)
    subcategory TEXT,           -- Подкатегория
    product_name TEXT,          -- Название товара
    sku TEXT,                   -- Артикул / SKU
    
    -- Количество и цены
    quantity INT NOT NULL DEFAULT 0,
    unit_price NUMERIC(10,2) NOT NULL DEFAULT 0,
    total_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
    
    -- Себестоимость и прибыль
    cost_amount NUMERIC(12,2) DEFAULT 0,
    profit_amount NUMERIC(12,2) DEFAULT 0,
    profit_margin NUMERIC(5,2), -- Процент маржи в %
    
    -- Способы оплаты
    payment_method TEXT,        -- Наличные, карта, онлайн, перевод
    shift_number INT,           -- Номер смены
    
    -- Дополнительная информация
    employee_name TEXT,         -- Квалифицирующий сотрудник
    discount_amount NUMERIC(10,2) DEFAULT 0,
    extra_data JSONB,           -- Произвольные дополнительные данные
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sales_records_import ON sales_records(import_id);
CREATE INDEX IF NOT EXISTS idx_sales_records_restaurant ON sales_records(restaurant_key);
CREATE INDEX IF NOT EXISTS idx_sales_records_date ON sales_records(sale_date);
CREATE INDEX IF NOT EXISTS idx_sales_records_category ON sales_records(category);
CREATE INDEX IF NOT EXISTS idx_sales_records_product ON sales_records(product_name);
CREATE INDEX IF NOT EXISTS idx_sales_records_payment ON sales_records(payment_method);

-- Таблица дневных сводок (агрегированные данные для быстрого отображения)
CREATE TABLE IF NOT EXISTS sales_daily_summary (
    id SERIAL PRIMARY KEY,
    restaurant_key TEXT NOT NULL REFERENCES restaurants(key),
    summary_date DATE NOT NULL,
    
    -- Основные метрики
    total_sales NUMERIC(12,2) DEFAULT 0,
    total_cost NUMERIC(12,2) DEFAULT 0,
    total_profit NUMERIC(12,2) DEFAULT 0,
    avg_margin NUMERIC(5,2),
    total_items_sold INT DEFAULT 0,
    total_transactions INT DEFAULT 0,
    avg_check NUMERIC(10,2),
    
    -- По способам оплаты
    cash_sales NUMERIC(12,2) DEFAULT 0,
    card_sales NUMERIC(12,2) DEFAULT 0,
    online_sales NUMERIC(12,2) DEFAULT 0,
    
    -- Пиковые метрики
    peak_hour INT,            -- Час с максимальной выручкой
    peak_hour_sales NUMERIC(12,2),
    
    -- Статистика
    unique_products INT DEFAULT 0,
    top_category TEXT,
    top_product TEXT,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(restaurant_key, summary_date)
);

CREATE INDEX IF NOT EXISTS idx_sales_daily_restaurant ON sales_daily_summary(restaurant_key, summary_date);
CREATE INDEX IF NOT EXISTS idx_sales_daily_date ON sales_daily_summary(summary_date);

-- Таблица целей и планов продаж
CREATE TABLE IF NOT EXISTS sales_targets (
    id SERIAL PRIMARY KEY,
    restaurant_key TEXT NOT NULL REFERENCES restaurants(key),
    target_date DATE NOT NULL,
    target_type TEXT NOT NULL,  -- daily, weekly, monthly
    
    target_amount NUMERIC(12,2) NOT NULL,
    actual_amount NUMERIC(12,2) DEFAULT 0,
    achievement_pct NUMERIC(5,2),
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(restaurant_key, target_date, target_type)
);

CREATE INDEX IF NOT EXISTS idx_sales_targets_restaurant ON sales_targets(restaurant_key);
CREATE INDEX IF NOT EXISTS idx_sales_targets_date ON sales_targets(target_date);
