CREATE TABLE IF NOT EXISTS control_documents (
 id BIGSERIAL PRIMARY KEY,
 category TEXT NOT NULL,
 restaurant_key TEXT REFERENCES restaurants(key),
 created_by BIGINT NOT NULL REFERENCES users(user_id),
 archived BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS control_document_versions (
 id BIGSERIAL PRIMARY KEY,
 document_id BIGINT NOT NULL REFERENCES control_documents(id),
 version INTEGER NOT NULL CHECK(version>0),
 title TEXT NOT NULL,
 content TEXT NOT NULL,
 published_by BIGINT NOT NULL REFERENCES users(user_id),
 published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(document_id,version)
);
CREATE TABLE IF NOT EXISTS control_acknowledgements (
 version_id BIGINT NOT NULL REFERENCES control_document_versions(id),
 user_id BIGINT NOT NULL REFERENCES users(user_id),
 acknowledged_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY(version_id,user_id)
);
