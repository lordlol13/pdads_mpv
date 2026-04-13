CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    location TEXT,
    interests JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    password_hash TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    country_code VARCHAR(8),
    region_code VARCHAR(16),
    embedding_vector JSONB,
    embedding_model TEXT,
    embedding_updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS registration_verifications (
    id TEXT PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    email TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    verification_code_hash TEXT NOT NULL,
    code_expires_at TIMESTAMPTZ NOT NULL,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consumed_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_registration_verifications_email
    ON registration_verifications (email);

CREATE TABLE IF NOT EXISTS password_reset_requests (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    used_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_password_reset_requests_email
    ON password_reset_requests (email);

CREATE TABLE IF NOT EXISTS raw_news (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    source_url TEXT,
    image_url TEXT,
    raw_text TEXT,
    category TEXT,
    region TEXT,
    is_urgent BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    process_status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_raw_news_status ON raw_news(process_status);
CREATE INDEX IF NOT EXISTS idx_raw_news_created ON raw_news(created_at);
CREATE INDEX IF NOT EXISTS idx_raw_news_category ON raw_news(category);
CREATE INDEX IF NOT EXISTS idx_raw_news_region ON raw_news(region);

CREATE TABLE IF NOT EXISTS ai_news (
    id BIGSERIAL PRIMARY KEY,
    raw_news_id BIGINT NOT NULL REFERENCES raw_news(id) ON DELETE CASCADE,
    target_persona TEXT NOT NULL,
    final_title TEXT NOT NULL,
    final_text TEXT NOT NULL,
    image_urls TEXT[] NULL,
    video_urls TEXT[] NULL,
    category TEXT,
    ai_score DOUBLE PRECISION,
    embedding_id BIGINT,
    embedding_vector JSONB,
    embedding_model TEXT,
    embedding_updated_at TIMESTAMPTZ,
    vector_status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_news_persona ON ai_news(target_persona);
CREATE INDEX IF NOT EXISTS idx_ai_news_created ON ai_news(created_at);

CREATE TABLE IF NOT EXISTS user_feed (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ai_news_id BIGINT NOT NULL REFERENCES ai_news(id) ON DELETE CASCADE,
    ai_score DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, ai_news_id)
);

CREATE INDEX IF NOT EXISTS idx_user_feed_user_id ON user_feed(user_id);
CREATE INDEX IF NOT EXISTS idx_user_feed_ai_news_id ON user_feed(ai_news_id);

CREATE TABLE IF NOT EXISTS interactions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ai_news_id BIGINT NOT NULL REFERENCES ai_news(id) ON DELETE CASCADE,
    liked BOOLEAN,
    viewed BOOLEAN,
    saved BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interactions_user_id ON interactions(user_id);
CREATE INDEX IF NOT EXISTS idx_interactions_ai_news_id ON interactions(ai_news_id);

CREATE TABLE IF NOT EXISTS feed_comments (
    id BIGSERIAL PRIMARY KEY,
    ai_news_id BIGINT NOT NULL REFERENCES ai_news(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    parent_comment_id BIGINT NULL REFERENCES feed_comments(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feed_comments_ai_news_created ON feed_comments(ai_news_id, created_at);
CREATE INDEX IF NOT EXISTS idx_feed_comments_parent ON feed_comments(parent_comment_id);

CREATE TABLE IF NOT EXISTS feed_comment_likes (
    id BIGSERIAL PRIMARY KEY,
    comment_id BIGINT NOT NULL REFERENCES feed_comments(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(comment_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_feed_comment_likes_comment ON feed_comment_likes(comment_id);

CREATE TABLE IF NOT EXISTS saved_news (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ai_news_id BIGINT NOT NULL REFERENCES ai_news(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, ai_news_id)
);

CREATE INDEX IF NOT EXISTS idx_saved_news_user_created ON saved_news(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS feed_feature_log (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    ai_news_id BIGINT NOT NULL,
    reason TEXT NOT NULL,
    feature_value DOUBLE PRECISION,
    rank_position INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
