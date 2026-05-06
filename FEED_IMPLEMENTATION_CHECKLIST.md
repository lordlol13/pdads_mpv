# Feed Refactoring - Implementation Checklist & Next Steps

## ✅ Completed Refactoring

### Code Changes

- [x] **feed_loader.py** - Fresh data loading (no personalization)
  - `load_fresh_candidates()` - Load ai_news (48h window)
  - `load_user_interactions()` - Optional enrichment

- [x] **feed_ranker.py** - Pure scoring functions
  - `compute_rank_score()` - Transparent scoring formula
  - `rank_items()` - Sort by score + recency
  - `separate_by_region()` - Regional/global split

- [x] **feed_filter.py** - Data cleaning pipeline
  - `normalize_item()` - Validate format
  - `deduplicate()` - O(n) hash-based
  - `filter_seen_items()` - Remove viewed
  - `limit_topic_domination()` - Max 3 per category
  - `filter_feed()` - Complete pipeline

- [x] **feed_service.py** - Refactored orchestrator
  - `get_user_feed()` - Main pipeline
  - `_get_user_seen_ids()` - Fetch viewed items
  - `_get_user_profile()` - User context

- [x] **interaction_tracker.py** - Clarified interaction model
  - `record_impression()` - Feed appearance
  - `record_view()` - Article click
  - `record_like()`, `record_save()`, `record_skip()`

- [x] **Documentation**
  - FEED_REFACTORING.md - Design decisions & architecture
  - This file - implementation guide

---

## ✅ Key Improvements Achieved

1. **Real-Time Feed Generation**
   - No longer depends on stale `user_feed` cache
   - Loads fresh `ai_news` every request
   - Includes latest high-quality articles

2. **Clean Separation of Concerns**
   - Loader: data only
   - Ranker: scoring only (pure functions)
   - Filter: cleaning only
   - Service: orchestration only

3. **Efficient Deduplication**
   - Changed from O(n²) to O(n)
   - Hash-based content matching
   - Prevents duplicate articles

4. **Correct Interaction Model**
   - Clear: impression vs view vs like vs save vs skip
   - No auto-marking viewed on impression
   - Foundation for better ranking

5. **Structured Logging**
   - Every step logs metrics
   - Easy to debug & monitor
   - Foundation for analytics

---

## 📋 Next Steps - Ranked by Priority

### P0: Verify No Breaking Changes ⚠️

**TODO (Test):**
```bash
# 1. Start system (already running)
docker compose ps  # Should show all services

# 2. Test feed endpoint
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/feed/me?limit=50

# 3. Verify response format
# Expected: list of items with rank_score, image_url, etc

# 4. Test basic interaction endpoints
curl -X POST http://localhost:8000/api/feed/react \
  -H "Content-Type: application/json" \
  -d '{"ai_news_id": 1, "liked": true}'
```

**Success Criteria:**
- Feed returns 50 items
- All items have `ai_news_id`, `final_title`, `final_text`, `rank_score`
- No errors in logs
- Response time < 500ms

---

### P1: Hook Up Interaction Tracking

**TODO (Backend):**
```python
# File: app/backend/api/routes/feed.py

from app.backend.services.feed.interaction_tracker import (
    record_impression,
    record_view,
    record_like,
    record_save,
    record_skip,
)

@router.post("/feed/react")
async def react_to_news(
    payload: FeedReactionRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Record user reaction to news item."""
    
    # When user clicks article (VIEW)
    if payload.event == "view":
        await record_view(session, user.id, payload.ai_news_id, 
                         dwell_time_seconds=payload.dwell_time)
    
    # When user likes (LIKE)
    elif payload.event == "like":
        await record_like(session, user.id, payload.ai_news_id, True)
    
    # When user saves (SAVE)
    elif payload.event == "save":
        await record_save(session, user.id, payload.ai_news_id, True)
    
    # When user skips (SKIP)
    elif payload.event == "skip":
        await record_skip(session, user.id, payload.ai_news_id)
    
    return {"status": "ok"}
```

**Frontend TODO:**
```typescript
// app/frontend/src/api/services.ts

export const feedService = {
  recordView: (ai_news_id: number, dwell_time: number) =>
    apiRequest('/feed/react', {
      method: 'POST',
      body: { ai_news_id, event: 'view', dwell_time }
    }),
  
  recordLike: (ai_news_id: number, liked: boolean) =>
    apiRequest('/feed/react', {
      method: 'POST',
      body: { ai_news_id, event: 'like', liked }
    }),
  
  recordSkip: (ai_news_id: number) =>
    apiRequest('/feed/react', {
      method: 'POST',
      body: { ai_news_id, event: 'skip' }
    }),
}
```

---

### P2: Add Feed Performance Monitoring

**TODO (Backend):**
```python
# File: app/backend/services/feed/metrics.py

from app.backend.core.logging import ContextLogger

logger = ContextLogger(__name__)

def log_feed_metrics(
    user_id: int,
    candidates: int,
    after_rank: int,
    after_filter: int,
    final: int,
    duration_ms: float,
    uz_language: int,
    uz_region: int,
):
    """Log feed generation metrics for monitoring."""
    
    logger.info("feed_metrics", extra={
        "user_id": user_id,
        "candidates_loaded": candidates,
        "after_ranking": after_rank,
        "after_filtering": after_filter,
        "final_count": final,
        "duration_ms": duration_ms,
        "uz_language_pct": (uz_language / final * 100) if final > 0 else 0,
        "uz_region_pct": (uz_region / final * 100) if final > 0 else 0,
        "dedupe_rate": ((candidates - after_filter) / candidates * 100) if candidates > 0 else 0,
    })
```

