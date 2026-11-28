CREATE TABLE IF NOT EXISTS timesheet_kol_plans (
    restaurant_key TEXT NOT NULL REFERENCES restaurants(key),
    effective_from DATE NOT NULL,
    percentage NUMERIC(7,4) NOT NULL CHECK (percentage BETWEEN 0 AND 100),
    created_by BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (restaurant_key, effective_from)
);

CREATE TABLE IF NOT EXISTS timesheet_kol_payment_locations (
    payment_id INTEGER PRIMARY KEY REFERENCES payments(id) ON DELETE CASCADE,
    restaurant_key TEXT NOT NULL REFERENCES restaurants(key),
    created_by BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason TEXT NOT NULL CHECK (length(trim(reason)) BETWEEN 1 AND 1000)
);
