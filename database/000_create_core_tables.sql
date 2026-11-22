-- Базовая схема для новой установки. Существующие таблицы сохраняются.
CREATE TABLE IF NOT EXISTS citizenships (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS restaurants (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT, hours TEXT, phone TEXT, org TEXT,
    lat DOUBLE PRECISION, lon DOUBLE PRECISION,
    force_status TEXT, sort INTEGER NOT NULL DEFAULT 100,
    territory_manager_id BIGINT
);

CREATE TABLE IF NOT EXISTS users (
    user_id BIGSERIAL PRIMARY KEY,
    login TEXT UNIQUE,
    password_hash TEXT,
    full_name TEXT NOT NULL,
    phone TEXT, birth_date TEXT, position TEXT, restaurant_key TEXT,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    is_super_admin BOOLEAN NOT NULL DEFAULT FALSE,
    is_fired BOOLEAN NOT NULL DEFAULT FALSE,
    is_certified BOOLEAN NOT NULL DEFAULT FALSE,
    permissions JSONB NOT NULL DEFAULT '{}',
    medbook JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ, fired_at TIMESTAMPTZ, fired_by TEXT,
    hire_date TEXT,
    citizenship_id INTEGER REFERENCES citizenships(id),
    payment_type TEXT DEFAULT 'hourly',
    rate NUMERIC DEFAULT 0
);

CREATE TABLE IF NOT EXISTS web_sessions (
    token TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    last_used_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS timesheet_records (
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    work_date DATE NOT NULL,
    hours NUMERIC NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'work',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, work_date)
);

CREATE TABLE IF NOT EXISTS news (
    id SERIAL PRIMARY KEY, title TEXT NOT NULL, body TEXT,
    image_url TEXT, restaurant_key TEXT, status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS standards (
    id SERIAL PRIMARY KEY, title TEXT NOT NULL, body TEXT,
    category TEXT, file_url TEXT, restaurant_key TEXT, status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS faq (
    id SERIAL PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL,
    category TEXT, sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS questions (
    id SERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(user_id), text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), replied BOOLEAN NOT NULL DEFAULT FALSE,
    replied_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, is_archived BOOLEAN NOT NULL DEFAULT FALSE,
    sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS admin_audit (
    id BIGSERIAL PRIMARY KEY, admin_id BIGINT REFERENCES users(user_id), action TEXT NOT NULL,
    target_type TEXT, target_id TEXT, details TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS medbook_doctors (
    id SERIAL PRIMARY KEY, name TEXT NOT NULL, required BOOLEAN NOT NULL DEFAULT FALSE,
    validity_months INTEGER NOT NULL DEFAULT 12, sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS medbook_tests (
    id SERIAL PRIMARY KEY, name TEXT NOT NULL, required BOOLEAN NOT NULL DEFAULT FALSE,
    validity_months INTEGER NOT NULL DEFAULT 12, sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS medbook_vaccines (
    id SERIAL PRIMARY KEY, name TEXT NOT NULL, required BOOLEAN NOT NULL DEFAULT FALSE,
    validity_months INTEGER NOT NULL DEFAULT 12, sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS academy_courses (
    id SERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT, category TEXT,
    is_published BOOLEAN NOT NULL DEFAULT TRUE, sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS academy_lessons (
    id SERIAL PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES academy_courses(id) ON DELETE CASCADE,
    title TEXT NOT NULL, content TEXT, video_url TEXT, sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS academy_questions (
    id SERIAL PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES academy_courses(id) ON DELETE CASCADE,
    question TEXT NOT NULL, options JSONB NOT NULL, correct_index INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS academy_test_results (
    id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(user_id),
    course_id INTEGER NOT NULL REFERENCES academy_courses(id) ON DELETE CASCADE,
    correct_count INTEGER NOT NULL, total_count INTEGER NOT NULL, score_pct INTEGER NOT NULL,
    passed BOOLEAN NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS certification_questions (
    id SERIAL PRIMARY KEY, question TEXT NOT NULL, options JSONB NOT NULL, correct_index INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    subscription JSONB NOT NULL
);