**Monitoring Dashboard:**
- Feed generation latency (target: < 200ms)
- Deduplication rate (target: < 10%)
- Uzbek language %
- Uzbek region %

---

### P3: Optimize User Embedding Caching

**TODO:**
```python
# File: app/backend/services/feed/embedding_cache.py

import redis
from datetime import timedelta

class EmbeddingCache:
    """Cache user embeddings for feed performance."""
    
    async def get_or_compute(self, session, user_id: int):
        """
        Get user embedding from cache or compute.
        Cache for 1 hour.
        """
        cache_key = f"user_embedding:{user_id}"
        
        # Try cache
        cached = await self.redis.get(cache_key)
        if cached:
            return json.loads(cached)
        
        # Compute
        embedding = await ensure_user_embedding(session, user_id)
        
        # Cache for 1 hour
        await self.redis.setex(
            cache_key,
            timedelta(hours=1),
            json.dumps(embedding)
        )
        
        return embedding
```

---

### P4: A/B Testing Framework

**TODO:**
```python
# File: app/backend/services/feed/ab_testing.py

class FeedExperiment:
    """A/B test different ranking weights."""
    
    async def get_score_multipliers(self, user_id: int) -> dict:
        """
        Get score multipliers for this user.
        Could vary by experiment assignment.
        """
        
        # Check if user is in experiment
        group = await get_experiment_group(user_id, "feed_ranking_v2")
        
        if group == "control":
            return {
                "uz_language": 3.0,
                "uz_region": 5.0,
                "image": 1.0,
                "text_length": 2.0,
            }
        
        elif group == "treatment_higher_region":
            return {
                "uz_language": 2.0,
                "uz_region": 8.0,  # Boosted
                "image": 1.0,
                "text_length": 2.0,
            }
        
        return default_multipliers
```

---

### P5: Feed Caching (Optional Performance)

**TODO:**
```python
# File: app/backend/services/feed/cache.py

async def get_user_feed_cached(
    session: AsyncSession,
    user_id: int,
    limit: int = DEFAULT_LIMIT,
    cache_ttl: int = 300,  # 5 minutes
) -> list[dict]:
    """
    Get feed with 5-minute cache.
    Invalidate on new articles.
    """
    
    cache_key = f"feed:{user_id}:{limit}"
    
    # Try cache
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)
    
    # Generate fresh
    feed = await get_user_feed(session, user_id, limit)
    
    # Cache
    await redis.setex(cache_key, cache_ttl, json.dumps(feed))
    
    return feed
```

**Benefit:** Reduce DB load by 70%+ for repeat requests

---

## 🧪 Testing Checklist

### Unit Tests

```bash
# TODO: Create tests/unit/test_feed_ranker.py
pytest tests/unit/test_feed_ranker.py -v

# TODO: Create tests/unit/test_feed_filter.py
pytest tests/unit/test_feed_filter.py -v
```

### Integration Tests

```bash
# TODO: Create tests/integration/test_feed_service.py
pytest tests/integration/test_feed_service.py -v
```

### Manual Testing

```bash
# 1. Fetch feed
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/feed/me?limit=10

# 2. Verify items have rank_score
# Expected: [{"ai_news_id": 1, "rank_score": 12.5, ...}, ...]

# 3. Check server logs
docker compose logs web | grep "feed_generated"

# 4. Verify no raw_news items
# All items should have ai_news_id (not raw_news_id)
```

---

## 📊 Success Metrics

Once refactoring is complete & validated:

| Metric | Target | How to Measure |
|--------|--------|-----------------|
| **Feed latency** | < 200ms | `docker logs web \| grep feed_generated` |
| **Dedup rate** | < 10% | Logger metrics in `filtered_seen` |
| **Uzbek language** | > 80% | Logger `uz_language_count` |
| **Uzbek region** | > 50% | Logger `uz_region_count` |
| **No errors** | 0/req | Check error logs |
| **API response** | 200 OK | Curl test above |

---

## 🚨 Rollback Plan

If issues arise:

1. **Feed latency spike?**
   - Reduce `limit * 5` to `limit * 3` in feed_loader
   - Add embedding cache

2. **Too many duplicates?**
   - Check deduplication hash function
   - Verify normalize_item() not filtering too much

3. **Wrong items in feed?**
   - Check feed_filter normalization
   - Verify ai_news table has content

4. **User confusion?**
   - Feed is different because:
     - Real-time (fresher)
     - No stale cache
     - Better deduplication
     - Correct interaction tracking (eventually)

---

## Summary

**Status:** ✅ Refactoring Complete

The feed system has been refactored into a clean, modular architecture that is:
- ✅ Real-time (no stale cache)
- ✅ Efficient (O(n) deduplication)
- ✅ Maintainable (4 clear modules)
- ✅ Testable (pure functions)
- ✅ Observable (structured logging)

**Next:** Validate no breaking changes, then hook up interaction tracking.
