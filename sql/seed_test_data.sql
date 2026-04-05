INSERT INTO users (
	username,
	location,
	interests,
	created_at,
	email,
	password_hash,
	is_active,
	is_verified,
	country_code,
	region_code,
	updated_at
)
VALUES (
	'demo',
	'Global',
	'{"topics": ["business", "technology"]}'::jsonb,
	NOW(),
	'demo@example.com',
	'700df07311d0db1ba781b03dda662de1$UoHTXeEdZ63lHgGGEkbwMwm74I-UwKuW9Mn80zP_FCQ',
	TRUE,
	TRUE,
	'US',
	'NA',
	NOW()
)
ON CONFLICT (email) DO NOTHING;

INSERT INTO raw_news (
	title,
	source_url,
	raw_text,
	category,
	region,
	is_urgent,
	created_at,
	process_status,
	error_message,
	attempt_count,
	content_hash
)
VALUES (
	'Global Markets React to Inflation Data',
	'https://example.com/news/inflation-markets',
	'Stock indices moved after latest inflation numbers were published.',
	'business',
	'global',
	FALSE,
	NOW(),
	'pending',
	NULL,
	0,
	'seed-raw-news-001'
)
ON CONFLICT (content_hash) DO NOTHING;

INSERT INTO raw_news (
	title,
	source_url,
	raw_text,
	category,
	region,
	is_urgent,
	created_at,
	process_status,
	error_message,
	attempt_count,
	content_hash
)
VALUES (
	'AI Model Update Lands This Week',
	'https://example.com/news/ai-update',
	'A new AI model release is expected to improve latency and quality.',
	'technology',
	'global',
	TRUE,
	NOW(),
	'pending',
	NULL,
	0,
	'seed-raw-news-002'
)
ON CONFLICT (content_hash) DO NOTHING;
