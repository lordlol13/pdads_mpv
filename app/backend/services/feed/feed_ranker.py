"""Feed ranker - scoring and ranking logic."""

from typing import Any
from datetime import datetime

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
            age_hours = (datetime.utcnow() - created_at).total_seconds() / 3600
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
        score += 8.0
    if item.get("disliked") or item.get("skipped"):
        score -= 5.0
    if item.get("saved"):
        score += 0.75
    if item.get("viewed"):
        score += 2.0
    
    # Task 1: Topic-based interaction scoring
    user_topics = _extract_topics_from_interests(user_profile.get("interests") if user_profile else None)
    category = item.get("category")
    if user_topics and category:
        category_lower = str(category).lower().strip()
        if category_lower in user_topics:
            score += 2.0
    
    # Task 5: Diversity penalty - repeated topics
    if item.get("_topic_count", 0) >= 3:
        score -= 3.0
    
    return round(score, 6)


def rank_items(
    candidates: list[dict[str, Any]],
    user_profile: dict[str, Any] | None = None,
    user_embedding: list[float] | None = None,
    is_cold_start: bool = False,
) -> list[dict[str, Any]]:
    """
    Rank candidates by score.
    
    Returns candidates with rank_score field added, sorted descending.
    Task 5: Tracks topic count for diversity penalty.
    """
    
    # Task 5: Count topics for diversity enforcement
    topic_counts = {}
    
    for item in candidates:
        score = compute_rank_score(item, user_profile, user_embedding, is_cold_start)
        item["rank_score"] = score
        
        # Task 5: Track topic count
        category = item.get("category", "unknown")
        topic_counts[category] = topic_counts.get(category, 0) + 1
        item["_topic_count"] = topic_counts[category]
    
    # Re-score with topic count info
    for item in candidates:
        score = compute_rank_score(item, user_profile, user_embedding, is_cold_start)
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
