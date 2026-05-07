"""Feed ranker - scoring and ranking logic."""

from typing import Any
from datetime import datetime
from datetime import datetime, timezone

from app.backend.core.logging import ContextLogger
from app.backend.services.recommender_service import compute_score

logger = ContextLogger(__name__)


def _soft_normalize_image(url: str | None) -> str | None:
    """
    Normalize and validate image URL.
    Filters out logos, placeholders, etc.
    """
    if not url:
        return None
    
    value = str(url).strip()
    if not value or not value.startswith(("http://", "https://")):
        return None
    
    lowered = value.lower()
    bad_keywords = ("logo", "icon", "placeholder", "default", "avatar", "thumbnail")
    if any(kw in lowered for kw in bad_keywords):
        return None
    
    return value


def _get_timestamp(item: dict[str, Any]) -> float:
    """Convert created_at to timestamp for sorting."""
    created_at = item.get("created_at")
    if isinstance(created_at, datetime):
        try:
            return created_at.timestamp()
        except Exception as exc:
            logger.warning("timestamp_parse_failed", extra={"error": str(exc)})
            return 0.0
    return 0.0


def _extract_topics_from_interests(interests: dict | str | None) -> set[str]:
    """Extract topic set from user interests JSON."""
    if not interests:
        return set()
    
    try:
        if isinstance(interests, str):
            import json
            interests = json.loads(interests)
        
        if not isinstance(interests, dict):
            return set()
        
        topics = set()
        for key in ("all_topics", "topics", "custom_topics", "interests"):
            if key in interests:
                val = interests[key]
                if isinstance(val, (list, set)):
                    topics.update(str(t).lower().strip() for t in val if t)
                elif isinstance(val, str):
                    topics.update(t.lower().strip() for t in val.split(",") if t)
        
        return topics
    except Exception as exc:
        logger.warning("extract_topics_failed", extra={"error": str(exc)})
        return set()


