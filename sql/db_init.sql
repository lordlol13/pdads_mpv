CREATE TABLE IF NOT EXISTS users (
	id SERIAL PRIMARY KEY,
	username VARCHAR(100) NOT NULL,
	location VARCHAR(255),
	interests JSONB DEFAULT '{}'::jsonb,
	created_at TIMESTAMPTZ DEFAULT NOW(),
	email TEXT NOT NULL UNIQUE,
	password_hash TEXT NOT NULL,
	is_active BOOLEAN DEFAULT TRUE,
	is_verified BOOLEAN DEFAULT FALSE,
	country_code VARCHAR(8),
	region_code VARCHAR(32),
	updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raw_news (
	id SERIAL PRIMARY KEY,
	title VARCHAR(500) NOT NULL,
	source_url TEXT,
	raw_text TEXT,
	category VARCHAR(100),
	region VARCHAR(100),
	is_urgent BOOLEAN DEFAULT FALSE,
	created_at TIMESTAMPTZ DEFAULT NOW(),
	process_status VARCHAR(32) DEFAULT 'pending',
	error_message TEXT,
	attempt_count INTEGER DEFAULT 0,
	content_hash VARCHAR(64) NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_raw_news_status_created_at
	ON raw_news (process_status, created_at DESC);

CREATE TABLE IF NOT EXISTS ai_news (
	id SERIAL PRIMARY KEY,
	raw_news_id INTEGER NOT NULL REFERENCES raw_news(id) ON DELETE CASCADE,
	target_persona VARCHAR(100) NOT NULL,
	final_title VARCHAR(500) NOT NULL,
	final_text TEXT NOT NULL,
	image_urls TEXT[] DEFAULT ARRAY[]::TEXT[],
	category VARCHAR(100),
	ai_score NUMERIC,
	created_at TIMESTAMPTZ DEFAULT NOW(),
	embedding_id VARCHAR(255),
	vector_status VARCHAR(32) DEFAULT 'pending',
	UNIQUE (raw_news_id, target_persona)
);

CREATE INDEX IF NOT EXISTS idx_ai_news_created_at
	ON ai_news (created_at DESC);

CREATE TABLE IF NOT EXISTS user_feed (
	id SERIAL PRIMARY KEY,
	user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
	ai_news_id INTEGER NOT NULL REFERENCES ai_news(id) ON DELETE CASCADE,
	ai_score NUMERIC,
	created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_feed_user_score
	ON user_feed (user_id, ai_score DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS interactions (
	id SERIAL PRIMARY KEY,
	user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
	ai_news_id INTEGER NOT NULL REFERENCES ai_news(id) ON DELETE CASCADE,
	liked BOOLEAN,
	viewed BOOLEAN,
	watch_time INTEGER,
	created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interactions_user_news_created
	ON interactions (user_id, ai_news_id, created_at DESC);

CREATE TABLE IF NOT EXISTS feed_feature_log (
	id BIGSERIAL PRIMARY KEY,
	user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
	ai_news_id INTEGER NOT NULL REFERENCES ai_news(id) ON DELETE CASCADE,
	reason VARCHAR(255),
	feature_value NUMERIC,
	rank_position INTEGER,
	created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feed_feature_log_user_created
	ON feed_feature_log (user_id, created_at DESC);
