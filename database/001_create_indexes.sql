-- ============================================
-- Wokker Bot — SQL скрипт для создания индексов
-- ============================================
-- Запуск: psql -d wokker_db -f 001_create_indexes.sql

-- Индекс для быстрого поиска сессии по токену
CREATE INDEX IF NOT EXISTS idx_web_sessions_token ON web_sessions(token);

-- Индекс для быстрого поиска пользователей по логину (case-insensitive)
CREATE INDEX IF NOT EXISTS idx_users_login ON users(LOWER(login));

-- Индекс для табеля: поиск записей по сотруднику и дате
CREATE INDEX IF NOT EXISTS idx_timesheet_records_date ON timesheet_records(user_id, work_date);

-- Индекс для новостей: фильтрация по статусу
CREATE INDEX IF NOT EXISTS idx_news_status ON news(status);

-- Индекс для стандартов: фильтрация по статусу
CREATE INDEX IF NOT EXISTS idx_standards_status ON standards(status);

-- Индекс для выплат: поиск по дате и статусу
DO $migration$ BEGIN
    IF to_regclass('payments') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date, status);
        CREATE INDEX IF NOT EXISTS idx_payments_user_date ON payments(user_id, payment_date);
    END IF;
END $migration$;

-- Индекс для вопросов: поиск по replied
CREATE INDEX IF NOT EXISTS idx_questions_replied ON questions(replied);

-- Индекс для academy_progress: поиск по user_id и course_id
DO $migration$ BEGIN
    IF to_regclass('academy_progress') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS idx_academy_progress_user_course ON academy_progress(user_id, course_id);
    END IF;
END $migration$;