def compute_rank_score(
    item: dict[str, Any],
    user_profile: dict[str, Any] | None = None,
    user_embedding: list[float] | None = None,
    is_cold_start: bool = False,
    session_context: dict | None = None,
) -> float:
    """
    Compute ranking score for an item.
    
    Pure function - no side effects.
    
    Ranking factors:
    - Task 1: Topic interaction (liked +5, skipped -5, viewed +2)
    - Task 2: Language safety (mismatch -5)
    - Task 3: Cold start boost (fresh +2, regional +8)
    - Task 4: Quality threshold (enforced post-filter)
    - Task 5: Diversity penalty (repeated topic -3)
    - Plus base factors: ai_score, language, region, image, text, embedding, interactions
    """
    
    score = 0.0
    
    # 1. Base quality score
    ai_score = float(item.get("ai_score") or item.get("base_score") or 0.0)
    score += min(ai_score, 10.0)  # Cap at 10 to avoid domination
    
    # 2. Language score with Task 2: Language safety
    language = str(item.get("language") or "").strip().lower()
    user_language = "uz"
    if user_profile:
        interests = user_profile.get("interests")
        if isinstance(interests, str):
            try:
                import json
                interests = json.loads(interests)
            except Exception as exc:
                logger.warning("interest_json_parse_failed", extra={"error": str(exc)})
                interests = {}
        if isinstance(interests, dict):
            user_language = interests.get("language", "uz").lower()
    
    if language == user_language:
        score += 3.0
    elif language == "uz":
        score += 2.0
    elif language not in ("", "unknown"):
        score -= 3.0
    
    # 3. Region score (Task 3: Cold start boost)
    region = str(item.get("region") or "").strip().lower()
    if region == "uz":
        if is_cold_start:
            score += 8.0  # Boost regional in cold start
        else:
            score += 5.0
    
    # 4. Image score
    image_url = _soft_normalize_image(item.get("image_url"))
    if image_url:
        score += 1.0
        item["image_url"] = image_url
    
    # 5. Text quality score
    text = str(item.get("final_text") or "").strip()
    if len(text) > 200:
        score += 2.0
    elif len(text) < 50:
        score -= 1.0
    
    # Task 3: Cold start boost - prefer fresh content
    if is_cold_start:
        created_at = item.get("created_at")
        if isinstance(created_at, datetime):
            now = datetime.now(timezone.utc)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            age_hours = (now - created_at).total_seconds() / 3600
            if age_hours < 6:
                score += 2.0
            elif age_hours < 24:
                score += 1.0
    
    # 6. User embedding similarity
    if user_embedding:
        try:
            embedding_score = compute_score(item, user_profile, user_embedding)
            score += float(embedding_score) * 0.5
        except Exception as e:
            logger.warning("embedding_score_failed", extra={"error": str(e)})
    
    # 7. User interaction history
    if item.get("topic_liked"):
        score += 5.0
    if item.get("liked"):
        score += 10.0
    if item.get("disliked") or item.get("skipped"):
        score -= 6.0
    if item.get("saved"):
        score += 0.75
    if item.get("viewed"):
        score += 2.0

    # Popularity boost (Task 7)
    try:
        like_count = int(item.get("like_count") or 0)
        if like_count > 0:
            from math import log1p
            score += float(log1p(like_count)) * 1.5
    except Exception:
        pass
    
    # Task 1: Topic-based interaction scoring
    # Preference boost: user_profile may be produced by profile_store
    try:
        topics_profile = (user_profile or {}).get("topics") or {}
        sources_profile = (user_profile or {}).get("sources") or {}
        keywords_profile = (user_profile or {}).get("keywords") or {}
    except Exception:
        topics_profile = {}
        sources_profile = {}
        keywords_profile = {}

    now = datetime.now(timezone.utc)
    def _hours_since(iso_ts: str | None) -> float:
        if not iso_ts:
            return 0.0
        try:
            dt = datetime.fromisoformat(iso_ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, (now - dt).total_seconds() / 3600.0)
        except Exception:
            return 0.0

    category = (item.get("category") or "").lower().strip()
    if category and category in topics_profile:
        entry = topics_profile.get(category) or {}
        count = float(entry.get("count") or 0)
        hours = _hours_since(entry.get("last_seen"))
        decay = 0.95 ** hours if hours > 0 else 1.0
        score += count * 1.5 * decay

    # Source boost with decay
    source_url = str(item.get("source_url") or "").strip().lower()
    if source_url:
        try:
            from urllib.parse import urlparse
            host = urlparse(source_url).hostname or source_url
        except Exception:
            host = source_url
        if host and host in sources_profile:
            entry = sources_profile.get(host) or {}
            count = float(entry.get("count") or 0)
            hours = _hours_since(entry.get("last_seen"))
            decay = 0.95 ** hours if hours > 0 else 1.0
            score += count * 0.5 * decay * 4.0  # scaled so typical source counts give ~2 points

    # Keyword overlap boost with decay-weighted counts
    try:
        item_text = str(item.get("final_text") or "")
        tokens = set(w.lower().strip(".,!?;:\"'()") for w in item_text.split() if len(w) > 3)
        overlap_weight = 0.0
        for kw, kv in keywords_profile.items():
            if kw in tokens:
                cnt = float((kv or {}).get("count") or 0)
                hours = _hours_since((kv or {}).get("last_seen"))
                decay = 0.95 ** hours if hours > 0 else 1.0
                overlap_weight += cnt * decay
        if overlap_weight > 0:
            added = min(4.0, 2.0 + 0.25 * overlap_weight)
            score += added
    except Exception:
        pass
    
    # SESSION MOMENTUM: boost topics seen multiple times in current session
    session_context = session_context or {}
    session_topics = session_context.get("topics", {})
    item_topic = (item.get("category") or "").lower()
    if item_topic and session_topics.get(item_topic, 0) >= 2:
        score += 5.0

    # MICRO-TREND BOOST: amplify if same topic has 3+ recent interactions
    if item_topic and session_topics.get(item_topic, 0) >= 3:
        score += 3.0

    # ANTI-BOREDOM: penalize if topic appears 4+ times in session (prevent saturation)
    if item_topic and session_topics.get(item_topic, 0) >= 4:
        score -= 3.0
    
    # ============================================
    # NEXT-TOPIC PREDICTION: Forecast user intent
    # ============================================
    last_interactions = session_context.get("last_interactions", [])
    
    # NEXT-TOPIC PREDICTION: If topic repeats in last 3 interactions, user wants it
    if last_interactions and item_topic:
        topic_count_in_history = sum(1 for inter in last_interactions if inter.get("topic") == item_topic)
        if topic_count_in_history >= 2:
            score += 6.0
    
    # INTERACTION PATTERN: Quick consecutive likes signal strong interest
    if last_interactions:
        likes_in_history = [inter for inter in last_interactions if inter.get("liked")]
        if len(likes_in_history) >= 2:
            # User liked 2+ items recently; boost similar content
            liked_topics = {inter.get("topic") for inter in likes_in_history}
            if item_topic in liked_topics:
                score += 4.0
    
    # ============================================
    # DWELL TIME ANALYSIS: Real behavioral signal
    # ============================================
    dwell_time = item.get("watch_time") or 0
    
    if dwell_time > 6:
        # Deep engagement: user spent significant time
        score += 8.0
    elif dwell_time > 3:
        # Moderate engagement
        score += 4.0
    elif 0 < dwell_time < 1:
        # Accidental click or scroll-through
        score -= 5.0
    
    # DWELL-TIME + LIKE SYNERGY: Validate genuine interest
    if item.get("liked") and dwell_time > 3:
        # Real interest: took time to read, then liked
        score += 5.0
    elif item.get("liked") and dwell_time < 1:
        # Suspicious: liked without reading (reduce impact)
        score -= 3.0
    
    # SESSION DWELL PATTERN: If user spends time on same topic repeatedly
    if last_interactions and item_topic:
        dwell_topics = {}
        for inter in last_interactions:
            topic = inter.get("topic")
            watch_time = inter.get("watch_time") or 0
            if watch_time > 3 and topic:
                dwell_topics[topic] = dwell_topics.get(topic, 0) + 1
        
        if dwell_topics.get(item_topic, 0) >= 2:
            score += 6.0
    
    # Task 5: Diversity penalty - repeated topics
    if item.get("_topic_count", 0) >= 3:
        score -= 3.0
    
    return round(score, 6)


