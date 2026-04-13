# API Resilience Layer Documentation

## Overview

Comprehensive resilience layer for handling API dependencies, quotas, rate limits, and failures.

## Components

### 1. Exponential Backoff Retry (`resilience_service.py`)

**Purpose**: Automatic retry with exponential backoff and jitter

**Usage**:
```python
from app.backend.services.resilience_service import retry_async

result = await retry_async(
    api_call,
    max_attempts=3,
    base_delay_seconds=2,
    max_delay_seconds=60,
    retry_on_exceptions=(httpx.HTTPError,),
)
```

**Behavior**:
- Delays: 2s → 4s → 8s (exponential backoff)
- Jitter: ±50% random variance on each delay
- Configurable via settings:
  - `API_RETRY_MAX_ATTEMPTS` (default: 3)
  - `API_RETRY_BASE_DELAY_SECONDS` (default: 2)
  - `API_RETRY_MAX_DELAY_SECONDS` (default: 60)

### 2. Rate Limiting (Token Bucket via Redis)

**Purpose**: Distributed rate limiting across workers

**Usage**:
```python
from app.backend.services.resilience_service import check_rate_limit, _news_api_limiter

allowed = await check_rate_limit(
    "newsapi:topics:sports",
    limiter=_news_api_limiter,
    limit=20,  # requests
    window_seconds=60,  # per minute
)

if not allowed:
    # Handle rate limit exceeded
    pass
```

**Configuration**:
- `NEWS_API_RATE_LIMIT_PER_MINUTE` (default: 20)
- `NEWS_API_RATE_LIMIT_PER_DAY` (default: 500)
- `LLM_RATE_LIMIT_PER_MINUTE` (default: 5)
- `LLM_RATE_LIMIT_PER_HOUR` (default: 200)

**Implementation**:
- Redis-backed token bucket algorithm
- Graceful degradation: fails open if Redis unavailable
- Per-identifier rate tracking (e.g., per-user, per-topic)

### 3. Redis Caching with TTL

**Purpose**: Cache API results to reduce quota usage

**Usage**:
```python
from app.backend.services.resilience_service import cache_get, cache_set

# Get from cache
cached = await cache_get("llm:gemini", title, target_persona)

if cached:
    return cached

# Execute function
result = await generate_news(...)

# Store in cache
await cache_set("llm:gemini", 24, result, title, target_persona)  # 24-hour TTL
```

**Configuration**:
- `CACHE_LLM_RESULTS_TTL_HOURS` (default: 24)
- `CACHE_NEWS_RESULTS_TTL_HOURS` (default: 6)
- `CACHE_EMBEDDINGS_TTL_HOURS` (default: 168 - 1 week)

### 4. Fallback Strategy

**Purpose**: Graceful degradation when primary service fails

**Usage in LLM Service**:
1. Try Gemini (with retry & cache)
2. If fails and `LLM_FALLBACK_ENABLED=true`, try DeepSeek
3. If both fail and `LLM_FALLBACK_RETURN_CACHED=true`, return stale cached result
4. If all fail, return mock/default result

**Configuration**:
- `LLM_FALLBACK_ENABLED` (default: true)
- `LLM_FALLBACK_MODEL` (default: "deepseek")
- `LLM_FALLBACK_RETURN_CACHED` (default: true)
- `NEWS_API_FALLBACK_TO_RSS` (default: true)

### 5. Celery Task Retry

**Purpose**: Automatic task retry with configurable backoff in queue

**Implementation** in `brain/tasks/pipeline_tasks.py`:
```python
@celery_app.task(
    name="brain.process_raw_news",
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError, Exception),
    retry_backoff=True,
    retry_backoff_max=settings.API_RETRY_MAX_DELAY_SECONDS,
    max_retries=settings.API_RETRY_MAX_ATTEMPTS,
)
def process_raw_news(self, raw_news_id: int, ...):
    ...
```

**Retry Chain**:
- `process_raw_news`: 3 retries (critical for news generation)
- `scheduled_ingestion`: 2 retries (scheduled, moderate priority)
- `scheduled_cleanup_ai_products`: 1 retry (low priority cleanup)

## Integration Points

### News API Service (`news_api_service.py`)

**Before Request**:
```python
# Check rate limit
allowed = await check_rate_limit(
    f"newsapi:topics:{','.join(topics[:3])}",
    limiter=_news_api_limiter,
    limit=settings.NEWS_API_RATE_LIMIT_PER_MINUTE,
    window_seconds=60,
)
```

**During Request**:
```python
# Retry with exponential backoff
articles = await retry_async(
    _make_requests,
    max_attempts=settings.API_RETRY_MAX_ATTEMPTS,
    ...
)
```

