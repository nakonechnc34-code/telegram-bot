-- Reject identical files in progress or already imported. Existing rows have NULL hashes.
ALTER TABLE sales_imports ADD COLUMN IF NOT EXISTS file_hash TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_imports_active_file_hash
    ON sales_imports(file_hash)
    WHERE file_hash IS NOT NULL AND status IN ('processing', 'completed');