def rank_items(
    candidates: list[dict[str, Any]],
    user_profile: dict[str, Any] | None = None,
    user_embedding: list[float] | None = None,
    is_cold_start: bool = False,
    session_context: dict | None = None,
) -> list[dict[str, Any]]:
    """
    Rank candidates by score.
    
    Returns candidates with rank_score field added, sorted descending.
    Task 5: Tracks topic count for diversity penalty.
    """
    
    # Task 5: Count topics for diversity enforcement
    topic_counts = {}
    
    for item in candidates:
        score = compute_rank_score(item, user_profile, user_embedding, is_cold_start, session_context=session_context)
        item["rank_score"] = score
        
        # Task 5: Track topic count
        category = item.get("category", "unknown")
        topic_counts[category] = topic_counts.get(category, 0) + 1
        item["_topic_count"] = topic_counts[category]
    
    # Re-score with topic count info
    for item in candidates:
        score = compute_rank_score(item, user_profile, user_embedding, is_cold_start, session_context=session_context)
        item["rank_score"] = score
    
    # Sort by score (desc) then by recency (desc)
    candidates.sort(
        key=lambda x: (float(x.get("rank_score") or 0.0), _get_timestamp(x)),
        reverse=True
    )
    
    return candidates


def separate_by_region(items: list[dict[str, Any]]) -> tuple[list, list]:
    """
    Separate items into regional (uz) and global.
    
    Used for maintaining regional diversity in final feed.
    """
    regional = []
    global_news = []
    
    for item in items:
        region = str(item.get("region") or "").strip().lower()
        if region == "uz":
            regional.append(item)
        else:
            global_news.append(item)
    
    return regional, global_news