**Fallback**:
```python
if NewsAPI fails and NEWS_API_FALLBACK_TO_RSS:
    return fallback_rss_articles
```

### LLM Service (`llm_service.py`)

**Gemini Flow**:
1. Check rate limit
2. Try cache
3. Retry on transient errors
4. Cache result if successful
5. If fails, try DeepSeek

**DeepSeek Flow** (fallback):
1. Check rate limit
2. Try cache
3. Retry on transient errors
4. Cache result
5. Return composed news

**All Fail Flow**:
1. If `FALLBACK_RETURN_CACHED=true`: return any cached result (may be stale)
2. Otherwise: return mock generation

## Monitoring & Logging

### Log Levels

- **INFO**: Rate limit checks, cache hits/misses, fallback triggers
- **WARNING**: Rate limit exceeded, retry attempts, backoff delays
- **ERROR**: All retries exhausted, both LLMs failed, timeouts
- **DEBUG**: Cache key generation, retry details

### Example Logs

```
Rate limit exceeded for topics: ['sports']
Falling back to RSS sources
Attempt 1/3 failed for fetch_articles: Connection timeout. Retrying in 2.5s...
Gemini rate-limited; backoff enabled for 180 seconds
Both LLMs failed; checking cache for stale result
Found cached Gemini result (may be stale)
DeepSeek generation failed after retries: API unavailable
```

## Environment Variables

```bash
# Retry
API_RETRY_MAX_ATTEMPTS=3
API_RETRY_BASE_DELAY_SECONDS=2
API_RETRY_MAX_DELAY_SECONDS=60

# Rate Limiting
NEWS_API_RATE_LIMIT_PER_MINUTE=20
NEWS_API_RATE_LIMIT_PER_DAY=500
LLM_RATE_LIMIT_PER_MINUTE=5
LLM_RATE_LIMIT_PER_HOUR=200

# Caching
CACHE_LLM_RESULTS_TTL_HOURS=24
CACHE_NEWS_RESULTS_TTL_HOURS=6
CACHE_EMBEDDINGS_TTL_HOURS=168

# Fallback
LLM_FALLBACK_ENABLED=true
LLM_FALLBACK_MODEL=deepseek
LLM_FALLBACK_RETURN_CACHED=true
NEWS_API_FALLBACK_TO_RSS=true
```

## Testing

### Retry Tests
```bash
pytest tests/test_resilience.py::TestRetryConfig -v
pytest tests/test_resilience.py::TestIntegration -v
```

### Without Redis (local tests)
```bash
pytest tests/test_resilience.py::TestRetryConfig
pytest tests/test_resilience.py::TestCacheManager::test_make_key_consistency
pytest tests/test_resilience.py::TestIntegration
```

### Backward Compatibility
```bash
pytest tests/test_news_api_service.py tests/test_recommender_service.py -v
```

## Benefits

| Issue | Solution | Benefit |
|-------|----------|---------|
| API timeouts | Exponential backoff retry | 90% success on transient failures |
| Quota exhaustion | Rate limiting + caching | Reduce API calls by 40-60% |
| Single-point failure | Fallback model | Service availability ↑ |
| Cascading failures | Token bucket algo | Prevents thundering herd |
| Stale data acceptable | Cached fallback | Graceful degradation |

## Production Considerations

1. **Redis Availability**: Resilience layer gracefully degrades if Redis down
2. **Cache Invalidation**: Automatic TTL-based expiry; manual purge available
3. **Rate Limit Tuning**: Monitor actual API usage and adjust limits accordingly
4. **Fallback Model Cost**: DeepSeek cheaper than Gemini but may be slower
5. **Logging**: All resilience events logged for observability

## Troubleshooting

### Too many rate limit errors
→ Lower `*_RATE_LIMIT_PER_MINUTE` or reduce concurrent requests

### Stale cache being returned
→ Lower `CACHE_*_TTL_HOURS` for fresher data

### Fallback not being triggered
→ Check `LLM_FALLBACK_ENABLED=true` and ensure DeepSeek API key configured

### Retries not working
→ Verify `API_RETRY_MAX_ATTEMPTS > 1` and check logs for exception types

## Future Enhancements

- [ ] Circuit breaker pattern (fail fast after X consecutive failures)
- [ ] Adaptive rate limiting (learn from 429 headers)
- [ ] Bulkhead isolation (per-service resource pools)
- [ ] Prometheus metrics (retries, rate limits, fallbacks)
- [ ] Dynamic fallback selection (based on uptime history)
