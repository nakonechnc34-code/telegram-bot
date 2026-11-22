-- Bring pre-existing production tables up to the schema expected by content.py.
-- Additive and repeatable: no table drops, no destructive rewrites.
ALTER TABLE news ADD COLUMN IF NOT EXISTS restaurant_key TEXT;
ALTER TABLE standards ADD COLUMN IF NOT EXISTS restaurant_key TEXT;
-- Legacy production standards table may predate the category column.
ALTER TABLE standards ADD COLUMN IF NOT EXISTS category TEXT;
-- Existing group_name values represent the same category in the current API.
UPDATE standards SET category = group_name
WHERE category IS NULL AND group_name IS NOT NULL;

ALTER TABLE certification_questions ADD COLUMN IF NOT EXISTS options JSONB;
ALTER TABLE certification_questions ADD COLUMN IF NOT EXISTS correct_index INTEGER;

-- Preserve answers stored in the legacy option_a..option_d layout, when present.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'certification_questions' AND column_name = 'option_a'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'certification_questions' AND column_name = 'option_b'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'certification_questions' AND column_name = 'option_c'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'certification_questions' AND column_name = 'option_d'
    ) THEN
        EXECUTE '
            UPDATE certification_questions
            SET options = jsonb_build_array(option_a, option_b, option_c, option_d)
            WHERE options IS NULL
        ';
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'certification_questions' AND column_name = 'correct_option'
    ) THEN
        EXECUTE '
            UPDATE certification_questions
            SET correct_index = CASE lower(correct_option::text)
                WHEN ''a'' THEN 0 WHEN ''b'' THEN 1
                WHEN ''c'' THEN 2 WHEN ''d'' THEN 3
                ELSE 0 END
            WHERE correct_index IS NULL
        ';
    END IF;
END $$;

UPDATE certification_questions SET options = '[]'::jsonb WHERE options IS NULL;
UPDATE certification_questions SET correct_index = 0 WHERE correct_index IS NULL;
ALTER TABLE certification_questions ALTER COLUMN options SET DEFAULT '[]'::jsonb;
ALTER TABLE certification_questions ALTER COLUMN correct_index SET DEFAULT 0;
